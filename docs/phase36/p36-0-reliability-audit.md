# AOP Phase 36.0 — End-to-End Reliable Execution Audit

**Audit Date:** 2026-09-19  
**Auditor:** Principal Backend Engineer & Distributed Systems Reliability Architect  
**Scope:** Complete AOP task execution lifecycle reliability audit  
**Repository:** AOP (Agent Orchestration Platform) - Branch: main  
**Phase Coverage:** 1–34 implemented components

---

## Executive Summary

This audit provides a comprehensive source-code-based reliability assessment of the AOP (Agent Orchestration Platform) task execution lifecycle. The audit examines the actual implementation across all critical components: Go Gateway, Python Orchestrator, Planner, Router, Scheduler, Executor, Redis Streams, PostgreSQL persistence, A2A integration, Artifact handling, and failure recovery mechanisms.

### Key Findings Summary

**P0 (Critical):** 3 findings  
**P1 (Major):** 8 findings  
**P2 (Recoverability/Observability):** 12 findings  
**P3 (Optimization/Maintainability):** 7 findings

### Top 5 Reliability Risks

1. **P0-001: No Exactly-Once Execution Guarantees** - Redis Stream message delivery is at-least-once, with no deduplication at execution layer
2. **P0-002: Worker Crash Between Agent Success and Persistence** - External Agent execution can succeed but PostgreSQL update may fail, creating data inconsistency
3. **P0-003: No Distributed Transaction Coordination** - PostgreSQL state changes and Redis queue operations are not atomic, enabling split-brain scenarios
4. **P1-001: Stale Node Reclaim Race Conditions** - Node state checks and updates are not atomic, risking duplicate execution
5. **P1-002: Timeout Handling Without Idempotency** - Agent timeouts may trigger retries while original request still executing

### Overall Assessment

AOP implements a functional distributed task execution system with good architectural separation and comprehensive feature coverage. However, the system lacks production-grade reliability guarantees for distributed systems operations, particularly around exactly-once execution, crash recovery, and distributed transaction coordination. The current implementation provides at-least-once semantics with multiple failure modes that could result in duplicate executions, data inconsistency, or permanently stuck states.

---

## 1. Repository Reconnaissance

### 1.1 Repository Structure

```
AOP/
├── apps/
│   ├── gateway/              # Go Gateway (HTTP proxy, auth, RBAC)
│   ├── orchestrator/        # Python Orchestrator (core logic)
│   └── web/                 # Next.js Console
├── agents/                  # A2A Agents (search, rag, report, etc.)
├── packages/
│   ├── a2a-sdk/            # A2A protocol client
│   ├── schemas/            # Shared schemas
│   └── common/             # Shared utilities
├── infrastructure/
│   ├── postgres/           # PostgreSQL schema + migrations
│   └── redis/              # Redis configuration
├── deployments/            # Docker compose, deployment scripts
├── docs/                  # Technical documentation
└── scripts/               # Utility scripts
```

### 1.2 Current Branch State

- **Branch:** main
- **Status:** Clean working tree, up to date with origin/main
- **Phases Implemented:** 1–34 (as per README.md)

### 1.3 Key Components Identified

#### Gateway (Go)
- `apps/gateway/cmd/main.go` - Entry point
- `apps/gateway/internal/httpapi/proxy.go` - Load-balanced reverse proxy to Orchestrator
- `apps/gateway/internal/auth/` - API key, RBAC, user authentication
- **Purpose:** HTTP API gateway, authentication, load balancing to Orchestrator instances

#### Orchestrator (Python)
- `apps/orchestrator/main.py` - FastAPI HTTP server
- `apps/orchestrator/application/task_service.py` - Application facade
- `apps/orchestrator/application/task_manager.py` - Task use cases
- `apps/orchestrator/planner/` - Natural language to DAG planning
- `apps/orchestrator/router/` - Agent selection and routing
- `apps/orchestrator/scheduler/` - Task persistence and job queuing
- `apps/orchestrator/executor/` - A2A execution engine
- `apps/orchestrator/worker.py` - Worker entry point
- **Purpose:** Core orchestration logic, task lifecycle management

#### Persistence Layer
- **PostgreSQL:** Authoritative state storage (tasks, nodes, agents, events, etc.)
- **Redis:** Queue storage (Streams), skill indexing, distributed locks, pub/sub
- **MinIO:** Artifact storage
- **Schema:** `infrastructure/postgres/init/001_init.sql` through `012_tenant_egress.sql`

#### Agent Integration
- **Protocol:** A2A (Agent-to-Agent) via `packages/a2a-sdk`
- **Agents:** 8 implemented agents (search, rag, report, analysis, image, video, code, browser)
- **Discovery:** HTTP-based agent card discovery at `/.well-known/agent-card.json`

---

## 2. Actual Execution Lifecycle

### 2.1 Complete Call Chain

```
User/API Request
    ↓
Gateway (Go :8080)
    ├── Authentication (API key / session)
    ├── RBAC authorization
    └── Reverse proxy to Orchestrator
    ↓
Orchestrator HTTP API (Python :8090)
    ├── POST /v1/tasks
    ├── TaskService.create()
    └── TaskManager.create()
    ↓
TaskManager.create()
    ├── QuotaService.assert_can_create_task()
    ├── PlanningEngine.plan() → Planner.plan()
    │   ├── list_available_skills() (PostgreSQL query)
    │   ├── _heuristic_nodes() or decompose_to_nodes()
    │   └── validate_plan()
    ├── SchedulingEngine.create_and_enqueue()
    │   ├── Scheduler.create_task() (PostgreSQL transaction)
    │   │   ├── INSERT tasks (status='planning')
    │   │   ├── INSERT task_nodes (status='pending')
    │   │   ├── INSERT task_dependencies
    │   │   ├── UPDATE task_nodes (ready nodes → 'ready')
    │   │   ├── UPDATE tasks (status='running')
    │   │   └── INSERT task_events
    │   └── enqueue_jobs() → JobQueue.enqueue()
    │       └── StreamClient.enqueue_execution() (Redis XADD)
    └── MemoryService.remember_goal()
    ↓
Redis Stream: a2a.execution.queue
    ├── Message fields: task_id, node_id, node_key, skill, attempt, exclude_agent_ids
    └── Consumer group: cg-executor
    ↓
Worker Process (apps/orchestrator/worker.py)
    ├── ExecutionEngine.run_forever()
    ├── StreamClient.read_execution() (Redis XREADGROUP)
    └── ExecutionEngine.handle()
    ↓
ExecutionEngine.handle()
    ├── RoutingEngine.select() → AgentRouter.select()
    │   ├── _candidates_from_redis() or _candidates_from_pg()
    │   ├── _load_metrics() (agent_runs aggregation)
    │   └── ScoringEngine.score_candidate()
    ├── Sandbox checks (skill, endpoint)
    ├── Scheduler.claim_running() (PostgreSQL UPDATE)
    │   └── UPDATE task_nodes (status='running', assigned_agent_id, attempt)
    ├── A2AExecutor.execute() → A2AClient.send_text()
    │   ├── HTTP POST to Agent endpoint
    │   └── Response with artifacts
    ├── ArtifactStore.persist_node_output() (MinIO)
    │   ├── put_text() → output.txt
    │   ├── put_json() → output.json
    │   └── put_json() → meta.json
    ├── Scheduler.mark_success() (PostgreSQL transaction)
    │   ├── UPDATE task_nodes (status='success' or 'waiting_for_user')
    │   ├── INSERT agent_runs (audit record)
    │   ├── _unlock_dependents() → UPDATE task_nodes (ready nodes → 'ready')
    │   ├── UPDATE tasks (status='completed' or 'running')
    │   └── INSERT task_events
    ├── StreamClient.enqueue_execution() (downstream nodes)
    ├── Aggregator.build_result() (on task completion)
    │   ├── SELECT task_nodes (all outputs)
    │   ├── UPDATE tasks (result_json)
    │   └── INSERT task_events
    ├── EvaluationService.evaluate() (on terminal state)
    │   ├── _heuristic() scoring
    │   ├── INSERT task_evaluations
    │   └── INSERT task_events
    └── StreamClient.ack_execution() (Redis XACK)
```

### 2.2 Stage-by-Stage Analysis

#### Stage 1: API Entry (Gateway)
- **File:** `apps/gateway/internal/httpapi/proxy.go`
- **Function:** `LoadBalancedProxy.ServeHTTP()`
- **Input:** HTTP request with authentication headers
- **Output:** Forwarded request to Orchestrator
- **State Changes:** None (proxy only)
- **Persistence:** None
- **Error Propagation:** HTTP status codes to client
- **Idempotency:** Stateless proxy, idempotent by design

#### Stage 2: Task Creation (Orchestrator)
- **File:** `apps/orchestrator/application/task_manager.py`
- **Function:** `TaskManager.create()`
- **Input:** content string, optional title, tenant_id
- **Output:** task_id, status, plan, ready_nodes
- **State Changes:** 
  - PostgreSQL: tasks.status='planning' → 'running'
  - PostgreSQL: task_nodes.status='pending' → 'ready'
- **Persistence:** PostgreSQL transaction (tasks, task_nodes, task_dependencies, task_events)
- **Queue Operations:** Redis XADD to a2a.execution.queue
- **Error Propagation:** HTTP 400/429/500 to client
- **Idempotency:** No idempotency key - duplicate submissions create separate tasks

#### Stage 3: Planning (Planner)
- **File:** `apps/orchestrator/planner/__init__.py`
- **Function:** `Planner.plan()`
- **Input:** goal string, optional title
- **Output:** PlannerResult (plan, method, available_skills)
- **State Changes:** None (pure computation)
- **Persistence:** None
- **Error Propagation:** ValueError on validation failure
- **Idempotency:** Deterministic for same input, but no caching

#### Stage 4: Scheduling (Scheduler)
- **File:** `apps/orchestrator/scheduler/__init__.py`
- **Function:** `Scheduler.create_task()`
- **Input:** goal, TaskPlan, workflow_id, tenant_id
- **Output:** ScheduleResult (task_id, status, ready_nodes, ready_jobs)
- **State Changes:**
  - PostgreSQL: INSERT tasks, task_nodes, task_dependencies
  - PostgreSQL: UPDATE task_nodes (ready nodes → 'ready')
  - PostgreSQL: UPDATE tasks (status='running')
- **Persistence:** PostgreSQL transaction with event logging
- **Queue Operations:** Returns ready_jobs for external enqueue
- **Error Propagation:** psycopg exceptions
- **Idempotency:** None - each call creates new task

#### Stage 5: Job Enqueue (JobQueue)
- **File:** `apps/orchestrator/scheduler/job_queue.py`
- **Function:** `JobQueue.enqueue()`
- **Input:** task_id, node_id, node_key, skill, attempt, etc.
- **Output:** Redis Stream message ID
- **State Changes:** None (queue append only)
- **Persistence:** Redis XADD (append-only log)
- **Queue Operations:** XADD to a2a.execution.queue
- **Error Propagation:** Redis connection errors
- **Idempotency:** None - each enqueue creates new message

#### Stage 6: Queue Consumption (Worker)
- **File:** `apps/orchestrator/executor/engine.py`
- **Function:** `ExecutionEngine.run_forever()`, `StreamClient.read_execution()`
- **Input:** Redis Stream messages
- **Output:** Consumed message fields
- **State Changes:** None (consumption only)
- **Persistence:** Redis XREADGROUP (consumer group)
- **Queue Operations:** XREADGROUP with consumer acknowledgment
- **Error Propagation:** Exception caught in loop, continues
- **Idempotency:** At-least-once delivery guaranteed by Redis Streams

#### Stage 7: Agent Routing (Router)
- **File:** `apps/orchestrator/router/__init__.py`
- **Function:** `AgentRouter.select()`
- **Input:** skill, exclude_agent_ids
- **Output:** RoutedAgent (agent_id, endpoint, score)
- **State Changes:** None (read-only)
- **Persistence:** PostgreSQL read (agent_runs metrics), optional Redis read
- **Queue Operations:** None
- **Error Propagation:** RouterError if no agents available
- **Idempotency:** Deterministic scoring, but no caching

#### Stage 8: Node Claim (Scheduler)
- **File:** `apps/orchestrator/scheduler/__init__.py`
- **Function:** `Scheduler.claim_running()`
- **Input:** task_id, node_key, agent_id, attempt
- **Output:** boolean (success/failure)
- **State Changes:**
  - PostgreSQL: UPDATE task_nodes (status='running', assigned_agent_id, attempt)
  - PostgreSQL: UPDATE tasks (status='running')
- **Persistence:** PostgreSQL transaction with event logging
- **Queue Operations:** None
- **Error Propagation:** False return on concurrent claim
- **Idempotency:** Conditional UPDATE prevents duplicate claims

#### Stage 9: Agent Execution (Executor)
- **File:** `apps/orchestrator/executor/__init__.py`
- **Function:** `A2AExecutor.execute()`
- **Input:** agent_url, query, skill_id
- **Output:** ExecutionResult (task, text, data, artifacts)
- **State Changes:** None (external execution)
- **Persistence:** None (external side effects only)
- **Queue Operations:** None
- **Error Propagation:** SandboxViolation, AOPError
- **Idempotency:** None - depends on Agent implementation

#### Stage 10: Artifact Storage (ArtifactStore)
- **File:** `apps/orchestrator/artifacts/__init__.py`
- **Function:** `ArtifactStore.persist_node_output()`
- **Input:** task_id, node_key, text, data
- **Output:** list of ArtifactRef
- **State Changes:** MinIO object creation
- **Persistence:** MinIO (S3-compatible storage)
- **Queue Operations:** None
- **Error Propagation:** S3Error
- **Idempotency:** None - duplicate uploads create separate objects

