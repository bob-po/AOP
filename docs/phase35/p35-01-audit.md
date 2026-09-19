# Phase 35.1: Orchestrator Code Audit Report

**Date**: 2026-09-18  
**Objective**: Complete code audit of Orchestrator to identify refactoring opportunities  
**Scope**: `apps/orchestrator/` directory

---

## 1. Current Orchestrator Directory Structure

```
apps/orchestrator/
├── application/
│   ├── __init__.py
│   ├── task_manager.py       # Task lifecycle orchestration
│   └── task_service.py       # HTTP/API facade
├── planner/
│   ├── __init__.py           # Planner class (domain logic)
│   ├── engine.py             # PlanningEngine (thin wrapper)
│   ├── dag.py                # TaskPlan, PlanNode, validation
│   ├── decompose.py          # Step decomposition logic
│   └── json_plan.py          # LLM plan parsing
├── router/
│   ├── __init__.py           # AgentRouter class (domain logic)
│   └── engine.py             # RoutingEngine (thin wrapper)
├── scheduler/
│   ├── __init__.py           # Scheduler class (domain logic)
│   └── engine.py             # SchedulingEngine (thin wrapper)
├── executor/
│   ├── __init__.py           # A2AExecutor
│   └── engine.py             # ExecutionEngine (worker logic)
├── aggregator/
│   └── __init__.py           # Aggregator (result aggregation)
├── artifacts/
│   ├── __init__.py           # ArtifactStore (MinIO)
│   └── manager.py            # ArtifactManager (unified listing)
├── memory/
│   ├── __init__.py           # MemoryService (task + tenant memory)
│   └── tfidf.py              # TF-IDF ranking
├── evaluation/
│   └── __init__.py           # EvaluationService (heuristic scoring)
├── workflows/
│   └── __init__.py           # WorkflowService (template management)
├── billing/
│   ├── __init__.py           # BillingService
│   ├── invoice.py            # InvoiceService
│   ├── stripe_checkout.py    # Stripe integration
│   └── webhook.py            # Stripe webhooks
├── quota/
│   └── __init__.py           # QuotaService
├── egress/
│   └── __init__.py           # EgressService
├── streams/
│   └── __init__.py           # StreamClient (Redis Streams + Pub/Sub)
├── observability/
│   └── __init__.py           # MetricsService
├── marketplace/
│   └── __init__.py           # MarketplaceService
├── sandbox/
│   ├── __init__.py
│   └── profiles.py           # Seccomp profiles
├── error_handling/
│   └── __init__.py           # Circuit breakers, retry policies
├── tracing/
│   └── __init__.py           # OpenTelemetry tracing
├── websocket/
│   └── __init__.py           # WebSocket connection manager
├── health_monitor.py
├── service.py                # Legacy import shim (→ application.task_service)
├── main.py                   # FastAPI HTTP API
├── worker.py                 # Execution worker entry point
└── tests/                    # Test suite
```

---

## 2. TaskService Responsibilities

**File**: `apps/orchestrator/application/task_service.py`

### Current State
`TaskService` is already designed as a **facade** that delegates to specialized services:

### Core Responsibilities
1. **Lifecycle Operations** (delegated to `TaskManager`):
   - `create()` - Create task from natural language
   - `run_workflow()` - Execute workflow template
   - `get()`, `list()`, `cancel()` - Task CRUD
   - `approve()`, `reject()` - HITL decisions
   - `overview()`, `events()` - Task metadata
   - `list_artifacts()`, `list_all_artifacts()` - Artifact access

2. **Router Operations** (delegated to `RoutingEngine`):
   - `router_preview()` - Preview agent selection
   - `agent_performance()` - Agent performance metrics

3. **Evaluation Operations** (delegated to `EvaluationService`):
   - `evaluate()`, `get_evaluation()`, `list_evaluations()`, `evaluation_overview()`

