# Phase 4 Production Readiness Audit (P4.0)

**Date:** 2026-09-24  
**Scope:** A2A OS Phase 3 baseline → Phase 4 durable execution plane  
**Method:** Read-only code/schema audit (no implementation in this step)  
**Verdict:** Phase 3 APIs and state machines exist, but **production SoT is still memory-default**. Orchestrator restart loses Execution Records, Lifecycle, and Execution Events. Outbox/Postgres schemas for Phase 4 largely exist and can be reused.

---

## Summary

Phase 3 delivered correct *local* semantics (`ExecutionStateMachine`, `ExecutionService.apply_callback` terminal protection, in-process ownership, cancel_tree). Phase 4’s goal — survive Orchestrator restart, Agent crash, duplicate callback/recover with Postgres as SoT — is **not met** under current wiring:

| Area | Status |
|------|--------|
| `PostgresExecutionRecordStore` | Implemented in `apps/orchestrator/execution/record.py`, **not** used by `main.py` |
| `a2a_execution_records` / `a2a_execution_events` / `a2a_agent_lifecycle` | Schema in `020_a2a_phase3_execution.sql`; **events + lifecycle have no writers** |
| `ExecutionEventBus` | Pure memory; no outbox / Redis bridge |
| `AgentLifecycleService` | Pure memory; Router health filter ignores it |
| Outbox (`014_outbox.sql` + `outbox/`) | **Reusable for P4.4**; already used by DAG `JobQueue`, not by Phase 3 execution plane |
| Governance + RuntimeGraph | Already Postgres (+ Redis inflight) — Phase 4 must not rewrite |
| Collaboration realtime WS | Task WS exists (`/v1/tasks/{id}/events/ws`); **no** `/v1/collaboration/stream/{root}` |

**Bottom line:** leave memory-default only after Postgres store is default, ownership has leases, transitions write outbox in the same DB transaction, and restart recovery is proven against concurrent recover workers.

---

## Inventory (component → memory/persisted)

| Component | Path / symbols | Memory-only? | Persisted? | Notes |
|-----------|----------------|--------------|------------|-------|
| Execution Record SoT | `ExecutionRecordStore` (`execution/record.py`) | **Yes (default)** | Class `PostgresExecutionRecordStore` exists | `main.py`: `execution = ExecutionService()` → memory store |
| Execution transitions | `ExecutionService.transition/start/succeed/fail/…` | Follows store | Postgres path uses `FOR UPDATE` on transition | Events emitted after store change (not same txn as outbox) |
| Ownership | `try_acquire_ownership` / `release_ownership` | Process-local lock | Column `ownership_token` in SQL; Postgres CAS is weak (no `FOR UPDATE`, no `lease_until`) | Success path of `recover()` **never releases** token |
| Execution events | `ExecutionEventBus` (`execution/events.py`) | **Yes** `_events`, `_seen_ids`, hooks | Table `a2a_execution_events` unused | `event_id` dedupe is in-process only |
| Retry / timeout policy | `RetryPolicy`, `TimeoutPolicy` (`retry.py`) | In-process config | Policy numbers can come from governance DB columns (020 ALTER) | No background timeout scanner |
| Collaboration policy | `CollaborationPolicy`, `PolicyEngine` (`policy.py`) | Defaults in memory | Merges from `a2a_governance_policies` when supplied | `capacity_overflow=wait` reserved; reject-only in practice |
| Agent lifecycle | `AgentLifecycleService` (`agent_lifecycle/__init__.py`) | **Yes** `_agents` | Table `a2a_agent_lifecycle` unused | Heartbeat/drain/health reset on restart |
| Governance | `GovernanceService` (`governance/__init__.py`) | — | Postgres policies/budget/denials; Redis `a2a:inflight:*` | Authoritative; keep as-is |
| Runtime graph | `RuntimeGraphService` (`runtime_graph/__init__.py`) | — | `a2a_runtime_edges` (+ Phase 3 timing columns) | Survives restart; `record_edge` always INSERT |
| DAG request tracking | `a2a_requests` (`013` + `017`) | — | Postgres | Executor/DAG idempotency; parallel to A2A-OS Execution Record |
| Outbox | `OutboxProcessor` (`outbox/__init__.py`), `OutboxProcessorService` | — | `outbox_events` | Used by `JobQueue.enqueue` / scheduler; not by `ExecutionEventBus` |
| Redis streams | `StreamClient` (`streams/__init__.py`) | — | Streams `a2a.execution.queue`, `a2a.execution.events`, `a2a.task.events` | Pub/Sub fan-out is best-effort, non-durable |
| WebSocket manager | `websocket.manager` | **Yes** connection sets | — | Relies on Redis Pub/Sub for fan-out |
| Agent task store / cancel | `agent_runtime.a2a_server.cancel_task` | **Yes** local `tasks` dict | — | OS cancel does not HTTP fan-out |
| Agent idempotency | `_IDEMPOTENCY_CACHE` in agent processes | **Yes** | Optional OS `a2a_requests` for DAG path | Restart → re-execute same `a2a-del-*` |
| Router health filter | `CandidateFilter._filter_by_health` (`router/filter.py`) | Uses registry `status` only | Registry DB | **No** lifecycle READY/BUSY/DRAINING/capacity |
| Metrics hook | `execution.events.on_emit` → `observe_execution_event` | Process metrics | — | Survives only while process lives |

