"""Simplified tests for request tracking service (P36.1 idempotency)."""

from __future__ import annotations

import uuid

import pytest

# Import request tracking service
try:
    from request_tracking import RequestTrackingService, get_request_tracking_service
    REQUEST_TRACKING_AVAILABLE = True
except ImportError:
    REQUEST_TRACKING_AVAILABLE = False
    pytest.skip("Request tracking not available", allow_module_level=True)


@pytest.fixture
def tracking_service(database_url):
    """Create a request tracking service for testing."""
    if not REQUEST_TRACKING_AVAILABLE:
        pytest.skip("Request tracking not available")
    return RequestTrackingService(database_url=database_url)


class TestRequestTrackingSimple:
    """Simplified tests for request tracking service."""

    def test_generate_idempotency_key(self, tracking_service):
        """Test idempotency key generation."""
        key1 = tracking_service.generate_idempotency_key()
        key2 = tracking_service.generate_idempotency_key()
        
        assert key1 != key2
        assert key1.startswith("req_")
        assert key2.startswith("req_")
    
    def test_get_nonexistent_request(self, tracking_service):
        """Test getting a request that doesn't exist."""
        idempotency_key = tracking_service.generate_idempotency_key()
        
        result = tracking_service.get_request(idempotency_key)
        assert result is None
    
    def test_is_request_completed_nonexistent(self, tracking_service):
        """Test checking completion for nonexistent request."""
        idempotency_key = tracking_service.generate_idempotency_key()
        
        assert tracking_service.is_request_completed(idempotency_key) is False
    
    def test_get_cached_response_nonexistent(self, tracking_service):
        """Test getting cached response for nonexistent request."""
        idempotency_key = tracking_service.generate_idempotency_key()
        
        result = tracking_service.get_cached_response(idempotency_key)
        assert result is None


class TestRequestTrackingIntegration:
    """Integration tests that require full database setup."""
    
    @pytest.fixture
    def full_test_data(self, database_url):
        """Create minimal test data in database."""
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
        
        tenant_id = "00000000-0000-0000-0000-000000000001"
        task_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())
        agent_id = str(uuid.uuid4())
        agent_key = f"test-agent-integration-{agent_id[:8]}"
        
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                # Create agent
                conn.execute(
                    """
                    INSERT INTO agents (
                      id, tenant_id, agent_key, name, protocol, status, 
                      created_at, updated_at
                    ) VALUES (
                      %s::uuid, %s::uuid, %s, %s, %s, %s, now(), now()
                    )
                    """,
                    (agent_id, tenant_id, agent_key, "Test Agent Integration", "A2A", "active"),
                )
                
                # Create task
                conn.execute(
                    """
                    INSERT INTO tasks (
                      id, tenant_id, title, input_json, status, progress,
                      plan_json, created_at, updated_at, started_at
                    ) VALUES (
                      %s::uuid, %s::uuid, %s, %s::jsonb, 'created', 0,
                      %s::jsonb, now(), now(), now()
                    )
                    """,
                    (task_id, tenant_id, "Test task integration", 
                     Jsonb({"type": "text", "content": "test"}),
                     Jsonb({"nodes": []})),
                )
                
                # Create node
                conn.execute(
                    """
                    INSERT INTO task_nodes (
                      id, task_id, node_key, skill, status, started_at, created_at, updated_at
                    ) VALUES (
                      %s::uuid, %s::uuid, %s, %s, 'pending', now(), now(), now()
                    )
                    """,
                    (node_id, task_id, "test-node-integration", "web-search"),
                )
        
        yield {
            "task_id": task_id,
            "node_id": node_id,
            "agent_id": agent_id,
        }
        
        # Cleanup
        with psycopg.connect(database_url) as conn:
            with conn.transaction():
                conn.execute("DELETE FROM a2a_requests WHERE task_id = %s::uuid", (task_id,))
                conn.execute("DELETE FROM task_nodes WHERE task_id = %s::uuid", (task_id,))
                conn.execute("DELETE FROM tasks WHERE id = %s::uuid", (task_id,))
                conn.execute("DELETE FROM agents WHERE id = %s::uuid", (agent_id,))
    
    def test_track_new_request(self, tracking_service, full_test_data):
        """Test tracking a new request with full database setup."""
        idempotency_key = tracking_service.generate_idempotency_key()
        request_json = {"query": "test query", "skill": "web-search"}
        
        result = tracking_service.track_request(
            idempotency_key,
            full_test_data["task_id"],
            full_test_data["node_id"],
            full_test_data["agent_id"],
            request_json,
        )
        
        assert result is not None
        assert result["idempotency_key"] == idempotency_key
        assert result["status"] == "pending"
    
    def test_track_duplicate_request(self, tracking_service, full_test_data):
        """Test tracking a duplicate request returns existing."""
        idempotency_key = tracking_service.generate_idempotency_key()
        request_json = {"query": "test query", "skill": "web-search"}
        
        # First request
        result1 = tracking_service.track_request(
            idempotency_key,
            full_test_data["task_id"],
            full_test_data["node_id"],
            full_test_data["agent_id"],
            request_json,
        )
        
        # Duplicate request
        result2 = tracking_service.track_request(
            idempotency_key,
            full_test_data["task_id"],
            full_test_data["node_id"],
            full_test_data["agent_id"],
            request_json,
        )
        
        # Should return the same request
        assert result1["id"] == result2["id"]
        assert result1["idempotency_key"] == result2["idempotency_key"]
    
    def test_mark_request_completed(self, tracking_service, full_test_data):
        """Test marking a request as completed."""
        idempotency_key = tracking_service.generate_idempotency_key()
        request_json = {"query": "test query", "skill": "web-search"}
        response_json = {"result": "test result", "artifacts": []}
        
        # Track request
        tracking_service.track_request(
            idempotency_key,
            full_test_data["task_id"],
            full_test_data["node_id"],
            full_test_data["agent_id"],
            request_json,
        )
        
        # Mark as completed
        tracking_service.mark_request_completed(idempotency_key, response_json)
        
        # Verify completion
        assert tracking_service.is_request_completed(idempotency_key) is True
        cached = tracking_service.get_cached_response(idempotency_key)
        assert cached is not None
        # get_cached_response returns just the response_json, not the full request
        assert cached == response_json