4. **Memory Operations** (delegated to `MemoryService`):
   - Task memory: `list_memory()`, `put_memory()`, `delete_memory()`
   - Tenant memory: `list_tenant_memory()`, `put_tenant_memory()`, `search_tenant_memory()`, `delete_tenant_memory()`
   - Promotion: `promote_task_memory()`

5. **Metrics/Billing/Quota/Egress** (delegated to respective services):
   - Metrics: `metrics_snapshot()`, `metrics_prometheus()`
   - Billing: `billing_usage()`, `billing_summary()`, invoice operations
   - Quota: `quota_status()`, `get_quota()`, `update_quota()`, `list_quota_grants()`
   - Egress: `egress_policy()`, `update_egress()`, `check_egress()`

### Dependencies
```python
from artifacts import ArtifactStore
from artifacts.manager import ArtifactManager
from billing import BillingService
from billing.invoice import InvoiceService
from evaluation import EvaluationService
from egress import EgressService
from memory import MemoryService
from observability import MetricsService
from planner.engine import PlanningEngine
from quota import QuotaService
from router.engine import RoutingEngine
from scheduler.engine import SchedulingEngine
from streams import StreamClient
from workflows import WorkflowService
from aggregator import Aggregator
from .task_manager import TaskManager
```

### Initialization Pattern
```python
def __init__(self) -> None:
    # Domain engines
    self.planner_engine = PlanningEngine()
    self.router_engine = RoutingEngine()
    self.scheduling = SchedulingEngine(...)
    
    # Data services
    self.artifact_store = ArtifactStore()
    self.artifacts = self.artifact_store
    self.workflows = WorkflowService()
    self.evaluations = EvaluationService()
    self.aggregator = Aggregator()
    self.memory = MemoryService()
    self.metrics = MetricsService()
    
    # Business services
    self.billing = BillingService()
    self.invoices = InvoiceService(billing=self.billing)
    self.quotas = QuotaService(billing=self.billing)
    self.egress = EgressService()
    
    # Application orchestrator
    self.tasks = TaskManager(
        planning=self.planner_engine,
        scheduling=self.scheduling,
        workflows=self.workflows,
        quotas=self.quotas,
        memory=self.memory,
        artifacts=self.artifact_manager,
    )
```

---

## 3. TaskManager Responsibilities

**File**: `apps/orchestrator/application/task_manager.py`

### Core Responsibilities
1. **Task Creation Flow**:
   - Quota validation (`quotas.assert_can_create_task()`)
   - Planning (`planning.plan()`)
   - Scheduling (`scheduling.create_and_enqueue()`)
   - Memory integration (`_remember_goal()`)

2. **Workflow Execution**:
   - Workflow lookup and validation
   - Plan building from workflow template
   - Skill availability validation
   - Scheduling with workflow metadata

3. **Task Query Operations**:
   - Get/List tasks (delegated to scheduler)
   - Cancel task (delegated to scheduler)
   - HITL approve/reject (delegated to scheduler)
   - Overview statistics (delegated to scheduler)
   - Event listing (delegated to scheduler)

4. **Artifact Operations**:
   - List task artifacts (delegated to ArtifactManager)
   - List all artifacts (delegated to ArtifactManager)

5. **Memory Integration**:
   - Remember goal on task creation
   - Recall tenant memory into task context
   - Compose memory context for executor

### Dependencies
```python
from artifacts.manager import ArtifactManager
from memory import MemoryService
from planner.dag import TaskPlan, validate_plan
from planner.engine import PlanningEngine
from quota import QuotaService
from scheduler.engine import SchedulingEngine
from workflows import WorkflowService
```

---

## 4. Entry Points Calling TaskService

### Primary Entry Points

1. **HTTP API** (`main.py`):
   - FastAPI endpoints instantiate `tasks = TaskService()`
   - All `/v1/tasks/*` endpoints delegate to TaskService methods
   - `/v1/memory/*`, `/v1/evaluations/*`, `/v1/billing/*` etc. all use TaskService