### State that exists ONLY in memory (critical)

1. **`ExecutionRecordStore._by_key` / `_by_idemp`** — production SoT under current `main.py`.
2. **`ExecutionEventBus._events` / `_seen_ids`** — all `GET …/collaboration/events`, `get_execution_view().events`.
3. **`AgentLifecycleService._agents`** — health, capacity gate on `POST /v1/governance/check`, graph enrichment.
4. **WebSocket connection registry** — reconnectable, but mid-flight messages not buffered.
5. **Agent-side** `_IDEMPOTENCY_CACHE` and in-memory task maps for `tasks/cancel` / `tasks/subscribe`.
6. **Recover ownership token** after successful `ExecutionService.recover` (held forever in memory store).

### Already persisted (Postgres / Redis)

| Store | What |
|-------|------|
| Postgres `tasks` / `task_nodes` / workflows | Classic orchestrator DAG tasks |
| Postgres `a2a_runtime_edges` | Collaboration edges + lineage for governance |
| Postgres `a2a_governance_*` / `a2a_budget_usage` | Policy, denials, cumulative budget/calls |
| Postgres `outbox_events` | Reliable enqueue of DAG jobs / some task events |
| Postgres `a2a_requests` | DAG A2A request idempotency (+ `unknown` status) |
| Postgres `a2a_execution_*` / `a2a_agent_lifecycle` | **Schema ready; not default-wired** |
| Redis streams | Job queue + event streams (at-least-once to consumers) |
| Redis keys `a2a:inflight:*` | Governance concurrency (TTL’d; lost on Redis wipe) |
| Redis Pub/Sub `aop:events` / `aop:task:{id}:events` | Live WS fan-out (no retention) |

---

## Gaps vs Phase 4 goals

Mapped to P4.1–P4.23:

| ID | Goal | Gap vs current code |
|----|------|---------------------|
| **P4.1** | Postgres Execution Store default | `main.py` L52–54 uses memory `ExecutionService()`; `PostgresExecutionRecordStore` not selected; not exported from `execution/__init__.py` |
| **P4.2** | Distributed ownership | Token exists; no `owner_id`, no multi-instance lease; Postgres acquire lacks row lock |
| **P4.3** | `lease_until` + heartbeat | Absent from schema/code; stale = `updated_at` age only in `classify()` |
| **P4.4** | Record + Outbox same txn | `ExecutionService._emit` → memory bus only; no outbox insert |
| **P4.5** | Outbox worker for execution events | `OutboxProcessorService` exists for DAG types; needs claim/`processing` status + stable `event_id` |
| **P4.6** | Event idempotency | In-memory `_seen_ids`; SQL `event_id UNIQUE` unused; Redis publish mints new UUID every time |
| **P4.7** | Distributed RecoveryWorker | Only on-demand `POST /v1/tasks/{id}/recover`; no scan loop |
| **P4.8** | Agent crash → OFFLINE → recover | Lifecycle memory; no linker from stale heartbeat to execution recover |
| **P4.9** | Orchestrator restart recovery | Memory SoT wiped; `recover` may **seed TIMEOUT** from `tasks` row (destructive for unknown state) |
| **P4.10** | Cancel along runtime edges | `cancel_tree` uses `list_for_root` on execution store only; does not walk `a2a_runtime_edges` |
| **P4.11** | A2A `tasks/cancel` fan-out | `a2a_sdk.A2AClient.cancel_task` exists; OS cancel path does not call agents |
| **P4.12** | Cross-agent `traceparent` | Lineage fields exist; unified OTel propagation not enforced on all agents |
| **P4.13–14** | Capacity WAIT + queue depth | `capacity_overflow` column default `reject`; no WAITING queue |
| **P4.15** | Router lifecycle/capacity | `_filter_by_health` checks registry online only (TODO comment L268) |
| **P4.16–17** | Collaboration WS + sequence | No `/v1/collaboration/stream/{root}`; no per-root `sequence` |
| **P4.18** | Lifecycle auto OFFLINE/READY | Heartbeat can READY; no background stale→OFFLINE sweeper |
| **P4.19** | RecoveryScheduler | Missing (outbox poller is separate process) |
| **P4.20** | Graceful shutdown | No drain of ownership/leases on Orchestrator stop |
| **P4.21** | Production config | No `execution.store` / lease / recovery YAML |
| **P4.22** | DB consistency | Transition then emit is split; edge insert not idempotent on `delegation_id` |
| **P4.23** | API surface | Most Phase 3 routes exist; missing collaboration stream; events empty after restart |

---

## Race / durability risks

### What state exists ONLY in memory?

- Execution records (default), execution event log, agent lifecycle, WS peers, agent idempotency caches, held ownership tokens after recover.

### What is already persisted?

- Runtime graph, governance budget/policy/denials, DAG tasks/outbox/request tracking, Redis job/event streams (when producers call `StreamClient` / outbox). Phase 3 execution plane does **not** produce those for A2A OS transitions.

### Which operations are NOT idempotent?

| Operation | Why |
|-----------|-----|
| `RuntimeGraphService.record_edge` | Always `INSERT`; retry creates duplicate edges |
| `StreamClient.publish_*` | New `event_id` per call |
| `GovernanceService.check_and_reserve` | Each success increments calls/budget/inflight; retry without `release` doubles |
| `AgentLifecycleService.on_task_started/finished` | Counter ±1 without request id |
| Outbox → Redis | At-least-once: crash after XADD before `processed` → duplicate stream messages |
| Agent work after process restart | Memory idempotency cache cleared; stable `a2a-del-*` alone insufficient without durable callee cache |
| `main.recover_task` seed path | Creates record + forces `TIMEOUT` if missing — not safe under concurrent recover |

**Mostly idempotent (good):**

- `ExecutionRecordStore.upsert` by `(task_id, operation)` / idempotency key (memory + Postgres conflict noop)
- `ExecutionService.apply_callback` ignores terminal states
- `ExecutionStateMachine` self-transitions / terminal protection
- `cancel_tree` skips terminals
- `ExecutionEventBus.emit` same `event_id` (memory only)

### Race conditions?