#### Stage 11: Success Marking (Scheduler)
- **File:** `apps/orchestrator/scheduler/__init__.py`
- **Function:** `Scheduler.mark_success()`
- **Input:** task_id, node_key, output, a2a_task_id, latency_ms
- **Output:** list of ready_jobs (downstream nodes)
- **State Changes:**
  - PostgreSQL: UPDATE task_nodes (status='success' or 'waiting_for_user')
  - PostgreSQL: INSERT agent_runs (audit record)
  - PostgreSQL: UPDATE task_nodes (downstream → 'ready')
  - PostgreSQL: UPDATE tasks (status='completed' or 'running')
- **Persistence:** PostgreSQL transaction with event logging
- **Queue Operations:** Returns ready_jobs for external enqueue
- **Error Propagation:** psycopg exceptions
- **Idempotency:** Conditional UPDATE prevents duplicate marking

#### Stage 12: Failure Handling (Scheduler)
- **File:** `apps/orchestrator/scheduler/__init__.py`
- **Function:** `Scheduler.mark_failure()`
- **Input:** task_id, node_key, error, attempt, agent_id
- **Output:** decision dict (retry/failed, next_attempt)
- **State Changes:**
  - PostgreSQL: UPDATE task_nodes (status='retrying' or 'failed')
  - PostgreSQL: UPDATE tasks (status='failed' on terminal failure)
- **Persistence:** PostgreSQL transaction with event logging
- **Queue Operations:** None (retry enqueue handled by caller)
- **Error Propagation:** psycopg exceptions
- **Idempotency:** Attempt-based conditional updates

#### Stage 13: Aggregation (Aggregator)
- **File:** `apps/orchestrator/aggregator/__init__.py`
- **Function:** `Aggregator.build_result()`
- **Input:** task_id
- **Output:** result dict (summary, artifacts, nodes)
- **State Changes:**
  - PostgreSQL: UPDATE tasks (result_json)
- **Persistence:** PostgreSQL with event logging
- **Queue Operations:** None
- **Error Propagation:** ValueError on task not found
- **Idempotency:** Idempotent - overwrites same result_json

#### Stage 14: Evaluation (EvaluationService)
- **File:** `apps/orchestrator/evaluation/__init__.py`
- **Function:** `EvaluationService.evaluate()`
- **Input:** task_id, method
- **Output:** evaluation dict (score, grade, dimensions)
- **State Changes:**
  - PostgreSQL: INSERT task_evaluations (ON CONFLICT UPDATE)
- **Persistence:** PostgreSQL with event logging
- **Queue Operations:** None
- **Error Propagation:** ValueError on task not found
- **Idempotency:** Idempotent via ON CONFLICT UPDATE

#### Stage 15: Message Acknowledgment (StreamClient)
- **File:** `apps/orchestrator/streams/__init__.py`
- **Function:** `StreamClient.ack_execution()`
- **Input:** message_id
- **Output:** None
- **State Changes:** Redis XACK (removes from pending)
- **Persistence:** Redis consumer group state
- **Queue Operations:** XACK
- **Error Propagation:** Redis connection errors
- **Idempotency:** Idempotent - duplicate XACK safe

### 2.3 Execution Lifecycle Diagram

```
┌─────────────┐
│  User/API   │
└──────┬──────┘
       │ POST /v1/tasks
       ▼
┌─────────────┐
│   Gateway   │ (Load balancer, auth)
└──────┬──────┘
       │ Proxy to :8090
       ▼
┌─────────────┐
│Orchestrator │ (FastAPI)
└──────┬──────┘
       │ TaskManager.create()
       ├────────────────────────────────┐
       │                                │
       ▼                                ▼
┌─────────────┐              ┌─────────────┐
│   Planner   │              │   Quota     │
│  (DAG gen)  │              │   Check     │
└──────┬──────┘              └──────┬──────┘
       │                            │
       └──────────┬─────────────────┘
                  ▼
         ┌─────────────┐
         │  Scheduler  │ (PostgreSQL transaction)
         └──────┬──────┘
                │ INSERT tasks, task_nodes
                │ UPDATE ready nodes
                │ INSERT task_events
                ▼
         ┌─────────────┐
         │  JobQueue   │ (Redis XADD)
         └──────┬──────┘
                │ a2a.execution.queue
                ▼
         ┌─────────────┐
         │ Redis Stream│ (Consumer group)
         └──────┬──────┘
                │ XREADGROUP
                ▼
         ┌─────────────┐
         │   Worker    │ (ExecutionEngine)
         └──────┬──────┘
                │
       ┌────────┴────────┐
       │                 │
       ▼                 ▼
┌─────────────┐  ┌─────────────┐
│   Router    │  │   Sandbox   │
│ (Agent sel) │  │   Checks    │
└──────┬──────┘  └──────┬──────┘
       │                │
       └────────┬───────┘
                ▼
         ┌─────────────┐
         │ Scheduler   │ (claim_running)
         └──────┬──────┘
                │ UPDATE task_nodes
                ▼
         ┌─────────────┐
         │  Executor   │ (A2A HTTP call)
         └──────┬──────┘
                │
       ┌────────┴────────┐
       │                 │
       ▼                 ▼
┌─────────────┐  ┌─────────────┐
│  A2A Agent  │  │   Error     │
│  Execution  │  │  Handling   │
└──────┬──────┘  └──────┬──────┘
       │                │
       └────────┬───────┘
                │
       ┌────────┴────────┐
       │                 │
       ▼                 ▼
┌─────────────┐  ┌─────────────┐
│ ArtifactStore│  │   Retry     │
│  (MinIO)     │  │   Logic     │
└──────┬──────┘  └──────┬──────┘
       │                │
       └────────┬───────┘
                ▼
         ┌─────────────┐
         │ Scheduler   │ (mark_success/failure)
         └──────┬──────┘
                │
       ┌────────┴────────┐
       │                 │
       ▼                 ▼
┌─────────────┐  ┌─────────────┐
│ Aggregator  │  │ Evaluation  │
│ (result)    │  │ (scoring)   │
└──────┬──────┘  └──────┬──────┘
       │                │
       └────────┬───────┘
                ▼
         ┌─────────────┐
         │   Stream    │ (XACK + enqueue downstream)
         └──────┬──────┘
                │
                ▼
         ┌─────────────┐
         │   Events    │ (Pub/Sub)
         └─────────────┘
```

---

## 3. Task and Node State Machine Audit

### 3.1 Task States

**Table: tasks.status (PostgreSQL)**

| State | Description | Transitions From | Transitions To | Terminal |
|-------|-------------|------------------|----------------|----------|
| `created` | Initial state (rarely used) | None | `planning` | No |
| `planning` | DAG generation in progress | `created` | `planned`, `running` | No |
| `planned` | DAG ready, waiting for enqueue | `planning` | `running` | No |
| `running` | DAG execution in progress | `planned`, `ready` | `completed`, `failed`, `cancelled`, `waiting_for_user` | No |
| `waiting_for_user` | HITL approval pending | `running` | `running`, `failed`, `cancelled` | No |
| `completed` | All nodes succeeded | `running` | None | Yes |
| `failed` | Node failure or rejection | `running`, `waiting_for_user` | None | Yes |
| `cancelled` | User cancellation | Any non-terminal | None | Yes |

**State Transition Owner:**
- `created` → `planning`: Planner (TaskManager.create)
- `planning` → `planned`: Scheduler (create_task)
- `planned` → `running`: Scheduler (create_task, unlock_dependents)
- `running` → `waiting_for_user`: Scheduler (mark_success with HITL)
- `running` → `completed`: Scheduler (unlock_dependents)
- `running` → `failed`: Scheduler (mark_failure, reject_node, cancel_task)
- `running` → `cancelled`: Scheduler (cancel_task)
- `waiting_for_user` → `running`: Scheduler (approve_node)
- `waiting_for_user` → `failed`: Scheduler (reject_node)
- `waiting_for_user` → `cancelled`: Scheduler (cancel_task)

**Transition Validation:**
- No explicit state machine validation in code
- Transitions are conditional UPDATEs with WHERE clauses
- Example: `UPDATE tasks SET status = 'running' WHERE id = %s AND status IN ('ready', 'planning', 'running')`
- Risk: Invalid transitions possible if WHERE clause conditions are incorrect

### 3.2 Node States

**Table: task_nodes.status (PostgreSQL)**

| State | Description | Transitions From | Transitions To | Terminal |
|-------|-------------|------------------|----------------|----------|
| `pending` | Node created, dependencies not satisfied | None | `ready`, `cancelled` | No |
| `ready` | Dependencies satisfied, ready for execution | `pending` | `running`, `cancelled` | No |
| `running` | Agent execution in progress | `ready`, `retrying` | `success`, `failed`, `retrying`, `cancelled` | No |
| `retrying` | Awaiting retry after failure | `running` | `running`, `failed`, `cancelled` | No |
| `success` | Node completed successfully | `running` | None | Yes |
| `waiting_for_user` | HITL approval pending | `running` | `success`, `failed`, `cancelled` | No |
| `failed` | Node failed after max retries | `running`, `retrying` | None | Yes |
| `cancelled` | Task cancelled | Any non-terminal | None | Yes |
| `skipped` | Not implemented in current code | N/A | N/A | Yes |

**State Transition Owner:**
- `pending` → `ready`: Scheduler (create_task, unlock_dependents)
- `ready` → `running`: Scheduler (claim_running)
- `running` → `success`: Scheduler (mark_success)
- `running` → `waiting_for_user`: Scheduler (mark_success with HITL)
- `running` → `retrying`: Scheduler (mark_failure)
- `running` → `failed`: Scheduler (mark_failure, reclaim_stale_nodes)
- `retrying` → `running`: Scheduler (claim_running)
- `waiting_for_user` → `success`: Scheduler (approve_node)
- `waiting_for_user` → `failed`: Scheduler (reject_node)
- Any → `cancelled`: Scheduler (cancel_task)

**Transition Validation:**
- Conditional UPDATEs with status checks
- Example: `UPDATE task_nodes SET status = 'running' WHERE task_id = %s AND node_key = %s AND status IN ('ready', 'retrying')`
- Attempt counter and max_retry constraints
- Risk: Race conditions between concurrent workers

### 3.3 State Transition Table

**Task State Transitions:**

| Current State | Event | Next State | Validation | Component |
|---------------|-------|------------|------------|-----------|
| `created` | Task created | `planning` | None | TaskManager |
| `planning` | Plan generated | `planned` | None | Scheduler |
| `planned` | Ready nodes enqueued | `running` | None | Scheduler |
| `running` | All nodes complete | `completed` | Node count check | Scheduler |
| `running` | Node failure (terminal) | `failed` | Max retry exceeded | Scheduler |
| `running` | HITL node success | `waiting_for_user` | requires_approval flag | Scheduler |
| `running` | User cancellation | `cancelled` | FOR UPDATE lock | Scheduler |
| `waiting_for_user` | User approval | `running` | status = 'waiting_for_user' | Scheduler |
| `waiting_for_user` | User rejection | `failed` | status = 'waiting_for_user' | Scheduler |
| `waiting_for_user` | User cancellation | `cancelled` | FOR UPDATE lock | Scheduler |

**Node State Transitions:**

| Current State | Event | Next State | Validation | Component |
|---------------|-------|------------|------------|-----------|
| `pending` | Dependencies satisfied | `ready` | All deps in completed | Scheduler |
| `ready` | Worker claims | `running` | status IN ('ready', 'retrying') | Scheduler |
| `running` | Agent success | `success` | status IN ('ready', 'running', 'retrying') | Scheduler |
| `running` | Agent success + HITL | `waiting_for_user` | requires_approval flag | Scheduler |
| `running` | Agent failure | `retrying` | attempt < max_retry | Scheduler |
| `running` | Agent failure (terminal) | `failed` | attempt >= max_retry | Scheduler |
| `retrying` | Worker claims | `running` | status IN ('ready', 'retrying') | Scheduler |
| `waiting_for_user` | User approval | `success` | status = 'waiting_for_user' | Scheduler |
| `waiting_for_user` | User rejection | `failed` | status = 'waiting_for_user' | Scheduler |
| Any non-terminal | Task cancellation | `cancelled` | status IN ('pending', 'ready', 'running', 'retrying') | Scheduler |

### 3.4 Concurrent State Update Risks

**Risk 1: Double Claim**
- **Location:** `Scheduler.claim_running()`
- **Code:** Conditional UPDATE with `WHERE status IN ('ready', 'retrying')`
- **Protection:** Single-row UPDATE atomicity
- **Risk:** Low - PostgreSQL row-level locking prevents double claim
- **Evidence:** Returns False if no row updated

**Risk 2: Concurrent Success/Failure**
- **Location:** `Scheduler.mark_success()` and `Scheduler.mark_failure()`
- **Code:** Conditional UPDATE with status check
- **Protection:** Transaction isolation
- **Risk:** Medium - race condition if same node processed by two workers
- **Evidence:** No unique constraint on (task_id, node_key, attempt)

**Risk 3: Stale Reclaim Race**
- **Location:** `Scheduler.reclaim_stale_nodes()`
- **Code:** SELECT then UPDATE without lock
- **Protection:** None
- **Risk:** High - worker may complete node between SELECT and UPDATE
- **Evidence:** Lines 248-342 in scheduler/__init__.py

**Risk 4: Task Status Inconsistency**
- **Location:** `Scheduler._unlock_dependents()`
- **Code:** Updates task status based on node completion count
- **Protection:** Transaction
- **Risk:** Medium - concurrent node completions could cause status flip-flop
- **Evidence:** No lock on task row during node updates

