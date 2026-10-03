"""Shareable task package (zip + markdown report)."""

from __future__ import annotations

import io
import zipfile

from artifacts.package import (
    build_citations,
    build_package_zip,
    build_run_report_markdown,
)


def test_report_includes_goal_agents_and_eval():
    task = {
        "id": "abc-123",
        "title": "Research",
        "status": "completed",
        "input_json": {"content": "Write a brief"},
        "nodes": [{"id": "n1", "agent_key": "claude-code", "agent_name": "Claude Code"}],
        "created_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:12Z",
    }
    cites = build_citations(
        task,
        artifacts=[{"name": "output.md", "url": "http://x/output.md", "uri": "s3://b/k"}],
        events=[{"event_type": "task.completed", "message": "ok", "ts": "2026-01-01T00:00:12Z"}],
        evaluation={"score": 81.6, "grade": "B"},
    )
    md = build_run_report_markdown(cites)
    assert "abc-123" in md
    assert "Write a brief" in md
    assert "claude-code" in md
    assert "B" in md
    assert "output.md" in md
    assert "task.completed" in md


def test_zip_contains_report_citations_and_files():
    data = build_package_zip(
        {"id": "t9", "status": "completed", "title": "t"},
        artifacts=[{"name": "output.md", "uri": "s3://a/b", "node_id": "hop"}],
        events=[],
        evaluation=None,
        fetch_bytes=lambda uri: b"hello artifact",
    )
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = set(zf.namelist())
    assert "run-report.md" in names
    assert "citations.json" in names
    assert "manifest.json" in names
    assert "artifacts/hop/output.md" in names
    assert zf.read("artifacts/hop/output.md") == b"hello artifact"


def test_zip_skips_unreadable_artifacts():
    data = build_package_zip(
        {"id": "t9"},
        artifacts=[{"name": "gone.bin", "uri": "s3://missing"}],
        fetch_bytes=lambda uri: None,
    )
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "run-report.md" in names
    assert not any(n.startswith("artifacts/") for n in names)
