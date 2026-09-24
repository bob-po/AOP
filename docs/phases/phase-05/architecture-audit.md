# Phase 5 Architecture Audit (P5.0)

**Date:** 2026-09-24  
**Scope:** A2A OS Phase 1–4 baseline → Phase 5 Intelligent Scheduling + Multi-Tenancy + Cost Governance  
**Method:** Read-only code/schema audit (no Phase 5 implementation in this step)  
**Verdict:** Strong reuse surface exists (Router v3 scoring, QuotaService, Governance budget, Billing estimated USD, Lifecycle/Capacity Queue). Gaps are: unified TenantContext on A2A hot path, Execution-linked cost_records, capability model beyond skills, Fair/aging priority, agent_reliability rollups, Adaptive Retry with Agent Reselection, Policy-as-Code layering, and a **Scheduler** module distinct from Router filter/score.

```text
Phase 5 Architecture Audit
├── Existing reusable modules
├── Existing gaps
├── Required new modules
├── Required DB migrations
├── Required API changes
├── Required compatibility risks
└── Implementation order
```

---

## 1. Existing reusable modules (MUST NOT rewrite)

| Area | Path / symbols | Phase 5 role |
|------|----------------|--------------|
| **Router v3** | `apps/orchestrator/router/__init__.py` `AgentRouter` | Discovery + candidate pipeline; keep |
| **CandidateFilter** | `router/filter.py` — skill / capability / mode / health / resource / tenant / policy | Extend stages; do not fork |
| **ScoringEngine** | `router/scoring.py` — availability, priority, latency, success_rate, **cost weight (default 0)** | Feed Scheduler score; enable cost weight |
| **Registry** | Gateway `agents.go` + PG `agents` (tenant_id) | Source of candidates |
| **Governance** | `governance/__init__.py` — visits, depth, concurrency, `a2a_budget_usage` units | Authority for delegation; extend budget units ↔ USD |
| **CollaborationPolicy / PolicyEngine** | `execution/policy.py` | Merge Global→Tenant→Task overrides (extend fields) |
| **Execution Record SoT** | `execution/record.py` + Postgres store + leases | Source for reliability + cost attach |
| **Retry / Recovery** | `ExecutionService.mark_retry/recover`, `RecoveryScheduler` | Hook reselection **after** recover classify |
| **Lifecycle** | `agent_lifecycle/` — READY/BUSY/DRAINING/OFFLINE | Load-aware input |
| **CapacityQueue** | `execution/capacity_queue.py` | Queue depth / WAIT |
| **Outbox / Events** | `outbox/`, `ExecutionEventBus` | Emit `cost.recorded`, `schedule.selected` |
| **Runtime graph** | `runtime_graph/` (tenant_id column) | Isolation + cost tree aggregation |
| **QuotaService** | `quota/__init__.py` + `007_tenant_quotas.sql` | Tenant task/run/concurrent/USD month caps |
| **BillingService** | `billing/` — `estimated_cost_usd` from agent_runs | Seed Cost Model; do not duplicate invoices |
| **DAG Scheduler** | `scheduler/` (JobQueue / DAG) | **Unrelated** to A2A Agent Scheduler — keep name boundary |
| **Auth / Tenant** | Gateway `tenantOrDefault`, RBAC, `006_user_auth.sql` | Propagate TenantContext |
| **Metrics / OTel** | `observability/a2a_metrics.py`, tracing | Observe schedule/cost; no second stack |
| **CLI** | `scripts/aop.py` | Extend commands |
| **Gateway proxy** | `/v1/route`, `/v1/discover`, `/v1/collaboration`, `/v1/governance` | Add `/v1/scheduling/*`, `/v1/cost/*` proxies |

### What already exists vs Phase 5 vocabulary