### 3.5 Parent/Child State Consistency

**Mechanism:**
- Parent task status derived from child node states
- `Scheduler._unlock_dependents()` counts completed nodes
- Task status = 'completed' when all nodes success
- Task status = 'failed' when any node fails (if not retryable)

**Consistency Risks:**
1. **Partial Node Failure:** Some nodes succeed, some fail → task status = 'failed' (correct)
2. **Retry After Partial Success:** Retry of failed node → task status remains 'failed' until all complete
3. **Concurrent Node Completion:** Race condition in completion count → potential status inconsistency
4. **Orchestrator Restart:** Task and node states consistent (PostgreSQL authoritative)

**Recovery Behavior:**
- On restart, task status recalculated from node states
- No explicit reconciliation logic
- Status may be stale until next node transition

### 3.6 Permanent State Risks

**Potential Stuck States:**

1. **Node `running` indefinitely:**
   - Cause: Worker crash after claim, before success/failure
   - Recovery: Stale reclaim mechanism (NODE_STALE_SECONDS)
   - Risk: If NODE_STALE_SECONDS = 0, node permanently stuck
   - Evidence: Line 79 in executor/engine.py

2. **Task `running` with all nodes `success`:**
   - Cause: Aggregator not called on completion
   - Recovery: Manual intervention or task re-evaluation
   - Risk: Low - aggregator called in executor completion path
   - Evidence: Lines 331-339 in executor/engine.py

3. **Node `retrying` with no agents available:**
   - Cause: All agents excluded or offline
   - Recovery: Manual agent registration or exclusion removal
   - Risk: Medium - no automatic timeout for retrying state
   - Evidence: No timeout mechanism for retrying state

4. **Task `waiting_for_user` indefinitely:**
   - Cause: User never approves/rejects
   - Recovery: Manual API call to approve/reject/cancel
   - Risk: Low - designed for human intervention
   - Evidence: HITL design intention

### 3.7 Cancellation Semantics

**Implementation:** `Scheduler.cancel_task()`

**Behavior:**
- FOR UPDATE lock on task row
- Updates task status to 'cancelled'
- Updates all non-terminal nodes to 'cancelled'
- Sets finished_at timestamp
- Logs cancellation event

**Limitations:**
- Does not cancel in-flight A2A requests
- Does not revoke Redis queue messages
- Workers may still process already-claimed nodes
- Cancellation is "best effort" for in-flight work

**Evidence:** Lines 876-921 in scheduler/__init__.py

### 3.8 Duplicate Completion Handling

**Node Completion:**
- `mark_success()` uses conditional UPDATE: `WHERE status IN ('ready', 'running', 'retrying')`
- Duplicate completion silently ignored (no row updated)
- Second completion does not re-unlock dependents
- Risk: Medium - could miss downstream unlocks if first completion failed mid-transaction

**Task Completion:**
- `_unlock_dependents()` checks completed count vs total
- Multiple calls to `mark_success()` on last node safe
- Aggregator called once per task completion
- Risk: Low - idempotent completion handling

---

## 4. Failure and Recovery Audit

### 4.1 Failure Scenario Analysis

#### Scenario 1: Agent Returns Execution Error

**Current Code Path:**
1. `ExecutionEngine.handle()` calls `A2AExecutor.execute()`
2. Agent returns error status in A2A response
3. `ExecutionResult.ok` returns False
4. Raises `RuntimeError(f"a2a status={result.task.status.value}")`
5. Caught in exception handler, calls `_on_failure()`
6. `Scheduler.mark_failure()` determines retry vs fail

**Expected Behavior:**
- Error classified via `handle_a2a_error()`
- Retry if attempt < max_retry
- Fail if attempt >= max_retry
- Exclude failed agent from retry

**Actual Recovery Mechanism:**
- Attempt counter incremented
- Exclude agent added to retry message
- Backoff delay applied (1s, 3s, 10s)
- New message enqueued to Redis

**State Consistency Risk:**
- **Medium:** If `mark_failure()` succeeds but Redis enqueue fails, node in `retrying` state with no retry message
- **Evidence:** Lines 405-443 in executor/engine.py

**Duplicate Execution Risk:**
- **Low:** Retry includes attempt number and exclude_agent_ids
- **Evidence:** Retry message includes attempt field

**Automated Tests:**
- **Partial:** `test_mark_failure_retries_then_fails` in test_scheduler_flow.py
- **Coverage:** Tests retry logic but not Redis enqueue failure

**Severity:** P1
**User Impact:** Agent errors trigger retry with backoff, eventual failure after max retries

---

#### Scenario 2: Agent Request Times Out

**Current Code Path:**
1. `A2AExecutor.execute()` uses timeout parameter (default 60s)
2. Timeout raises exception (connection timeout)
3. Caught in executor exception handler
4. Calls `_on_failure()` with timeout error
5. `Scheduler.mark_failure()` treats as retryable error

**Expected Behavior:**
- Timeout classified as transient error
- Retry with same or different agent
- Backoff delay applied

**Actual Recovery Mechanism:**
- Same as Scenario 1 (retry via `mark_failure()`)
- No special timeout handling beyond default retry
- Circuit breaker may trigger if enabled (ERROR_HANDLING_AVAILABLE)

**State Consistency Risk:**
- **High:** Timeout may leave Agent still processing request
- Retry may cause duplicate Agent execution
- Agent may complete both requests, causing side effects

**Duplicate Execution Risk:**
- **High:** No idempotency key sent to Agent
- Agent cannot distinguish duplicate timeout retries
- **Evidence:** Lines 61-95 in executor/__init__.py

**Automated Tests:**
- **None:** No timeout-specific tests found
- **Coverage:** Not tested

**Severity:** P0
**User Impact:** Timeouts may cause duplicate Agent execution and side effects

---

#### Scenario 3: Agent Becomes Unreachable

**Current Code Path:**
1. Router selects agent from available pool
2. A2AExecutor.execute() attempts HTTP connection
3. Connection fails (network error, DNS failure, etc.)
4. Exception caught and classified via `handle_a2a_error()`
5. Returns `NetworkError` or `AgentError`
6. Worker calls `_on_failure()` with network error
7. `Scheduler.mark_failure()` marks node for retry

**Expected Behavior:**
- Network error classified as transient
- Retry with different agent (exclude failed agent)
- Circuit breaker may open for repeated failures

**Actual Recovery Mechanism:**
- `exclude_agent_ids` includes unreachable agent
- Router will select different agent on retry
- Circuit breaker limits repeated calls to same endpoint

**State Consistency Risk:**
- **Low:** No state changes until Agent responds
- Failed agent excluded from future routing

**Duplicate Execution Risk:**
- **Low:** No execution occurred, no side effects

**Automated Tests:**
- **Partial:** Circuit breaker tests in test_error_handling.py
- **Coverage:** Tests circuit breaker but not agent unreachability

**Severity:** P1
**User Impact:** Unreachable agents trigger failover to alternative agents

---

#### Scenario 4: Redis Message Delivered More Than Once

**Current Code Path:**
1. Redis Streams provides at-least-once delivery
2. Worker reads message via XREADGROUP
3. Worker processes message in `ExecutionEngine.handle()`
4. Worker calls XACK to acknowledge
5. If worker crashes before XACK, message re-delivered

**Expected Behavior:**
- Redis consumer group re-delivers unacknowledged messages
- Same message processed by different worker

**Actual Recovery Mechanism:**
- No deduplication at execution layer
- `claim_running()` provides some protection via conditional UPDATE
- Second claim attempt returns False, skips execution

**State Consistency Risk:**
- **Medium:** If first claim succeeds but worker crashes before XACK, second worker skips (good)
- **Medium:** If first claim fails but worker crashes, second worker may claim (good)
- **High:** If first claim succeeds and worker crashes after success but before XACK, second worker skips (no problem)

**Duplicate Execution Risk:**
- **Low:** `claim_running()` conditional UPDATE prevents double execution
- **Risk:** If claim succeeds but success marking fails, retry may cause duplicate execution

**Automated Tests:**
- **Partial:** `test_claim_running_is_idempotent` in test_scheduler_flow.py
- **Coverage:** Tests claim idempotency but not message re-delivery scenario

**Severity:** P1
**User Impact:** Redis at-least-once delivery mitigated by conditional claim, but not fully protected

---

#### Scenario 5: Worker Crashes After Claiming Task

**Current Code Path:**
1. Worker calls `Scheduler.claim_running()` - succeeds
2. Worker crashes (process kill, OOM, etc.)
3. Node status = 'running' in PostgreSQL
4. No XACK sent to Redis
5. Redis message remains in pending

**Expected Behavior:**
- Redis message re-delivered to another worker
- Second worker attempts claim
- First claim prevents second claim

**Actual Recovery Mechanism:**
- Second worker's `claim_running()` returns False (node already running)
- Second worker skips execution
- Stale reclaim mechanism eventually recovers node

**State Consistency Risk:**
- **High:** Node stuck in 'running' state until stale reclaim
- If NODE_STALE_SECONDS = 0, node permanently stuck
- Task may never complete

**Duplicate Execution Risk:**
- **Low:** Conditional claim prevents double execution

**Automated Tests:**
- **Partial:** `test_reclaim_stale_running_enqueues_retry` in test_stale_reclaim.py
- **Coverage:** Tests stale reclaim but not worker crash scenario

**Severity:** P1
**User Impact:** Worker crash leaves node in 'running' state, requires stale reclaim for recovery

---

#### Scenario 6: Worker Crashes After Agent Execution But Before Persisting Result

**Current Code Path:**
1. Agent executes successfully, returns result
2. Worker crashes before `Scheduler.mark_success()`
3. Agent believes task completed
4. PostgreSQL shows node still 'running'
5. Artifacts may or may not be persisted to MinIO

**Expected Behavior:**
- No automatic recovery
- Manual intervention required
- Stale reclaim may retry, causing duplicate Agent execution

**Actual Recovery Mechanism:**
- None - no detection of Agent success without persistence
- Stale reclaim will treat as timeout and retry
- Agent may execute duplicate request

**State Consistency Risk:**
- **Critical:** Agent success not reflected in PostgreSQL
- External side effects already occurred
- Retry will cause duplicate side effects

**Duplicate Execution Risk:**
- **Critical:** No idempotency, Agent will execute duplicate request
- External systems may see duplicate effects

**Automated Tests:**
- **None:** No tests for this scenario
- **Coverage:** Not tested

**Severity:** P0
**User Impact:** Worker crash after Agent success causes data inconsistency and duplicate execution

---

#### Scenario 7: Orchestrator Restarts While DAG Is Running

**Current Code Path:**
1. Orchestrator process crashes or restarts
2. In-memory state lost
3. PostgreSQL state persists
4. Redis queue state persists

**Expected Behavior:**
- Workers continue processing from Redis
- Orchestrator HTTP API unavailable during restart
- Task execution continues if workers independent

**Actual Recovery Mechanism:**
- Workers are independent processes, continue running
- Orchestrator restart does not affect worker execution
- PostgreSQL state remains authoritative
- Workers continue claiming and processing nodes

**State Consistency Risk:**
- **Low:** State persisted in PostgreSQL and Redis
- Workers can complete tasks without Orchestrator
- HTTP API temporarily unavailable

**Duplicate Execution Risk:**
- **Low:** Workers maintain their state via Redis consumer groups

**Automated Tests:**
- **None:** No orchestrator restart tests
- **Coverage:** Not tested

**Severity:** P2
**User Impact:** Orchestrator restart does not affect running tasks, HTTP API temporarily unavailable

---

#### Scenario 8: PostgreSQL Update Fails After External Agent Succeeds

**Current Code Path:**
1. Agent executes successfully
2. Worker calls `Scheduler.mark_success()`
3. PostgreSQL UPDATE fails (connection error, constraint violation, etc.)
4. Agent success confirmed externally
5. PostgreSQL state not updated

**Expected Behavior:**
- Transaction rollback
- Node status unchanged
- Worker may retry or fail

**Actual Recovery Mechanism:**
- Exception caught in worker error handler
- `_on_failure()` called
- Node marked for retry or failure
- Retry may cause duplicate Agent execution

**State Consistency Risk:**
- **Critical:** External success not reflected in PostgreSQL
- Agent state inconsistent with orchestrator state
- Retry causes duplicate execution

**Duplicate Execution Risk:**
- **Critical:** No idempotency, duplicate Agent execution
- External side effects duplicated

**Automated Tests:**
- **None:** No PostgreSQL failure tests
- **Coverage:** Not tested

**Severity:** P0
**User Impact:** PostgreSQL failure after Agent success causes data inconsistency and duplicate execution

---

#### Scenario 9: Artifact Upload Succeeds But Task Completion Persistence Fails

**Current Code Path:**
1. Agent executes successfully
2. Artifacts uploaded to MinIO successfully
3. Worker calls `Scheduler.mark_success()`
4. PostgreSQL UPDATE fails
5. Artifacts exist in MinIO but task not marked complete

**Expected Behavior:**
- Transaction rollback
- Node status unchanged
- Artifacts orphaned in MinIO

**Actual Recovery Mechanism**
- None - orphaned artifacts not cleaned up
- Retry may upload duplicate artifacts
- No deduplication in MinIO uploads

**State Consistency Risk:**
- **High:** Artifacts exist without corresponding task state
- Storage leak (orphaned artifacts)
- Potential storage cost increase

**Duplicate Execution Risk:**
- **High:** Retry uploads duplicate artifacts
- No deduplication in artifact paths

**Automated Tests:**
- **None:** No artifact upload failure tests
- **Coverage:** Not tested

