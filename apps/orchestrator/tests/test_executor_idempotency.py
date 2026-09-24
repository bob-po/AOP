"""Tests for executor idempotency (P36.1)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

# Import executor components
try:
    from executor import A2AExecutor, ExecutionResult
    from a2a_sdk import Task, TaskStatus
    EXECUTOR_AVAILABLE = True
except ImportError:
    EXECUTOR_AVAILABLE = False
    pytest.skip("Executor not available", allow_module_level=True)


@pytest.fixture
def mock_a2a_client():
    """Mock A2A client."""
    client = MagicMock()
    card = MagicMock()
    card.name = "test-agent"
    client.card = card
    return client


@pytest.fixture
def mock_task():
    """Mock A2A task."""
    return Task(
        id=str(uuid.uuid4()),
        status=TaskStatus.COMPLETED,
        artifacts=[],
    )


class TestExecutorIdempotency:
    """Test executor idempotency functionality."""

    def test_execute_generates_idempotency_key(self, mock_a2a_client, mock_task):
        """Test that execute generates idempotency key when not provided."""
        with patch("executor.A2AClient", return_value=mock_a2a_client):
            with patch("executor.guard_call", return_value=("test query", 60.0)):
                with patch("executor.A2AExecutor._get_request_tracking_service", return_value=None):
                    mock_a2a_client.send_text.return_value = mock_task

                    executor = A2AExecutor()
                    result = executor.execute("http://test.agent", "test query")

                    # Verify idempotency key was passed to send_text
                    mock_a2a_client.send_text.assert_called_once()
                    call_kwargs = mock_a2a_client.send_text.call_args[1]
                    assert "idempotency_key" in call_kwargs
                    assert call_kwargs["idempotency_key"].startswith("req_")

    def test_execute_uses_provided_idempotency_key(self, mock_a2a_client, mock_task):
        """Test that execute uses provided idempotency key."""
        provided_key = "custom_key_123"

        with patch("executor.A2AClient", return_value=mock_a2a_client):
            with patch("executor.guard_call", return_value=("test query", 60.0)):
                with patch("executor.A2AExecutor._get_request_tracking_service", return_value=None):
                    mock_a2a_client.send_text.return_value = mock_task

                    executor = A2AExecutor()
                    result = executor.execute(
                        "http://test.agent",
                        "test query",
                        idempotency_key=provided_key,
                    )

                    # Verify provided key was used
                    mock_a2a_client.send_text.assert_called_once()
                    call_kwargs = mock_a2a_client.send_text.call_args[1]
                    assert call_kwargs["idempotency_key"] == provided_key

    def test_execute_returns_cached_response(self, mock_a2a_client, mock_task):
        """Test that execute returns cached response when request already completed."""
        idempotency_key = "cached_key_123"
        cached_response = {
            "agent_name": "cached-agent",
            "task": {"id": mock_task.id, "status": "completed", "artifacts": []},
            "text": "cached result",
            "data": {"cached": True},
        }
        
        with patch("executor.A2AClient", return_value=mock_a2a_client):
            with patch("executor.guard_call", return_value=("test query", 60.0)):
                # Mock request tracking service
                mock_service = MagicMock()
                mock_service.is_request_completed.return_value = True
                mock_service.get_cached_response.return_value = cached_response
                
                with patch("executor.A2AExecutor._get_request_tracking_service", return_value=mock_service):
                    executor = A2AExecutor()
                    result = executor.execute(
                        "http://test.agent",
                        "test query",
                        idempotency_key=idempotency_key,
                    )
                    
                    # Verify cached response was returned
                    assert result.agent_name == "cached-agent"
                    assert result.text == "cached result"
                    assert result.data == {"cached": True}
                    
                    # Verify A2A call was NOT made (cached response used)
                    mock_a2a_client.send_text.assert_not_called()

    def test_execute_proceeds_without_cache(self, mock_a2a_client, mock_task):
        """Test that execute proceeds normally when request not cached."""
        idempotency_key = "new_key_123"
        
        with patch("executor.A2AClient", return_value=mock_a2a_client):
            with patch("executor.guard_call", return_value=("test query", 60.0)):
                # Mock request tracking service (not completed)
                mock_service = MagicMock()
                mock_service.is_request_completed.return_value = False
                mock_service.get_cached_response.return_value = None
                
                with patch("executor.A2AExecutor._get_request_tracking_service", return_value=mock_service):
                    mock_a2a_client.send_text.return_value = mock_task
                    
                    executor = A2AExecutor()
                    result = executor.execute(
                        "http://test.agent",
                        "test query",
                        idempotency_key=idempotency_key,
                    )
                    
                    # Verify A2A call was made (not cached)
                    mock_a2a_client.send_text.assert_called_once()
                    call_kwargs = mock_a2a_client.send_text.call_args[1]
                    assert call_kwargs["idempotency_key"] == idempotency_key

    def test_execute_without_request_tracking(self, mock_a2a_client, mock_task):
        """Test that execute works normally when request tracking not available."""
        with patch("executor.A2AClient", return_value=mock_a2a_client):
            with patch("executor.guard_call", return_value=("test query", 60.0)):
                # Mock no request tracking service
                with patch("executor.A2AExecutor._get_request_tracking_service", return_value=None):
                    mock_a2a_client.send_text.return_value = mock_task
                    
                    executor = A2AExecutor()
                    result = executor.execute("http://test.agent", "test query")
                    
                    # Verify A2A call was made normally
                    mock_a2a_client.send_text.assert_called_once()
                    # Idempotency key should still be generated
                    call_kwargs = mock_a2a_client.send_text.call_args[1]
                    assert "idempotency_key" in call_kwargs
