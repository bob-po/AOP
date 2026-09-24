# Phase 6 Architecture Audit (P6.0)

**Date:** 2026-09-24  
**Scope:** Phase 1–5 baseline → Agent Marketplace + Skill System + Dynamic Discovery  
**Method:** Read-only audit (no Phase 6 implementation in this step)  
**Verdict:** Strong reuse surface — **do not create a second Registry/Discovery/Lifecycle**. Extend Gateway registry + Orchestrator marketplace + Phase 5 Capability/Scheduler.

```text
Phase 6 Architecture Audit

Existing:
- Agent Registry          (Gateway Go registry.Store + PG agents / agent_skills / agent_versions / agent_endpoints)
- Capability              (scheduling/capability.py + a2a_agent_capabilities)
- Skill                   (agent_skills.skill_id strings; AgentCard.Skill in card.go; Router skill match)
- Lifecycle               (agent_lifecycle REGISTERED→READY→BUSY→DRAINING→OFFLINE)
- Discovery               (POST /v1/discover, /v1/route, Router v3 CandidateFilter)
- Scheduling              (scheduling/ IntelligentScheduler)
- Marketplace (proto)     (marketplace/__init__.py curated CATALOG + install→gateway register)
- Sandbox (policy)        (sandbox/ skill/host allowlists — not install sandbox)
- Agent Card              (/.well-known/agent-card.json fetch on register)

Missing:
- Agent Manifest          (YAML/JSON standard; validation pipeline)
- Skill Manifest          (structured skill object with schemas/version — beyond skill_id string)
- Versioning UX           (agent_versions table exists; ACTIVE/DEPRECATED/REVOKED + constraint routing incomplete)
- Marketplace persistence (DB-backed packages vs in-memory CATALOG)
- Install/Activate state  (installations table; INSTALLING/ACTIVATING states)
- Dependency graph        (skills/agents version constraints + conflict detection)
- Permission model        (manifest permissions ↔ Governance/Tenant)
- SandboxProvider         (LocalProcess / Docker / K8s interfaces for dynamic install)
- Skill Discovery APIs    (GET/POST /v1/skills*)
- Version-aware routing   (skill + version constraint into Scheduler)
```

---

## Reuse map

| Asset | Action |
|-------|--------|
| `agents` / `agent_versions` / `agent_skills` / `agent_endpoints` | **Extend** — status enums, manifest JSON, skill version FK |
| Gateway `POST /v1/agents/register` | **Keep** — endpoint+card path; Orchestrator adds manifest path that ends in same Registry |
| `MarketplaceService` + `CATALOG` | **Extend** — persist published packages; keep curated seed |
| `scheduling.Capability` / `Requirement` | **Extend** — version constraints, modalities from skill schemas |
| `AgentLifecycleService` | **Extend** — INSTALLING / ACTIVATING / DEPRECATED / REVOKED overlays (compat with Phase 3 states) |
| `sandbox/` policy | **Reuse** for invocation; **new** `SandboxProvider` for install isolation |
| Outbox / ExecutionEventBus | **Reuse** — emit AGENT_* / SKILL_* events |
| Phase 5 TenantContext | **Reuse** for marketplace tenant isolation |

## Migration numbering

Next free: **`028+`** (027 is Phase 5 scheduling).

## Compatibility risks

1. Skill upgrades must not break Router string skill matching (keep `skill_id` as primary key).  
2. New lifecycle labels must map onto Phase 3 machine without illegal transitions (use metadata + soft status).  
3. Marketplace install must continue to call Gateway register (single Registry SoT).  
4. Do not replace `/v1/discover` — Skill Discovery feeds candidates into existing discover/route/scheduler.

## Implementation order

P6.0 → Manifest → Registration/Version → Skill System/Discovery → Marketplace Publish/Install → Dependency/Permission/Sandbox → Dynamic Discovery/Invocation → APIs/CLI/DB/Events → Security/E2E.