**Severity:** P1
**User Impact:** Artifact orphanage and storage leaks on PostgreSQL failures

---

#### Scenario 10: Retry Limit Reached

**Current Code Path:**
1. Node fails repeatedly
2. Attempt counter increments
3. Attempt >= max_retry (default 3)
4. `Scheduler.mark_failure()` marks node as 'failed'
5. Task marked as 'failed'

**Expected Behavior:**
- Node permanently failed
- Task marked as failed
- No further retries
- Evaluation executed on failed task

**Actual Recovery Mechanism**
- Manual intervention required
- Option to manually retry task
- No automatic escalation or alerting

**State Consistency Risk:**
- **Low:** Terminal state is consistent
- Task and node states reflect failure

**Duplicate Execution Risk:**
- **None:** Terminal state prevents further execution

**Automated Tests:**
- **Partial:** `test_mark_failure_retries_then_fails` in test_scheduler_flow.py
- **Coverage:** Tests retry limit but not recovery mechanisms

**Severity:** P2
**User Impact:** Manual intervention required after retry exhaustion

---

#### Scenario 11: Parent DAG Node Fails While Dependent Nodes Are Pending

**Current Code Path:**
1. Parent node fails after max retries
2. `Scheduler.mark_failure()` marks node as 'failed'
3. `Scheduler.mark_failure()` marks task as 'failed'
4. Dependent nodes still in 'pending' state

**Expected Behavior:**
- Task marked as failed
- Dependent nodes never execute
- DAG execution halts

**Actual Recovery Mechanism**
- `cancel_task()` updates pending nodes to 'cancelled'
- No automatic cancellation of dependents on parent failure
- Dependents remain in 'pending' state

**State Consistency Risk:**
- **Medium:** Pending nodes never transition
- Task status = 'failed' but nodes = 'pending'
- Inconsistent state representation

**Duplicate Execution Risk:**
- **None:** Task failed, no further execution

**Automated Tests:**
- **None:** No dependent node failure tests
- **Coverage:** Not tested

**Severity:** P2
**User Impact:** Dependent nodes left in pending state after parent failure

---

#### Scenario 12: User Cancels a Running Task

**Current Code Path:**
1. User calls POST /v1/tasks/{task_id}/cancel
2. `Scheduler.cancel_task()` executed
3. Task status updated to 'cancelled'
4. Node statuses updated to 'cancelled' (non-terminal nodes only)
5. In-flight Agent requests not cancelled

**Expected Behavior:**
- Task and nodes marked as cancelled
- Workers skip cancelled nodes
- In-flight Agent requests complete (no cancellation)

**Actual Recovery Mechanism**
- Workers check node status before processing
- Cancelled nodes skipped in `claim_running()`
- No cancellation of in-flight A2A requests

**State Consistency Risk:**
- **Medium:** In-flight Agent requests may complete after cancellation
- Worker may attempt to mark success on cancelled node
- Conditional UPDATE prevents status change

**Duplicate Execution Risk:**
- **Low:** Cancellation prevents new executions
- In-flight requests may complete once

**Automated Tests:**
- **None:** No cancellation tests
- **Coverage:** Not tested

**Severity:** P2
**User Impact:** Cancellation is best-effort, in-flight requests complete

---

#### Scenario 13: Late Agent Response Arrives After Timeout or Cancellation

**Current Code Path:**
1. Agent request times out or task cancelled
2. Worker marks node as failed/cancelled
3. Agent later completes request
4. No mechanism to handle late response

**Expected Behavior:**
- Late response ignored
- No state change from late response

**Actual Recovery Mechanism**
- None - late responses not handled
- Worker already moved on to retry or failure
- No callback registration for late responses

**State Consistency Risk:**
- **Low:** Late response ignored
- No state impact

**Duplicate Execution Risk:**
- **Low:** Late response ignored
- No side effects from late response

**Automated Tests:**
- **None:** No late response tests
- **Coverage:** Not tested

**Severity:** P3
**User Impact:** Late Agent responses ignored, no impact on system state

---

### 4.2 Failure Matrix

| Scenario | Current Code Path | Expected Behavior | Actual Recovery | State Consistency Risk | Duplicate Execution Risk | Automated Tests | Severity |
|----------|------------------|------------------|-----------------|------------------------|-------------------------|-----------------|----------|
| Agent execution error | executor/engine.py:handle() | Retry with backoff | mark_failure() + retry enqueue | Medium (retry enqueue fail) | Low (attempt tracking) | Partial | P1 |
| Agent timeout | executor/__init__.py:execute() | Retry with backoff | mark_failure() + retry enqueue | High (Agent still processing) | High (no idempotency) | None | P0 |
| Agent unreachable | router/__init__.py:select() | Failover to other agent | exclude_agent_ids + retry | Low (no state change) | Low (no execution) | Partial | P1 |
| Redis duplicate delivery | streams/__init__.py:read_execution() | Skip duplicate claim | claim_running() returns False | Medium (claim/success race) | Low (conditional claim) | Partial | P1 |
| Worker crash after claim | scheduler/__init__.py:claim_running() | Stale reclaim recovery | reclaim_stale_nodes() | High (stuck if NODE_STALE_SECONDS=0) | Low (conditional claim) | Partial | P1 |
| Worker crash after Agent success | executor/engine.py:handle() | No recovery | None (manual only) | Critical (success not persisted) | Critical (duplicate execution) | None | P0 |
| Orchestrator restart | N/A (process crash) | Workers continue | Workers independent | Low (state persisted) | Low (consumer groups) | None | P2 |
| PostgreSQL update fail after Agent success | scheduler/__init__.py:mark_success() | Retry causes duplicate | mark_failure() + retry | Critical (success not persisted) | Critical (duplicate execution) | None | P0 |
| Artifact upload success, persistence fail | artifacts/__init__.py:persist_node_output() | Orphaned artifacts | None (manual cleanup) | High (orphaned artifacts) | High (duplicate uploads) | None | P1 |
| Retry limit reached | scheduler/__init__.py:mark_failure() | Permanent failure | Manual intervention | Low (terminal state) | None (terminal state) | Partial | P2 |
| Parent node fails, dependents pending | scheduler/__init__.py:mark_failure() | Dependents never execute | No auto-cancellation | Medium (pending nodes stuck) | None (task failed) | None | P2 |
| User cancels running task | scheduler/__init__.py:cancel_task() | Best-effort cancellation | Workers skip cancelled nodes | Medium (in-flight requests) | Low (in-flight complete once) | None | P2 |
| Late Agent response | N/A (no handler) | Ignore late response | None (ignored) | Low (ignored) | Low (ignored) | None | P3 |

---

## 5. Idempotency and Duplicate Execution Audit

### 5.1 Idempotency Analysis by Layer

#### Task Submission
- **Idempotency:** None
- **Mechanism:** No idempotency key or deduplication
- **Impact:** Duplicate API calls create separate tasks
- **Evidence:** `TaskManager.create()` has no idempotency check
- **Risk:** Low - API layer idempotency typically handled by client

#### Queue Consumption
- **Idempotency:** Partial
- **Mechanism:** Redis Streams at-least-once delivery
- **Protection:** Consumer group with pending message tracking
- **Impact:** Messages may be re-delivered after worker crash
- **Evidence:** `StreamClient.read_execution()` uses XREADGROUP
- **Risk:** Medium - duplicate delivery possible

#### Node Execution
- **Idempotency:** Partial
- **Mechanism:** Conditional UPDATE in `claim_running()`
- **Protection:** `WHERE status IN ('ready', 'retrying')` prevents double claim
- **Impact:** Second claim attempt returns False, skips execution
- **Evidence:** Lines 344-382 in scheduler/__init__.py
- **Risk:** Low - effective protection against double execution

#### A2A Task Creation
- **Idempotency:** None
- **Mechanism:** No idempotency key sent to Agents
- **Protection:** None
- **Impact:** Retry sends duplicate request to Agent
- **Evidence:** `A2AExecutor.execute()` has no idempotency key
- **Risk:** Critical - duplicate Agent execution possible

#### Retry Attempts
- **Idempotency:** Partial
- **Mechanism:** Attempt counter and exclude_agent_ids
- **Protection:** Retry includes attempt number, excludes failed agents
- **Impact:** Retries distinguishable by attempt number
- **Evidence:** Retry message includes attempt field
- **Risk:** Medium - Agent sees duplicate requests without idempotency

#### Artifact Creation
- **Idempotency:** None
- **Mechanism:** No deduplication in MinIO uploads
- **Protection:** None
- **Impact:** Retry uploads duplicate artifacts
- **Evidence:** `ArtifactStore.persist_node_output()` has no deduplication
- **Risk:** High - storage leak from duplicate uploads

#### Aggregation
- **Idempotency:** Yes
- **Mechanism:** Overwrites result_json
- **Protection:** Idempotent UPDATE
- **Impact:** Multiple calls produce same result
- **Evidence:** `Aggregator.build_result()` overwrites result_json
- **Risk:** Low - idempotent by design

#### Billing/Quota Side Effects
- **Idempotency:** Partial
- **Mechanism:** Database constraints and idempotent operations
- **Protection:** Quota checks are reads, billing is estimation only
- **Impact:** Quota enforcement may double-count on retry
- **Evidence:** `QuotaService.assert_can_create_task()` is read-only
- **Risk:** Medium - quota enforcement may be inconsistent

### 5.2 Idempotency Boundaries

**At-Most-Once Behavior:**
- Task submission: Not at-most-once (creates separate tasks)
- Node execution: Effectively at-most-once via conditional claim
- Aggregation: At-most-once (idempotent UPDATE)

**At-Least-Once Behavior:**
- Queue consumption: At-least-once (Redis Streams)
- A2A execution: At-least-once (no idempotency)
- Artifact creation: At-least-once (no deduplication)

**Effectively-Once Behavior:**
- Node execution: Effectively once (conditional claim protection)
- Task completion: Effectively once (idempotent aggregation)

**Exactly-Once Claims (Not Supported):**
- A2A execution: No exactly-once guarantees
- Artifact creation: No exactly-once guarantees
- Billing/quota: No exactly-once guarantees

### 5.3 Duplicate Execution Boundaries

**Boundary 1: Redis Message Delivery**
- **Risk:** At-least-once delivery may cause duplicate processing
- **Protection:** Conditional claim at database layer
- **Gap:** If claim succeeds but processing fails, retry may cause issues

**Boundary 2: Agent Request/Response**
- **Risk:** No idempotency key, duplicate requests cause duplicate execution
- **Protection:** None
- **Gap:** Critical - no protection against duplicate Agent execution

**Boundary 3: Artifact Upload**
- **Risk:** No deduplication, duplicate uploads cause storage leak
- **Protection:** None
- **Gap:** High - storage leak and duplicate artifacts

**Boundary 4: PostgreSQL State Updates**
- **Risk:** Transaction rollback on failure may cause inconsistency
- **Protection:** ACID transactions
- **Gap:** Cross-system coordination (PostgreSQL + Redis + MinIO)

### 5.4 Idempotency Mechanisms Summary

| Operation | Idempotency Mechanism | Effectiveness | Gap |
|-----------|----------------------|---------------|-----|
| Task creation | None | None | No deduplication |
| Queue enqueue | None (append-only) | N/A | Expected behavior |
| Queue consumption | Consumer group | Medium | At-least-once delivery |
| Node claim | Conditional UPDATE | High | Effective protection |
| A2A execution | None | None | Critical gap |
| Artifact upload | None | None | High gap |
| Success marking | Conditional UPDATE | High | Effective protection |
| Failure marking | Attempt counter | Medium | Retry tracking |
| Aggregation | Idempotent UPDATE | High | Effective |
| Evaluation | ON CONFLICT UPDATE | High | Effective |

---

## 6. DAG and Parallel Execution Audit

### 6.1 Dependency Readiness Implementation

**Implementation:** `ready_node_ids()` in planner/dag.py

**Logic:**
- Takes list of nodes, completed set, pending set
- Returns nodes in pending whose dependencies are all in completed
- Linear scan over pending nodes
- Dependency check: `all(dep in completed for dep in node.depends_on)`

**Evidence:** Lines 108-116 in planner/dag.py

**Correctness:**
- Correctly identifies ready nodes
- Handles parallel root nodes (no dependencies)
- Handles sequential dependencies
- Handles diamond dependencies (multiple dependents)

**Limitations:**
- In-memory computation, requires loading all nodes
- No optimization for large DAGs
- No support for dynamic dependencies

### 6.2 Parallel Branch Execution

**Implementation:** Redis Streams consumer group with multiple workers

**Mechanism:**
- Multiple ready nodes enqueued as separate messages
- Multiple workers consume from same consumer group
- Redis consumer group distributes messages among workers
- Parallel execution of independent nodes

**Evidence:** Lines 103-114 in streams/__init__.py

**Correctness:**
- Correctly enables parallel execution
- Consumer group provides load distribution
- No coordination needed for independent nodes

**Limitations:**
- No maximum concurrency control at DAG level
- No prioritization of critical paths
- No resource-aware scheduling

### 6.3 Maximum Concurrency Control

**Implementation:** QuotaService concurrent task limit

**Mechanism:**
- `QuotaService.assert_can_create_task()` checks concurrent task count
- Count: `SELECT COUNT(*) FROM tasks WHERE status IN ('running', 'waiting_for_user', 'created')`
- Enforced at task creation, not node execution
- Configurable via `max_concurrent_tasks`

**Evidence:** Lines 438-471 in quota/__init__.py

**Correctness:**
- Limits total concurrent tasks per tenant
- Does not limit parallel nodes within a task
- Does not limit concurrent Agent calls

