"""Agent Contract Tests - harness virtual agent cards."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from packages.schemas import AgentManifest

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ROOT / "agents" / "harness-agent" / "profiles"

HARNESS_CARDS = [
    (PROFILES / "claude-coder", "http://127.0.0.1:8011"),
    (PROFILES / "claude-researcher", "http://127.0.0.1:8012"),
    (PROFILES / "pi-coder", "http://127.0.0.1:8013"),
    (PROFILES / "pi-researcher", "http://127.0.0.1:8014"),
    (PROFILES / "deepseek-coder", "http://127.0.0.1:8015"),
    (PROFILES / "deepseek-researcher", "http://127.0.0.1:8016"),
]


class AgentContractTestBase:
    def __init__(self, agent_path: Path, base_url: str):
        self.agent_path = Path(agent_path)
        self.base_url = base_url
        self.card_path = self.agent_path / "agent-card.json"

    def load_agent_card(self) -> dict[str, Any]:
        if not self.card_path.exists():
            raise FileNotFoundError(f"Agent Card not found: {self.card_path}")
        return json.loads(self.card_path.read_text(encoding="utf-8"))

    def parse_agent_manifest(self) -> AgentManifest:
        return AgentManifest.from_dict(self.load_agent_card())

    def fetch_agent_card_from_endpoint(self) -> dict[str, Any]:
        client = httpx.Client(timeout=10.0)
        try:
            response = client.get(f"{self.base_url.rstrip('/')}/.well-known/agent-card.json")
            response.raise_for_status()
            return response.json()
        finally:
            client.close()

    def fetch_health(self) -> dict[str, Any]:
        client = httpx.Client(timeout=10.0)
        try:
            response = client.get(f"{self.base_url.rstrip('/')}/health")
            response.raise_for_status()
            return response.json()
        finally:
            client.close()


def test_agent_card_can_be_read():
    for agent_path, base_url in HARNESS_CARDS:
        base = AgentContractTestBase(agent_path, base_url)
        card = base.load_agent_card()
        assert "name" in card
        assert "skills" in card and len(card["skills"]) > 0
        assert "protocolVersion" in card


def test_skill_can_be_discovered():
    for agent_path, base_url in HARNESS_CARDS:
        base = AgentContractTestBase(agent_path, base_url)
        manifest = base.parse_agent_manifest()
        assert len(manifest.skills) > 0
        for skill in manifest.skills:
            assert skill.id and skill.name


def test_agent_card_endpoint():
    if not os.getenv("AGENTS_RUNNING"):
        pytest.skip("Agents not running - set AGENTS_RUNNING=1 to enable")
    for agent_path, base_url in HARNESS_CARDS:
        base = AgentContractTestBase(agent_path, base_url)
        card = base.fetch_agent_card_from_endpoint()
        assert "name" in card and "skills" in card


def test_health_check():
    if not os.getenv("AGENTS_RUNNING"):
        pytest.skip("Agents not running - set AGENTS_RUNNING=1 to enable")
    for agent_path, base_url in HARNESS_CARDS:
        base = AgentContractTestBase(agent_path, base_url)
        health = base.fetch_health()
        assert health.get("status") == "ok"
        assert health.get("harness") is True
