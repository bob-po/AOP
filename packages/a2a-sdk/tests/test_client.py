import pytest
import httpx
from a2a_sdk.client import A2AClient, A2AError
from a2a_sdk.models import Message, Part, Task, TaskStatus


class MockAgent:
    def __init__(self):
        self.requests = []
        self.responses = []

    def add_response(self, response_data, response_id=None):
        self.responses.append((response_data, response_id))

    def __call__(self, method, params):
        self.requests.append((method, params))
        if self.responses:
            response_data, response_id = self.responses.pop(0)
            return {
                "jsonrpc": "2.0",
                "result": response_data,
                "id": response_id or str(len(self.requests))
            }
        return {"jsonrpc": "2.0", "error": {"message": "No response", "code": -1}, "id": "1"}


def test_send_text():
    mock_agent = MockAgent()
    mock_agent.add_response({
        "id": "task1",
        "status": "completed",
        "artifacts": [],
        "history": [],
        "metadata": {},
        "error": None,
        "parent_task_id": None,
        "root_task_id": None,
        "correlation_id": "corr1",
        "caller_agent_id": None,
        "target_agent_id": None,
        "depth": 0
    }, response_id="task1")

    client = A2AClient("http://test-agent", card=None)
    # Mock _rpc to extract result from JSON-RPC response
    client._rpc = lambda method, params: mock_agent(method, params).get("result")

    task = client.send_text("test message", skill_id="test-skill", correlation_id="corr1")

    assert task.id == "task1"
    assert task.status == TaskStatus.COMPLETED
    assert task.correlation_id == "corr1"


def test_send_message():
    mock_agent = MockAgent()
    mock_agent.add_response({
        "id": "task2",
        "status": "working",
        "artifacts": [],
        "history": [],
        "metadata": {},
        "error": None,
        "parent_task_id": "parent1",
        "root_task_id": "root1",
        "correlation_id": "corr2",
        "caller_agent_id": "caller1",
        "target_agent_id": "target1",
        "depth": 1
    }, response_id="task2")

    client = A2AClient("http://test-agent", card=None)
    # Mock _rpc to extract result from JSON-RPC response
    client._rpc = lambda method, params: mock_agent(method, params).get("result")

    message = Message(
        role="user",
        parts=[Part(type="text", text="test")],
        message_id="msg1",
        idempotency_key="idemp1",
        correlation_id="corr2",
        parent_task_id="parent1",
        root_task_id="root1",
        depth=1
    )

    task = client.send_message(message, skill_id="test-skill")

    assert task.id == "task2"
    assert task.status == TaskStatus.WORKING
    assert task.parent_task_id == "parent1"
    assert task.root_task_id == "root1"
    assert task.correlation_id == "corr2"
    assert task.caller_agent_id == "caller1"
    assert task.target_agent_id == "target1"
    assert task.depth == 1


def test_cancel_task():
    mock_agent = MockAgent()
    mock_agent.add_response(True, response_id="cancel1")

    client = A2AClient("http://test-agent", card=None)
    # Mock _rpc to extract result from JSON-RPC response
    client._rpc = lambda method, params: mock_agent(method, params).get("result")

    result = client.cancel_task("task1")

    assert result is True


def test_cancel_task_accepts_task_dict():
    client = A2AClient("http://test-agent", card=None)
    client._rpc = lambda method, params: {
        "id": params["id"],
        "status": {"state": "canceled"},
        "artifacts": [],
    }
    assert client.cancel_task("task-os-root") is True


def test_delegate_task_removed():
    from a2a_sdk.client import A2AError

    client = A2AClient("http://test-agent", card=None)
    try:
        client.delegate_task("task1", "target-agent")
        assert False, "expected A2AError"
    except A2AError as exc:
        assert exc.code == -32601
        assert "delegate" in str(exc).lower()


def test_stream_tasks_removed():
    from a2a_sdk.client import A2AError

    client = A2AClient("http://test-agent", card=None)
    try:
        client.stream_tasks(skill_id="test-skill")
        assert False, "expected A2AError"
    except A2AError as exc:
        assert exc.code == -32601
        assert "subscribe" in str(exc).lower() or "stream" in str(exc).lower()


if __name__ == "__main__":
    pytest.main([__file__])