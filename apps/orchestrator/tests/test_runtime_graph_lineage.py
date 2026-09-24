"""Phase 2 — branch_lineage limited revisits + collaboration_graph shaping."""

from __future__ import annotations

from runtime_graph import RuntimeGraphService


def test_branch_lineage_counts_limited_revisits(monkeypatch):
    svc = RuntimeGraphService.__new__(RuntimeGraphService)
    edges = [
        {
            "id": 1,
            "root_task_id": "root",
            "parent_task_id": None,
            "task_id": "t-b",
            "correlation_id": "c",
            "caller_agent_id": "agent-a",
            "target_agent_id": "agent-b",
            "skill": "s",
            "depth": 1,
            "status": "completed",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "id": 2,
            "root_task_id": "root",
            "parent_task_id": "t-b",
            "task_id": "t-a2",
            "correlation_id": "c",
            "caller_agent_id": "agent-b",
            "target_agent_id": "agent-a",
            "skill": "s2",
            "depth": 2,
            "status": "completed",
            "created_at": "2026-01-01T00:00:01+00:00",
        },
    ]
    monkeypatch.setattr(svc, "list_edges", lambda root, limit=500: edges)

    lin = svc.branch_lineage("root", "t-a2")
    assert lin["agent_chain"] == ["agent-a", "agent-b", "agent-a"]
    assert lin["agent_visits"]["agent-a"] == 2
    assert lin["agent_visits"]["agent-b"] == 1


def test_collaboration_graph_shapes_nodes_and_links(monkeypatch):
    svc = RuntimeGraphService.__new__(RuntimeGraphService)
    edges = [
        {
            "id": 1,
            "root_task_id": "root",
            "parent_task_id": None,
            "task_id": "t-b",
            "caller_agent_id": "agent-a",
            "target_agent_id": "agent-b",
            "skill": "s",
            "depth": 1,
            "status": "completed",
            "correlation_id": "c",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    monkeypatch.setattr(svc, "list_edges", lambda root, limit=500: edges)
    g = svc.collaboration_graph("root")
    assert g["kind"] == "collaboration_graph"
    assert g["link_count"] == 1
    assert any(n["type"] == "agent" and n["id"] == "agent-a" for n in g["nodes"])
    assert any(n["type"] == "task" for n in g["nodes"])
    assert g["links"][0]["source"] == "agent-a"
    assert g["links"][0]["target"] == "agent-b"