| Concept | Status |
|---------|--------|
| Tenant | **Partial** — UUID on tasks/agents/runtime edges/governance; default tenant everywhere; weak isolation on A2A execution APIs |
| Quota | **Yes** — `tenant_quotas` (tasks/day, runs/day, concurrent, USD/month) via QuotaService |
| Resource (cpu/gpu/mem) | **Partial** — CandidateFilter resource stage + agent card resources; no OS ResourceQuota table |
| Cost | **Partial** — Billing `estimated_cost_usd` aggregation; **no** per-execution `cost_records` linked to Execution Record |
| Capability | **Partial** — skills + input/output modes + streaming/browsing/code flags in filter; no first-class Capability model / modalities / models list |
| Priority | **Partial** — agent registry `priority` + scoring; no task CRITICAL/HIGH/NORMAL/LOW + aging fairness |
| Scheduling | **Partial** — Router score = selection; no separate Scheduler / preview / simulator |
| Policy | **Partial** — Governance DB + CollaborationPolicy; no YAML Policy-as-Code Global→Tenant→Project→Task |
| Reliability | **Partial** — Scoring uses historical success/latency metrics window; **no** `agent_reliability` rollup table from Execution Records |
| Adaptive reselection | **Gap** — recover retries **same** task/agent record; DAG path has `exclude_agent_ids`; A2A OS path does not rediscover |

---

## 2. Existing gaps (must close in Phase 5)

