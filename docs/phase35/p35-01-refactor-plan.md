# Phase 35.2: Orchestrator Refactor Plan

**Date**: 2026-09-18  
**Based on**: Phase 35.1 Audit Report  
**Objective**: Minimal, safe refactoring to improve code organization without breaking functionality

---

## Executive Summary

The audit revealed that the Orchestrator codebase is **already well-structured** with proper domain separation and no circular dependencies. The main refactoring opportunity is extracting side effects from core domain logic to improve testability and maintainability.

**Key Decision**: Conservative, incremental refactoring focusing on the highest-impact, lowest-risk changes.

---

## Current Structure Analysis

### What's Working Well ✅
- **TaskService** is already a proper facade following delegation pattern
- **Domain services** (Planner, Router, Scheduler) have clear boundaries
- **No circular dependencies** - clean dependency hierarchy
- **Dependency injection** in TaskManager
- **Thin engine wrappers** provide clean API boundaries

### What Needs Improvement ⚠️
- **ExecutionEngine** is monolithic (500+ lines, multiple responsibilities)
- **SchedulingEngine** mixes persistence with enqueueing/events
- **Direct DB access** scattered across domain services
- **SQL queries** embedded in domain logic

---

## Refactoring Principles

1. **Preserve API Compatibility**: No changes to HTTP API or public method signatures
2. **Preserve Behavior**: All existing functionality must work identically
3. **Incremental Changes**: One small change at a time, test after each
4. **No Schema Changes**: Database and Redis structures remain unchanged
5. **Test-Driven**: Add tests before/after refactoring
6. **Backward Compatibility**: Keep legacy import paths working

---

## Proposed Refactoring Structure

### Phase 1: Extract Side Effects from SchedulingEngine

#### Current Structure
```
SchedulingEngine
 ├─ Scheduler (domain logic: DAG persistence)
 ├─ StreamClient (side effect: enqueue jobs)
 ├─ Aggregator (side effect: build results)
 └─ EvaluationService (side effect: auto-evaluate)
```

#### Target Structure
```
SchedulingEngine (focused on DAG persistence)
 ├─ Scheduler (domain logic)
 └─ EventPublisher (side effects: events + aggregation + evaluation)

JobQueue (new: Redis enqueue operations)
 ├─ StreamClient
 └─ enqueue_execution()
```

#### Rationale
- Separates **state management** from **side effects**
- Makes SchedulingEngine easier to test (no Redis required)
- EventPublisher can be mocked in tests
- JobQueue can be tested independently

#### Changes Required
1. Create `apps/orchestrator/scheduling/event_publisher.py`
2. Create `apps/orchestrator/scheduling/job_queue.py`
3. Modify `SchedulingEngine.__init__()` to accept `event_publisher` and `job_queue`
4. Move enqueue logic from `SchedulingEngine.enqueue_jobs()` to `JobQueue`
5. Move event/aggregation/evaluation logic to `EventPublisher`
6. Update `TaskManager` initialization to create new services

#### API Impact
- **None**: Public methods unchanged
- **Internal**: Constructor signatures change (with defaults)

---

### Phase 2: Decompose ExecutionEngine

#### Current Structure
```
ExecutionEngine (500+ lines)
 ├─ Redis stream consumption
 ├─ Agent routing
 ├─ A2A execution
 ├─ Artifact persistence
 ├─ DAG state updates
 ├─ Memory operations
 ├─ Evaluation
 ├─ Error handling
 ├─ Tracing
 └─ Circuit breakers
```

#### Target Structure
```
ExecutionEngine (coordinator)
 ├─ JobQueue (Redis stream consumption)
 ├─ RoutingOrchestrator (routing + retry + circuit breaker)
 ├─ NodeExecutor (A2A execution + artifact persistence)
 ├─ StateUpdater (DAG state transitions)
 └─ MemoryCoordinator (memory operations)
```

