"""Live terminal preview: tee CLI stdout/stderr to console + log file.

Invoked as::

    python -m agent_runtime.harness.preview_tee --log <path> -- <argv...>

When launched with Windows ``CREATE_NEW_CONSOLE``, this process's stdio must be
attached to that console (parent must not redirect to DEVNULL/PIPE).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _tee_stream(stream, log_fp, console_fp) -> None:
    if stream is None:
        return
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            try:
                log_fp.write(chunk)
                log_fp.flush()
            except OSError:
                pass
            try:
                buf = getattr(console_fp, "buffer", None)
                if buf is not None:
                    buf.write(chunk)
                    buf.flush()
                else:
                    console_fp.write(chunk.decode("utf-8", errors="replace"))
                    console_fp.flush()
            except OSError:
                pass
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="preview_tee", add_help=True)
    parser.add_argument("--log", required=True, help="Path to preview.log")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command after --")
    args = parser.parse_args(argv)

    cmd = list(args.cmd or [])
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("preview_tee: missing command after --", file=sys.stderr)
        return 2

    log_path = Path(args.log).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Windows: allow .cmd/.bat via cmd /c
    if sys.platform == "win32" and cmd:
        head = cmd[0].lower()
        if head.endswith((".cmd", ".bat")):
            cmd = ["cmd.exe", "/c", *cmd]

    # Make the new console useful immediately.
    try:
        title = "AOP live preview"
        if len(cmd) >= 1:
            title = f"AOP preview · {Path(cmd[0]).stem}"
        if sys.platform == "win32":
            os.system(f"title {title}")  # noqa: S605 — local console title only
        print(f"[aop-preview] cwd={os.getcwd()}", flush=True)
        print(f"[aop-preview] log={log_path}", flush=True)
        print(f"[aop-preview] exec: {' '.join(cmd[:6])}{' ...' if len(cmd) > 6 else ''}", flush=True)
        print("-" * 60, flush=True)
    except OSError:
        pass

    # Line-buffer Python prints; child still binary-tee'd.
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass

    with log_path.open("ab", buffering=0) as log_fp:
        # Child inherits nothing special; we PIPE so we can tee to THIS console + log.
        # This process's stdout/stderr must be the visible console (parent inherits).
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env=os.environ.copy(),
            bufsize=0,
        )
        assert proc.stdout is not None and proc.stderr is not None

        import threading

        t_out = threading.Thread(
            target=_tee_stream, args=(proc.stdout, log_fp, sys.stdout), daemon=True
        )
        t_err = threading.Thread(
            target=_tee_stream, args=(proc.stderr, log_fp, sys.stderr), daemon=True
        )
        t_out.start()
        t_err.start()
        rc = proc.wait()
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        print("-" * 60, flush=True)
        print(f"[aop-preview] exit={rc}", flush=True)
        return int(rc if rc is not None else 1)


if __name__ == "__main__":
    raise SystemExit(main())