**Limitations:**
- No per-task concurrency limit
- No per-skill concurrency limit
- No resource-based concurrency limits

### 6.4 Dependency Failure Propagation

**Implementation:** Task failure on node failure

**Mechanism:**
- `Scheduler.mark_failure()` marks task as 'failed' when node fails
- Dependent nodes never transition from 'pending'
- Task status = 'failed' even if some nodes succeeded

**Evidence:** Lines 574-581 in scheduler/__init__.py

**Correctness:**
- Correctly halts DAG on node failure
- Prevents execution of dependent nodes
- Maintains task-node consistency

**Limitations:**
- No selective failure (fail specific branch, continue others)
- No retry of individual failed nodes without task retry
- No compensation transactions for partial success

### 6.5 Retry of Individual Node

**Implementation:** Attempt-based retry with agent exclusion

**Mechanism:**
- `mark_failure()` increments attempt counter
- Retry if attempt < max_retry
- Exclude failed agent from retry
- Backoff delay between attempts

**Evidence:** Lines 505-531 in scheduler/__init__.py

**Correctness:**
- Correctly retries individual nodes
- Tracks attempt count
- Excludes failing agents

**Limitations:**
- No exponential backoff at database level
- No circuit breaker at node level
- No manual retry mechanism

### 6.6 Retry of Parent Task

**Implementation:** Create new task with same input

**Mechanism:**
- No built-in task retry
- User creates new task via API
- New task gets new task_id and nodes
- Original task remains in failed state

**Correctness:**
- Simple but effective
- Maintains audit trail
- No automatic retry

**Limitations:**
- No automatic task retry
- No retry with same task_id
- No resume from failed state

### 6.7 Partial Success Handling

**Implementation:** Task failed state on any node failure

**Mechanism:**
- Any node failure marks task as 'failed'
- Successful nodes remain in 'success' state
- Failed nodes marked with error details
- Aggregation includes partial results

**Evidence:** Lines 574-581 in scheduler/__init__.py

**Correctness:**
- Correctly identifies partial success
- Preserves successful node outputs
- Maintains audit trail

**Limitations:**
- No compensation for partial success
- No selective retry of failed branches
- No partial completion status

### 6.8 Output Aggregation

**Implementation:** Aggregator.build_result()

**Mechanism:**
- Collects all node outputs from PostgreSQL
- Builds summary from successful nodes
- Includes artifact references
- Stores in tasks.result_json

**Evidence:** Lines 25-109 in aggregator/__init__.py

**Correctness:**
- Correctly aggregates successful outputs
- Handles missing outputs gracefully
- Preserves artifact references

**Limitations:**
- Only called on task completion
- No incremental aggregation
- No aggregation on partial success

### 6.9 Artifact References Between Nodes

**Implementation:** Output JSON with artifact URIs

**Mechanism:**
- Node output includes artifact URIs
- Downstream nodes load artifacts from URIs
- Executor composes query with upstream artifact content
- MinIO stores artifacts with consistent paths

**Evidence:** Lines 463-511 in executor/engine.py

**Correctness:**
- Correctly references artifacts between nodes
- Loads artifact content for downstream nodes
- Consistent path structure

**Limitations:**
- No artifact deduplication
- No artifact versioning
- No artifact garbage collection

### 6.10 Deadlock or Permanently Pending Nodes

**Potential Deadlock Scenarios:**

1. **Circular Dependencies:**
   - **Prevention:** DAG validation detects cycles
   - **Evidence:** Lines 88-105 in planner/dag.py
   - **Risk:** Low - validated at plan time

2. **Dependency on Failed Node:**
   - **Behavior:** Dependent nodes remain in 'pending'
   - **Recovery:** No automatic recovery
   - **Risk:** Medium - requires manual intervention

3. **Excluded All Agents:**
   - **Behavior:** Node in 'retrying' state, no agents available
   - **Recovery:** Manual agent registration
   - **Risk:** Medium - no automatic timeout

4. **Stale Node Reclaim Disabled:**
   - **Behavior:** NODE_STALE_SECONDS = 0
   - **Recovery:** Manual intervention
   - **Risk:** High - nodes permanently stuck

**Permanently Pending Prevention:**
- Stale reclaim mechanism (if enabled)
- DAG validation prevents cycles
- Conditional claims prevent stuck claims
- Timeout limits prevent indefinite execution

### 6.11 Real DAG Execution Trace

**Test Case:** Research pipeline DAG (search → rag → analysis → report)

**Implementation:** `test_create_task_marks_parallel_roots_ready` in test_scheduler_flow.py

**Trace:**
1. Plan created with 4 nodes: search, rag (parallel), analysis (depends on search, rag), report (depends on analysis)
2. `Scheduler.create_task()` creates task and nodes
3. Ready nodes: search, rag (both have no dependencies)
4. Two messages enqueued to Redis
5. Workers claim and execute search and rag in parallel
6. Both succeed, unlock analysis
7. Analysis executes, succeeds, unlocks report
8. Report executes, succeeds
9. Task completes

**Evidence:** Lines 37-48 in test_scheduler_flow.py

**Correctness:**
- Correctly identifies parallel roots
- Correctly unlocks dependents
- Correctly handles sequential dependencies

**Test Coverage:**
- Basic DAG execution tested
- Parallel execution tested
- Dependency unlocking tested
- Failure scenarios not covered in this test

---

## 7. Existing Tests and Coverage

### 7.1 Test Inventory

**Total Test Files:** 24 Python test files  
**Total Test Lines:** ~2,114 lines (estimated)  
**Test Framework:** pytest

**Test Files:**
1. `test_application_refactor.py` - Application layer refactoring tests
2. `test_billing.py` - Billing service tests
3. `test_billing_webhook.py` - Stripe webhook tests
4. `test_browser_agent.py` - Browser agent integration tests
5. `test_code_agent_safe.py` - Code agent safety tests
6. `test_dag.py` - DAG validation and ready node tests
7. `test_egress.py` - Egress policy tests
8. `test_error_handling.py` - Error handling and retry policy tests
9. `test_invoice.py` - Invoice generation tests
10. `test_migrate.py` - Database migration tests
11. `test_observability_metrics.py` - Metrics collection tests
12. `test_planner_heuristic.py` - Planner heuristic tests
13. `test_planner_v2.py` - Planner v2 tests
14. `test_pubsub_fanout.py` - Pub/Sub fanout tests
15. `test_quota.py` - Quota enforcement tests
16. `test_quota_boost.py` - Quota boost tests
17. `test_router.py` - Agent routing tests
18. `test_sandbox.py` - Sandbox policy tests
19. `test_scheduler_flow.py` - Scheduler integration tests
20. `test_seccomp_profiles.py` - Seccomp profile tests
21. `test_stale_reclaim.py` - Stale node reclaim tests
22. `test_stripe_checkout.py` - Stripe checkout tests
23. `test_tenant_memory.py` - Tenant memory tests

**Gateway Tests (Go):**
1. `apikey_test.go` - API key authentication tests
2. `audit_test.go` - Audit logging tests
3. `rbac_test.go` - RBAC authorization tests
4. `user_test.go` - User management tests
5. `proxy_test.go` - Load balancer proxy tests

### 7.2 Critical Scenario Coverage

| Scenario | Test File | Test Function | Coverage |
|----------|-----------|--------------|----------|
| Task lifecycle | test_scheduler_flow.py | test_create_task_marks_parallel_roots_ready | Partial |
| DAG execution | test_dag.py | test_validate_ok_linear_dag | Partial |
| Retry | test_scheduler_flow.py | test_mark_failure_retries_then_fails | Partial |
| Timeout | None | N/A | Not tested |
| Worker recovery | test_stale_reclaim.py | test_reclaim_stale_running_enqueues_retry | Partial |
| Duplicate delivery | test_scheduler_flow.py | test_claim_running_is_idempotent | Partial |
| Idempotency | None | N/A | Not tested |
| A2A failure | None | N/A | Not tested |
| Artifact consistency | None | N/A | Not tested |
| Cancellation | None | N/A | Not tested |
| Failover | test_error_handling.py | test_circuit_breaker_opens_after_threshold | Partial |
| E2E execution | None | N/A | Not tested |

### 7.3 Coverage Classification

**Tested:**
- DAG validation (cycles, duplicate IDs, missing dependencies)
- Ready node selection (parallel roots, sequential dependencies)
- Scheduler claim idempotency
- Scheduler success/failure marking
- Retry logic (attempt counter, max_retry)
- HITL approve/reject
- Stale node reclaim
- Circuit breaker (unit level)
- Error classification
- Retry policy (unit level)

**Partially Tested:**
- Task creation and enqueue
- Node unlock and dependent execution
- Agent routing (unit level, no integration)
- Billing estimation (unit level)
- Quota enforcement (unit level)
- Artifact storage (unit level)
- Evaluation scoring (unit level)

**Not Tested:**
- End-to-end task execution (real Agent calls)
- Timeout handling
- Worker crash recovery
- PostgreSQL failure scenarios
- Artifact upload failure
- Duplicate Redis message delivery
- A2A protocol failure modes
- Orchestrator restart during execution
- Cancellation during execution
- Late Agent response handling
- Exactly-once execution guarantees
- Distributed transaction consistency
- Parallel execution at scale
- Resource exhaustion scenarios

**Cannot Determine:**
- Production environment stress tests
- Long-running execution stability
- Network partition scenarios
- Database failover scenarios
- Redis failover scenarios

### 7.4 Test Quality Assessment

**Strengths:**
- Good unit test coverage for core algorithms
- Integration tests for scheduler flow
- Database-backed tests with proper fixtures
- Test isolation with disposable agents

**Weaknesses:**
- Limited end-to-end testing
- Missing failure scenario tests
- No chaos engineering
- No performance/load testing
- No distributed system failure tests
- Missing idempotency tests
- Missing crash recovery tests

**Gaps:**
- No integration tests with real Agents
- No Redis failure simulation
- No PostgreSQL failure simulation
- No network partition testing
- No resource exhaustion testing
- No concurrent execution stress tests

---

## 8. Prioritized Findings

### P0 - Critical Risks

#### P0-001: No Exactly-Once Execution Guarantees

**Severity:** P0 (Critical)  
**Evidence:** `executor/__init__.py:61-95`, `scheduler/__init__.py:384-478`  
**File:** `apps/orchestrator/executor/__init__.py`  
**Function:** `A2AExecutor.execute()`  
**Code Behavior:** A2A execution has no idempotency key, retry sends duplicate request to Agent

**Reproduction Scenario:**
1. Worker executes Agent request
2. Worker crashes after Agent success but before persistence
3. Retry sends duplicate request to Agent
4. Agent executes request twice, causing duplicate side effects

**User-Visible Impact:**
- Duplicate Agent execution
- Duplicate external side effects (API calls, database writes, etc.)
- Data inconsistency
- Duplicate billing charges (if Agent has side effects)

**Recommended Remediation:**
- Add idempotency key to A2A protocol
- Implement idempotency in Agent SDK
- Track request IDs in orchestrator
- Deduplicate based on request ID

**Dependencies/Blockers:**
- Requires A2A protocol change
- Requires Agent SDK updates
- Requires schema migration for request tracking

**Schema Migration Required:** Yes

---

#### P0-002: Worker Crash Between Agent Success and Persistence

**Severity:** P0 (Critical)  
**Evidence:** `executor/engine.py:240-322`  
**File:** `apps/orchestrator/executor/engine.py`  
**Function:** `ExecutionEngine.handle()`  
**Code Behavior:** Agent execution succeeds, but worker may crash before PostgreSQL persistence

**Reproduction Scenario:**
1. Agent completes request successfully
2. Worker crashes before `Scheduler.mark_success()`
3. Agent state: completed
4. PostgreSQL state: node still 'running'
5. Retry causes duplicate Agent execution

**User-Visible Impact:**
- Data inconsistency between Agent and orchestrator
- Duplicate Agent execution on retry
- Lost results
- User sees task failed despite Agent success

**Recommended Remediation:**
- Implement two-phase commit with Agent
- Add Agent callback mechanism
- Implement exactly-once processing
- Add request acknowledgment before execution

**Dependencies/Blockers:**
- Requires Agent protocol changes
- Requires callback infrastructure
- Requires state reconciliation logic

**Schema Migration Required:** Possibly (for request tracking)

---

#### P0-003: No Distributed Transaction Coordination

**Severity:** P0 (Critical)  
**Evidence:** `scheduler/__init__.py:69-95`, `streams/__init__.py:55-81`  
**File:** `apps/orchestrator/scheduler/__init__.py`, `apps/orchestrator/streams/__init__.py`  
**Function:** `Scheduler.create_task()`, `StreamClient.enqueue_execution()`  
**Code Behavior:** PostgreSQL transaction and Redis enqueue are not atomic

**Reproduction Scenario:**
1. PostgreSQL transaction commits (task created, nodes ready)
2. Redis enqueue fails (network error, Redis down)
3. Task in PostgreSQL shows 'running'
4. No messages in Redis queue
5. Task never progresses

**User-Visible Impact:**
- Task stuck in 'running' state
- No workers processing the task
- Manual intervention required
- User sees task never completes

**Recommended Remediation:**
- Implement transactional outbox pattern
- Add compensating transactions
- Implement reconciliation logic
- Add saga pattern for distributed transactions

**Dependencies/Blockers:**
- Requires architectural changes
- Requires reconciliation infrastructure
- Requires monitoring for orphaned tasks

**Schema Migration Required:** Yes (for outbox table)

---

### P1 - Major Reliability Gaps

#### P1-001: Stale Node Reclaim Race Conditions