#### Rationale
- Separates **concerns** into focused components
- Each component can be tested independently
- Reduces complexity of individual files
- Makes error handling clearer

#### Changes Required
1. Create `apps/orchestrator/execution/routing_orchestrator.py`
2. Create `apps/orchestrator/execution/node_executor.py`
3. Create `apps/orchestrator/execution/state_updater.py`
4. Create `apps/orchestrator/execution/memory_coordinator.py`
5. Refactor `ExecutionEngine` to use these components
6. Move retry/circuit breaker logic to `RoutingOrchestrator`
7. Move A2A execution to `NodeExecutor`
8. Move DAG updates to `StateUpdater`

#### API Impact
- **None**: ExecutionEngine interface unchanged
- **Internal**: Implementation delegates to new components

---

### Phase 3: Repository Layer (Optional/Deferred)

#### Current Structure
```
Planner (direct psycopg calls)
Router (direct psycopg calls)
Scheduler (direct psycopg calls)
MemoryService (direct psycopg calls)
...
```

#### Target Structure
```
Planner → TaskRepository, AgentRepository
Router → AgentRepository
Scheduler → TaskRepository, NodeRepository
MemoryService → MemoryRepository
...
```

#### Rationale
- Centralizes SQL logic
- Makes domain services testable with mock repositories
- Easier to add caching later
- Standardizes data access patterns

#### Changes Required
1. Create `apps/orchestrator/repositories/` directory
2. Create repository classes for each entity
3. Migrate SQL from domain services to repositories
4. Update domain services to use repositories
5. Add repository tests

#### API Impact
- **None**: Public interfaces unchanged
- **Internal**: Implementation uses repositories

#### Decision
**DEFER to future phase** - This is larger scope and can be done independently

---

## Detailed Module Specifications

### New Module: JobQueue

**File**: `apps/orchestrator/scheduling/job_queue.py`

**Responsibilities**:
- Enqueue jobs to Redis Streams
- Handle delayed execution (backoff)
- Manage job priority

**Input**:
- Job metadata (task_id, node_id, node_key, skill, attempt, exclude_agent_ids)

**Output**:
- Redis Stream message ID

**Dependencies**:
- StreamClient

**API**:
```python
class JobQueue:
    def __init__(self, streams: StreamClient | None = None):
        self.streams = streams or StreamClient()
    
    def enqueue(
        self,
        *,
        task_id: str,
        node_id: str,
        node_key: str,
        skill: str,
        attempt: int = 1,
        exclude_agent_ids: list[str] | None = None,
        delay_seconds: float = 0,
    ) -> str:
        """Enqueue job to Redis Stream, returns message ID"""
    
    def enqueue_batch(self, jobs: list[dict]) -> list[str]:
        """Enqueue multiple jobs"""
```

**State Management**: Stateless (Redis is the state)

---

### New Module: EventPublisher

**File**: `apps/orchestrator/scheduling/event_publisher.py`

**Responsibilities**:
- Publish task lifecycle events
- Trigger aggregation on task completion
- Trigger evaluation on task completion/failure
- Fanout to WebSocket clients

**Input**:
- Event type, task_id, node_id, payload

**Output**:
- Redis Stream message ID

**Dependencies**:
- StreamClient
- Aggregator
- EvaluationService

**API**:
```python
class EventPublisher:
    def __init__(
        self,
        streams: StreamClient | None = None,
        aggregator: Aggregator | None = None,
        evaluations: EvaluationService | None = None,
    ):
        self.streams = streams or StreamClient()
        self.aggregator = aggregator or Aggregator()
        self.evaluations = evaluations or EvaluationService()
    
    def publish_node_enqueued(self, task_id: str, node_key: str, skill: str) -> str:
        """Publish node enqueued event"""
    
    def publish_task_completed(self, task_id: str) -> dict:
        """Publish task completed event with aggregation and evaluation"""
    
    def publish_task_failed(self, task_id: str) -> dict:
        """Publish task failed event with evaluation"""
    
    def publish_node_completed(self, task_id: str, node_key: str, agent_id: str, latency_ms: int) -> str:
        """Publish node completed event"""
```