2. **Legacy Import** (`service.py`):
   - Compatibility shim: `from service import TaskService` → `application.task_service`
   - Used by `main.py` and scripts

3. **Scripts** (`scripts/`):
   - Various phase scripts import from `service` or directly use engines
   - Example: `phase3_create_task.py`, `phase4_execute_dag.py`

### API Routes Summary
```
POST   /v1/tasks                    → tasks.create()
GET    /v1/tasks                    → tasks.list()
GET    /v1/tasks/{id}               → tasks.get()
POST   /v1/tasks/{id}/cancel        → tasks.cancel()
POST   /v1/tasks/{id}/approve       → tasks.approve()
POST   /v1/tasks/{id}/reject        → tasks.reject()
GET    /v1/tasks/{id}/events        → tasks.events()
GET    /v1/tasks/{id}/artifacts     → tasks.list_artifacts()
GET    /v1/tasks/{id}/memory        → tasks.list_memory()
PUT    /v1/tasks/{id}/memory        → tasks.put_memory()
POST   /v1/tasks/{id}/evaluate      → tasks.evaluate()
POST   /v1/workflows/{id}/run       → tasks.run_workflow()
```

---

## 5. Planner/Router/Scheduler/Executor Call Relationships

### Call Flow: Task Creation
```
HTTP POST /v1/tasks
  ↓
TaskService.create()
  ↓
TaskManager.create()
  ↓
1. QuotaService.assert_can_create_task()
2. PlanningEngine.plan() → Planner.plan()
3. SchedulingEngine.create_and_enqueue() → Scheduler.create_task()
4. StreamClient.enqueue_execution() (for ready nodes)
5. MemoryService.remember_goal()
```

### Call Flow: Execution
```
Redis Stream consumer (worker.py)
  ↓
ExecutionEngine.run_forever()
  ↓
ExecutionEngine.handle()
  ↓
1. RoutingEngine.select() → AgentRouter.select()
2. A2AExecutor.execute() (HTTP call to agent)
3. ArtifactStore.persist_node_output()
4. Scheduler.mark_success() / mark_failure()
5. StreamClient.enqueue_execution() (downstream nodes)
6. Aggregator.build_result() (on task completion)
7. EvaluationService.evaluate() (auto-evaluation)
8. MemoryService operations
```

### Component Dependencies
```
TaskService
 ├─→ TaskManager
 │    ├─→ PlanningEngine → Planner
 │    ├─→ SchedulingEngine → Scheduler
 │    ├─→ WorkflowService
 │    ├─→ QuotaService
 │    ├─→ MemoryService
 │    └─→ ArtifactManager → ArtifactStore
 ├─→ RoutingEngine → AgentRouter
 ├─→ EvaluationService
 ├─→ Aggregator
 ├─→ BillingService → InvoiceService
 └─→ EgressService

ExecutionEngine (independent worker)
 ├─→ RoutingEngine → AgentRouter
 ├─→ A2AExecutor
 ├─→ Scheduler
 ├─→ ArtifactStore
 ├─→ Aggregator
 ├─→ EvaluationService
 └─→ MemoryService
```

---

## 6. Task/Node/Run/Event Data Flow

### Task Creation Flow
```
1. User POST /v1/tasks with content
2. TaskManager.create():
   - Validate quota
   - Call Planner.plan(goal) → TaskPlan
   - Call Scheduler.create_task(plan) → ScheduleResult
   - Extract ready_nodes from plan
   - For each ready node:
     - StreamClient.enqueue_execution(node)
     - StreamClient.publish_task_event("task.node.enqueued")
   - MemoryService.remember_goal()
   - MemoryService.recall_into_task()
3. Return task_id, plan, ready_nodes
```

