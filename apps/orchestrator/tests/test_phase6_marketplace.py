"""Phase 6 — Manifest / Skill / Marketplace / Discovery / Sandbox tests."""

from __future__ import annotations

import pytest

from agent_lifecycle import AgentLifecycleService
from execution.events import ExecutionEventBus
from marketplace import (
    DependencyResolver,
    LocalProcessSandbox,
    ManifestValidationError,
    MarketplaceService,
    PermissionService,
    SandboxSpec,
    SkillRegistry,
    parse_dependencies,
    satisfies,
    validate_manifest,
)
from marketplace.deps import Dependency
from marketplace.sandbox_provider import DockerSandbox, get_sandbox_provider
from scheduling import Requirement, SchedulingService, filter_by_capability
from scheduling.capability import Capability, capability_match


def _manifest(**overrides):
    base = {
        "name": "image-analysis-agent",
        "version": "1.2.0",
        "description": "Image analysis agent",
        "author": "tester",
        "runtime": {"protocol": "a2a", "endpoint": "http://127.0.0.1:9001"},
        "capabilities": ["image_analysis", "ocr"],
        "skills": ["image-analysis", "ocr"],
        "inputs": ["image", "text"],
        "outputs": ["json", "report"],
        "requirements": {"cpu": 2, "memory_mb": 4096, "gpu": False},
        "permissions": ["network", "other_agents"],
        "dependencies": {"skills": ["ocr>=1.0.0"]},
        "metadata": {},
    }
    base.update(overrides)
    return base


def test_manifest_validation():
    m = validate_manifest(_manifest())
    assert m.name == "image-analysis-agent"
    assert m.checksum()
    with pytest.raises(ManifestValidationError):
        validate_manifest({"name": "x"})  # missing version/endpoint
    with pytest.raises(ManifestValidationError):
        validate_manifest(_manifest(version="not-semver"))
    with pytest.raises(ManifestValidationError):
        validate_manifest(_manifest(permissions=["network", "evil_perm"]))
    with pytest.raises(ManifestValidationError):
        validate_manifest(
            _manifest(permissions=["shell", "filesystem"], metadata={})
        )


def test_agent_registration():
    bus = ExecutionEventBus()
    life = AgentLifecycleService(event_bus=bus)
    svc = MarketplaceService(event_bus=bus, lifecycle=life)
    # seed skill so dependency resolves
    svc.skills.register({"name": "ocr", "version": "1.0.0"})
    out = svc.register_manifest(_manifest(), skip_gateway=True)
    assert out["registered"] is True
    assert out["version"] == "1.2.0"
    assert svc.stats["agent_registration_count"] == 1
    events = [e.event_type for e in bus._events]
    assert "AGENT_REGISTERED" in events
    assert life.get(out["agent_id"]) is not None


def test_agent_versioning():
    svc = MarketplaceService()
    svc.skills.register({"name": "ocr", "version": "1.0.0"})
    svc.register_manifest(_manifest(version="1.0.0"), skip_gateway=True)
    svc.register_manifest(_manifest(version="1.1.0"), skip_gateway=True)
    svc.register_manifest(_manifest(version="2.0.0"), skip_gateway=True)
    vers = svc.list_versions("image-analysis-agent")
    assert len(vers) == 3
    assert svc.get_manifest("image-analysis-agent").version == "2.0.0"
    svc.set_version_status("image-analysis-agent", "1.1.0", "DEPRECATED")
    with pytest.raises(ValueError):
        svc.set_version_status(
            "image-analysis-agent",
            "2.0.0",
            "REVOKED",
            active_task_versions={"2.0.0"},
        )


def test_skill_registration():
    reg = SkillRegistry()
    s = reg.register(
        {
            "name": "image-generation",
            "version": "2.1.0",
            "description": "Generate images",
            "inputs": {"prompt": "string"},
            "outputs": {"image": "binary"},
            "requirements": {"gpu": True},
            "tags": ["vision"],
        }
    )
    assert s.name == "image-generation"
    assert reg.get("image-generation").version == "2.1.0"


def test_skill_discovery():
    svc = MarketplaceService()
    hits = svc.search_skills({"skill": "image-generation"})
    assert any(h["name"] == "image-generation" for h in hits)
    hits2 = svc.search_skills({"input": "image", "output": "text"})
    assert any(h["name"] == "ocr" for h in hits2)
    hits3 = svc.search_skills({"resource": "gpu"})
    assert any(h["name"] == "image-generation" for h in hits3)


def test_marketplace_publish():
    svc = MarketplaceService()
    svc.skills.register({"name": "ocr", "version": "1.0.0"})
    out = svc.publish(_manifest(package_id="pkg-img-test"))
    assert out["published"] is True
    pkg = svc.get_package("pkg-img-test")
    assert pkg["status"] == "PUBLISHED"
    assert pkg["checksum"]