**State Management**: Stateless

---

### New Module: RoutingOrchestrator

**File**: `apps/orchestrator/execution/routing_orchestrator.py`

**Responsibilities**:
- Agent selection with retry logic
- Circuit breaker integration
- Endpoint normalization
- Sandbox validation

**Input**:
- skill, exclude_agent_ids

**Output**:
- RoutedAgent (agent_id, endpoint, score)

**Dependencies**:
- RoutingEngine
- Sandbox (validation)

**API**:
```python
class RoutingOrchestrator:
    def __init__(
        self,
        routing: RoutingEngine | None = None,
        enable_retry: bool = True,
        enable_circuit_breaker: bool = True,
    ):
        self.routing = routing or RoutingEngine()
        self.enable_retry = enable_retry
        self.enable_circuit_breaker = enable_circuit_breaker
    
    def select_agent(
        self,
        skill: str,
        *,
        exclude_agent_ids: set[str] | None = None,
    ) -> RoutedAgent:
        """Select agent with retry and circuit breaker"""
    
    def validate_endpoint(self, endpoint: str, skill: str) -> None:
        """Validate endpoint against sandbox rules"""
```

**State Management**: Stateless

---

### New Module: NodeExecutor

**File**: `apps/orchestrator/execution/node_executor.py`

**Responsibilities**:
- Execute A2A call to agent
- Persist artifacts to MinIO
- Handle execution errors
- Measure latency

**Input**:
- endpoint, query, skill, task_id, node_key

**Output**:
- ExecutionResult (text, data, artifacts, latency_ms)

**Dependencies**:
- A2AExecutor
- ArtifactStore

**API**:
```python
class NodeExecutor:
    def __init__(
        self,
        executor: A2AExecutor | None = None,
        artifacts: ArtifactStore | None = None,
        timeout: float = 60.0,
    ):
        self.executor = executor or A2AExecutor(timeout=timeout)
        self.artifacts = artifacts or ArtifactStore()
    
    def execute(
        self,
        endpoint: str,
        query: str,
        skill: str,
        *,
        task_id: str,
        node_key: str,
    ) -> ExecutionResult:
        """Execute node and persist artifacts"""
```

**State Management**: Stateless

---

### New Module: StateUpdater

**File**: `apps/orchestrator/execution/state_updater.py`

**Responsibilities**:
- Mark node success/failure in DAG
- Unlock dependent nodes
- Handle HITL state transitions
- Generate ready jobs for downstream nodes

**Input**:
- task_id, node_key, output/error, agent_id, latency_ms

**Output**:
- UpdateResult (status, ready_jobs, unlocked_nodes)

**Dependencies**:
- Scheduler

**API**:
```python
class StateUpdater:
    def __init__(self, scheduler: Scheduler | None = None):
        self.scheduler = scheduler or Scheduler()
    
    def mark_success(
        self,
        task_id: str,
        node_key: str,
        *,
        output: dict,
        agent_id: str,
        latency_ms: int,
    ) -> UpdateResult:
        """Mark node success and unlock dependents"""
    
    def mark_failure(
        self,
        task_id: str,
        node_key: str,
        *,
        error: str,
        attempt: int,
        agent_id: str | None,
    ) -> UpdateResult:
        """Mark node failure and determine retry/stop"""
    
    def claim_running(
        self,
        task_id: str,
        node_key: str,
        agent_id: str,
        attempt: int,
    ) -> bool:
        """Claim node for execution"""
```

**State Management**: Stateless (Scheduler manages DB state)

---

### New Module: MemoryCoordinator

**File**: `apps/orchestrator/execution/memory_coordinator.py`

**Responsibilities**:
- Compose memory context for executor
- Remember node outputs
- Promote task memory to tenant memory