**Severity:** P1 (Major)  
**Evidence:** `scheduler/__init__.py:242-342`  
**File:** `apps/orchestrator/scheduler/__init__.py`  
**Function:** `Scheduler.reclaim_stale_nodes()`  
**Code Behavior:** SELECT then UPDATE without lock, race condition possible

**Reproduction Scenario:**
1. Stale reclaim SELECT identifies node as stale
2. Worker completes node before reclaim UPDATE
3. Reclaim UPDATE marks node as 'retrying'
4. Node status flip-flop between 'success' and 'retrying'

**User-Visible Impact:**
- Node status inconsistency
- Potential duplicate execution
- Task completion delays
- Confusing state for users

**Recommended Remediation:**
- Add row-level locking in reclaim
- Use conditional UPDATE with status check
- Add optimistic concurrency control
- Implement node versioning

**Dependencies/Blockers:**
- Requires scheduler logic changes
- Requires testing for race conditions

**Schema Migration Required:** No

---

#### P1-002: Timeout Handling Without Idempotency

**Severity:** P1 (Major)  
**Evidence:** `executor/__init__.py:61-95`  
**File:** `apps/orchestrator/executor/__init__.py`  
**Function:** `A2AExecutor.execute()`  
**Code Behavior:** Timeout triggers retry without idempotency, Agent may still be processing

**Reproduction Scenario:**
1. Agent request times out (network delay)
2. Worker marks node for retry
3. Agent completes original request
4. Retry sends duplicate request
5. Agent processes both requests

**User-Visible Impact:**
- Duplicate Agent execution
- Duplicate external side effects
- Data inconsistency
- Unpredictable behavior

**Recommended Remediation:**
- Add idempotency keys (see P0-001)
- Implement longer timeouts with better detection
- Add Agent heartbeat mechanism
- Implement request cancellation

**Dependencies/Blockers:**
- Blocked by P0-001

**Schema Migration Required:** No

---

#### P1-003: No Maximum Concurrency Control at Node Level

**Severity:** P1 (Major)  
**Evidence:** `quota/__init__.py:438-471`  
**File:** `apps/orchestrator/quota/__init__.py`  
**Function:** `QuotaService.assert_can_create_task()`  
**Code Behavior:** Concurrency limit at task level only, no per-node or per-skill limits

**Reproduction Scenario:**
1. Task with 100 parallel nodes created
2. All nodes enqueued simultaneously
3. 100 concurrent Agent requests
4. Resource exhaustion
5. System degradation

**User-Visible Impact:**
- Resource exhaustion
- System instability
- Performance degradation
- Potential cascading failures

**Recommended Remediation:**
- Add per-node concurrency limits
- Add per-skill concurrency limits
- Implement resource-aware scheduling
- Add backpressure mechanisms

**Dependencies/Blockers:**
- Requires scheduler enhancements
- Requires resource tracking

**Schema Migration Required:** Yes (for resource tracking)

---

#### P1-004: Artifact Orphanage on Persistence Failure

**Severity:** P1 (Major)  
**Evidence:** `executor/engine.py:260-265`, `artifacts/__init__.py:157-199`  
**File:** `apps/orchestrator/executor/engine.py`, `apps/orchestrator/artifacts/__init__.py`  
**Function:** `ArtifactStore.persist_node_output()`  
**Code Behavior:** Artifacts uploaded to MinIO before PostgreSQL success marking

**Reproduction Scenario:**
1. Artifacts uploaded to MinIO successfully
2. PostgreSQL UPDATE fails
3. Artifacts orphaned in MinIO
4. Task not marked complete
5. Storage leak

**User-Visible Impact:**
- Storage cost increase
- Orphaned artifacts
- Inconsistent state
- Manual cleanup required

**Recommended Remediation:**
- Implement two-phase artifact upload
- Add artifact garbage collection
- Implement artifact deduplication
- Add artifact reference counting

**Dependencies/Blockers:**
- Requires artifact manager changes
- Requires garbage collection infrastructure

**Schema Migration Required:** Yes (for artifact tracking)

---

#### P1-005: No Automatic Dependent Node Cancellation

**Severity:** P1 (Major)  
**Evidence:** `scheduler/__init__.py:574-581`  
**File:** `apps/orchestrator/scheduler/__init__.py`  
**Function:** `Scheduler.mark_failure()`  
**Code Behavior:** Parent node failure does not cancel dependent nodes

**Reproduction Scenario:**
1. Parent node fails permanently
2. Task marked as 'failed'
3. Dependent nodes remain in 'pending'
4. Nodes never transition
5. Inconsistent state

**User-Visible Impact:**
- Confusing state representation
- Manual cleanup required
- Inconsistent status
- User confusion

**Recommended Remediation:**
- Auto-cancel dependent nodes on parent failure
- Add cascading cancellation logic
- Implement selective retry
- Add compensation transactions

**Dependencies/Blockers:**
- Requires scheduler logic changes
- Requires cascading failure handling

**Schema Migration Required:** No

---

#### P1-006: Missing Circuit Breaker Integration

**Severity:** P1 (Major)  
**Evidence:** `executor/engine.py:121-142`, `error_handling/__init__.py:168-242`  
**File:** `apps/orchestrator/executor/engine.py`  
**Function:** `ExecutionEngine._execute_with_retry()`  
**Code Behavior:** Circuit breaker implemented but not consistently used

**Reproduction Scenario:**
1. Agent repeatedly fails
2. Circuit breaker should open
3. Inconsistent error handling
4. May continue calling failing agent
5. Resource waste

**User-Visible Impact:**
- Continued calls to failing agents
- Resource waste
- Performance degradation
- Poor user experience

**Recommended Remediation:**
- Consistently apply circuit breaker
- Add circuit breaker monitoring
- Implement automatic recovery
- Add circuit breaker metrics

**Dependencies/Blockers:**
- Requires executor refactoring
- Requires monitoring integration

**Schema Migration Required:** No

---

#### P1-007: No Task-Level Idempotency

**Severity:** P1 (Major)  
**Evidence:** `application/task_manager.py:45-65`  
**File:** `apps/orchestrator/application/task_manager.py`  
**Function:** `TaskManager.create()`  
**Code Behavior:** No idempotency key, duplicate submissions create separate tasks

**Reproduction Scenario:**
1. User submits task
2. Network error, user retries
3. Two separate tasks created
4. Duplicate execution
5. Duplicate charges

**User-Visible Impact:**
- Duplicate task execution
- Duplicate resource usage
- Duplicate billing
- User confusion

**Recommended Remediation:**
- Add idempotency key to task creation
- Implement deduplication at API layer
- Add client-generated request IDs
- Implement request deduplication window

**Dependencies/Blockers:**
- Requires API changes
- Requires schema migration

**Schema Migration Required:** Yes (for idempotency tracking)

---

#### P1-008: Insufficient Monitoring for Distributed State

**Severity:** P1 (Major)  
**Evidence:** Multiple files, limited observability  
**File:** Various  
**Function:** Various  
**Code Behavior:** Limited metrics for distributed state consistency

**Reproduction Scenario:**
1. Distributed state inconsistency occurs
2. No alerting
3. No detection
4. Manual discovery only
5. Extended outage

**User-Visible Impact:**
- Undetected failures
- Extended outages
- Manual troubleshooting
- Poor SLA compliance

**Recommended Remediation:**
- Add distributed state metrics
- Implement consistency checks
- Add alerting for state anomalies
- Implement health checks for cross-system consistency

**Dependencies/Blockers:**
- Requires monitoring infrastructure
- Requires metric design

**Schema Migration Required:** No

---

### P2 - Recoverability and Observability Weaknesses

#### P2-001: No Orchestrator Restart Recovery Logic

**Severity:** P2 (Recoverability)  
**Evidence:** No recovery logic found  
**File:** N/A  
**Function:** N/A  
**Code Behavior:** No explicit recovery logic on orchestrator restart

**Reproduction Scenario:**
1. Orchestrator crashes
2. In-memory state lost
3. No recovery on restart
4. Potential state inconsistency

**User-Visible Impact:**
- Potential state inconsistency
- Manual recovery required
- Extended recovery time

**Recommended Remediation:**
- Implement startup reconciliation
- Add state consistency checks
- Implement recovery procedures
- Add startup health checks

**Dependencies/Blockers:**
- Requires recovery logic implementation

**Schema Migration Required:** No

---

#### P2-002: No Deadlock Detection

**Severity:** P2 (Recoverability)  
**Evidence:** `planner/dag.py:88-105`  
**File:** `apps/orchestrator/planner/dag.py`  
**Function:** `validate_plan()`  
**Code Behavior:** Deadlock detection only at plan time, not runtime

**Reproduction Scenario:**
1. DAG validated at plan time
2. Runtime state changes
3. Potential deadlock (unlikely but possible)
4. No detection

**User-Visible Impact:**
- Potential deadlock
- Manual intervention required
- Task stuck

**Recommended Remediation:**
- Add runtime deadlock detection
- Implement timeout-based deadlock prevention
- Add deadlock alerting
- Implement deadlock recovery

**Dependencies/Blockers:**
- Requires runtime monitoring

**Schema Migration Required:** No

---

#### P2-003: Limited Failure Classification

**Severity:** P2 (Observability)  
**Evidence:** `error_handling/__init__.py:288-321`  
**File:** `apps/orchestrator/error_handling/__init__.py`  
**Function:** `classify_error()`  
**Code Behavior:** Basic error classification, limited granularity

**Reproduction Scenario:**
1. Various failure types occur
2. Coarse classification
3. Limited debugging information
4. Imprecise retry decisions

**User-Visible Impact:**
- Imprecise retry behavior
- Limited debugging
- Poor failure diagnosis

**Recommended Remediation:**
- Enhance error classification
- Add failure taxonomy
- Implement precise retry policies
- Add failure analytics

**Dependencies/Blockers:**
- Requires error handling enhancement

**Schema Migration Required:** No

---

#### P2-004: No Request Tracing Across Systems

**Severity:** P2 (Observability)  
**Evidence:** Limited tracing implementation  
**File:** Various  
**Function:** Various  
**Code Behavior:** Basic tracing, no cross-system correlation

**Reproduction Scenario:**
1. Request spans multiple systems
2. No distributed tracing
3. Difficult debugging
4. Long troubleshooting time

**User-Visible Impact:**
- Difficult debugging
- Long MTTR
- Poor observability

**Recommended Remediation:**
- Implement distributed tracing
- Add request correlation IDs
- Implement span propagation
- Add tracing to all components

**Dependencies/Blockers:**
- Requires tracing infrastructure
- Requires cross-system coordination

**Schema Migration Required:** No

---

#### P2-005: No Automated State Reconciliation

**Severity:** P2 (Recoverability)  
**Evidence:** No reconciliation logic found  
**File:** N/A  
**Function:** N/A  
**Code Behavior:** No automated state consistency checks

**Reproduction Scenario:**
1. State inconsistency occurs
2. No detection
3. No automated correction
4. Manual intervention required

**User-Visible Impact:**
- Undetected inconsistencies
- Manual recovery
- Extended downtime

**Recommended Remediation:**
- Implement state reconciliation jobs
- Add consistency checks
- Implement automated correction
- Add reconciliation metrics

**Dependencies/Blockers:**
- Requires reconciliation infrastructure

**Schema Migration Required:** Possibly (for reconciliation tracking)

---

#### P2-006: Limited Resource Monitoring

**Severity:** P2 (Observability)  
**Evidence:** Basic metrics only  
**File:** `observability/__init__.py`  
**Function:** Various  
**Code Behavior:** Basic metrics, no resource exhaustion detection

**Reproduction Scenario:**
1. Resource exhaustion occurs
2. No alerting
3. No prevention
4. System degradation

**User-Visible Impact:**
- Resource exhaustion
- System degradation
- Poor performance

**Recommended Remediation:**
- Add resource monitoring
- Implement resource quotas
- Add exhaustion alerting
- Implement backpressure

**Dependencies/Blockers:**
- Requires monitoring infrastructure

**Schema Migration Required:** No

---

#### P2-007: No Automated Testing for Failure Scenarios

**Severity:** P2 (Maintainability)  
**Evidence:** Test coverage gaps  
**File:** Various test files  
**Function:** Various  
**Code Behavior:** Limited failure scenario testing

**Reproduction Scenario:**
1. Failure scenarios not tested
2. Issues discovered in production
3. Poor reliability
4. User impact

**User-Visible Impact:**
- Production failures
- Poor reliability
- User dissatisfaction

**Recommended Remediation:**
- Add chaos engineering tests
- Implement failure injection
- Add stress tests
- Implement automated failure testing

**Dependencies/Blockers:**
- Requires test infrastructure

**Schema Migration Required:** No

---

#### P2-008: No Backup/Restore Verification

**Severity:** P2 (Recoverability)  
**Evidence:** No backup verification found  
**File:** N/A  
**Function:** N/A  
**Code Behavior:** No automated backup verification

**Reproduction Scenario:**
1. Backup failure
2. No detection
3. Restore failure
4. Data loss

**User-Visible Impact:**
- Potential data loss
- Extended recovery time
- Poor RPO/RTO

**Recommended Remediation:**
- Implement backup verification
- Add restore testing
- Implement backup monitoring
- Add recovery procedures

**Dependencies/Blockers:**
- Requires backup infrastructure

**Schema Migration Required:** No

---

#### P2-009: Limited Performance Monitoring

**Severity:** P2 (Observability)  
**Evidence:** Basic metrics only  
**File:** `observability/__init__.py`  
**Function:** Various  
**Code Behavior:** Basic performance metrics, no SLO monitoring

**Reproduction Scenario:**
1. Performance degradation
2. No SLO alerting
3. Poor user experience
4. SLA violations