1. **Multi-Orchestrator memory stores** — each instance has a different SoT; recover/cancel disagree.
2. **`PostgresExecutionRecordStore.try_acquire_ownership`** — `UPDATE … WHERE ownership_token IS NULL OR state NOT IN (RUNNING,RETRYING)` without `FOR UPDATE` → two workers can both acquire.
3. **`recover()` holds ownership forever** on success → blocks future recover, or opposite: never released so single stuck owner.
4. **`cancel_tree` vs late `apply_callback`** — cancel wins if first; callback ignored if terminal (OK). Reverse order: SUCCEEDED then cancel raises / skips — OK locally; agents may still run.
5. **`update_edge_status`** — last writer wins; concurrent complete/fail races.
6. **Governance** — Redis incr then DB txn; failures call `_release_inflight`, but process crash between incr and commit can leak inflight until TTL.
7. **Outbox `process_pending_events`** — publish then update in same connection/lock (good); `publish_to_redis` standalone path can mark processed after duplicate risk.

### Events that can be lost?

1. All Phase 3 `ExecutionEventBus` events on process death.
2. Hook exceptions swallowed in `ExecutionEventBus.emit`.
3. Redis Pub/Sub messages if no subscriber (WS down).
4. Outbox rows stuck `failed` until `retry_failed_event` (no auto-backoff loop beyond manual status).
5. Best-effort `notify_callback` failures (logged, task still completes).

### Callbacks that can duplicate?

1. Agent `notify_callback` retries / network double-POST → caller must be idempotent; OS `apply_callback` is if wired.
2. At-least-once Redis stream redelivery to consumers.
3. Outbox republish after crash.
4. Duplicate A2A completion after agent restart (lost `_IDEMPOTENCY_CACHE`).

### Recoveries that can run concurrently?

1. Two HTTP `POST …/recover` on **one** memory instance: second gets `action=contention` **only while** token held; after leak/stuck token, permanent contention or none.
2. Two Orchestrator processes: **both** recover the “same” logical task independently (no shared store).
3. Postgres path: concurrent acquire race (see above) → dual `mark_retry`.
4. No RecoveryScheduler yet — chaos will be worse once background scanners exist without leases.

### APIs that fail or lie after Orchestrator restart?

| API | Behavior after restart (memory-default) |
|-----|----------------------------------------|
| `GET /v1/tasks/{id}/execution` | Empty execute/delegate; events `[]` |
| `GET /v1/collaboration/events/{root}` | Empty |
| `POST /v1/tasks/{id}/recover` | May invent TIMEOUT seed from `tasks` row |
| `POST /v1/tasks/{id}/cancel` → `execution_cancel` | Cascade finds no records; DAG cancel may still work via `tasks.cancel` |
| `GET/POST …/agents/{id}/health\|heartbeat\|drain` | Lifecycle wiped; health `not_registered` |
| `POST /v1/governance/check` lifecycle gate | Falls back to `legacy_untracked` → **allows** all agents |
| `GET …/collaboration-graph` | **Edges still OK** (Postgres); agent `state` enrichment missing |
| Governance denials / budget | Still OK |
| DAG enqueue via outbox | Still OK if DB/Redis up |

---

## Reuse map (as-is / extend / new)

### As-is (do not rewrite)

| Asset | Reuse |
|-------|--------|
| `GovernanceService.check_and_reserve` / `release` | Keep DB+Redis authority |
| `RuntimeGraphService` + `018`/`020` edge columns | Lineage + collaboration graph source |
| `a2a-del-*` (`A2ACollaborationRuntime.delegation_idempotency_key`) | Keep stable hop keys |
| `ExecutionStateMachine` / `AgentLifecycleStateMachine` | Keep transition rules |
| `ExecutionService.apply_callback` terminal protection | Keep semantics |
| Router v3 `CandidateFilter` pipeline | Extend health stage only |
| `StreamClient` streams + Pub/Sub | Delivery backend for outbox publisher |
| Prometheus `observe_execution_event` / OTel | Keep; feed from durable events |
| `a2a_requests` + unknown status | Keep for DAG executor path alongside OS records |

### Extend (preferred for Phase 4)