def test_marketplace_install_and_activate(monkeypatch):
    svc = MarketplaceService()
    svc.skills.register({"name": "ocr", "version": "1.0.0"})
    pub = svc.publish(_manifest(package_id="pkg-img-install"))
    assert pub["published"]

    class _Resp:
        status_code = 200

        def json(self):
            return {"id": "agent-uuid-1", "agent_key": "image-analysis-agent"}

    monkeypatch.setattr("marketplace.service.httpx.post", lambda *a, **k: _Resp())
    out = svc.install(package_id="pkg-img-install", sandbox="local_process")
    assert out["installed"] and out["activated"]
    assert out["sandbox"]["ok"] is True
    de = svc.deactivate("pkg-img-install")
    assert de["deactivated"]
    act = svc.activate("pkg-img-install")
    assert act.get("activated") or act.get("installed")


def test_dependency_resolution():
    r = DependencyResolver()
    deps = parse_dependencies({"skills": ["ocr>=1.0", "image-analysis>=2.0"]})
    assert len(deps) == 2
    available = {
        "skill": {"ocr": ["1.0.0", "1.1.0"], "image-analysis": ["2.0.0", "1.5.0"]},
        "agent": {},
    }
    result = r.resolve(deps, available)
    assert result.ok
    assert result.resolved["skill:ocr"] == "1.1.0"
    assert result.resolved["skill:image-analysis"] == "2.0.0"
    bad = r.resolve(
        [Dependency("skill", "ocr", ">=9.0")],
        {"skill": {"ocr": ["1.0.0"]}},
    )
    assert not bad.ok and bad.conflicts
    assert satisfies("2.1.0", ">=2.0")
    assert not satisfies("1.9.0", ">=2.0")


def test_permission():
    ps = PermissionService()
    ok = ps.validate_declared(["network", "gpu"])
    assert ok.allowed
    bad = ps.validate_declared(["network", "root"])
    assert not bad.allowed
    ten = ps.tenant_allows("t1", ["network", "shell"])
    assert not ten.allowed and "shell" in ten.denied
    ps.grant("t1", "agent-a", ["network", "other_agents"])
    inv = ps.check_invocation("t1", "agent-a", ["network"])
    assert inv.allowed
    inv2 = ps.check_invocation("t1", "agent-a", ["filesystem"])
    assert not inv2.allowed


def test_sandbox():
    sb = LocalProcessSandbox()
    ok = sb.provision(
        SandboxSpec(
            agent_key="a",
            version="1.0.0",
            endpoint="http://127.0.0.1:9001",
            permissions=["network"],
            checksum="abc",
        )
    )
    assert ok.ok and sb.health_check(ok.sandbox_id)
    deny = sb.provision(
        SandboxSpec(
            agent_key="b",
            version="1.0.0",
            endpoint="http://127.0.0.1:9001",
            permissions=["shell"],
            source_url="http://evil/payload.py",
        )
    )
    assert not deny.ok
    docker = get_sandbox_provider("docker")
    assert isinstance(docker, DockerSandbox)
    assert not docker.provision(
        SandboxSpec(agent_key="c", version="1", endpoint="http://x")
    ).ok


def test_dynamic_discovery():
    svc = MarketplaceService()
    svc.skills.register({"name": "ocr", "version": "1.0.0"})
    svc.register_manifest(_manifest(), skip_gateway=True)
    agents = [
        {
            "agent_id": "a1",
            "agent_key": "image-analysis-agent",
            "skills": ["image-analysis", "ocr"],
            "version": "1.2.0",
            "status": "online",
        }
    ]
    disc = svc.discover_by_skill("image-analysis", agents=agents)
    assert disc["candidates"]
    assert disc["candidates"][0]["agent_key"] == "image-analysis-agent"


def test_dynamic_invocation():
    svc = MarketplaceService()
    svc.skills.register({"name": "ocr", "version": "1.0.0"})
    svc.register_manifest(_manifest(), skip_gateway=True)
    # Agent B for report
    svc.register_manifest(
        _manifest(
            name="report-agent",
            version="1.0.0",
            skills=["report-generation"],
            capabilities=["report"],
            dependencies={},
            endpoint="http://127.0.0.1:9003",
            runtime={"protocol": "a2a", "endpoint": "http://127.0.0.1:9003"},
        ),
        skip_gateway=True,
    )
    agents = [
        {
            "agent_id": "a",
            "agent_key": "image-analysis-agent",
            "skills": ["image-analysis"],
            "version": "1.2.0",
            "status": "online",
        },
        {
            "agent_id": "b",
            "agent_key": "report-agent",
            "skills": ["report-generation"],
            "version": "1.0.0",
            "status": "online",
        },
    ]
    # A discovers report without hardcoding B URL
    inv = svc.resolve_invocation(
        "report-generation",
        agents=agents,
        scheduling=SchedulingService(),
    )
    assert inv["selected"] is not None
    assert inv["selected"]["agent_key"] == "report-agent"
    assert "endpoint" in inv["selected"] or inv["selected"].get("agent_key")