**User-Visible Impact:**
- Poor performance
- SLA violations
- User dissatisfaction

**Recommended Remediation:**
- Implement SLO monitoring
- Add performance alerting
- Implement performance dashboards
- Add SLO-based automation

**Dependencies/Blockers:**
- Requires monitoring infrastructure

**Schema Migration Required:** No

---

#### P2-010: No Capacity Planning Support

**Severity:** P2 (Observability)  
**Evidence:** No capacity planning metrics  
**File:** N/A  
**Function:** N/A  
**Code Behavior:** No capacity planning data

**Reproduction Scenario:**
1. Capacity exhaustion
2. No prediction
3. No scaling guidance
4. Outage

**User-Visible Impact:**
- Capacity exhaustion
- Outage
- Poor scalability

**Recommended Remediation:**
- Add capacity planning metrics
- Implement predictive scaling
- Add capacity alerting
- Implement auto-scaling

**Dependencies/Blockers:**
- Requires monitoring infrastructure

**Schema Migration Required:** No

---

#### P2-011: No Security Audit Logging

**Severity:** P2 (Observability)  
**Evidence:** Limited security logging  
**File:** `gateway/internal/auth/audit.go`  
**Function:** Various  
**Code Behavior:** Basic audit logging, limited security events

**Reproduction Scenario:**
1. Security incident
2. Limited audit trail
3. Poor investigation
4. Compliance issues

**User-Visible Impact:**
- Security risks
- Compliance issues
- Poor investigation

**Recommended Remediation:**
- Enhance security logging
- Add security event correlation
- Implement security monitoring
- Add compliance reporting

**Dependencies/Blockers:**
- Requires logging infrastructure

**Schema Migration Required:** No

---

#### P2-012: No Disaster Recovery Testing

**Severity:** P2 (Recoverability)  
**Evidence:** No DR testing found  
**File:** N/A  
**Function:** N/A  
**Code Behavior:** No disaster recovery procedures

**Reproduction Scenario:**
1. Disaster occurs
2. No tested procedures
3. Extended recovery
4. Data loss

**User-Visible Impact:**
- Extended downtime
- Potential data loss
- Poor RPO/RTO

**Recommended Remediation:**
- Implement DR procedures
- Add DR testing
- Implement failover automation
- Add DR monitoring

**Dependencies/Blockers:**
- Requires DR infrastructure

**Schema Migration Required:** No

---

### P3 - Optimization and Maintainability Issues

#### P3-001: Inefficient DAG Traversal

**Severity:** P3 (Optimization)  
**Evidence:** `planner/dag.py:108-116`  
**File:** `apps/orchestrator/planner/dag.py`  
**Function:** `ready_node_ids()`  
**Code Behavior:** Linear scan over all nodes for each readiness check

**Reproduction Scenario:**
1. Large DAG with thousands of nodes
2. Frequent readiness checks
3. Performance degradation
4. Slow execution

**User-Visible Impact:**
- Performance degradation
- Slow task execution
- Poor scalability

**Recommended Remediation:**
- Implement incremental readiness tracking
- Add DAG topology optimization
- Cache readiness computation
- Implement parallel traversal

**Dependencies/Blockers:**
- Requires planner optimization

**Schema Migration Required:** No

---

#### P3-002: No Request Batching

**Severity:** P3 (Optimization)  
**Evidence:** Individual Redis operations  
**File:** `streams/__init__.py`  
**Function:** Various  
**Code Behavior:** Individual Redis operations, no batching

**Reproduction Scenario:**
1. High volume of operations
2. Individual Redis calls
3. Network overhead
4. Performance degradation

**User-Visible Impact:**
- Performance degradation
- Redis bottleneck
- Poor scalability

**Recommended Remediation:**
- Implement Redis pipelining
- Add operation batching
- Optimize Redis usage
- Implement connection pooling

**Dependencies/Blockers:**
- Requires Redis client optimization

**Schema Migration Required:** No

---

#### P3-003: Limited Code Reusability

**Severity:** P3 (Maintainability)  
**Evidence:** Duplicated patterns in code  
**File:** Various  
**Function:** Various  
**Code Behavior:** Similar patterns repeated across components

**Reproduction Scenario:**
1. Bug found in one component
2. Same bug in other components
3. Multiple fixes required
4. Maintenance burden

**User-Visible Impact:**
- Maintenance burden
- Inconsistent fixes
- Technical debt

**Recommended Remediation:**
- Extract common patterns
- Implement shared utilities
- Add code reuse
- Reduce duplication

**Dependencies/Blockers:**
- Requires refactoring

**Schema Migration Required:** No

---

#### P3-004: Limited Error Context

**Severity:** P3 (Maintainability)  
**Evidence:** Basic error messages  
**File:** Various  
**Function:** Various  
**Code Behavior:** Limited error context in messages

**Reproduction Scenario:**
1. Error occurs
2. Limited context
3. Difficult debugging
4. Long MTTR

**User-Visible Impact:**
- Difficult debugging
- Long MTTR
- Poor developer experience

**Recommended Remediation:**
- Enhance error context
- Add structured error data
- Implement error correlation
- Add debugging information

**Dependencies/Blockers:**
- Requires error handling enhancement

**Schema Migration Required:** No

---

#### P3-005: No Configuration Validation

**Severity:** P3 (Maintainability)  
**Evidence:** Environment variable usage  
**File:** Various  
**Function:** Various  
**Code Behavior:** Limited configuration validation

**Reproduction Scenario:**
1. Invalid configuration
2. Runtime failure
3. Difficult diagnosis
4. Configuration errors

**User-Visible Impact:**
- Configuration errors
- Runtime failures
- Poor deployment experience

**Recommended Remediation:**
- Add configuration validation
- Implement configuration schema
- Add configuration testing
- Implement configuration documentation

**Dependencies/Blockers:**
- Requires configuration management

**Schema Migration Required:** No

---

#### P3-006: Limited Documentation

**Severity:** P3 (Maintainability)  
**Evidence:** Limited code documentation  
**File:** Various  
**Function:** Various  
**Code Behavior:** Limited inline documentation

**Reproduction Scenario:**
1. New developer joins
2. Limited documentation
3. Slow onboarding
4. Misunderstanding

**User-Visible Impact:**
- Slow onboarding
- Misunderstanding
- Maintenance burden

**Recommended Remediation:**
- Add inline documentation
- Implement architecture docs
- Add runbooks
- Implement training materials

**Dependencies/Blockers:**
- Requires documentation effort

**Schema Migration Required:** No

---

#### P3-007: No Health Check Depth

**Severity:** P3 (Maintainability)  
**Evidence:** Basic health check  
**File:** `apps/orchestrator/main.py:88-90`  
**Function:** `health()`  
**Code Behavior:** Basic health check, no dependency checks

**Reproduction Scenario:**
1. Dependency unhealthy
2. Health check passes
3. Traffic routed to unhealthy instance
4. Errors

**User-Visible Impact:**
- Unhealthy instances in rotation
- Errors
- Poor user experience

**Recommended Remediation:**
- Implement deep health checks
- Add dependency health checks
- Implement health check metrics
- Add health-based routing

**Dependencies/Blockers:**
- Requires health check enhancement

**Schema Migration Required:** No

---

## 9. Phase 36 Implementation Roadmap

### 9.1 Recommended First Implementation Task

**P36.1: Idempotency Keys and Exactly-Once Execution**

**Problem Being Solved:**
P0-001, P0-002 - Critical lack of exactly-once execution guarantees causing duplicate Agent execution and data inconsistency.

**Scope:**
- Add idempotency key to A2A protocol
- Implement request ID tracking in orchestrator
- Add deduplication logic in executor
- Implement Agent-side idempotency

**Files/Modules Likely Affected:**
- `packages/a2a-sdk/` - A2A protocol client
- `apps/orchestrator/executor/__init__.py` - Execution engine
- `apps/orchestrator/scheduler/__init__.py` - Scheduler (for request tracking)
- `infrastructure/postgres/init/` - Schema for request tracking
- `agents/*/` - Agent implementations for idempotency

**Prerequisites:**
- A2A protocol design approval
- Schema migration planning
- Agent SDK updates

**Tests Required:**
- Idempotency key generation and tracking
- Duplicate request detection
- Agent-side idempotency
- End-to-end exactly-once execution
- Crash recovery with idempotency

**Acceptance Criteria:**
- Every A2A request includes unique idempotency key
- Orchestrator tracks request IDs in PostgreSQL
- Duplicate requests detected and skipped
- Agents implement idempotency logic
- Worker crash after Agent success does not cause duplicate execution
- Tests verify exactly-once behavior

**Risks to Existing Functionality:**
- Breaking change to A2A protocol
- Requires Agent updates
- Schema migration required
- Potential performance impact from deduplication checks

**Estimated Effort:** 3-4 weeks

---

### 9.2 Subsequent Implementation Phases

#### P36.2: Distributed Transaction Coordination

**Problem Being Solved:**
P0-003 - No atomic coordination between PostgreSQL and Redis operations.

**Scope:**
- Implement transactional outbox pattern
- Add compensating transaction logic
- Implement state reconciliation
- Add saga pattern for multi-step operations

**Files/Modules Likely Affected:**
- `apps/orchestrator/scheduler/__init__.py` - Scheduler
- `apps/orchestrator/streams/__init__.py` - Stream client
- `infrastructure/postgres/init/` - Outbox table schema
- New reconciliation module

**Prerequisites:**
- P36.1 completion
- Schema migration planning

**Tests Required:**
- Outbox pattern implementation
- Compensating transaction logic
- State reconciliation
- Cross-system failure scenarios

**Acceptance Criteria:**
- PostgreSQL and Redis operations coordinated via outbox
- Failed operations compensated automatically
- State reconciliation detects and fixes inconsistencies
- Tests verify distributed transaction correctness

**Risks to Existing Functionality:**
- Significant architectural changes
- Performance impact from outbox pattern
- Complex reconciliation logic

**Estimated Effort:** 4-5 weeks

---

#### P36.3: Enhanced Failure Handling and Recovery

**Problem Being Solved:**
P1-001, P1-002, P1-006 - Stale reclaim race conditions, timeout handling, circuit breaker integration.

**Scope:**
- Fix stale reclaim race conditions
- Improve timeout handling with idempotency
- Consistently apply circuit breakers
- Add comprehensive failure classification

**Files/Modules Likely Affected:**
- `apps/orchestrator/scheduler/__init__.py` - Stale reclaim
- `apps/orchestrator/executor/__init__.py` - Timeout handling
- `apps/orchestrator/error_handling/__init__.py` - Error classification
- `apps/orchestrator/router/__init__.py` - Circuit breaker integration

**Prerequisites:**
- P36.1 completion (for idempotency)

**Tests Required:**
- Stale reclaim race condition tests
- Timeout handling with idempotency
- Circuit breaker integration tests
- Failure classification accuracy

**Acceptance Criteria:**
- Stale reclaim uses row-level locking
- Timeout handling leverages idempotency
- Circuit breakers consistently applied
- Failures accurately classified

**Risks to Existing Functionality:**
- Scheduler logic changes
- Potential performance impact from locking

**Estimated Effort:** 2-3 weeks

---

#### P36.4: Artifact Consistency and Cleanup

**Problem Being Solved:**
P1-004 - Artifact orphanage on persistence failure.

**Scope:**
- Implement two-phase artifact upload
- Add artifact garbage collection
- Implement artifact deduplication
- Add artifact reference counting

**Files/Modules Likely Affected:**
- `apps/orchestrator/artifacts/__init__.py` - Artifact store
- `apps/orchestrator/executor/engine.py` - Artifact persistence
- `infrastructure/postgres/init/` - Artifact tracking schema
- New garbage collection module

**Prerequisites:**
- Schema migration planning

**Tests Required:**
- Two-phase artifact upload
- Garbage collection logic
- Artifact deduplication
- Failure scenario tests

**Acceptance Criteria:**
- Artifacts uploaded in two-phase pattern
- Orphaned artifacts automatically cleaned
- Duplicate uploads detected and skipped
- Reference counting prevents premature deletion

**Risks to Existing Functionality:**
- Artifact manager changes
- Storage behavior changes
- Performance impact from garbage collection

**Estimated Effort:** 2-3 weeks

---

#### P36.5: Enhanced Concurrency Control

**Problem Being Solved:**
P1-003 - No maximum concurrency control at node level.

**Scope:**
- Add per-node concurrency limits
- Add per-skill concurrency limits
- Implement resource-aware scheduling
- Add backpressure mechanisms

**Files/Modules Likely Affected:**
- `apps/orchestrator/scheduler/__init__.py` - Scheduler
- `apps/orchestrator/executor/engine.py` - Execution engine
- `apps/orchestrator/quota/__init__.py` - Quota service
- `infrastructure/postgres/init/` - Resource tracking schema

**Prerequisites:**
- Schema migration planning

**Tests Required:**
- Per-node concurrency limits
- Per-skill concurrency limits
- Resource-aware scheduling
- Backpressure mechanisms

**Acceptance Criteria:**
- Per-node concurrency enforced
- Per-skill concurrency enforced
- Resource-aware scheduling implemented
- Backpressure prevents overload

**Risks to Existing Functionality:**
- Scheduler logic changes
- Potential performance impact
- Configuration complexity

**Estimated Effort:** 3-4 weeks

---

#### P36.6: Enhanced Observability and Monitoring

**Problem Being Solved:**
P1-008, P2-003, P2-004, P2-006, P2-009 - Insufficient monitoring and observability.

**Scope:**
- Add distributed state metrics
- Implement enhanced error classification
- Add distributed tracing
- Implement resource monitoring
- Add SLO monitoring