| Asset | How |
|-------|-----|
| **`outbox_events` + `OutboxProcessor` + `OutboxProcessorService`** | **P4.4/P4.5 primary reuse.** Already supports `execution_event` → `publish_execution_event`. Add: same-txn write with record updates; stable `event_id` in payload; optional columns `aggregate_id`, `root_task_id`, `published_at`; use `processing` status + SKIP LOCKED claim; auto-retry failed with backoff |
| `PostgresExecutionRecordStore` | Make default via config; add `lease_until` / `owner_id`; harden `try_acquire_ownership` with `FOR UPDATE` + CAS on expired lease |
| `020_a2a_phase3_execution.sql` | Additive `021_*.sql` for lease/sequence; start writing `a2a_execution_events` and `a2a_agent_lifecycle` |
| `ExecutionService._emit` | Persist event (outbox or events table) in same transaction as transition |
| `cancel_tree` | Resolve children from `RuntimeGraphService.list_edges` + optional `A2AClient.cancel_task` |
| `CandidateFilter._filter_by_health` | Consult `AgentLifecycleService.health` / capacity |
| Existing task WS + Redis Pub/Sub | Pattern for `/v1/collaboration/stream/{root}` |

### New

| Piece | Why |
|-------|-----|
| `RecoveryScheduler` / RecoveryWorker | P4.7 / P4.19 |
| Lease renewal heartbeat | P4.3 |
| Capacity WAIT queue | P4.13–14 |
| Per-root event `sequence` | P4.17 |
| Graceful shutdown drain | P4.20 |
| Production config block | P4.21 |
| Postgres-backed `AgentLifecycleService` | Schema exists; service is memory-only |
| Durable agent idempotency (or always OS-side) | Memory `_IDEMPOTENCY_CACHE` insufficient |

### Outbox reuse detail (P4.4)

**Already present:**

- Schema: `infrastructure/postgres/init/014_outbox.sql` (`id`, `event_type`, `payload`, `target_stream`, `status`, `attempts`, `last_error`, `created_at`, `processed_at`; status includes `processing` in CHECK but code mostly uses pending/processed/failed).
- Writer: `OutboxProcessor.write_event`
- Consumer: `process_pending_events` with `FOR UPDATE SKIP LOCKED`
- Service loop: `outbox_processor_service.py`
- Call sites: `JobQueue.enqueue(use_outbox=True)`, scheduler `write_outbox_event`
- Event type `execution_event` already mapped to `streams.publish_execution_event`

**Extend, don’t fork:** wrap Phase 3 state transitions so `UPDATE a2a_execution_records` + `INSERT outbox_events` share one Postgres transaction; publisher remains the existing worker.

---

## Recommended Phase 4 implementation order (aligned with P4.1–P4.23)

1. **P4.0** — this audit (`docs/phase4-production-readiness.md`) ✅  
2. **P4.1** — Default `PostgresExecutionRecordStore` behind config; hermetic tests keep memory.  
3. **P4.2 + P4.3** — Ownership + `lease_until` / renew; fix acquire with row lock; release/expire semantics; fix recover token leak.  
4. **P4.22 + P4.4 + P4.5 + P4.6** — Transactional outbox on every transition; extend existing outbox worker; unique `event_id`; at-least-once + idempotent consumers.  
5. **P4.9** — Prove Orchestrator kill/restart restores records/events/graph without TIMEOUT seed hacks.  
6. **P4.7 + P4.19 + P4.8 + P4.18** — RecoveryScheduler; stale lease + offline agent scans; lifecycle persistence + heartbeat sweeper.  
7. **P4.10 + P4.11** — Cancel via runtime edges + A2A `tasks/cancel` with idempotent keys.  
8. **P4.15** — Router health/lifecycle/capacity filter.  
9. **P4.13 + P4.14** — WAITING queue + `max_queue_depth`.  
10. **P4.16 + P4.17** — Collaboration stream WS + per-root sequence.  
11. **P4.12** — Enforce `traceparent` / OTel context on agent wire.  
12. **P4.20 + P4.21 + P4.23** — Graceful shutdown, config defaults, API polish / acceptance suite (chaos: crash, late callback, concurrent recover).