def test_version_constraint():
    req = Requirement(skill="image-generation", version_constraint=">=2.0.0")
    cap_ok = Capability(skill="image-generation", version="2.1.0")
    cap_bad = Capability(skill="image-generation", version="1.0.0")
    ok, _, _ = capability_match(req, cap_ok)
    assert ok
    bad, reason, _ = capability_match(req, cap_bad)
    assert not bad and "version_mismatch" in reason

    cands = [
        {
            "agent_id": "old",
            "skills": ["image-generation"],
            "version": "1.0.0",
            "matched_version": "1.0.0",
            "status": "online",
        },
        {
            "agent_id": "new",
            "skills": ["image-generation"],
            "version": "2.1.0",
            "matched_version": "2.1.0",
            "status": "online",
        },
    ]
    passed, excluded = filter_by_capability(cands, req)
    assert [c["agent_id"] for c in passed] == ["new"]
    assert any(e["agent_id"] == "old" for e in excluded)


def test_tenant_isolation():
    svc = MarketplaceService(tenant_id="00000000-0000-0000-0000-000000000001")
    svc.skills.register({"name": "ocr", "version": "1.0.0"})
    svc.publish(_manifest(package_id="pkg-t1"), tenant_id="tenant-a")
    # tenant-b install of revoked should fail differently; publish is tenant tagged
    pkg = svc.get_package("pkg-t1")
    assert pkg["tenant_id"] == "tenant-a"
    ps = PermissionService(tenant_policy={"tenant-a": {"network"}, "tenant-b": set()})
    assert ps.tenant_allows("tenant-a", ["network"]).allowed
    assert not ps.tenant_allows("tenant-b", ["network"]).allowed


def test_agent_lifecycle_integration():
    life = AgentLifecycleService()
    svc = MarketplaceService(lifecycle=life)
    svc.skills.register({"name": "ocr", "version": "1.0.0"})
    out = svc.register_manifest(_manifest(), skip_gateway=True)
    rec = life.get(out["agent_id"])
    assert rec["state"] == "READY"
    assert rec["metadata"].get("marketplace_status") == "READY"
    svc.unregister(out["agent_id"], agent_key="image-analysis-agent")
    rec2 = life.get(out["agent_id"])
    assert rec2["state"] == "OFFLINE"


def test_e2e_skill_composition_chain():
    """A → skill discovery → B → skill discovery → C (no hardcoded URLs)."""
    svc = MarketplaceService()
    for sk in ("image-analysis", "document-analysis", "report-generation"):
        svc.skills.register({"name": sk, "version": "1.0.0"})

    manifests = [
        _manifest(
            name="agent-a",
            version="1.0.0",
            skills=["image-analysis"],
            dependencies={},
            endpoint="http://127.0.0.1:9101",
            runtime={"protocol": "a2a", "endpoint": "http://127.0.0.1:9101"},
        ),
        _manifest(
            name="agent-b",
            version="1.0.0",
            skills=["document-analysis"],
            dependencies={},
            endpoint="http://127.0.0.1:9102",
            runtime={"protocol": "a2a", "endpoint": "http://127.0.0.1:9102"},
        ),
        _manifest(
            name="agent-c",
            version="1.0.0",
            skills=["report-generation"],
            dependencies={},
            endpoint="http://127.0.0.1:9103",
            runtime={"protocol": "a2a", "endpoint": "http://127.0.0.1:9103"},
        ),
    ]
    for m in manifests:
        svc.register_manifest(m, skip_gateway=True)

    agents = [
        {"agent_id": "a", "agent_key": "agent-a", "skills": ["image-analysis"], "version": "1.0.0", "status": "online", "endpoint": "http://127.0.0.1:9101"},
        {"agent_id": "b", "agent_key": "agent-b", "skills": ["document-analysis"], "version": "1.0.0", "status": "online", "endpoint": "http://127.0.0.1:9102"},
        {"agent_id": "c", "agent_key": "agent-c", "skills": ["report-generation"], "version": "1.0.0", "status": "online", "endpoint": "http://127.0.0.1:9103"},
    ]
    chain = []
    for skill in ("image-analysis", "document-analysis", "report-generation"):
        inv = svc.resolve_invocation(skill, agents=agents, scheduling=SchedulingService())
        assert inv["selected"] is not None, skill
        chain.append(inv["selected"]["agent_key"])
    assert chain == ["agent-a", "agent-b", "agent-c"]