### Node Execution Flow
```
1. Worker reads from Redis Stream: StreamClient.read_execution()
2. ExecutionEngine.handle(fields):
   - RoutingEngine.select(skill) → RoutedAgent
   - Scheduler.claim_running(node_key, agent_id)
   - A2AExecutor.execute(endpoint, query)
   - ArtifactStore.persist_node_output()
   - Scheduler.mark_success(node_key, output)
     - Updates task_nodes.status = 'success'
     - Unlocks dependent nodes
     - Returns ready_jobs
   - For each ready_job:
     - StreamClient.enqueue_execution(job)
   - MemoryService.remember_node()
   - If task completed:
     - Aggregator.build_result()
     - StreamClient.publish_task_event("task.completed")
     - EvaluationService.evaluate()
     - MemoryService.promote_task()
```

### HITL Flow
```
1. Node requires approval (HITL skill)
2. Scheduler.mark_success() sets status = 'waiting_for_user'
3. Task status = 'waiting_for_user'
4. User POST /v1/tasks/{id}/approve or /reject
5. TaskManager.approve()/reject():
   - Scheduler.approve_node() / reject_node()
   - Unlock dependents (if approved)
   - Enqueue downstream nodes
```

### Event Flow
```
All state changes → Scheduler writes to task_events table
  ↓
Task events → StreamClient.publish_task_event()
  ↓
Redis Stream TASK_EVENTS
  ↓
Pub/Sub fanout → WebSocket clients
```

---

## 7. Redis Streams Data Flow

### Streams Used
1. **EXECUTION_STREAM** (`a2a.execution.queue`):
   - Consumer group: `cg-executor`
   - Purpose: Job queue for worker processes
   - Fields: task_id, node_id, node_key, skill, attempt, exclude_agent_ids

2. **EXECUTION_EVENTS** (`a2a.execution.events`):
   - Consumer group: `cg-aggregator`
   - Purpose: Agent execution events (optional, not actively used)
   - Fields: event_type, task_id, node_key, agent_id, latency_ms

3. **TASK_EVENTS** (`a2a.task.events`):
   - Consumer group: `cg-trace`
   - Purpose: Task lifecycle events for WebSocket fanout
   - Fields: event_type, task_id, node_key, status

### Pub/Sub Channels
1. **CHANNEL_GLOBAL** (`aop:events`):
   - Purpose: Global system events
   - Subscribers: WebSocket clients at `/v1/events/ws`

2. **CHANNEL_TASK_PREFIX** (`aop:task:{task_id}:events`):
   - Purpose: Task-specific events
   - Subscribers: WebSocket clients at `/v1/tasks/{id}/events/ws`

### Flow Pattern
```
Scheduler state change
  ↓
StreamClient.publish_task_event()
  ↓
XADD to TASK_EVENTS stream
  ↓
Fanout to Pub/Sub channels
  ↓
WebSocket clients receive real-time updates
```

---

## 8. Artifact Data Flow

### Storage
1. **MinIO/S3** (via ArtifactStore):
   - Raw outputs stored as objects
   - URIs stored in task_nodes.output_json

2. **PostgreSQL** (via Scheduler):
   - task_nodes.output_json contains artifact metadata
   - Structure: `{text, data, artifacts: [{name, uri, type, mime_type, size}]}`

### Access Patterns
1. **During Execution**:
   - A2AExecutor.execute() returns result with artifacts
   - ArtifactStore.persist_node_output() saves to MinIO
   - Metadata stored in task_nodes.output_json

2. **Query via API**:
   - TaskService.list_artifacts(task_id)
   - ArtifactManager.list_for_task(task_id)
   - Merges MinIO metadata with node output metadata

3. **Aggregation**:
   - Aggregator.build_result() collects all node artifacts
   - Writes to tasks.result_json

---

## 9. Current Circular Dependencies

### Analysis Result: **NO CIRCULAR DEPENDENCIES DETECTED**

The current architecture is well-structured with clear dependency hierarchy:

```
Level 1 (Data/Infrastructure):
  - ArtifactStore (MinIO)
  - StreamClient (Redis)
  - PostgreSQL (via direct psycopg)

Level 2 (Domain Services):
  - Planner (direct DB access)
  - AgentRouter (direct DB + Redis access)
  - Scheduler (direct DB access)
  - MemoryService (direct DB access)
  - EvaluationService (direct DB access)
  - WorkflowService (direct DB access)
  - BillingService (direct DB access)
  - QuotaService (direct DB access)
  - EgressService (direct DB access)
  - Aggregator (direct DB access)

Level 3 (Thin Wrappers):
  - PlanningEngine → Planner
  - RoutingEngine → AgentRouter
  - SchedulingEngine → Scheduler

Level 4 (Application):
  - TaskManager (orchestrates Level 3 + other services)
  - ExecutionEngine (independent worker, uses Level 2/3)

Level 5 (Facade):
  - TaskService (exposes Level 4 via HTTP API)
```

### Dependency Direction
All dependencies flow **downward** from application to infrastructure. No circular imports detected.

---

## 10. Current High Coupling Points

### 1. TaskManager Initialization Coupling
**Location**: `task_manager.py:25-43`

**Issue**: TaskManager creates default instances of all dependencies:
```python
def __init__(
    self,
    *,
    planning: PlanningEngine | None = None,
    scheduling: SchedulingEngine | None = None,
    workflows: WorkflowService | None = None,
    quotas: QuotaService | None = None,
    memory: MemoryService | None = None,
    artifacts: ArtifactManager | None = None,
) -> None:
    self.planning = planning or PlanningEngine()
    self.scheduling = scheduling or SchedulingEngine()
    # ... creates default instances
```

**Impact**: Tight coupling to concrete implementations, difficult to test in isolation.

**Risk**: **LOW** - Already uses dependency injection pattern with defaults.

### 2. Direct Database Access in Domain Services
**Location**: Multiple services (Planner, Router, Scheduler, etc.)

**Issue**: Each domain service directly creates psycopg connections:
```python
with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
    # SQL queries
```

**Impact**: No repository abstraction, SQL scattered across services.

**Risk**: **MEDIUM** - Makes testing harder, potential for SQL inconsistencies.

### 3. ExecutionEngine Monolith
**Location**: `executor/engine.py:82-522`

**Issue**: ExecutionEngine handles:
- Redis stream consumption
- Agent routing
- A2A execution
- Artifact persistence
- DAG state updates
- Memory operations
- Evaluation
- Error handling
- Tracing
- Circuit breakers

**Impact**: 500+ lines, multiple responsibilities, hard to test.

**Risk**: **HIGH** - Complex failure scenarios, difficult to extend.

### 4. TaskService Facade Fat
**Location**: `application/task_service.py:26-290`

**Issue**: TaskService has 30+ methods delegating to 10+ services.

**Impact**: Large facade, but follows delegation pattern correctly.

**Risk**: **LOW** - This is the intended role of a facade.

### 5. SchedulingEngine Side Effects
**Location**: `scheduler/engine.py:31-148`

**Issue**: SchedulingEngine mixes:
- DAG persistence (Scheduler responsibility)
- Redis enqueueing (StreamClient responsibility)
- Event publishing (StreamClient responsibility)
- Aggregation (Aggregator responsibility)
- Evaluation (EvaluationService responsibility)

**Impact**: Side effects mixed with core scheduling logic.

**Risk**: **MEDIUM** - Violates single responsibility, hard to test.

---

## 11. Modules That Can Be Safely Split

### HIGH CONFIDENCE

1. **ExecutionEngine Decomposition**:
   - Extract `RoutingOrchestrator` (routing + retry logic)
   - Extract `NodeExecutor` (A2A execution + artifact persistence)
   - Extract `StateUpdater` (DAG state transitions)
   - Keep `ExecutionEngine` as coordinator