**Input**:
- task_id, node_key, skill, text, agent_id

**Output**:
- Memory context string

**Dependencies**:
- MemoryService

**API**:
```python
class MemoryCoordinator:
    def __init__(self, memory: MemoryService | None = None):
        self.memory = memory or MemoryService()
    
    def compose_context(self, task_id: str) -> str:
        """Compose memory context for executor query"""
    
    def remember_node(
        self,
        task_id: str,
        node_key: str,
        skill: str,
        text: str,
        agent_id: str,
    ) -> dict:
        """Store node output in task memory"""
    
    def promote_task(self, task_id: str) -> list[dict]:
        """Promote task memory to tenant memory"""
```

**State Management**: Stateless (MemoryService manages DB state)

---

## Modified Module: SchedulingEngine

**Before**:
```python
class SchedulingEngine:
    def __init__(
        self,
        *,
        scheduler: Scheduler | None = None,
        streams: StreamClient | None = None,
        aggregator: Aggregator | None = None,
        evaluations: EvaluationService | None = None,
    ):
        self.scheduler = scheduler or Scheduler()
        self.streams = streams or StreamClient()
        self.aggregator = aggregator or Aggregator()
        self.evaluations = evaluations or EvaluationService()
    
    def enqueue_jobs(self, jobs: list[dict], *, task_id: str) -> list[str]:
        # Mixed: Redis enqueue + event publishing
        enqueued = []
        for job in jobs:
            self.streams.enqueue_execution(**job)
            self.streams.publish_task_event(...)
            enqueued.append(job["node_key"])
        return enqueued
```

**After**:
```python
class SchedulingEngine:
    def __init__(
        self,
        *,
        scheduler: Scheduler | None = None,
        job_queue: JobQueue | None = None,
        event_publisher: EventPublisher | None = None,
    ):
        self.scheduler = scheduler or Scheduler()
        self.job_queue = job_queue or JobQueue()
        self.event_publisher = event_publisher or EventPublisher()
    
    def enqueue_jobs(self, jobs: list[dict], *, task_id: str) -> list[str]:
        # Delegated to JobQueue + EventPublisher
        enqueued = self.job_queue.enqueue_batch(jobs)
        for job in jobs:
            self.event_publisher.publish_node_enqueued(
                task_id, job["node_key"], job["skill"]
            )
        return enqueued
```

**Changes**:
- Removed direct StreamClient dependency
- Removed direct Aggregator/EvaluationService dependencies
- Added JobQueue and EventPublisher dependencies
- enqueue_jobs() delegates to new services

---

## Modified Module: ExecutionEngine

**Before**:
```python
class ExecutionEngine:
    def __init__(self, consumer_name: str | None = None):
        self.worker_id = consumer_name or f"executor-{socket.gethostname()}-{os.getpid()}"
        self.streams = StreamClient()
        self.scheduler = Scheduler()
        self.routing = RoutingEngine()
        self.executor = A2AExecutor(timeout=60)
        self.aggregator = Aggregator()
        self.artifacts = ArtifactStore()
        self.evaluations = EvaluationService()
        self.memory = MemoryService()
    
    def handle(self, fields: dict[str, str]) -> None:
        # 500+ lines of mixed logic
        # - routing
        # - execution
        # - artifact persistence
        # - state updates
        # - memory operations
        # - evaluation
        # - error handling
```

