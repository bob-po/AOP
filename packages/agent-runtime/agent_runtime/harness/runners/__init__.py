"""Built-in harness runners."""

from .claude_cli import ClaudeCliRunner, parse_stream_json_line
from .pi_cli import PiCliRunner, parse_pi_jsonl_line
from .deepseek import DeepSeekHarnessRunner

__all__ = [
    "ClaudeCliRunner",
    "parse_stream_json_line",
    "PiCliRunner",
    "parse_pi_jsonl_line",
    "DeepSeekHarnessRunner",
]


def create_runner(name: str | None = None):
    """Factory: ``claude_cli`` | ``pi_cli`` | ``deepseek`` (aliases accepted)."""
    key = (name or "claude_cli").lower().replace("-", "_")
    if key in {"claude", "claude_cli", "claude_code"}:
        return ClaudeCliRunner()
    if key in {"pi", "pi_cli", "pi_coding_agent"}:
        return PiCliRunner()
    if key in {"deepseek", "dsh", "deepseek_harness", "deepseek_cli"}:
        return DeepSeekHarnessRunner()
    raise ValueError(f"Unsupported harness runner: {name!r}")