2. **SchedulingEngine Side Effects**:
   - Move Redis enqueueing to dedicated `JobQueue` service
   - Move event publishing to `EventPublisher` service
   - Keep SchedulingEngine focused on DAG persistence

3. **Repository Layer**:
   - Extract `TaskRepository`, `NodeRepository`, `AgentRepository`
   - Move SQL from domain services to repositories
   - Domain services use repositories instead of direct DB access

### MEDIUM CONFIDENCE

4. **TaskManager Flow Decomposition**:
   - Extract `TaskCreationFlow` (quota → plan → schedule → memory)
   - Extract `WorkflowExecutionFlow` (workflow lookup → plan → schedule)
   - Keep TaskManager as orchestrator

5. **ArtifactManager Separation**:
   - Split `ArtifactStore` (MinIO operations) from `ArtifactManager` (metadata merging)
   - Already partially separated, can be cleaned up

### LOW CONFIDENCE (NOT RECOMMENDED)

6. **TaskService Facade**:
   - Already follows correct facade pattern
   - Splitting would break API compatibility
   - No clear benefit

7. **Domain Services (Planner, Router, Scheduler)**:
   - Already well-separated
   - Thin engine wrappers are appropriate
   - Further splitting would add complexity without benefit

---

## 12. Modules That Should NOT Be Split

### DO NOT SPLIT

1. **TaskService** (`application/task_service.py`):
   - **Reason**: Already a proper facade following delegation pattern
   - **Risk**: Breaking API compatibility, no clear separation boundary
   - **Current State**: ✅ Well-designed

2. **Planner/Router/Scheduler Core Classes**:
   - **Reason**: Domain logic is cohesive and focused
   - **Risk**: Over-engineering, introducing indirection without benefit
   - **Current State**: ✅ Well-separated domains

3. **Thin Engine Wrappers** (PlanningEngine, RoutingEngine, SchedulingEngine):
   - **Reason**: Intentionally thin to provide clean API boundaries
   - **Risk**: Adding unnecessary abstraction layers
   - **Current State**: ✅ Appropriate pattern

4. **Infrastructure Services** (StreamClient, ArtifactStore):
   - **Reason**: Simple adapters to external systems
   - **Risk**: Splitting adapters adds no value
   - **Current State**: ✅ Focused responsibilities

5. **Business Services** (Billing, Quota, Egress, Memory, Evaluation):
   - **Reason**: Each service has clear, focused responsibility
   - **Risk**: Splitting would scatter related logic
   - **Current State**: ✅ Well-defined boundaries

---

## 13. Key Findings Summary

### POSITIVE FINDINGS
1. ✅ **No circular dependencies** - Clean dependency hierarchy
2. ✅ **Already partially refactored** - TaskService is a facade, engines are separated
3. ✅ **Clear domain boundaries** - Planner, Router, Scheduler, Executor are distinct
4. ✅ **Dependency injection** - TaskManager accepts injected dependencies
5. ✅ **Thin wrappers pattern** - Engine wrappers provide clean APIs

### AREAS FOR IMPROVEMENT
1. ⚠️ **ExecutionEngine is monolithic** - 500+ lines, multiple responsibilities
2. ⚠️ **SchedulingEngine has side effects** - Mixes persistence with enqueueing/events
3. ⚠️ **Direct DB access everywhere** - No repository abstraction
4. ⚠️ **SQL scattered** - Queries embedded in domain services

### RISK ASSESSMENT
- **Architecture Risk**: LOW - Foundation is solid
- **Refactoring Risk**: MEDIUM - Need to preserve behavior while splitting
- **Testing Risk**: MEDIUM - Some components lack comprehensive tests
- **Compatibility Risk**: LOW - Facade pattern protects API surface

---

## 14. Recommended Refactoring Scope

### PHASE 1: LOW-RISK EXTRACTIONS (Recommended)
1. Extract `JobQueue` service from SchedulingEngine
2. Extract `EventPublisher` service from SchedulingEngine
3. Extract `NodeExecutor` from ExecutionEngine
4. Extract `RoutingOrchestrator` from ExecutionEngine