**After**:
```python
class ExecutionEngine:
    def __init__(
        self,
        consumer_name: str | None = None,
        *,
        job_queue: JobQueue | None = None,
        routing_orchestrator: RoutingOrchestrator | None = None,
        node_executor: NodeExecutor | None = None,
        state_updater: StateUpdater | None = None,
        memory_coordinator: MemoryCoordinator | None = None,
        event_publisher: EventPublisher | None = None,
    ):
        self.worker_id = consumer_name or f"executor-{socket.gethostname()}-{os.getpid()}"
        self.job_queue = job_queue or JobQueue()
        self.routing_orchestrator = routing_orchestrator or RoutingOrchestrator()
        self.node_executor = node_executor or NodeExecutor()
        self.state_updater = state_updater or StateUpdater()
        self.memory_coordinator = memory_coordinator or MemoryCoordinator()
        self.event_publisher = event_publisher or EventPublisher()
    
    def handle(self, fields: dict[str, str]) -> None:
        # Coordinated orchestration
        task_id = fields["task_id"]
        node_key = fields["node_key"]
        skill = fields["skill"]
        
        # 1. Route agent
        routed = self.routing_orchestrator.select_agent(skill, exclude_agent_ids=exclude)
        
        # 2. Compose query with memory
        query = self.memory_coordinator.compose_context(task_id)
        
        # 3. Claim node
        claimed = self.state_updater.claim_running(task_id, node_key, routed.agent_id, attempt)
        if not claimed:
            return
        
        # 4. Execute node
        result = self.node_executor.execute(routed.endpoint, query, skill, task_id, node_key)
        
        # 5. Update state
        update = self.state_updater.mark_success(task_id, node_key, output=result.output, ...)
        
        # 6. Enqueue downstream
        self.job_queue.enqueue_batch(update.ready_jobs)
        
        # 7. Remember in memory
        self.memory_coordinator.remember_node(task_id, node_key, skill, result.text, routed.agent_id)
        
        # 8. Publish events
        self.event_publisher.publish_node_completed(task_id, node_key, routed.agent_id, result.latency_ms)
        
        # 9. Handle task completion
        if update.task_status == "completed":
            self.event_publisher.publish_task_completed(task_id)
            self.memory_coordinator.promote_task(task_id)
```

**Changes**:
- Extracted routing logic to RoutingOrchestrator
- Extracted execution logic to NodeExecutor
- Extracted state updates to StateUpdater
- Extracted memory operations to MemoryCoordinator
- Delegated job enqueue to JobQueue
- Delegated event publishing to EventPublisher
- Reduced from 500+ lines to ~100 lines of coordination

---

## Implementation Order

### Phase 1A: Extract JobQueue (Lowest Risk)
1. Create `scheduling/job_queue.py`
2. Write unit tests for JobQueue
3. Modify `SchedulingEngine` to use JobQueue
4. Update `TaskManager` initialization
5. Run existing tests
6. Verify behavior unchanged

### Phase 1B: Extract EventPublisher (Low Risk)
1. Create `scheduling/event_publisher.py`
2. Write unit tests for EventPublisher
3. Modify `SchedulingEngine` to use EventPublisher
4. Update `TaskManager` initialization
5. Run existing tests
6. Verify behavior unchanged

### Phase 2A: Extract RoutingOrchestrator (Medium Risk)
1. Create `execution/routing_orchestrator.py`
2. Write unit tests for RoutingOrchestrator
3. Modify `ExecutionEngine` to use RoutingOrchestrator
4. Run existing tests
5. Verify behavior unchanged

### Phase 2B: Extract NodeExecutor (Medium Risk)
1. Create `execution/node_executor.py`
2. Write unit tests for NodeExecutor
3. Modify `ExecutionEngine` to use NodeExecutor
4. Run existing tests
5. Verify behavior unchanged

### Phase 2C: Extract StateUpdater (Medium Risk)
1. Create `execution/state_updater.py`
2. Write unit tests for StateUpdater
3. Modify `ExecutionEngine` to use StateUpdater
4. Run existing tests
5. Verify behavior unchanged

### Phase 2D: Extract MemoryCoordinator (Low Risk)
1. Create `execution/memory_coordinator.py`
2. Write unit tests for MemoryCoordinator
3. Modify `ExecutionEngine` to use MemoryCoordinator
4. Run existing tests
5. Verify behavior unchanged