**Files/Modules Likely Affected:**
- `apps/orchestrator/observability/__init__.py` - Observability
- `apps/orchestrator/error_handling/__init__.py` - Error handling
- New tracing module
- New monitoring module

**Prerequisites:**
- Monitoring infrastructure setup
- Tracing infrastructure setup

**Tests Required:**
- Metrics collection accuracy
- Error classification accuracy
- Tracing end-to-end
- Monitoring integration

**Acceptance Criteria:**
- Distributed state metrics collected
- Errors accurately classified
- Distributed tracing implemented
- Resource monitoring operational
- SLO monitoring configured

**Risks to Existing Functionality:**
- Performance impact from instrumentation
- Complexity increase

**Estimated Effort:** 3-4 weeks

---

#### P36.7: Comprehensive Testing Infrastructure

**Problem Being Solved:**
P2-007, P1-008 - No automated testing for failure scenarios.

**Scope:**
- Add chaos engineering tests
- Implement failure injection
- Add stress tests
- Implement end-to-end tests

**Files/Modules Likely Affected:**
- New test infrastructure
- `apps/orchestrator/tests/` - Existing tests
- New chaos engineering module

**Prerequisites:**
- Test infrastructure setup
- Failure injection tools

**Tests Required:**
- Chaos engineering scenarios
- Failure injection tests
- Stress tests
- End-to-end execution tests

**Acceptance Criteria:**
- Chaos engineering tests automated
- Failure injection implemented
- Stress tests validate limits
- End-to-end tests cover critical paths

**Risks to Existing Functionality:**
- Test infrastructure complexity
- Maintenance burden

**Estimated Effort:** 4-5 weeks

---

#### P36.8: Enhanced Recovery and Disaster Preparedness

**Problem Being Solved:**
P2-001, P2-005, P2-008, P2-012 - Limited recovery and disaster preparedness.

**Scope:**
- Implement startup reconciliation
- Add state consistency checks
- Implement backup verification
- Add disaster recovery procedures

**Files/Modules Likely Affected:**
- New recovery module
- `apps/orchestrator/main.py` - Startup logic
- New backup verification module

**Prerequisites:**
- Backup infrastructure setup
- DR procedures documentation

**Tests Required:**
- Startup reconciliation tests
- State consistency checks
- Backup verification tests
- DR procedure tests

**Acceptance Criteria:**
- Startup reconciliation operational
- State consistency checks automated
- Backup verification automated
- DR procedures tested

**Risks to Existing Functionality:**
- Startup time increase
- Complexity increase

**Estimated Effort:** 3-4 weeks

---

### 9.3 Roadmap Dependencies

```
P36.1 (Idempotency) ───────────────────────────────────┐
                                                        │
P36.2 (Distributed Transactions) ───────────────────────┤
                                                        │
P36.3 (Failure Handling) ────────────────────────────────┤
                                                        │
P36.4 (Artifact Consistency) ───────────────────────────┤
                                                        │
P36.5 (Concurrency Control) ────────────────────────────┤
                                                        │
P36.6 (Observability) ─────────────────────────────────┤
                                                        │
P36.7 (Testing Infrastructure) ────────────────────────┤
                                                        │
P36.8 (Recovery and DR) ───────────────────────────────┘
```

**Critical Path:** P36.1 → P36.2 → P36.3 → P36.4 → P36.5  
**Parallel Tracks:** P36.6, P36.7, P36.8 (can run in parallel after P36.1)

---

## 10. Deliverables

### 10.1 Files Created

1. `docs/phase36/p36-0-reliability-audit.md` - This comprehensive audit document
2. `docs/phase36/p36-roadmap.md` - Implementation roadmap (next section)

### 10.2 Audit Components Included

- ✅ Repository reconnaissance and structure analysis
- ✅ Complete execution lifecycle reconstruction
- ✅ Task and node state machine audit with transition tables
- ✅ Failure and recovery scenario analysis (13 scenarios)
- ✅ Idempotency and duplicate execution audit
- ✅ DAG and parallel execution audit
- ✅ Existing tests and coverage assessment
- ✅ Prioritized findings (30 findings, P0-P3)
- ✅ Phase 36 implementation roadmap
- ✅ Execution lifecycle diagram
- ✅ State transition tables
- ✅ Failure matrix
- ✅ Test coverage matrix

### 10.3 Confirmation of Audit-Only Approach

**Application Code Modifications:** None  
**Schema Modifications:** None  
**Configuration Changes:** None  
**Dependency Changes:** None  
**Test Modifications:** None  
**Git Operations:** None  

This audit was conducted as a read-only analysis of the existing codebase. No application code, schemas, configurations, dependencies, or tests were modified during this audit.

---

## 11. Final Report

### 11.1 Actual End-to-End Execution Path

**Summary:**
The AOP platform implements a functional distributed task execution system with the following execution path:

1. **API Entry:** Gateway (Go) proxies authenticated requests to Orchestrator (Python)
2. **Task Creation:** TaskManager validates quotas, plans DAG via Planner, persists to PostgreSQL
3. **Scheduling:** Scheduler creates task nodes, identifies ready nodes, enqueues to Redis
4. **Execution:** Workers consume from Redis, route to Agents via Router, execute via A2A
5. **Persistence:** Results persisted to PostgreSQL, artifacts to MinIO
6. **Completion:** Aggregator builds final result, Evaluation scores task
7. **Events:** Redis Pub/Sub and PostgreSQL events provide real-time updates

**Key Characteristics:**
- PostgreSQL is authoritative state store
- Redis provides at-least-once queue delivery
- MinIO stores artifacts
- Workers are independent processes
- No distributed transaction coordination
- No exactly-once execution guarantees

### 11.2 Top 5 Reliability Risks

1. **P0-001: No Exactly-Once Execution Guarantees** - Critical lack of idempotency in A2A execution
2. **P0-002: Worker Crash Between Agent Success and Persistence** - Data inconsistency risk
3. **P0-003: No Distributed Transaction Coordination** - Split-brain scenarios possible
4. **P1-001: Stale Node Reclaim Race Conditions** - Duplicate execution risk
5. **P1-002: Timeout Handling Without Idempotency** - Duplicate Agent execution

### 11.3 Confirmed vs Unverified Capabilities

**Confirmed Capabilities:**
- ✅ Task creation and DAG planning
- ✅ Parallel node execution via Redis consumer groups
- ✅ Agent routing with scoring
- ✅ Retry with attempt tracking and agent exclusion
- ✅ HITL (human-in-the-loop) approval workflow
- ✅ Artifact storage and metadata
- ✅ Task aggregation and evaluation
- ✅ Stale node reclaim (if enabled)
- ✅ Basic circuit breaker implementation
- ✅ Quota enforcement at task level
- ✅ Billing estimation and invoice generation

**Unverified Capabilities:**
- ❌ Exactly-once execution (not implemented)
- ❌ Distributed transaction coordination (not implemented)
- ❌ Automatic dependent node cancellation (not implemented)
- ❌ Per-node concurrency limits (not implemented)
- ❌ Artifact garbage collection (not implemented)
- ❌ Startup reconciliation (not implemented)
- ❌ State consistency checks (not implemented)
- ❌ Disaster recovery procedures (not documented)
- ❌ End-to-end failure scenario testing (not implemented)

### 11.4 Critical Missing Tests

**High Priority:**
1. End-to-end execution with real Agents
2. Worker crash recovery scenarios
3. PostgreSQL failure scenarios
4. Redis failure scenarios
5. Timeout handling with idempotency
6. Duplicate message delivery
7. Artifact upload failure
8. Cancellation during execution
9. Network partition scenarios
10. Resource exhaustion scenarios

**Medium Priority:**
1. Distributed state consistency
2. Concurrent execution stress tests
3. Long-running execution stability
4. Performance under load
5. Cross-system failure modes

### 11.5 Recommended P36.1

**P36.1: Idempotency Keys and Exactly-Once Execution**

**Justification:**
This is the highest priority because it addresses P0-001 and P0-002, the two most critical reliability risks. Without exactly-once execution guarantees, the system cannot reliably handle worker crashes, timeouts, or network failures without risking duplicate execution and data inconsistency.

**Expected Impact:**
- Eliminates duplicate Agent execution
- Prevents data inconsistency from worker crashes
- Enables reliable retry mechanisms
- Foundation for other reliability improvements

**Dependencies:**
- A2A protocol changes
- Agent SDK updates
- Schema migration for request tracking

**Estimated Timeline:** 3-4 weeks

### 11.6 Files Created

1. `docs/phase36/p36-0-reliability-audit.md` - Comprehensive reliability audit (this file)
2. `docs/phase36/p36-roadmap.md` - Implementation roadmap (to be created)

### 11.7 Application Code Modification Confirmation

**Confirmation:** No application code was modified during this audit.

**Changes Made:**
- None

**Audit Approach:**
- Read-only analysis of existing codebase
- No code modifications
- No schema changes
- No configuration changes
- No test modifications
- No git operations

---

## Appendix A: Component File Mapping

### A.1 Gateway Components

| Component | File | Purpose |
|-----------|------|---------|
| Main | `apps/gateway/cmd/main.go` | Entry point |
| Proxy | `apps/gateway/internal/httpapi/proxy.go` | Load balancer |
| Auth | `apps/gateway/internal/auth/` | Authentication |
| RBAC | `apps/gateway/internal/auth/rbac.go` | Authorization |
| API Keys | `apps/gateway/internal/auth/apikey.go` | API key management |

### A.2 Orchestrator Components

| Component | File | Purpose |
|-----------|------|---------|
| Main | `apps/orchestrator/main.py` | FastAPI server |
| Task Service | `apps/orchestrator/application/task_service.py` | Application facade |
| Task Manager | `apps/orchestrator/application/task_manager.py` | Task use cases |
| Planner | `apps/orchestrator/planner/__init__.py` | DAG generation |
| Router | `apps/orchestrator/router/__init__.py` | Agent selection |
| Scheduler | `apps/orchestrator/scheduler/__init__.py` | Task persistence |
| Executor | `apps/orchestrator/executor/__init__.py` | A2A execution |
| Worker | `apps/orchestrator/worker.py` | Worker entry point |
| Aggregator | `apps/orchestrator/aggregator/__init__.py` | Result aggregation |
| Evaluation | `apps/orchestrator/evaluation/__init__.py` | Task scoring |
| Artifacts | `apps/orchestrator/artifacts/__init__.py` | Artifact storage |
| Streams | `apps/orchestrator/streams/__init__.py` | Redis client |
| Quota | `apps/orchestrator/quota/__init__.py` | Quota enforcement |
| Billing | `apps/orchestrator/billing/__init__.py` | Usage estimation |
| Error Handling | `apps/orchestrator/error_handling/__init__.py` | Error classification |

### A.3 Schema Files

| Schema | File | Purpose |
|--------|------|---------|
| Base Schema | `infrastructure/postgres/init/001_init.sql` | Core tables |
| Evaluation | `infrastructure/postgres/init/002_evaluation.sql` | Evaluation tables |
| Memory | `infrastructure/postgres/init/003_memory.sql` | Memory tables |
| Tenant Memory | `infrastructure/postgres/init/004_tenant_memory.sql` | Tenant memory |
| Audit Index | `infrastructure/postgres/init/005_audit_index.sql` | Audit indexes |
| User Auth | `infrastructure/postgres/init/006_user_auth.sql` | User tables |
| Quotas | `infrastructure/postgres/init/007_tenant_quotas.sql` | Quota tables |
| Billing Invoice | `infrastructure/postgres/init/008_billing_invoices.sql` | Invoice tables |
| Stripe Checkout | `infrastructure/postgres/init/009_billing_checkout.sql` | Checkout tables |
| Stripe Webhook | `infrastructure/postgres/init/010_billing_webhooks.sql` | Webhook tables |
| Quota Grants | `infrastructure/postgres/init/011_quota_grants.sql` | Grant tables |
| Egress | `infrastructure/postgres/init/012_tenant_egress.sql` | Egress tables |

---

## Appendix B: Glossary

- **A2A:** Agent-to-Agent protocol for agent communication
- **DAG:** Directed Acyclic Graph - task dependency structure
- **HITL:** Human-in-the-loop - requires human approval
- **MinIO:** S3-compatible object storage
- **PostgreSQL:** Relational database for authoritative state
- **Redis:** In-memory data store for queues and caching
- **SSE:** Server-Sent Events for real-time updates
- **WebSocket:** Bidirectional communication protocol
- **Worker:** Process that consumes execution queue and calls Agents

---

## Appendix C: References

### C.1 Documentation

- `docs/A2A-Agent-调度平台-v1.0-技术方案.md` - Technical architecture
- `docs/architecture.md` - Architecture overview
- `docs/database.md` - Database schema documentation
- `docs/redis.md` - Redis design documentation
- `docs/api.md` - API documentation
- `docs/agent.md` - Agent development guidelines
- `docs/agent-sandbox.md` - Sandbox security documentation
- `docs/billing.md` - Billing documentation
- `docs/quotas.md` - Quota documentation
- `docs/egress.md` - Egress policy documentation

### C.2 Code References

- `apps/gateway/` - Gateway implementation
- `apps/orchestrator/` - Orchestrator implementation
- `packages/a2a-sdk/` - A2A protocol SDK
- `agents/` - Agent implementations
- `infrastructure/postgres/` - Database schema and migrations

### C.3 Test References

- `apps/orchestrator/tests/` - Orchestrator test suite
- `apps/gateway/internal/*_test.go` - Gateway test suite

---

**Audit End**

This audit provides a comprehensive assessment of the AOP platform's reliability characteristics. The findings and roadmap are based on actual code inspection and do not assume capabilities based solely on documentation.
