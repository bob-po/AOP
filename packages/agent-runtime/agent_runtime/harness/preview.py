"""Live local-terminal preview for harness CLI runners.

Controlled by ``HARNESS_LIVE_PREVIEW=1|true|yes|on``. When enabled, runners spawn
the agent CLI inside a new console window (Windows ``CREATE_NEW_CONSOLE``) via
:mod:`preview_tee`, which mirrors output to ``<workdir>/preview.log`` so the
parent can still emit DELTA events and collect a final transcript.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional

from .process import ManagedProcess, ProcessSupervisor
from .runners._cli_common import resolve_binary

logger = logging.getLogger(__name__)

OnLine = Callable[[str], Awaitable[None] | None]

# Profile / agent_key → default preview binary name (PATH or *_CLI_PATH).
_PREVIEW_BINARIES: dict[str, tuple[str, tuple[str, ...]]] = {
    # (default_bin, env_overrides)
    "deepseek-harness": ("codewhale", ("CODEWHALE_CLI_PATH",)),
    "deepseek": ("codewhale", ("CODEWHALE_CLI_PATH",)),
    "claude-code": ("claude", ("CLAUDE_CLI_PATH",)),
    "claude": ("claude", ("CLAUDE_CLI_PATH",)),
    "pi": ("pi", ("PI_CLI_PATH",)),
    "openclaw": ("openclaw", ("OPENCLAW_CLI_PATH",)),
    "hermes": ("hermes", ("HERMES_CLI_PATH",)),
}


def live_preview_enabled() -> bool:
    raw = (os.getenv("HARNESS_LIVE_PREVIEW") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def desktop_preview_available() -> bool:
    """Heuristic: skip popup when no interactive desktop session is likely."""
    if sys.platform == "win32":
        # SessionName is typically Console / RDP-Tcp#N when interactive.
        session = (os.getenv("SESSIONNAME") or "").strip().lower()
        if session in {"", "console"} or session.startswith("rdp"):
            return True
        # Services often have no SESSIONNAME or "Services".
        if session == "services":
            return False
        return True
    # POSIX: require a TTY-capable display for a visible window.
    if os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"):
        return True
    return sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False


def preview_log_path(cwd: str | Path) -> Path:
    return Path(cwd).expanduser().resolve() / "preview.log"


def preview_binary(agent_key: str, *, default: Optional[str] = None) -> Optional[str]:
    """Resolve the CLI used for live preview for this agent profile."""
    key = (agent_key or "").strip().lower()
    spec = _PREVIEW_BINARIES.get(key)
    if spec is None:
        # Prefix match: deepseek-*, claude-*, …
        for name, s in _PREVIEW_BINARIES.items():
            if key.startswith(name):
                spec = s
                break
    if spec is None:
        bin_name = default or agent_key or ""
        env_keys: tuple[str, ...] = ()
    else:
        bin_name, env_keys = spec
    for env_name in env_keys:
        val = (os.getenv(env_name) or "").strip()
        if val:
            found = resolve_binary(val)
            if found:
                return found
            if os.path.isfile(val):
                return val
    if not bin_name:
        return None
    return resolve_binary(bin_name)


def harness_preview_mode() -> str:
    """Global live-preview style: ``tui`` (real interactive UI) or ``exec`` (piped tee).

    ``HARNESS_PREVIEW_MODE`` wins; ``CODEWHALE_PREVIEW_MODE`` kept as alias for deepseek.
    """
    raw = (
        os.getenv("HARNESS_PREVIEW_MODE")
        or os.getenv("CODEWHALE_PREVIEW_MODE")
        or "tui"
    ).strip().lower()
    if raw in {"exec", "headless", "text", "cli"}:
        return "exec"
    return "tui"


def deepseek_preview_mode() -> str:
    """Backward-compatible alias of :func:`harness_preview_mode`."""
    return harness_preview_mode()


def prepare_preview_workspace(
    cwd: str | Path,
    *,
    user_goal: str = "",
    prompt: str = "",
) -> Path:
    """Write goal/prompt files so TUI agents can discover the task without fragile argv."""
    root = Path(cwd).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    goal = (user_goal or "").strip() or "(empty goal)"
    body = (prompt or "").strip() or goal
    try:
        (root / "USER_GOAL.md").write_text(goal, encoding="utf-8")
        (root / "preview_prompt.md").write_text(body, encoding="utf-8")
        # Many TUIs auto-load AGENTS.md / CLAUDE.md as project context.
        agents = (
            "# AOP live-preview task\n\n"
            f"## User goal\n\n{goal}\n\n"
            "## Instructions\n\n"
            "- Complete the user goal end-to-end.\n"
            "- Write the final answer to `output.md` when finished.\n"
            "- The workspace may start empty; that is normal.\n"
        )
        if body and body != goal:
            agents += f"\n## Full prompt\n\n{body}\n"
        (root / "AGENTS.md").write_text(agents, encoding="utf-8")
        (root / "CLAUDE.md").write_text(agents, encoding="utf-8")
    except OSError as exc:
        logger.warning("prepare_preview_workspace failed: %s", exc)
    return root


def collect_preview_artifacts(cwd: str | Path, *, fallback: str = "") -> str:
    """Prefer agent-written ``output.md``; else ``fallback`` (often preview.log / tee text)."""
    root = Path(cwd).expanduser().resolve()
    for name in ("output.md", "OUTPUT.md", "final_answer.md"):
        path = root / name
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    return text
        except OSError:
            continue
    return (fallback or "").strip()


def deepseek_preview_argv(
    prompt: str,
    *,
    binary: Optional[str] = None,
    workspace: Optional[str] = None,
) -> list[str]:
    """CodeWhale argv for a visible local console.

    Default is **interactive TUI** (same UI as bare ``codewhale``), not
    ``codewhale exec`` — exec only prints a tool transcript and has no TUI.

    Escape hatches:
    - ``HARNESS_PREVIEW_MODE=exec`` / ``CODEWHALE_PREVIEW_MODE=exec`` → ``codewhale exec --auto``
    - ``CODEWHALE_PREVIEW_STREAM_JSON=1`` → stream-json when in exec mode
    """
    bin_path = binary or preview_binary("deepseek-harness") or "codewhale"
    if harness_preview_mode() == "exec":
        argv = [bin_path, "exec", "--auto"]
        raw = (os.getenv("CODEWHALE_PREVIEW_STREAM_JSON") or "").strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            argv.extend(["--output-format", "stream-json"])
        else:
            argv.extend(["--output-format", "text"])
        argv.append(prompt)
        return argv

    # Interactive TUI — must NOT be wrapped by preview_tee (PIPEs kill the UI).
    argv = [
        bin_path,
        "--fresh",
        "--skip-onboarding",
        "--approval-policy",
        "auto",
    ]
    if workspace:
        argv.extend(["-C", str(workspace)])
    # -p seeds the first turn inside the TUI (same screen as `codewhale` alone).
    argv.extend(["-p", prompt])
    return argv


def ensure_claude_workspace_trusted(cwd: str | Path) -> None:
    """Best-effort: skip Claude Code trust + Bypass Permissions startup dialogs."""
    root = str(Path(cwd).expanduser().resolve())
    try:
        import json

        # 1) Project trust in ~/.claude.json
        cfg = Path.home() / ".claude.json"
        data: dict = {}
        if cfg.is_file():
            raw = cfg.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            data = {}
        projects = data.get("projects")
        if not isinstance(projects, dict):
            projects = {}
            data["projects"] = projects
        keys = {root}
        if os.name == "nt":
            keys.add(root.replace("\\", "/"))
        changed = False
        for key in keys:
            entry = projects.get(key)
            if not isinstance(entry, dict):
                entry = {}
            if entry.get("hasTrustDialogAccepted") is True:
                continue
            entry["hasTrustDialogAccepted"] = True
            projects[key] = entry
            changed = True
        if changed:
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        # 2) Suppress "Bypass Permissions mode / Yes, I accept" (same as accepting once).
        settings_path = Path.home() / ".claude" / "settings.json"
        settings: dict = {}
        if settings_path.is_file():
            sraw = settings_path.read_text(encoding="utf-8")
            settings = json.loads(sraw) if sraw.strip() else {}
        if not isinstance(settings, dict):
            settings = {}
        perms = settings.get("permissions")
        if not isinstance(perms, dict):
            perms = {}
            settings["permissions"] = perms
        s_changed = False
        if settings.get("skipDangerousModePermissionPrompt") is not True:
            settings["skipDangerousModePermissionPrompt"] = True
            s_changed = True
        if not perms.get("defaultMode"):
            perms["defaultMode"] = "bypassPermissions"
            s_changed = True
        if s_changed:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(
                json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("ensure_claude_workspace_trusted skipped: %s", exc)


def ensure_openclaw_config_ready() -> None:
    """Drop known-bad legacy keys so OpenClaw does not block on doctor Y/n."""
    cfg = Path.home() / ".openclaw" / "openclaw.json"
    try:
        import json

        if not cfg.is_file():
            return
        data = json.loads(cfg.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        changed = False
        meta = data.get("meta")
        if isinstance(meta, dict):
            for dead in ("lastTouchedAt", "lastTouchedVersion", "lastTouchedAtMs"):
                if dead in meta:
                    meta.pop(dead, None)
                    changed = True
        if changed:
            cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("ensure_openclaw_config_ready skipped: %s", exc)


def claude_tui_argv(
    prompt: str,
    *,
    binary: Optional[str] = None,
    permission_mode: Optional[str] = None,
    allowed_tools: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> list[str]:
    """Interactive Claude Code TUI (no ``-p/--print`` — that forces headless).

    Important: ``--allowed-tools`` is variadic (``<tools...>``). The prompt must
    not follow it as a separate argv token, or Claude will treat the prompt
    words as tool names (see ``Ignoring --allowedTools rule ...`` spam).
    """
    bin_path = binary or preview_binary("claude-code") or "claude"
    mode = (
        permission_mode
        or os.getenv("CLAUDE_CLI_TUI_PERMISSION_MODE")
        or os.getenv("CLAUDE_CLI_PERMISSION_MODE")
        or "bypassPermissions"
    ).strip()
    tools = allowed_tools
    if tools is None:
        tools = (
            os.getenv("CLAUDE_CLI_ALLOWED_TOOLS")
            or "WebSearch,WebFetch,Bash,Read,Edit,Write,Glob,Grep,Agent,Skill,TodoWrite"
        ).strip()
    argv = [bin_path, "--permission-mode", mode]
    if mode == "bypassPermissions":
        argv.append("--dangerously-skip-permissions")
    # Prefer single-token form so the prompt cannot be swallowed.
    if tools and tools.lower() not in {"-", "none", "off"}:
        argv.append(f"--allowed-tools={tools}")
    if extra_args:
        argv.extend(extra_args)
    # ``--`` ends option parsing; prompt is positional after that.
    argv.extend(["--", prompt])
    return argv


def pi_tui_argv(
    prompt: str,
    *,
    binary: Optional[str] = None,
    provider_args: Optional[list[str]] = None,
    system_args: Optional[list[str]] = None,
    extra_args: Optional[list[str]] = None,
) -> list[str]:
    """Interactive Pi TUI (no ``--print`` / ``--mode json``)."""
    bin_path = binary or preview_binary("pi") or "pi"
    argv = [bin_path]
    if provider_args:
        argv.extend(provider_args)
    if system_args:
        argv.extend(system_args)
    if extra_args:
        argv.extend(extra_args)
    argv.extend(["--", prompt])
    return argv


def openclaw_tui_argv(
    prompt: str,
    *,
    binary: Optional[str] = None,
    workspace: Optional[str] = None,
    session_key: Optional[str] = None,
    timeout_s: float | int | None = None,
    extra_args: Optional[list[str]] = None,
) -> list[str]:
    """Visible OpenClaw preview argv.

    Default is ``openclaw agent exec --cwd … --message-file …`` (isolated turn,
    no Gateway). Pair with **tee** (``interactive=False``) so the popup shows
    the stream and A2A still captures output.

    ``OPENCLAW_PREVIEW_UI=tui`` forces the chat TUI (often banner-only without a
    healthy Gateway). ``agent --local`` is avoided — it tends to print the
    witty banner and hang.
    """
    bin_path = binary or preview_binary("openclaw") or "openclaw"
    ensure_openclaw_config_ready()
    ui = (os.getenv("OPENCLAW_PREVIEW_UI") or "exec").strip().lower()
    root = Path(workspace).expanduser().resolve() if workspace else Path.cwd()
    prompt_file = root / "preview_prompt.md"
    seed = (
        "Read USER_GOAL.md and preview_prompt.md in the current working directory. "
        "Complete that task end-to-end. Write the final answer to output.md when done."
    )
    _ = session_key

    if ui in {"tui", "chat", "terminal"}:
        argv = [bin_path, "tui", "--local", "--message", seed]
        if session_key:
            argv.extend(["--session", str(session_key)])
        if extra_args:
            argv.extend(extra_args)
        return argv

    # Reliable path: isolated exec turn (works offline / without Gateway).
    argv = [bin_path, "agent", "exec", "--cwd", str(root)]
    if prompt_file.is_file():
        argv.extend(["--message-file", str(prompt_file)])
    else:
        body = (prompt or "").strip() or seed
        if len(body) > 3500:
            body = body[:3500] + "\n…(truncated; see preview_prompt.md)"
        argv.append(body)
    model = (os.getenv("OPENCLAW_MODEL") or "").strip()
    if model:
        argv.extend(["--model", model])
    to = timeout_s if timeout_s is not None else os.getenv("OPENCLAW_AGENT_TIMEOUT_S")
    if to:
        try:
            argv.extend(["--timeout", str(int(float(to)))])
        except (TypeError, ValueError):
            pass
    if extra_args:
        skip = {"--json", "--local", "--verbose", "on", "tui"}
        argv.extend(a for a in extra_args if a not in skip)
    return argv


def hermes_tui_argv(
    prompt: str,
    *,
    binary: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    toolsets: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> list[str]:
    """Hermes live-preview argv.

    Default is top-level oneshot ``hermes -z … --yolo`` (pair with tee). Avoid
    ``hermes chat`` on many Windows installs — it imports a shadowed ``cli``
    package and crashes with ``ImportError: cannot import name 'main' from 'cli'``.

    ``HERMES_PREVIEW_UI=tui`` → modern TUI with a short ``-z`` seed.
    ``HERMES_PREVIEW_UI=chat`` → ``hermes chat -q`` (may be broken if ``cli`` conflicts).
    """
    bin_path = binary or preview_binary("hermes") or "hermes"
    ui = (os.getenv("HERMES_PREVIEW_UI") or "oneshot").strip().lower()
    short_seed = (
        "Read USER_GOAL.md and preview_prompt.md in the working directory. "
        "Complete that task end-to-end (research with tools if needed). "
        "Write the final answer to output.md when finished."
    )
    body = (prompt or "").strip()
    query = short_seed if (not body or len(body) > 4000) else body

    def _model_flags() -> list[str]:
        out: list[str] = []
        if model:
            out.extend(["-m", model])
        if provider:
            out.extend(["--provider", provider])
        if toolsets:
            out.extend(["-t", toolsets])
        if extra_args:
            out.extend(extra_args)
        return out

    if ui in {"tui", "repl"}:
        return [bin_path, "--tui", "--yolo", "--accept-hooks", *_model_flags(), "-z", short_seed]

    if ui in {"chat", "chat-q"}:
        return [bin_path, "chat", "--yolo", "--accept-hooks", "-v", *_model_flags(), "-q", query]

    # Default: top-level oneshot (does not go through hermes_cli.cmd_chat → cli.main).
    return [bin_path, "--yolo", "--accept-hooks", *_model_flags(), "-z", query]


def looks_like_cli_crash(text: str) -> Optional[str]:
    """Return a short error if stdout/stderr looks like a hard CLI failure."""
    low = (text or "").lower()
    if "importerror" in low or "cannot import name" in low:
        return "hermes/cli ImportError (conflicting Python package named 'cli'?)"
    if "no inference provider configured" in low or "no api keys or providers found" in low:
        return "hermes not configured (run `hermes setup` / set API keys in ~/.hermes/.env)"
    if "no route-compatible authentication source" in low:
        return "openclaw auth missing for configured model (set provider API key / OPENCLAW_MODEL)"
    if "traceback (most recent call last)" in low and "error:" in low:
        # Grab last Error line if present.
        for line in reversed((text or "").splitlines()):
            s = line.strip()
            if s.lower().startswith("error:") or "Error:" in s:
                return s[:300]
        return "CLI crashed (see preview.log traceback)"
    return None


def build_preview_user_prompt(
    user_goal: str,
    *,
    system: str = "",
    skill_id: str = "",
) -> str:
    """Lead with the concrete user goal so TUI agents do not treat system titles as the task.

    System guidance is secondary; empty workspaces are called out as OK.
    """
    goal = (user_goal or "").strip()
    guide = (system or "").strip()
    parts: list[str] = [
        "## User goal (complete this end-to-end)",
        goal or "(empty goal)",
        "",
        "## Constraints",
        "- The working directory may be empty; that is normal — do not scaffold a project unless the goal asks for it.",
        "- Prefer web/search/tool use when the goal requires research or public information.",
        "- Deliver the final answer (summary/report) directly; do not ask clarifying questions unless the goal is impossible.",
        "- Do not reinterpret agent/profile names (e.g. \"DeepSeek Harness\") as the task title.",
        "- When finished, write the final answer to `output.md` in the working directory (overwrite OK).",
        "- If this prompt looks truncated, read `preview_prompt.md` / `USER_GOAL.md` in the working directory.",
    ]
    if skill_id:
        parts.extend(["", f"(skill={skill_id})"])
    if guide:
        parts.extend(["", "## Secondary guidance (do not override the user goal)", guide])
    return "\n".join(parts)


def extract_codewhale_final_text(raw_stream: str) -> str:
    """Pull the human-visible final answer from a CodeWhale ``stream-json`` transcript.

    Prefers ``metadata.meta.visible_final_answer_excerpt``, then the last non-JSON
    prose block. Falls back to empty string (caller may keep a short fallback).
    """
    import json
    import re

    text = raw_stream or ""
    if not text.strip():
        return ""

    # 1) Prefer structured metadata from the stream.
    excerpt = ""
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("{"):
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        meta = obj.get("meta") if obj.get("type") == "metadata" else None
        if not isinstance(meta, dict):
            meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else None
        if isinstance(meta, dict):
            cand = meta.get("visible_final_answer_excerpt") or meta.get("visible_final_answer")
            if isinstance(cand, str) and cand.strip():
                excerpt = cand.strip()
        # Some builds nest under payload
        if not excerpt and isinstance(obj.get("payload"), dict):
            cand = obj["payload"].get("visible_final_answer_excerpt")
            if isinstance(cand, str) and cand.strip():
                excerpt = cand.strip()
    if excerpt:
        return excerpt

    # 2) Last contiguous non-JSON prose block (assistant reply printed between events).
    prose_chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if current:
                current.append("")
            continue
        if s.startswith("{") and s.endswith("}"):
            if current:
                prose_chunks.append("\n".join(current).strip())
                current = []
            continue
        # Skip redacted session markers / bare tokens
        if s.startswith("<redacted:") or s in {"done", "[done]"}:
            continue
        current.append(line.rstrip())
    if current:
        prose_chunks.append("\n".join(current).strip())
    for block in reversed(prose_chunks):
        if len(block) >= 40:
            # Drop leading stream noise if any
            cleaned = re.sub(r"^\{[^\n]*\}\s*", "", block, count=1).strip()
            if cleaned:
                return cleaned
    if prose_chunks:
        return prose_chunks[-1]
    return ""


async def spawn_preview_run(
    supervisor: ProcessSupervisor,
    task_id: str,
    *,
    cwd: str,
    argv: list[str],
    log_path: Optional[str | Path] = None,
    env: Optional[dict[str, str]] = None,
) -> tuple[ManagedProcess, Path]:
    """Spawn ``preview_tee`` in a new console; return (managed_proc, log_path)."""
    log = Path(log_path) if log_path else preview_log_path(cwd)
    log.parent.mkdir(parents=True, exist_ok=True)
    # Truncate previous run log so tail starts clean.
    log.write_bytes(b"")

    tee_argv = [
        sys.executable,
        "-m",
        "agent_runtime.harness.preview_tee",
        "--log",
        str(log),
        "--",
        *argv,
    ]
    mp = await supervisor.spawn(
        task_id,
        *tee_argv,
        env=env,
        cwd=cwd,
        new_console=True,
    )
    return mp, log


async def tail_preview_log(
    log_path: Path,
    *,
    proc: asyncio.subprocess.Process,
    on_line: OnLine,
    poll_s: float = 0.15,
) -> str:
    """Follow ``preview.log`` until ``proc`` exits; invoke ``on_line`` per line.

    Returns the full decoded log text.
    """
    pos = 0
    buf = ""
    chunks: list[str] = []

    while True:
        try:
            data = log_path.read_bytes()
        except OSError:
            data = b""
        if len(data) > pos:
            piece = data[pos:]
            pos = len(data)
            text = piece.decode("utf-8", errors="replace")
            buf += text
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line_out = line + "\n"
                chunks.append(line_out)
                maybe = on_line(line_out)
                if asyncio.iscoroutine(maybe):
                    await maybe
        if proc.returncode is not None:
            # Final flush
            if buf:
                chunks.append(buf)
                maybe = on_line(buf)
                if asyncio.iscoroutine(maybe):
                    await maybe
                buf = ""
            break
        await asyncio.sleep(poll_s)

    return "".join(chunks)


def should_use_live_preview() -> bool:
    """True when preview is requested and a desktop session is available."""
    if not live_preview_enabled():
        return False
    if not desktop_preview_available():
        logger.warning(
            "HARNESS_LIVE_PREVIEW is set but no desktop session detected; "
            "falling back to headless execution"
        )
        return False
    return True


def _collect_preview_artifacts(cwd: str | Path) -> str:
    """Prefer ``output.md`` written by the agent; else any leftover preview.log."""
    text = collect_preview_artifacts(cwd)
    if text:
        return text
    log = preview_log_path(cwd)
    try:
        if log.is_file():
            return log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


async def run_interactive_preview_and_collect(
    supervisor: ProcessSupervisor,
    task_id: str,
    *,
    cwd: str,
    argv: list[str],
    env: Optional[dict[str, str]] = None,
    timeout_s: float = 1800.0,
) -> tuple[Optional[int], str, bool]:
    """Spawn CodeWhale (or other TUI) **directly** in a new console — no stdout PIPE.

    ``preview_tee`` must not wrap interactive CLIs: piping destroys the TUI and
    forces a plain tool-transcript dump.
    """
    log = preview_log_path(cwd)
    try:
        log.write_text(
            "[aop-preview] interactive TUI mode (no stdout tee)\n"
            f"[aop-preview] cwd={cwd}\n"
            f"[aop-preview] exec: {' '.join(argv[:8])}{' ...' if len(argv) > 8 else ''}\n",
            encoding="utf-8",
        )
    except OSError:
        pass

    mp = await supervisor.spawn(
        task_id,
        *argv,
        env=env,
        cwd=cwd,
        new_console=True,
    )
    killed = False
    try:
        try:
            await asyncio.wait_for(mp.proc.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            await supervisor.cancel(task_id)
            killed = True
        killed = killed or bool(getattr(mp, "_killed", False))
        text = _collect_preview_artifacts(cwd)
        return mp.returncode, text, killed
    finally:
        await supervisor.unregister(task_id)


async def run_preview_and_collect(
    supervisor: ProcessSupervisor,
    task_id: str,
    *,
    cwd: str,
    argv: list[str],
    env: Optional[dict[str, str]] = None,
    timeout_s: float = 1800.0,
    on_line: Optional[OnLine] = None,
    interactive: Optional[bool] = None,
) -> tuple[Optional[int], str, bool]:
    """Spawn live preview until exit.

    Returns ``(returncode, full_log_text, was_killed)``.

    When ``interactive`` is True (or default TUI mode), spawns the CLI directly
    so CodeWhale can render its real UI. Otherwise uses ``preview_tee``.
    """
    use_tui = interactive if interactive is not None else (harness_preview_mode() == "tui")
    # Detect headless argv even if caller forgot the flag.
    if use_tui and len(argv) >= 2 and argv[1] in {"exec", "agent"}:
        # openclaw agent exec / codewhale exec → must tee
        if argv[1] == "exec" or (argv[1] == "agent" and len(argv) >= 3 and argv[2] == "exec"):
            use_tui = False
    if use_tui and "-p" in argv and "--output-format" in argv:
        # claude -p --output-format stream-json is headless print mode
        use_tui = False
    if use_tui and "--print" in argv:
        use_tui = False
    if use_tui and "--mode" in argv:
        try:
            mi = argv.index("--mode")
            if mi + 1 < len(argv) and argv[mi + 1] in {"json", "rpc"}:
                use_tui = False
        except ValueError:
            pass
    if use_tui:
        return await run_interactive_preview_and_collect(
            supervisor,
            task_id,
            cwd=cwd,
            argv=argv,
            env=env,
            timeout_s=timeout_s,
        )

    async def _noop(_line: str) -> None:
        return None

    handler = on_line or _noop
    mp, log = await spawn_preview_run(
        supervisor, task_id, cwd=cwd, argv=argv, env=env
    )
    killed = False
    try:
        text_task = asyncio.create_task(
            tail_preview_log(log, proc=mp.proc, on_line=handler)
        )
        try:
            await asyncio.wait_for(mp.proc.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            await supervisor.cancel(task_id)
            killed = True
            try:
                await asyncio.wait_for(text_task, timeout=2.0)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                text_task.cancel()
            raw = ""
            try:
                raw = log.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
            return mp.returncode, raw, True
        text = await text_task
        killed = bool(getattr(mp, "_killed", False))
        return mp.returncode, text, killed
    finally:
        await supervisor.unregister(task_id)


__all__ = [
    "build_preview_user_prompt",
    "claude_tui_argv",
    "collect_preview_artifacts",
    "deepseek_preview_argv",
    "deepseek_preview_mode",
    "desktop_preview_available",
    "ensure_claude_workspace_trusted",
    "ensure_openclaw_config_ready",
    "extract_codewhale_final_text",
    "harness_preview_mode",
    "hermes_tui_argv",
    "live_preview_enabled",
    "openclaw_tui_argv",
    "pi_tui_argv",
    "prepare_preview_workspace",
    "preview_binary",
    "preview_log_path",
    "run_interactive_preview_and_collect",
    "run_preview_and_collect",
    "should_use_live_preview",
    "spawn_preview_run",
    "tail_preview_log",
]