### Phase 2E: Consolidate ExecutionEngine (Low Risk)
1. Refactor ExecutionEngine to use all new components
2. Simplify handle() method to orchestration only
3. Run full integration test
4. Verify behavior unchanged

---

## Testing Strategy

### Unit Tests for New Components
Each new component will have:
- Constructor tests (dependency injection)
- Core method tests with mocks
- Error handling tests
- Edge case tests

### Integration Tests
- Full task lifecycle: create → plan → route → schedule → execute → artifact → aggregate
- HITL flow: create → execute → wait → approve → complete
- Error flow: create → execute → fail → retry → complete
- Memory flow: create → execute → remember → promote

### Regression Tests
- All existing tests must pass
- API behavior must be identical
- Database state must be identical
- Redis state must be identical

---

## Risk Assessment

### Phase 1 Risks (Low)
- **Risk**: Constructor signature changes in SchedulingEngine
- **Mitigation**: Provide default parameter values for backward compatibility
- **Risk**: Event ordering changes
- **Mitigation**: Preserve exact event sequence in EventPublisher

### Phase 2 Risks (Medium)
- **Risk**: ExecutionEngine behavior changes due to decomposition
- **Mitigation**: Extensive integration testing, step-by-step verification
- **Risk**: Error handling分散 across components
- **Mitigation**: Keep error handling in ExecutionEngine coordinator

### Overall Risk
- **Architecture Risk**: LOW - Foundation is solid
- **Breaking Changes Risk**: LOW - API compatibility preserved
- **Behavior Risk**: LOW - Comprehensive testing
- **Timeline Risk**: LOW - Incremental approach allows rollback

---

## Rollback Plan

If any phase fails:
1. Revert changes to modified files
2. Delete new component files
3. Restore previous initialization code
4. Run tests to verify rollback

Each phase is independently reversible.

---

## Success Criteria

### Functional
- ✅ All existing tests pass
- ✅ API behavior unchanged
- ✅ Task lifecycle works end-to-end
- ✅ HITL flow works
- ✅ Error handling works
- ✅ Memory operations work

### Code Quality
- ✅ New components have unit tests
- ✅ Code is more readable
- ✅ Responsibilities are clearer
- ✅ Dependencies are explicit

### Performance
- ✅ No performance regression
- ✅ Latency unchanged
- ✅ Memory usage unchanged

---

## What Will NOT Change

### No Changes To
- ✅ HTTP API endpoints
- ✅ TaskService public interface
- ✅ Database schema
- ✅ Redis data structures
- ✅ Agent protocol
- ✅ Task/Node/Run data models
- ✅ Event types and payloads
- ✅ WebSocket protocols

### No Splitting Of
- ✅ TaskService (already correct as facade)
- ✅ Planner, Router, Scheduler (already well-separated)
- ✅ Thin engine wrappers (already appropriate)
- ✅ Business services (Billing, Quota, Egress, etc.)

---

## Estimated Timeline

- Phase 1A (JobQueue): 2-3 hours
- Phase 1B (EventPublisher): 2-3 hours
- Phase 2A (RoutingOrchestrator): 3-4 hours
- Phase 2B (NodeExecutor): 3-4 hours
- Phase 2C (StateUpdater): 3-4 hours
- Phase 2D (MemoryCoordinator): 2-3 hours
- Phase 2E (Consolidation): 2-3 hours
- Testing & Verification: 4-6 hours

**Total**: ~21-30 hours

---

## Next Steps

1. **Review and Approve**: Stakeholder review of this plan
2. **Phase 1A**: Implement JobQueue extraction
3. **Phase 1B**: Implement EventPublisher extraction
4. **Phase 2**: Implement ExecutionEngine decomposition
5. **Testing**: Comprehensive test suite
6. **Documentation**: Update code comments and docs
7. **Final Report**: Document changes and lessons learned

---

**Plan Complete**  
**Ready for Implementation**: Phase 35.3