After each milestone: run Phase 2 + Phase 3 regression suites.

---

## Acceptance criteria for leaving memory-default

Do **not** switch production off memory-default until all of the following hold:

1. **Config default** `execution.store=postgres` in non-test environments; memory only when explicitly set (tests/CI hermetic).  
2. **Restart test:** create A→B→C collaboration, kill Orchestrator, restart — `GET /v1/tasks/{id}/execution` returns prior states; collaboration graph reconstructs from DB; no reliance on process dicts.  
3. **Ownership:** two concurrent `recover` calls → exactly one `action=retry`; the other `contention` or no-op; expired lease allows CAS takeover.  
4. **Outbox atomicity:** crash between record update and Redis publish still leaves pending outbox row; no silent “DB yes / event never”.  
5. **Event durability:** `event_id` unique in Postgres; duplicate publish does not duplicate consumer side-effects.  
6. **Late/duplicate callback:** terminal states never regress (`apply_callback` + DB).  
7. **Lifecycle:** heartbeat persisted; after restart, drain/capacity gate still excludes DRAINING/OFFLINE/stale agents.  
8. **Cancel:** cancel root walks active runtime edges and does not spam terminal children; repeated cancel is idempotent.  
9. **Router:** DRAINING/OFFLINE/at-capacity agents excluded by CandidateFilter health stage.  
10. **Chaos CI:** concurrent recover, late callback, Orchestrator crash mid-transition, Agent kill mid-RUNNING — all green.  
11. **Phase 2/3 regression:** existing suites still pass with Postgres store enabled in integration profile.

Until then, treat Phase 3 memory-default as **dev/test only**, matching `../phase-03/delivery-report.md` known limitation #1.

---

## Implementation status (post P4.0 — 2026-09-24)

| ID | Status | Notes |
|----|--------|-------|
| P4.0 | ✅ | This audit |
| P4.1 | ✅ | `build_execution_service()` — Postgres default; `EXECUTION_STORE=memory` for tests |
| P4.2–3 | ✅ | `owner_id` / `lease_until` + FOR UPDATE CAS / steal on expiry |
| P4.4–6 | ✅ | Postgres transition writes outbox same txn; `event_id` unique; EventBus sequence |
| P4.7–9 | ✅ | `RecoveryScheduler` + lifecycle stale→OFFLINE; restart relies on Postgres SoT |
| P4.10–11 | ✅ | `cancel_fanout` walks runtime graph + optional `A2AClient.cancel_task` |
| P4.12 | ⚠️ | Reuses existing `root_task_id` / `correlation_id` / OTel; no new protocol |
| P4.13–15 | ✅ | `CapacityQueue` WAIT + max depth; Router `lifecycle_checker` |
| P4.16–17 | ✅ | WS `/v1/collaboration/stream/{root}` + per-root `sequence` |
| P4.18–20 | ✅ | OFFLINE→REGISTERED→READY on heartbeat; scheduler start/stop on lifespan |
| P4.21–23 | ✅ | `ExecutionConfig.from_env`; APIs preserved + stream; hermetic tests |

**Hermetic:** `tests/test_phase4_execution.py` + Phase 3 suite green.  
**Config:** see `apps/orchestrator/execution/config.py` (`EXECUTION_*`, `CAPACITY_*`, `COLLABORATION_STREAM_ENABLED`).

---

## Appendix: key wiring references (updated)

```text
main.py → build_execution_service(ExecutionConfig.from_env())
       → RecoveryScheduler on startup / stop on shutdown
       → cancel_fanout on POST /v1/tasks/{id}/cancel
       → WS /v1/collaboration/stream/{root}
```

Schema: `021_a2a_phase4_execution.sql` (lease, outbox enrich, capacity queue).