1. **No TenantContext** on ExecutionService / collaboration WS / events — tenant often defaulted, not enforced on read APIs.  
2. **No Execution↔Cost 1:1** — cannot `GET /v1/tasks/{id}/cost` from Execution Record.  
3. **Capability matching** still skill/mode-centric; GPU/models/modalities not first-class requirements.  
4. **Load signals** (cpu/mem/gpu usage, p95) not live on lifecycle heartbeat → Scheduler.  
5. **No Fair Scheduling / aging** — high priority can starve LOW forever.  
6. **No agent_reliability** derived from Execution Records (timeout_rate, retry_rate, availability).  
7. **Adaptive Retry ≠ Agent Reselection** — Phase 3/4 recover stays on same agent_id.  
8. **Budget** is governance *units* + quota *USD/month* — no per-task / per-day soft budget with cancel-on-exceed tied to Execution.  
9. **No Scheduler module** — selection buried in `AgentRouter.rank` / ScoringEngine.  
10. **No scheduling preview / simulator / Phase 5 benchmark artifacts**.  
11. **Migration ceiling is `021`** — Phase 5 must start at **`022`** (user's 021_phase5 suggestion conflicts with Phase 4).

---

## 3. Required new modules (additive only)

```text
apps/orchestrator/scheduling/     # NEW — Intelligent Scheduler (not DAG scheduler/)
  __init__.py
  context.py                      # TenantContext
  capability.py                   # Capability model + matcher
  resource.py                     # ResourceQuota view over quota + lifecycle
  cost.py                         # CostModel + cost_records writer
  budget.py                       # Budget check/update (wraps governance + quota)
  reliability.py                  # agent_reliability rollups from execution store
  priority.py                     # Priority + aging fairness
  policy_layers.py                # Global→Tenant→Project→Task merge (extends PolicyEngine)
  selector.py                     # score + select (uses ScoringEngine weights)
  reselection.py                  # failure class → rediscover + exclude
  simulator.py                    # offline preview
  service.py                      # façade for HTTP

infrastructure/postgres/init/
  022_a2a_phase5_tenant_context.sql
  023_a2a_phase5_cost.sql
  024_a2a_phase5_budget.sql
  025_a2a_phase5_capabilities.sql
  026_a2a_phase5_reliability.sql
  027_a2a_phase5_scheduling.sql
```

**Do NOT create:** second Router, second Governance, second EventBus, second Metrics, second Execution Store.

---

## 4. Required DB migrations (next free: **022+**)

| File | Purpose |
|------|---------|
| `022_a2a_phase5_tenant_context.sql` | Ensure `tenant_id` on `a2a_execution_records`, `a2a_execution_events`, capacity queue; indexes; backfill default tenant |
| `023_a2a_phase5_cost.sql` | `a2a_cost_records` (+ unique on execution identity) |
| `024_a2a_phase5_budget.sql` | `a2a_budgets` / usage counters (per_task, per_day, per_month) |
| `025_a2a_phase5_capabilities.sql` | Optional `a2a_agent_capabilities` JSONB mirror of card (or extend agents) |
| `026_a2a_phase5_reliability.sql` | `a2a_agent_reliability` rollup table |
| `027_a2a_phase5_scheduling.sql` | `a2a_scheduling_decisions` audit (optional) + policy JSON storage per tenant |

Compatibility: all columns `ADD IF NOT EXISTS`; default `tenant_id = 00000000-0000-0000-0000-000000000001`.

---

## 5. Required API changes (Gateway proxy + Orchestrator)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/v1/scheduling/candidates` | Reuse discover+filter; expose candidates |
| POST | `/v1/scheduling/preview` | Dry-run select + estimate |
| POST | `/v1/scheduling/select` | Authoritative select (writes decision audit) |
| GET | `/v1/agents/{id}/capacity` | Lifecycle + queue depth |
| GET | `/v1/agents/{id}/reliability` | Rollup |
| GET | `/v1/tasks/{id}/cost` | Aggregate |
| GET | `/v1/tasks/{id}/cost/breakdown` | Per-edge / per-execution |
| GET | `/v1/tenants/{id}/quota` | Wrap QuotaService |
| GET | `/v1/tenants/{id}/budget` | New budget view |
| GET | `/v1/tenants/{id}/cost` | Billing + cost_records |
| GET/POST | `/v1/tenants/{id}/policy` | Policy-as-Code document |

Preserve all Phase 2–4 routes. Tenant isolation filters on task/execution/collaboration/events.

---

## 6. Compatibility risks

| Risk | Mitigation |
|------|------------|
| Name collision: DAG `scheduler/` vs Intelligent Scheduler | Package as `scheduling/` (gerund); never rename DAG Scheduler |
| Enabling Scoring cost weight breaks rank order | Default cost weight stays 0 until Cost Model wired; feature flag |
| Reselection breaks `visited_agents` / idempotency | New agent gets new `a2a-del-*` child task; lineage append; same root/correlation |
| Tenant filter breaks default-tenant demos | Default tenant UUID remains; isolation only when non-default + auth |
| Double budget (governance units vs USD) | Map: Cost estimated_cost → budget USD; governance units remain for call metering |
| Postgres store required for cost durability | Write cost in same txn as SUCCEEDED transition when store is Postgres |
| Router rewrite temptation | Scheduler **calls** CandidateFilter + ScoringEngine; Router stays entry for skill route |

---

## 7. Implementation order (mandatory)

```text
P5.0 Audit ← THIS DOCUMENT
 ↓
P5.1 TenantContext + tenant_id on execution/events APIs
 ↓
P5.2 ResourceQuota façade over QuotaService + lifecycle concurrency
 ↓
P5.3 Cost records + task cost APIs
 ↓
P5.4 Capability model + matcher (extend CandidateFilter)
 ↓
P5.5 Load-aware signals (lifecycle + queue + optional usage)
 ↓
P5.6 Priority + aging fairness
 ↓
P5.7 agent_reliability rollups
 ↓
P5.8 Adaptive retry + AgentReselection
 ↓
P5.9 Policy layers (extend PolicyEngine)
 ↓
P5.10 Budget control (pre-check + post-update)
 ↓
P5.11 Intelligent Scheduler (selector) + APIs
 ↓
P5.12 Tenant isolation enforcement pass
 ↓
P5.13 Simulator
 ↓
P5.14 Benchmark
 ↓
P5.15 E2E + Phase 1–4 regression + Delivery Report
```

Each step: code → unit → integration → fix → next. No big-bang merge.

---

## 8. CLI extensions (later)

```text
aop scheduling preview|candidates|select
aop agent reliability|capacity
aop task cost
aop tenant quota|budget
```

---

## 9. Acceptance gate (preview)

PHASE 5 PASS only when checklist in the user brief is green **with real pytest output**. Forgery forbidden.

---

## Appendix: key wiring citations

```text
DEFAULT_TENANT_ID = 00000000-0000-0000-0000-000000000001
Quota: apps/orchestrator/quota/__init__.py
Scoring cost weight default 0: router/scoring.py ScoringWeights.cost
Governance budget units: governance/__init__.py a2a_budget_usage
Phase 4 execution store: execution/factory.py build_execution_service
Migrations applied through: 021_a2a_phase4_execution.sql
```

**P5.0 complete. Next: P5.1 TenantContext.**
