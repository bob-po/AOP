"""Phase 2.1 — governance context on the A2A wire.

Verifies that visited_agents / governance_policy_id / deadline / caller & target
identity survive Message serialization (to_dict -> from_dict) and are emitted by
A2AClient.send_text at both the nested-message and top-params level, so they can
propagate across a real process boundary.
"""

from a2a_sdk.client import A2AClient
from a2a_sdk.models import Message, Part


def test_message_wire_roundtrip_carries_governance_context():
    msg = Message(
        role="user",
        parts=[Part(type="text", text="hi")],
        correlation_id="corr-1",
        parent_task_id="task-p",
        root_task_id="task-root",
        depth=2,
        caller_agent_id="agent-a",
        target_agent_id="agent-b",
        visited_agents=["agent-a", "agent-b"],
        governance_policy_id="policy-default",
        deadline="2026-01-01T00:00:00+00:00",
    )
    wire = msg.to_dict()
    assert wire["metadata"]["visitedAgents"] == ["agent-a", "agent-b"]
    assert wire["metadata"]["governancePolicyId"] == "policy-default"
    assert wire["metadata"]["deadline"] == "2026-01-01T00:00:00+00:00"
    # Top-level mirrors are no longer written:
    assert "visitedAgents" not in wire
    assert "callerAgentId" not in wire
    assert "targetAgentId" not in wire

    back = Message.from_dict(wire)
    assert back.visited_agents == ["agent-a", "agent-b"]
    assert back.governance_policy_id == "policy-default"
    assert back.deadline == "2026-01-01T00:00:00+00:00"
    assert back.depth == 2
    assert back.caller_agent_id == "agent-a"


def test_message_from_dict_still_accepts_legacy_top_level():
    """Inbound compat: old agents may still send top-level governance fields."""
    back = Message.from_dict(
        {
            "role": "user",
            "parts": [{"kind": "text", "text": "hi"}],
            "visitedAgents": ["agent-a"],
            "callerAgentId": "agent-a",
            "correlationId": "corr-legacy",
        }
    )
    assert back.visited_agents == ["agent-a"]
    assert back.caller_agent_id == "agent-a"
    assert back.correlation_id == "corr-legacy"



def test_send_text_emits_governance_context_on_params():
    captured = {}

    client = A2AClient("http://agent-b:8000/", card=None)

    def fake_rpc(method, params):
        captured["method"] = method
        captured["params"] = params
        return {"id": "t1", "status": "completed"}

    client._rpc = fake_rpc
    client.send_text(
        "delegate this",
        skill_id="knowledge-search",
        correlation_id="corr-9",
        root_task_id="root-9",
        parent_task_id="p-9",
        depth=1,
        caller_agent_id="agent-a",
        target_agent_id="agent-b",
        visited_agents=["agent-a"],
        governance_policy_id="policy-x",
        deadline="2026-01-01T00:00:00+00:00",
        callback_url="http://cb/done",
    )
    assert captured["method"] == "message/send"
    params = captured["params"]
    # Preferred home: params.metadata (official extension surface)
    meta = params["metadata"]
    assert meta["visitedAgents"] == ["agent-a"]
    assert meta["governancePolicyId"] == "policy-x"
    assert meta["deadline"] == "2026-01-01T00:00:00+00:00"
    assert meta["callerAgentId"] == "agent-a"
    assert meta["targetAgentId"] == "agent-b"
    assert meta["correlationId"] == "corr-9"
    assert meta["depth"] == 1
    assert meta["callbackUrl"] == "http://cb/done"
    assert meta["pushNotificationConfig"]["url"] == "http://cb/done"
    # Top-level mirrors are no longer dual-written:
    assert "visitedAgents" not in params
    assert "callbackUrl" not in params
    # Nested message metadata carries the same context:
    assert params["message"]["metadata"]["visitedAgents"] == ["agent-a"]
    assert params["message"]["metadata"]["governancePolicyId"] == "policy-x"
    assert params["message"]["metadata"]["callbackUrl"] == "http://cb/done"
