"""Agent Contract Tests - Validate AOP Reference Agent compliance.

These tests verify that reference agents comply with the standardized
agent manifest, runtime interface, and error model.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from packages.schemas import (
    AgentManifest,
    AgentError,
    ErrorCode,
)


class AgentContractTestBase:
    """Base class for agent contract tests."""

    def __init__(self, agent_path: str, base_url: str):
        self.agent_path = Path(agent_path)
        self.base_url = base_url
        self.card_path = self.agent_path / "agent-card.json"

    def load_agent_card(self) -> dict[str, Any]:
        """Load Agent Card from file."""
        if not self.card_path.exists():
            raise FileNotFoundError(f"Agent Card not found: {self.card_path}")
        return json.loads(self.card_path.read_text(encoding="utf-8"))

    def parse_agent_manifest(self) -> AgentManifest:
        """Parse Agent Card into AgentManifest."""
        card_data = self.load_agent_card()
        return AgentManifest.from_dict(card_data)

    def fetch_agent_card_from_endpoint(self) -> dict[str, Any]:
        """Fetch Agent Card from well-known endpoint."""
        client = httpx.Client(timeout=10.0)
        try:
            response = client.get(f"{self.base_url}/.well-known/agent-card.json")
            response.raise_for_status()
            return response.json()
        finally:
            client.close()

    def fetch_health(self) -> dict[str, Any]:
        """Fetch health status from agent."""
        client = httpx.Client(timeout=10.0)
        try:
            response = client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()
        finally:
            client.close()

    def send_a2a_message(self, text: str, skill_id: str | None = None) -> dict[str, Any]:
        """Send A2A message to agent."""
        client = httpx.Client(timeout=60.0)
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": "test-request",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": text}],
                    }
                },
            }
            if skill_id:
                payload["params"]["metadata"] = {"skillId": skill_id}

            response = client.post(self.base_url, json=payload)
            response.raise_for_status()
            return response.json()
        finally:
            client.close()

    def get_a2a_task(self, task_id: str) -> dict[str, Any]:
        """Get A2A task status."""
        client = httpx.Client(timeout=10.0)
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": "test-request",
                "method": "tasks/get",
                "params": {"id": task_id},
            }
            response = client.post(self.base_url, json=payload)
            response.raise_for_status()
            return response.json()
        finally:
            client.close()


def test_agent_card_can_be_read():
    """Test that Agent Card can be read from file."""
    agents = [
        ("../../agents/search-agent", "http://127.0.0.1:8001"),
        ("../../agents/rag-agent", "http://127.0.0.1:8002"),
        ("../../agents/analysis-agent", "http://127.0.0.1:8004"),
        ("../../agents/report-agent", "http://127.0.0.1:8003"),
    ]

    for agent_path, base_url in agents:
        base = AgentContractTestBase(agent_path, base_url)
        card = base.load_agent_card()

        # Verify required fields
        assert "name" in card, f"{agent_path}: missing name"
        assert "description" in card, f"{agent_path}: missing description"
        assert "url" in card, f"{agent_path}: missing url"
        assert "version" in card, f"{agent_path}: missing version"
        assert "protocolVersion" in card, f"{agent_path}: missing protocolVersion"
        assert "skills" in card, f"{agent_path}: missing skills"
        assert isinstance(card["skills"], list), f"{agent_path}: skills must be array"
        assert len(card["skills"]) > 0, f"{agent_path}: must have at least one skill"


def test_skill_can_be_discovered():
    """Test that skills can be discovered from Agent Card."""
    agents = [
        ("../../agents/search-agent", "http://127.0.0.1:8001"),
        ("../../agents/rag-agent", "http://127.0.0.1:8002"),
        ("../../agents/analysis-agent", "http://127.0.0.1:8004"),
        ("../../agents/report-agent", "http://127.0.0.1:8003"),
    ]

    for agent_path, base_url in agents:
        base = AgentContractTestBase(agent_path, base_url)
        manifest = base.parse_agent_manifest()

        # Verify skills are properly parsed
        assert len(manifest.skills) > 0, f"{agent_path}: must have skills"

        for skill in manifest.skills:
            assert skill.id, f"{agent_path}: skill missing id"
            assert skill.name, f"{agent_path}: skill missing name"
            assert skill.description, f"{agent_path}: skill missing description"
            assert isinstance(skill.input_modes, list), f"{agent_path}: skill input_modes must be list"
            assert isinstance(skill.output_modes, list), f"{agent_path}: skill output_modes must be list"
            assert len(skill.input_modes) > 0, f"{agent_path}: skill must have input_modes"
            assert len(skill.output_modes) > 0, f"{agent_path}: skill must have output_modes"


def test_agent_card_endpoint():
    """Test that Agent Card can be fetched from well-known endpoint."""
    # This test requires agents to be running
    # Skip if agents are not available
    if not os.getenv("AGENTS_RUNNING"):
        pytest.skip("Agents not running - set AGENTS_RUNNING=1 to enable")

    agents = [
        ("../../agents/search-agent", "http://127.0.0.1:8001"),
        ("../../agents/rag-agent", "http://127.0.0.1:8002"),
        ("../../agents/analysis-agent", "http://127.0.0.1:8004"),
        ("../../agents/report-agent", "http://127.0.0.1:8003"),
    ]

    for agent_path, base_url in agents:
        base = AgentContractTestBase(agent_path, base_url)
        card = base.fetch_agent_card_from_endpoint()

        # Verify endpoint returns valid Agent Card
        assert "name" in card, f"{agent_path}: endpoint missing name"
        assert "skills" in card, f"{agent_path}: endpoint missing skills"


def test_health_check():
    """Test that health check endpoint returns valid status."""
    # This test requires agents to be running
    if not os.getenv("AGENTS_RUNNING"):
        pytest.skip("Agents not running - set AGENTS_RUNNING=1 to enable")

    agents = [
        ("../../agents/search-agent", "http://127.0.0.1:8001"),
        ("../../agents/rag-agent", "http://127.0.0.1:8002"),
        ("../../agents/analysis-agent", "http://127.0.0.1:8004"),
        ("../../agents/report-agent", "http://127.0.0.1:8003"),
    ]

    for agent_path, base_url in agents:
        base = AgentContractTestBase(agent_path, base_url)
        health = base.fetch_health()

        # Verify health response structure
        assert "status" in health, f"{agent_path}: health missing status"
        assert health["status"] in ["ok", "degraded", "unhealthy"], f"{agent_path}: invalid health status"
        assert "agent" in health, f"{agent_path}: health missing agent field"


def test_a2a_task_creation():
    """Test that A2A tasks can be created."""
    # This test requires agents to be running
    if not os.getenv("AGENTS_RUNNING"):
        pytest.skip("Agents not running - set AGENTS_RUNNING=1 to enable")

    test_cases = [
        ("agents/search-agent", "http://127.0.0.1:8001", "web-search", "test query"),
        ("agents/rag-agent", "http://127.0.0.1:8002", "knowledge-search", "test query"),
        ("agents/analysis-agent", "http://127.0.0.1:8004", "business-analysis", "test query"),
        ("agents/report-agent", "http://127.0.0.1:8003", "report-generation", "test query"),
    ]

    for agent_path, base_url, skill_id, query in test_cases:
        base = AgentContractTestBase(agent_path, base_url)
        response = base.send_a2a_message(query, skill_id)

        # Verify A2A response structure
        assert "jsonrpc" in response, f"{agent_path}: missing jsonrpc"
        assert response["jsonrpc"] == "2.0", f"{agent_path}: wrong jsonrpc version"
        assert "result" in response, f"{agent_path}: missing result"
        assert "id" in response["result"], f"{agent_path}: result missing task id"
        assert "status" in response["result"], f"{agent_path}: result missing status"


def test_task_status_query():
    """Test that task status can be queried."""
    # This test requires agents to be running
    if not os.getenv("AGENTS_RUNNING"):
        pytest.skip("Agents not running - set AGENTS_RUNNING=1 to enable")

    test_cases = [
        ("agents/search-agent", "http://127.0.0.1:8001", "web-search", "test query"),
    ]

    for agent_path, base_url, skill_id, query in test_cases:
        base = AgentContractTestBase(agent_path, base_url)

        # Create a task first
        create_response = base.send_a2a_message(query, skill_id)
        task_id = create_response["result"]["id"]

        # Query task status
        task_response = base.get_a2a_task(task_id)

        # Verify task response structure
        assert "jsonrpc" in task_response, f"{agent_path}: missing jsonrpc"
        assert "result" in task_response, f"{agent_path}: missing result"
        assert task_response["result"]["id"] == task_id, f"{agent_path}: task id mismatch"


def test_artifact_return():
    """Test that artifacts are returned in proper format."""
    # This test requires agents to be running
    if not os.getenv("AGENTS_RUNNING"):
        pytest.skip("Agents not running - set AGENTS_RUNNING=1 to enable")

    test_cases = [
        ("agents/search-agent", "http://127.0.0.1:8001", "web-search", "test query"),
    ]

    for agent_path, base_url, skill_id, query in test_cases:
        base = AgentContractTestBase(agent_path, base_url)
        response = base.send_a2a_message(query, skill_id)

        # Verify artifacts are present
        result = response["result"]
        assert "artifacts" in result, f"{agent_path}: result missing artifacts"
        assert isinstance(result["artifacts"], list), f"{agent_path}: artifacts must be array"
        assert len(result["artifacts"]) > 0, f"{agent_path}: must return at least one artifact"

        # Verify artifact structure
        for artifact in result["artifacts"]:
            assert "artifactId" in artifact, f"{agent_path}: artifact missing id"
            assert "name" in artifact, f"{agent_path}: artifact missing name"
            assert "parts" in artifact, f"{agent_path}: artifact missing parts"
            assert isinstance(artifact["parts"], list), f"{agent_path}: artifact parts must be array"


def test_error_format():
    """Test that errors follow standardized format."""
    # This test requires agents to be running
    if not os.getenv("AGENTS_RUNNING"):
        pytest.skip("Agents not running - set AGENTS_RUNNING=1 to enable")

    base = AgentContractTestBase("agents/search-agent", "http://127.0.0.1:8001")

    # Try to get non-existent task (should return error)
    response = base.get_a2a_task("non-existent-task-id")

    # Verify error response structure
    assert "error" in response, "Response should contain error"
    error = response["error"]
    assert "code" in error, "Error should contain code"
    assert "message" in error, "Error should contain message"


def test_agent_manifest_schema():
    """Test that Agent Cards conform to AgentManifest schema."""
    agents = [
        ("../../agents/search-agent", "http://127.0.0.1:8001"),
        ("../../agents/rag-agent", "http://127.0.0.1:8002"),
        ("../../agents/analysis-agent", "http://127.0.0.1:8004"),
        ("../../agents/report-agent", "http://127.0.0.1:8003"),
    ]

    for agent_path, base_url in agents:
        base = AgentContractTestBase(agent_path, base_url)
        manifest = base.parse_agent_manifest()

        # Verify AgentManifest fields
        assert manifest.name, f"{agent_path}: manifest missing name"
        assert manifest.description, f"{agent_path}: manifest missing description"
        assert manifest.url, f"{agent_path}: manifest missing url"
        assert manifest.version, f"{agent_path}: manifest missing version"
        assert manifest.protocol_version == "0.3.0", f"{agent_path}: wrong protocol version"

        # Verify extended fields (if present)
        if manifest.agent_id:
            assert isinstance(manifest.agent_id, str), f"{agent_path}: agent_id must be string"
        if manifest.agent_key:
            assert isinstance(manifest.agent_key, str), f"{agent_path}: agent_key must be string"


def test_skill_independence():
    """Test that skills are independent of agent_id."""
    agents = [
        ("../../agents/search-agent", "http://127.0.0.1:8001"),
        ("../../agents/rag-agent", "http://127.0.0.1:8002"),
        ("../../agents/analysis-agent", "http://127.0.0.1:8004"),
        ("../../agents/report-agent", "http://127.0.0.1:8003"),
    ]

    skill_ids = set()
    for agent_path, base_url in agents:
        base = AgentContractTestBase(agent_path, base_url)
        manifest = base.parse_agent_manifest()

        for skill in manifest.skills:
            # Skill ID should be unique across agents
            assert skill.id not in skill_ids, f"Duplicate skill_id: {skill.id}"
            skill_ids.add(skill.id)

            # Skill should not reference agent-specific info
            assert "agent" not in skill.id.lower(), f"Skill ID should not reference agent: {skill.id}"
            assert skill.id.islower() or skill.id.replace("-", "").isalnum(), f"Skill ID should use kebab-case: {skill.id}"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