### PHASE 2: MEDIUM-RISK REFACTORING (Optional)
1. Introduce repository layer for Task/Node/Agent
2. Extract `TaskCreationFlow` from TaskManager
3. Clean up ArtifactManager vs ArtifactStore separation

### PHASE 3: DO NOT REFACTOR (Explicit Decision)
1. Keep TaskService as-is (facade pattern is correct)
2. Keep domain services (Planner, Router, Scheduler) as-is
3. Keep thin engine wrappers as-is

---

## 15. Testing Coverage Assessment

### Existing Tests
- ✅ `test_planner_heuristic.py` - Planner logic
- ✅ `test_planner_v2.py` - Step decomposition
- ✅ `test_router.py` - Agent routing
- ✅ `test_scheduler_flow.py` - DAG scheduling
- ✅ `test_dag.py` - DAG validation
- ✅ `test_application_refactor.py` - TaskManager tests
- ✅ `test_stale_reclaim.py` - Stale node reclamation
- ✅ `test_tenant_memory.py` - Memory operations
- ✅ Billing/quota/egress tests

### Missing Tests
- ⚠️ Integration tests for full task lifecycle
- ⚠️ ExecutionEngine unit tests
- ⚠️ SchedulingEngine side-effect tests
- ⚠️ Redis Streams integration tests
- ⚠️ Repository layer tests (if introduced)

---

## 16. Database Schema Dependencies

### Key Tables
- `tasks` - Task metadata
- `task_nodes` - DAG nodes
- `task_dependencies` - DAG edges
- `task_events` - Event log
- `agent_runs` - Execution audit
- `agents` / `agent_skills` / `agent_endpoints` - Agent registry
- `workflows` / `workflow_versions` - Workflow templates
- `task_memories` / `tenant_memories` - Memory storage
- `task_evaluations` - Evaluation results
- Billing/quota/egress tables

### Schema Change Risk
- **Risk**: LOW - No schema changes required for proposed refactoring
- **Reason**: Refactoring is code-only, no data model changes

---

## 17. Redis Dependencies

### Keys Used
- Stream: `a2a.execution.queue`
- Stream: `a2a.execution.events`
- Stream: `a2a.task.events`
- Pub/Sub: `aop:events`
- Pub/Sub: `aop:task:{task_id}:events`
- Locks: `lock:task:{task_id}`
- Indexes: `agent:skill:{skill}` (optional)

### Redis Change Risk
- **Risk**: LOW - No Redis structure changes required
- **Reason**: Refactoring changes code organization, not data structures

---

## 18. Conclusion

### Current State Assessment
The Orchestrator codebase is **already well-structured** with:
- Clear domain separation (Planner, Router, Scheduler, Executor)
- Proper facade pattern (TaskService)
- Dependency injection (TaskManager)
- No circular dependencies

### Refactoring Opportunity
The main opportunity is **extracting side effects** from core domain logic:
1. Extract job queue operations from SchedulingEngine
2. Extract event publishing from SchedulingEngine
3. Decompose the monolithic ExecutionEngine

### Recommended Approach
**Conservative, incremental refactoring**:
1. Start with low-risk extractions (JobQueue, EventPublisher)
2. Add tests for extracted components
3. Verify behavior preservation
4. Move to ExecutionEngine decomposition if needed

### What NOT To Do
- Do not split TaskService (it's already correct)
- Do not split domain services (they're already focused)
- Do not introduce heavy abstraction layers prematurely
- Do not change database schema
- Do not change Redis data structures

### Success Criteria
- ✅ No API changes
- ✅ No behavior changes
- ✅ All existing tests pass
- ✅ New components have tests
- ✅ Code is more testable
- ✅ Responsibilities are clearer

---

**Audit Complete**  
**Next Step**: Create detailed refactor plan (Phase 35.2)
