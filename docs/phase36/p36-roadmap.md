# AOP Phase 36 Implementation Roadmap

**Roadmap Version:** 1.0  
**Based On:** Phase 36.0 Reliability Audit  
**Date:** 2026-09-19  
**Objective:** Implement production-grade reliability guarantees for AOP task execution

---

## Executive Summary

This roadmap provides a sequenced implementation plan to address the reliability gaps identified in the Phase 36.0 audit. The roadmap prioritizes critical reliability risks (P0 findings) while establishing a foundation for comprehensive reliability improvements.

### Roadmap Principles

1. **Risk-Driven:** Address P0 findings first, then P1, then P2/P3
2. **Incremental:** Each phase builds on previous work
3. **Tested:** Every change includes comprehensive testing
4. **Minimal Disruption:** Avoid breaking changes where possible
5. **Production-Ready:** All changes suitable for production deployment

### Estimated Total Effort

- **P36.1 (Critical):** 3-4 weeks
- **P36.2 (Critical):** 4-5 weeks
- **P36.3 (Major):** 2-3 weeks
- **P36.4 (Major):** 2-3 weeks
- **P36.5 (Major):** 3-4 weeks
- **P36.6 (Observability):** 3-4 weeks
- **P36.7 (Testing):** 4-5 weeks
- **P36.8 (Recovery):** 3-4 weeks

**Total:** 24-32 weeks (6-8 months)

---

## Phase 36.1: Idempotency Keys and Exactly-Once Execution

**Priority:** P0 (Critical)  
**Duration:** 3-4 weeks  
**Addresses:** P0-001, P0-002

### Problem Statement

The current AOP implementation lacks exactly-once execution guarantees. Worker crashes, timeouts, and network failures can cause duplicate Agent execution, leading to data inconsistency and duplicate side effects.

### Scope

1. Add idempotency key to A2A protocol
2. Implement request ID tracking in orchestrator
3. Add deduplication logic in executor
4. Implement Agent-side idempotency
5. Add comprehensive testing

### Files/Modules Affected

- `packages/a2a-sdk/` - A2A protocol client and Agent SDK
- `apps/orchestrator/executor/__init__.py` - Execution engine
- `apps/orchestrator/scheduler/__init__.py` - Request tracking
- `infrastructure/postgres/init/013_request_tracking.sql` - New schema
- `agents/*/agent.py` - Agent implementations

### Detailed Implementation Plan

#### Step 1: A2A Protocol Enhancement (Week 1)

**Tasks:**
1. Design idempotency key format (UUID v4)
2. Update A2A protocol specification
3. Add idempotency key to message/send request
4. Update Agent SDK to include idempotency key
5. Update Agent SDK to return idempotency key in response

**Schema Changes:**
- Add `idempotency_key` field to A2A message schema
- Add `idempotency_key` field to A2A response schema

**Testing:**
- Unit tests for idempotency key generation
- Protocol validation tests
- SDK integration tests

#### Step 2: Orchestrator Request Tracking (Week 1-2)

**Tasks:**
1. Design request tracking table schema
2. Implement request ID generation in TaskManager
3. Add request ID to task creation flow
4. Add request ID to node execution flow
5. Implement request deduplication logic

**Schema Changes:**
```sql
CREATE TABLE a2a_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key TEXT NOT NULL UNIQUE,
  task_id UUID NOT NULL REFERENCES tasks(id),
  node_id UUID REFERENCES task_nodes(id),
  agent_id UUID REFERENCES agents(id),
  status TEXT NOT NULL DEFAULT 'pending',
  request_json JSONB,
  response_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_a2a_requests_idempotency ON a2a_requests(idempotency_key);
CREATE INDEX idx_a2a_requests_task ON a2a_requests(task_id);
```

**Implementation:**
- Add request tracking to `Scheduler.claim_running()`
- Add deduplication check in `ExecutionEngine.handle()`
- Update request status on success/failure

**Testing:**
- Request tracking unit tests
- Deduplication logic tests
- Integration tests with PostgreSQL

#### Step 3: Executor Deduplication (Week 2)

**Tasks:**
1. Add idempotency key to A2AExecutor.execute()
2. Check request tracking table before execution
3. Skip execution if request already completed
4. Return cached result if available
5. Handle idempotency conflicts

**Implementation:**
```python
def execute(self, agent_url, query, *, skill_id=None, idempotency_key=None):
    # Check if request already completed
    existing = self.scheduler.get_request(idempotency_key)
    if existing and existing['status'] == 'completed':
        return ExecutionResult.from_cached(existing)
    
    # Execute request
    result = A2AClient(agent_url).send_text(query, skill_id=skill_id, idempotency_key=idempotency_key)
    
    # Track request
    self.scheduler.track_request(idempotency_key, result)
    
    return result
```

**Testing:**
- Deduplication unit tests
- Executor integration tests
- Cache hit/miss tests

#### Step 4: Agent-Side Idempotency (Week 2-3)

**Tasks:**
1. Update Agent SDK to handle idempotency keys
2. Implement idempotency storage in Agents
3. Add idempotency checks in Agent execution
4. Return cached results for duplicate requests
5. Add idempotency to Agent documentation

**Implementation:**
- In-memory idempotency cache per Agent
- Optional persistent idempotency storage
- TTL-based cache invalidation

**Testing:**
- Agent idempotency unit tests
- Integration tests with multiple Agents
- Cache invalidation tests

#### Step 5: Comprehensive Testing (Week 3-4)

**Tasks:**
1. End-to-end exactly-once execution tests
2. Worker crash recovery tests
3. Timeout handling with idempotency tests
4. Duplicate request detection tests
5. Performance impact tests

**Test Scenarios:**
- Worker crash after Agent success
- Worker crash before Agent success
- Timeout with duplicate request
- Network partition with retry
- Concurrent duplicate requests

### Acceptance Criteria

- ✅ Every A2A request includes unique idempotency key
- ✅ Orchestrator tracks request IDs in PostgreSQL
- ✅ Duplicate requests detected and skipped
- ✅ Agents implement idempotency logic
- ✅ Worker crash after Agent success does not cause duplicate execution
- ✅ Timeout handling leverages idempotency
- ✅ Tests verify exactly-once behavior
- ✅ Performance impact < 10% overhead

### Risks and Mitigations

**Risk 1: Breaking A2A Protocol Change**
- **Mitigation:** Version the protocol, maintain backward compatibility
- **Fallback:** Add feature flag for idempotency

**Risk 2: Agent Updates Required**
- **Mitigation:** Provide clear migration guide for Agent developers
- **Fallback:** Graceful degradation for Agents without idempotency

**Risk 3: Performance Impact**
- **Mitigation:** Add request tracking indexes, optimize deduplication queries
- **Fallback:** Cache request tracking results

**Risk 4: Schema Migration Complexity**
- **Mitigation:** Use incremental migration, test in staging
- **Fallback:** Rollback plan prepared

### Dependencies

- A2A protocol design approval
- Schema migration planning
- Agent SDK updates
- Staging environment for testing

### Success Metrics

- Duplicate execution rate: < 0.1%
- Request tracking accuracy: 99.9%
- Idempotency cache hit rate: > 95%
- Performance overhead: < 10%

---

## Phase 36.2: Distributed Transaction Coordination

**Priority:** P0 (Critical)  
**Duration:** 4-5 weeks  
**Addresses:** P0-003  
**Prerequisites:** P36.1 completion

### Problem Statement

PostgreSQL state changes and Redis queue operations are not atomic, enabling split-brain scenarios where tasks are created in PostgreSQL but not enqueued in Redis, or vice versa.

### Scope

1. Implement transactional outbox pattern
2. Add compensating transaction logic
3. Implement state reconciliation
4. Add saga pattern for multi-step operations
5. Add comprehensive testing

### Files/Modules Affected

- `apps/orchestrator/scheduler/__init__.py` - Scheduler
- `apps/orchestrator/streams/__init__.py` - Stream client
- `infrastructure/postgres/init/014_outbox.sql` - New schema
- New `apps/orchestrator/outbox/` module
- New `apps/orchestrator/reconciliation/` module

### Detailed Implementation Plan

#### Step 1: Outbox Pattern Design (Week 1)

**Tasks:**
1. Design outbox table schema
2. Design outbox processor architecture
3. Design message format for outbox
4. Design retry and failure handling
5. Design monitoring and alerting

**Schema Changes:**
```sql
CREATE TABLE outbox_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  target_stream TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INT NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ,
  CONSTRAINT valid_target_stream CHECK (target_stream IN ('a2a.execution.queue', 'a2a.task.events'))
);

CREATE INDEX idx_outbox_status_created ON outbox_events(status, created_at);
CREATE INDEX idx_outbox_type ON outbox_events(event_type);
```

**Implementation:**
- Outbox event creation in Scheduler
- Outbox processor background job
- Retry logic with exponential backoff
- Dead letter queue for failed events

#### Step 2: Scheduler Integration (Week 1-2)

**Tasks:**
1. Replace direct Redis enqueue with outbox writes
2. Add outbox writes to PostgreSQL transactions
3. Update task creation flow
4. Update node unlock flow
5. Update event publishing flow

**Implementation:**
```python
def create_task(self, goal, plan, ...):
    with psycopg.connect(self.database_url) as conn:
        with conn.transaction():
            # Create task and nodes
            task_id = self._create_task_in_pg(conn, goal, plan)
            
            # Write outbox events instead of direct Redis enqueue
            for job in ready_jobs:
                self._write_outbox_event(conn, 'job_enqueue', job)
            
            # Transaction commits both task and outbox events
```

**Testing:**
- Outbox write unit tests
- Transaction rollback tests
- Integration tests with PostgreSQL

#### Step 3: Outbox Processor (Week 2-3)

**Tasks:**
1. Implement outbox processor background job
2. Add Redis enqueue logic to processor
3. Add retry logic for failed Redis operations
4. Add monitoring and metrics
5. Add dead letter queue handling

**Implementation:**
```python
class OutboxProcessor:
    def process_pending_events(self):
        pending = self._get_pending_events(limit=100)
        for event in pending:
            try:
                self._publish_to_redis(event)
                self._mark_event_processed(event['id'])
            except Exception as e:
                self._mark_event_failed(event['id'], str(e))
```

**Testing:**
- Outbox processor unit tests
- Redis failure simulation tests
- Retry logic tests
- Dead letter queue tests

#### Step 4: Compensating Transactions (Week 3)

**Tasks:**
1. Design compensating transaction logic
2. Implement rollback procedures
3. Add compensation for failed outbox events
4. Add compensation for failed Redis operations
5. Add compensation for failed Agent calls

**Implementation:**
- Compensation handlers for each operation type
- Transaction log for compensation tracking
- Manual compensation triggers

**Testing:**
- Compensating transaction unit tests
- Failure scenario tests
- Manual compensation procedure tests

#### Step 5: State Reconciliation (Week 3-4)

**Tasks:**
1. Design reconciliation logic
2. Implement PostgreSQL-Redis consistency checks
3. Implement PostgreSQL-MinIO consistency checks
4. Implement automated correction
5. Add reconciliation monitoring

**Implementation:**
```python
class ReconciliationService:
    def reconcile_tasks(self):
        # Find tasks in PostgreSQL but not in Redis
        orphaned_tasks = self._find_orphaned_tasks()
        for task in orphaned_tasks:
            self._enqueue_orphaned_task(task)
        
        # Find tasks in Redis but not in PostgreSQL
        ghost_tasks = self._find_ghost_tasks()
        for task in ghost_tasks:
            self._cancel_ghost_task(task)
```

**Testing:**
- Reconciliation logic tests
- Consistency check tests
- Automated correction tests

#### Step 6: Saga Pattern (Week 4)

**Tasks:**
1. Design saga pattern for multi-step operations
2. Implement saga coordinator
3. Add saga for task creation
4. Add saga for node execution
5. Add saga monitoring

**Implementation:**
- Saga state machine
- Step compensation logic
- Saga persistence
- Timeout handling

**Testing:**
- Saga pattern unit tests
- Multi-step operation tests
- Failure scenario tests

#### Step 7: Comprehensive Testing (Week 4-5)

**Tasks:**
1. Distributed transaction tests
2. Split-brain scenario tests
3. Recovery scenario tests
4. Performance tests
5. Chaos engineering tests

**Test Scenarios:**
- PostgreSQL commit, Redis failure
- Redis success, PostgreSQL rollback
- Network partition during transaction
- Concurrent transaction conflicts
- Outbox processor crash

### Acceptance Criteria

- ✅ PostgreSQL and Redis operations coordinated via outbox
- ✅ Failed operations compensated automatically
- ✅ State reconciliation detects and fixes inconsistencies
- ✅ Saga pattern handles multi-step operations
- ✅ Tests verify distributed transaction correctness
- ✅ Performance overhead < 15%
- ✅ Recovery time < 5 minutes for most scenarios

### Risks and Mitigations

**Risk 1: Performance Overhead**
- **Mitigation:** Optimize outbox queries, batch processing
- **Fallback:** Feature flag for outbox pattern

**Risk 2: Complexity Increase**
- **Mitigation:** Clear documentation, monitoring
- **Fallback:** Manual override procedures

**Risk 3: Redis Failure Scenarios**
- **Mitigation:** Retry logic, dead letter queue
- **Fallback:** Manual intervention procedures

**Risk 4: Reconciliation Errors**
- **Mitigation:** Conservative correction, manual review
- **Fallback:** Manual reconciliation procedures

### Dependencies

- P36.1 completion (for idempotency)
- Schema migration planning
- Redis monitoring setup
- Staging environment for testing

### Success Metrics

- Outbox event processing success rate: > 99.5%
- State reconciliation accuracy: 99.9%
- Compensating transaction success rate: > 99%
- Distributed transaction success rate: > 99.9%
- Performance overhead: < 15%

---

## Phase 36.3: Enhanced Failure Handling and Recovery

**Priority:** P1 (Major)  
**Duration:** 2-3 weeks  
**Addresses:** P1-001, P1-002, P1-006  
**Prerequisites:** P36.1 completion

### Problem Statement

Stale node reclaim has race conditions, timeout handling lacks idempotency, and circuit breakers are not consistently applied across the system.

### Scope

1. Fix stale reclaim race conditions
2. Improve timeout handling with idempotency
3. Consistently apply circuit breakers
4. Add comprehensive failure classification
5. Add comprehensive testing

### Files/Modules Affected

- `apps/orchestrator/scheduler/__init__.py` - Stale reclaim
- `apps/orchestrator/executor/__init__.py` - Timeout handling
- `apps/orchestrator/error_handling/__init__.py` - Error classification
- `apps/orchestrator/router/__init__.py` - Circuit breaker integration

### Detailed Implementation Plan

#### Step 1: Fix Stale Reclaim Race Conditions (Week 1)

**Tasks:**
1. Add row-level locking to stale reclaim
2. Use conditional UPDATE with status check
3. Add optimistic concurrency control
4. Add node versioning
5. Add comprehensive testing

**Implementation:**
```python
def reclaim_stale_nodes(self, *, stale_seconds=900):
    with psycopg.connect(self.database_url) as conn:
        with conn.transaction():
            # Use SELECT FOR UPDATE to lock rows
            rows = conn.execute("""
                SELECT id, task_id, node_key, skill, attempt, max_retry, assigned_agent_id
                FROM task_nodes
                WHERE status = 'running'
                  AND COALESCE(started_at, updated_at) < (%s - (%s || ' seconds')::interval)
                FOR UPDATE
                LIMIT 20
            """, (now, stale_seconds)).fetchall()
            
            for row in rows:
                # Conditional UPDATE with version check
                updated = conn.execute("""
                    UPDATE task_nodes
                    SET status = 'retrying',
                        attempt = %s,
                        error_message = %s,
                        updated_at = %s
                    WHERE id = %s AND status = 'running'
                    RETURNING id
                """, (attempt + 1, error_message, now, row['id'])).fetchone()
                
                if updated:
                    # Enqueue retry
                    jobs.append(self._create_retry_job(row))
```

**Testing:**
- Stale reclaim race condition tests
- Concurrent worker tests
- Lock contention tests

#### Step 2: Improve Timeout Handling (Week 1-2)

**Tasks:**
1. Leverage idempotency keys from P36.1
2. Implement adaptive timeout strategy
3. Add Agent heartbeat mechanism
4. Implement request cancellation
5. Add comprehensive testing

**Implementation:**
```python
def execute_with_timeout_aware_retry(self, endpoint, query, skill, idempotency_key):
    # Check if request already completed
    existing = self.scheduler.get_request(idempotency_key)
    if existing and existing['status'] == 'completed':
        return existing['response']
    
    # Execute with adaptive timeout
    timeout = self._calculate_adaptive_timeout(skill)
    try:
        result = self.executor.execute(endpoint, query, skill_id=skill, 
                                       idempotency_key=idempotency_key, 
                                       timeout=timeout)
        return result
    except TimeoutError:
        # Check if request completed elsewhere
        existing = self.scheduler.get_request(idempotency_key)
        if existing and existing['status'] == 'completed':
            return existing['response']
        raise
```

**Testing:**
- Timeout handling with idempotency tests
- Adaptive timeout tests
- Heartbeat mechanism tests

#### Step 3: Consistent Circuit Breaker Application (Week 2)

**Tasks:**
1. Audit all A2A call sites
2. Apply circuit breaker consistently
3. Add circuit breaker monitoring
4. Implement automatic recovery
5. Add circuit breaker metrics

**Implementation:**
- Wrap all A2A calls with circuit breaker
- Add circuit breaker state monitoring
- Implement automatic recovery logic
- Add circuit breaker metrics to observability

**Testing:**
- Circuit breaker integration tests
- Failure threshold tests
- Recovery mechanism tests

#### Step 4: Enhanced Error Classification (Week 2)

**Tasks:**
1. Expand error taxonomy
2. Add context-rich error classification
3. Implement precise retry policies
4. Add failure analytics
5. Add error classification tests

**Implementation:**
- Enhanced error classification in `error_handling/__init__.py`
- Context-aware error categorization
- Retry policy refinement
- Error analytics collection

**Testing:**
- Error classification accuracy tests
- Retry policy effectiveness tests
- Failure analytics tests

#### Step 5: Comprehensive Testing (Week 2-3)

**Tasks:**
1. Stale reclaim race condition tests
2. Timeout handling with idempotency tests
3. Circuit breaker integration tests
4. Error classification tests
5. End-to-end failure scenario tests

### Acceptance Criteria

- ✅ Stale reclaim uses row-level locking
- ✅ Timeout handling leverages idempotency
- ✅ Circuit breakers consistently applied
- ✅ Failures accurately classified
- ✅ Tests verify failure handling correctness
- ✅ Performance overhead < 5%

### Risks and Mitigations

**Risk 1: Lock Contention**
- **Mitigation:** Optimize lock duration, use lock timeouts
- **Fallback:** Fall back to optimistic concurrency

**Risk 2: Circuit Breaker False Positives**
- **Mitigation:** Tunable thresholds, monitoring
- **Fallback:** Manual override capability

**Risk 3: Error Classification Accuracy**
- **Mitigation:** Machine learning classification, feedback loop
- **Fallback:** Manual classification override

### Dependencies

- P36.1 completion (for idempotency)
- Monitoring infrastructure setup

### Success Metrics

- Stale reclaim race conditions: 0
- Timeout duplicate execution: 0
- Circuit breaker accuracy: > 95%
- Error classification accuracy: > 90%
- Performance overhead: < 5%

---

## Phase 36.4: Artifact Consistency and Cleanup

**Priority:** P1 (Major)  
**Duration:** 2-3 weeks  
**Addresses:** P1-004

### Problem Statement

Artifacts uploaded to MinIO before PostgreSQL success marking can become orphaned if persistence fails, causing storage leaks and inconsistency.

### Scope

1. Implement two-phase artifact upload
2. Add artifact garbage collection
3. Implement artifact deduplication
4. Add artifact reference counting
5. Add comprehensive testing

### Files/Modules Affected

- `apps/orchestrator/artifacts/__init__.py` - Artifact store
- `apps/orchestrator/executor/engine.py` - Artifact persistence
- `infrastructure/postgres/init/015_artifacts.sql` - New schema
- New `apps/orchestrator/artifacts/garbage_collector.py`

### Detailed Implementation Plan

#### Step 1: Two-Phase Artifact Upload (Week 1)

**Tasks:**
1. Design two-phase upload protocol
2. Implement artifact staging
3. Implement artifact commit
4. Implement artifact rollback
5. Add comprehensive testing

**Implementation:**
```python
class ArtifactStore:
    def persist_node_output_two_phase(self, task_id, node_key, text, data):
        # Phase 1: Stage artifacts
        staged_refs = self._stage_artifacts(task_id, node_key, text, data)
        
        # Return staged refs for external commit
        return staged_refs
    
    def commit_artifacts(self, staged_refs):
        # Phase 2: Commit staged artifacts
        for ref in staged_refs:
            self._commit_staged_artifact(ref)
    
    def rollback_artifacts(self, staged_refs):
        # Rollback: Delete staged artifacts
        for ref in staged_refs:
            self._delete_staged_artifact(ref)
```

**Testing:**
- Two-phase upload unit tests
- Commit/rollback tests
- Failure scenario tests

#### Step 2: Artifact Garbage Collection (Week 1-2)

**Tasks:**
1. Design garbage collection logic
2. Implement orphaned artifact detection
3. Implement artifact deletion
4. Add GC scheduling
5. Add GC monitoring

**Implementation:**
```python
class ArtifactGarbageCollector:
    def collect_orphaned_artifacts(self):
        # Find artifacts not referenced in PostgreSQL
        orphaned = self._find_orphaned_artifacts()
        
        # Delete orphaned artifacts
        for artifact in orphaned:
            self._delete_artifact(artifact['uri'])
        
        return len(orphaned)
    
    def _find_orphaned_artifacts(self):
        # Compare MinIO artifacts with PostgreSQL references
        minio_artifacts = self._list_minio_artifacts()
        pg_references = self._get_pg_artifact_references()
        
        orphaned = []
        for artifact in minio_artifacts:
            if artifact['uri'] not in pg_references:
                orphaned.append(artifact)
        
        return orphaned
```

**Testing:**
- Garbage collection unit tests
- Orphan detection tests
- Deletion safety tests

#### Step 3: Artifact Deduplication (Week 2)

**Tasks:**
1. Design artifact deduplication strategy
2. Implement content-based deduplication
3. Implement reference counting
4. Add deduplication to upload flow
5. Add comprehensive testing

**Implementation:**
- Content hash-based deduplication
- Reference counting for shared artifacts
- Deduplication cache

**Testing:**
- Deduplication unit tests
- Reference counting tests
- Cache consistency tests

#### Step 4: Reference Counting (Week 2)

**Tasks:**
1. Design reference counting schema
2. Implement reference tracking
3. Implement reference decrement
4. Implement deletion on zero reference
5. Add comprehensive testing

**Schema Changes:**
```sql
CREATE TABLE artifact_references (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_uri TEXT NOT NULL,
  task_id UUID NOT NULL REFERENCES tasks(id),
  node_id UUID REFERENCES task_nodes(id),
  reference_count INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (artifact_uri, task_id, node_id)
);

CREATE INDEX idx_artifact_references_uri ON artifact_references(artifact_uri);
```

**Testing:**
- Reference counting unit tests
- Deletion logic tests
- Concurrent reference tests

#### Step 5: Comprehensive Testing (Week 2-3)

**Tasks:**
1. Two-phase upload failure tests
2. Garbage collection effectiveness tests
3. Deduplication accuracy tests
4. Reference counting tests
5. End-to-end artifact consistency tests

### Acceptance Criteria

- ✅ Artifacts uploaded in two-phase pattern
- ✅ Orphaned artifacts automatically cleaned
- ✅ Duplicate uploads detected and skipped
- ✅ Reference counting prevents premature deletion
- ✅ Tests verify artifact consistency
- ✅ Storage leak rate: < 0.1%

### Risks and Mitigations

**Risk 1: Staged Artifact Accumulation**
- **Mitigation:** Frequent GC, monitoring
- **Fallback:** Manual cleanup procedures

**Risk 2: Deduplication Performance**
- **Mitigation:** Content hash caching, batch processing
- **Fallback:** Disable deduplication feature flag

**Risk 3: Reference Counting Errors**
- **Mitigation:** Conservative deletion, manual review
- **Fallback:** Manual correction procedures

### Dependencies

- Schema migration planning
- MinIO monitoring setup

### Success Metrics

- Orphaned artifact rate: < 0.1%
- Deduplication hit rate: > 20%
- Reference counting accuracy: 99.9%
- Storage overhead: < 5%

---

## Phase 36.5: Enhanced Concurrency Control

**Priority:** P1 (Major)  
**Duration:** 3-4 weeks  
**Addresses:** P1-003

### Problem Statement

Concurrency limits are enforced only at the task level, with no per-node or per-skill limits, risking resource exhaustion and system instability.

### Scope

1. Add per-node concurrency limits
2. Add per-skill concurrency limits
3. Implement resource-aware scheduling
4. Add backpressure mechanisms
5. Add comprehensive testing

### Files/Modules Affected

- `apps/orchestrator/scheduler/__init__.py` - Scheduler
- `apps/orchestrator/executor/engine.py` - Execution engine
- `apps/orchestrator/quota/__init__.py` - Quota service
- `infrastructure/postgres/init/016_concurrency.sql` - New schema

### Detailed Implementation Plan

#### Step 1: Per-Node Concurrency Limits (Week 1)

**Tasks:**
1. Design per-node concurrency schema
2. Implement concurrency tracking
3. Add concurrency checks to claim_running
4. Add concurrency monitoring
5. Add comprehensive testing

**Schema Changes:**
```sql
CREATE TABLE concurrency_limits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_type TEXT NOT NULL, -- 'task', 'node', 'skill', 'agent'
  scope_id TEXT NOT NULL,
  max_concurrent INT NOT NULL DEFAULT 10,
  current_concurrent INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (scope_type, scope_id)
);

CREATE INDEX idx_concurrency_limits_scope ON concurrency_limits(scope_type, scope_id);
```

**Implementation:**
```python
def claim_running(self, task_id, node_key, agent_id, attempt):
    # Check per-node concurrency
    if not self._check_node_concurrency(task_id):
        raise ConcurrencyLimitExceeded("Task concurrency limit reached")
    
    # Check per-skill concurrency
    if not self._check_skill_concurrency(skill):
        raise ConcurrencyLimitExceeded("Skill concurrency limit reached")
    
    # Proceed with claim
    # ...
```

**Testing:**
- Concurrency limit unit tests
- Claim blocking tests
- Concurrency monitoring tests

#### Step 2: Per-Skill Concurrency Limits (Week 1-2)

**Tasks:**
1. Design per-skill concurrency schema
2. Implement skill-level tracking
3. Add skill concurrency checks
4. Add skill concurrency monitoring
5. Add comprehensive testing

**Implementation:**
- Skill concurrency tracking in Redis
- Atomic increment/decrement operations
- Timeout-based concurrency release

**Testing:**
- Skill concurrency unit tests
- Atomic operation tests
- Timeout release tests

#### Step 3: Resource-Aware Scheduling (Week 2-3)

**Tasks:**
1. Design resource tracking schema
2. Implement resource usage tracking
3. Add resource-aware scheduling logic
4. Implement resource prioritization
5. Add comprehensive testing

**Schema Changes:**
```sql
CREATE TABLE resource_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  resource_type TEXT NOT NULL, -- 'cpu', 'memory', 'network'
  task_id UUID REFERENCES tasks(id),
  node_id UUID REFERENCES task_nodes(id),
  usage_value NUMERIC NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_resource_usage_task ON resource_usage(task_id);
```

**Implementation:**
- Resource usage estimation
- Resource-aware job queuing
- Resource prioritization logic

**Testing:**
- Resource tracking tests
- Scheduling logic tests
- Prioritization tests

#### Step 4: Backpressure Mechanisms (Week 3)

**Tasks:**
1. Design backpressure strategy
2. Implement queue length monitoring
3. Implement throttling logic
4. Add backpressure signaling
5. Add comprehensive testing

**Implementation:**
- Redis queue length monitoring
- Throttling based on queue depth
- Backpressure signals to Gateway
- Client-side rate limiting

**Testing:**
- Backpressure unit tests
- Throttling effectiveness tests
- Queue depth tests

#### Step 5: Comprehensive Testing (Week 3-4)

**Tasks:**
1. Per-node concurrency tests
2. Per-skill concurrency tests
3. Resource-aware scheduling tests
4. Backpressure mechanism tests
5. End-to-end concurrency tests

### Acceptance Criteria

- ✅ Per-node concurrency enforced
- ✅ Per-skill concurrency enforced
- ✅ Resource-aware scheduling implemented
- ✅ Backpressure prevents overload
- ✅ Tests verify concurrency correctness
- ✅ System stability under load

### Risks and Mitigations

**Risk 1: Concurrency Limit Too Restrictive**
- **Mitigation:** Tunable limits, monitoring
- **Fallback:** Administrative override

**Risk 2: Resource Tracking Overhead**
- **Mitigation:** Efficient tracking, batch updates
- **Fallback:** Disable resource tracking

**Risk 3: Backpressure False Positives**
- **Mitigation:** Tunable thresholds, monitoring
- **Fallback:** Manual override

### Dependencies

- Schema migration planning
- Resource monitoring setup

### Success Metrics

- Concurrency limit violations: 0
- Resource utilization: < 80%
- Backpressure effectiveness: > 95%
- System stability under 2x load

---

## Phase 36.6: Enhanced Observability and Monitoring

**Priority:** P2 (Observability)  
**Duration:** 3-4 weeks  
**Addresses:** P1-008, P2-003, P2-004, P2-006, P2-009

### Problem Statement

Current monitoring is insufficient for distributed state consistency, lacks comprehensive error classification, has no distributed tracing, and lacks SLO monitoring.

### Scope

1. Add distributed state metrics
2. Implement enhanced error classification
3. Add distributed tracing
4. Implement resource monitoring
5. Add SLO monitoring

### Files/Modules Affected

- `apps/orchestrator/observability/__init__.py` - Observability
- `apps/orchestrator/error_handling/__init__.py` - Error handling
- New `apps/orchestrator/tracing/__init__.py` - Tracing module
- New `apps/orchestrator/monitoring/__init__.py` - Monitoring module

### Detailed Implementation Plan

#### Step 1: Distributed State Metrics (Week 1)

**Tasks:**
1. Design state consistency metrics
2. Implement cross-system health checks
3. Add state anomaly detection
4. Add state reconciliation metrics
5. Add comprehensive testing

**Implementation:**
- PostgreSQL-Redis consistency metrics
- PostgreSQL-MinIO consistency metrics
- Task state distribution metrics
- Node state distribution metrics

**Testing:**
- Metrics collection tests
- Consistency check tests
- Anomaly detection tests

#### Step 2: Enhanced Error Classification (Week 1-2)

**Tasks:**
1. Expand error taxonomy
2. Implement context-rich classification
3. Add machine learning classification
4. Add failure analytics
5. Add comprehensive testing

**Implementation:**
- Enhanced error categories
- Context-aware classification
- Error pattern recognition
- Failure trend analysis

**Testing:**
- Classification accuracy tests
- Pattern recognition tests
- Analytics tests

#### Step 3: Distributed Tracing (Week 2)

**Tasks:**
1. Design tracing architecture
2. Implement span propagation
3. Add trace context to all components
4. Implement trace collection
5. Add trace visualization

**Implementation:**
- OpenTelemetry integration
- Trace context propagation
- Span creation for all operations
- Trace export to Jaeger/Tempo

**Testing:**
- Tracing integration tests
- Span propagation tests
- Trace collection tests

#### Step 4: Resource Monitoring (Week 2-3)

**Tasks:**
1. Design resource metrics
2. Implement resource usage tracking
3. Add resource exhaustion detection
4. Add resource alerting
5. Add comprehensive testing

**Implementation:**
- CPU, memory, network metrics
- PostgreSQL connection pool metrics
- Redis connection pool metrics
- MinIO storage metrics

**Testing:**
- Resource collection tests
- Exhaustion detection tests
- Alerting tests

#### Step 5: SLO Monitoring (Week 3)

**Tasks:**
1. Define SLOs for critical operations
2. Implement SLO tracking
3. Add SLO alerting
4. Implement SLO-based automation
5. Add SLO dashboards

**Implementation:**
- Task execution SLOs
- Agent response SLOs
- System availability SLOs
- Error budget tracking

**Testing:**
- SLO tracking tests
- Alerting tests
- Automation tests

#### Step 6: Comprehensive Testing (Week 3-4)

**Tasks:**
1. Distributed state metrics tests
2. Error classification tests
3. Distributed tracing tests
4. Resource monitoring tests
5. SLO monitoring tests

### Acceptance Criteria

- ✅ Distributed state metrics collected
- ✅ Errors accurately classified
- ✅ Distributed tracing implemented
- ✅ Resource monitoring operational
- ✅ SLO monitoring configured
- ✅ Performance overhead < 10%

### Risks and Mitigations

**Risk 1: Observability Overhead**
- **Mitigation:** Sampling, efficient collection
- **Fallback:** Reduce sampling rate

**Risk 2: Trace Volume**
- **Mitigation:** Sampling, retention policies
- **Fallback:** Disable tracing

**Risk 3: SLO False Positives**
- **Mitigation:** Tunable thresholds, monitoring
- **Fallback:** Manual override

### Dependencies

- Monitoring infrastructure setup
- Tracing infrastructure setup
- Alerting infrastructure setup

### Success Metrics

- State consistency check accuracy: > 99%
- Error classification accuracy: > 90%
- Trace collection rate: > 95%
- Resource monitoring coverage: 100%
- SLO alert accuracy: > 95%

---

## Phase 36.7: Comprehensive Testing Infrastructure

**Priority:** P2 (Maintainability)  
**Duration:** 4-5 weeks  
**Addresses:** P2-007

### Problem Statement

Current testing lacks chaos engineering, failure injection, stress testing, and end-to-end validation, limiting confidence in production reliability.

### Scope

1. Add chaos engineering tests
2. Implement failure injection
3. Add stress tests
4. Implement end-to-end tests
5. Add test automation

### Files/Modules Affected

- New `apps/orchestrator/tests/chaos/` - Chaos tests
- New `apps/orchestrator/tests/failure_injection/` - Failure injection tests
- New `apps/orchestrator/tests/stress/` - Stress tests
- New `apps/orchestrator/tests/e2e/` - End-to-end tests
- New `apps/orchestrator/tests/automation/` - Test automation

### Detailed Implementation Plan

#### Step 1: Chaos Engineering Tests (Week 1-2)

**Tasks:**
1. Design chaos test scenarios
2. Implement chaos test framework
3. Add random failure injection
4. Add chaos test automation
5. Add comprehensive testing

**Implementation:**
- Chaos Monkey integration
- Random process killing
- Network partition simulation
- Resource exhaustion simulation

**Testing:**
- Chaos test framework tests
- Failure injection tests
- Recovery tests

#### Step 2: Failure Injection Tests (Week 2)

**Tasks:**
1. Design failure injection scenarios
2. Implement fault injection framework
3. Add specific failure modes
4. Add failure injection automation
5. Add comprehensive testing

**Implementation:**
- PostgreSQL failure injection
- Redis failure injection
- MinIO failure injection
- Network failure injection

**Testing:**
- Failure injection framework tests
- Specific failure mode tests
- Recovery tests

#### Step 3: Stress Tests (Week 2-3)

**Tasks:**
1. Design stress test scenarios
2. Implement load generation
3. Add performance benchmarking
4. Add stress test automation
5. Add comprehensive testing

**Implementation:**
- High-volume task creation
- Concurrent Agent calls
- Large DAG execution
- Resource exhaustion tests

**Testing:**
- Load generation tests
- Performance benchmark tests
- Stability tests

#### Step 4: End-to-End Tests (Week 3-4)

**Tasks:**
1. Design E2E test scenarios
2. Implement real Agent integration
3. Add multi-component tests
4. Add E2E test automation
5. Add comprehensive testing

**Implementation:**
- Real Agent execution
- Multi-step workflows
- Cross-system validation
- User journey tests

**Testing:**
- E2E test framework tests
- Integration tests
- User journey tests

#### Step 5: Test Automation (Week 4)

**Tasks:**
1. Design test automation pipeline
2. Implement CI/CD integration
3. Add automated test scheduling
4. Add test result reporting
5. Add comprehensive testing

**Implementation:**
- GitHub Actions integration
- Automated test execution
- Test result collection
- Failure notification

**Testing:**
- Automation pipeline tests
- CI/CD integration tests
- Reporting tests

#### Step 6: Comprehensive Testing (Week 4-5)

**Tasks:**
1. Chaos engineering test suite
2. Failure injection test suite
3. Stress test suite
4. E2E test suite
5. Test automation validation

### Acceptance Criteria

- ✅ Chaos engineering tests automated
- ✅ Failure injection implemented
- ✅ Stress tests validate limits
- ✅ E2E tests cover critical paths
- ✅ Test automation operational
- ✅ Test execution time < 2 hours

### Risks and Mitigations

**Risk 1: Test Environment Complexity**
- **Mitigation:** Containerized test environment
- **Fallback:** Manual test execution

**Risk 2: Test Data Management**
- **Mitigation:** Test data isolation, cleanup
- **Fallback:** Manual data management

**Risk 3: Test Execution Time**
- **Mitigation:** Parallel execution, test selection
- **Fallback:** Reduced test scope

### Dependencies

- Test infrastructure setup
- CI/CD pipeline setup
- Test environment provisioning

### Success Metrics

- Test coverage: > 80% for critical paths
- Test execution success rate: > 95%
- Test execution time: < 2 hours
- Defect detection rate: > 70%

---

## Phase 36.8: Enhanced Recovery and Disaster Preparedness

**Priority:** P2 (Recoverability)  
**Duration:** 3-4 weeks  
**Addresses:** P2-001, P2-005, P2-008, P2-012

### Problem Statement

Current system lacks startup reconciliation, state consistency checks, backup verification, and disaster recovery procedures.

### Scope

1. Implement startup reconciliation
2. Add state consistency checks
3. Implement backup verification
4. Add disaster recovery procedures
5. Add comprehensive testing

### Files/Modules Affected

- `apps/orchestrator/main.py` - Startup logic
- New `apps/orchestrator/reconciliation/__init__.py` - Reconciliation module
- New `apps/orchestrator/backup/` - Backup module
- New `apps/orchestrator/dr/` - Disaster recovery module

### Detailed Implementation Plan

#### Step 1: Startup Reconciliation (Week 1)

**Tasks:**
1. Design startup reconciliation logic
2. Implement state consistency checks
3. Add orphan detection
4. Add automated correction
5. Add comprehensive testing

**Implementation:**
```python
def startup_reconciliation():
    # Check for orphaned tasks
    orphaned_tasks = find_orphaned_tasks()
    for task in orphaned_tasks:
        reconcile_task(task)
    
    # Check for stale nodes
    stale_nodes = find_stale_nodes()
    for node in stale_nodes:
        reconcile_node(node)
    
    # Check for inconsistent state
    inconsistent = find_inconsistent_state()
    for item in inconsistent:
        reconcile_state(item)
```

**Testing:**
- Startup reconciliation tests
- Orphan detection tests
- Correction logic tests

#### Step 2: State Consistency Checks (Week 1-2)

**Tasks:**
1. Design consistency check logic
2. Implement cross-system checks
3. Add consistency monitoring
4. Add automated correction
5. Add comprehensive testing

**Implementation:**
- PostgreSQL-Redis consistency
- PostgreSQL-MinIO consistency
- Task-node consistency
- Event consistency

**Testing:**
- Consistency check tests
- Cross-system tests
- Correction tests

#### Step 3: Backup Verification (Week 2)

**Tasks:**
1. Design backup verification logic
2. Implement backup integrity checks
3. Add restore testing
4. Add backup monitoring
5. Add comprehensive testing

**Implementation:**
- Backup integrity verification
- Restore procedure testing
- Backup monitoring and alerting
- RPO/RTO validation

**Testing:**
- Backup verification tests
- Restore tests
- Monitoring tests

#### Step 4: Disaster Recovery Procedures (Week 2-3)

**Tasks:**
1. Design DR procedures
2. Implement failover automation
3. Add DR testing
4. Add DR documentation
5. Add DR monitoring

**Implementation:**
- Failover procedures
- Data recovery procedures
- Service recovery procedures
- DR runbooks

**Testing:**
- Failover tests
- Recovery tests
- Procedure validation tests

#### Step 5: Comprehensive Testing (Week 3-4)

**Tasks:**
1. Startup reconciliation tests
2. State consistency check tests
3. Backup verification tests
4. DR procedure tests
5. End-to-end recovery tests

### Acceptance Criteria

- ✅ Startup reconciliation operational
- ✅ State consistency checks automated
- ✅ Backup verification automated
- ✅ DR procedures tested
- ✅ Recovery time < 30 minutes
- ✅ Data loss risk: < 1%

### Risks and Mitigations

**Risk 1: Startup Time Increase**
- **Mitigation:** Optimized reconciliation, parallel checks
- **Fallback:** Skip non-critical checks

**Risk 2: Correction Errors**
- **Mitigation:** Conservative correction, manual review
- **Fallback:** Manual correction procedures

**Risk 3: Backup Verification Time**
- **Mitigation:** Incremental verification, sampling
- **Fallback:** Reduced verification frequency

### Dependencies

- Backup infrastructure setup
- DR infrastructure setup
- Monitoring infrastructure setup

### Success Metrics

- Startup reconciliation success rate: > 99%
- State consistency check accuracy: > 99%
- Backup verification success rate: > 99%
- DR procedure success rate: > 95%
- Recovery time: < 30 minutes

---

## Timeline Summary

### Critical Path (Sequential)

```
P36.1 (3-4 weeks) → P36.2 (4-5 weeks) → P36.3 (2-3 weeks) → P36.4 (2-3 weeks) → P36.5 (3-4 weeks)
```

**Total Critical Path:** 14-19 weeks

### Parallel Tracks (After P36.1)

```
P36.6 (3-4 weeks) ───┐
P36.7 (4-5 weeks) ───┤──→ Can run in parallel
P36.8 (3-4 weeks) ───┘
```

**Total Parallel Tracks:** 10-13 weeks

### Overall Timeline

**Minimum Duration:** 24 weeks (6 months)  
**Maximum Duration:** 32 weeks (8 months)  
**Recommended Duration:** 28 weeks (7 months)

---

## Resource Requirements

### Development Team

- **Backend Engineers:** 2-3 full-time
- **DevOps Engineer:** 1 part-time
- **QA Engineer:** 1 part-time
- **Database Administrator:** 1 part-time (for schema migrations)

### Infrastructure

- **Staging Environment:** Full production replica
- **Testing Environment:** Chaos engineering capability
- **Monitoring Stack:** Prometheus, Grafana, Jaeger/Tempo
- **Backup Infrastructure:** Automated backups with verification

### Tools and Services

- **A2A Protocol Tools:** Protocol validation, SDK testing
- **Testing Tools:** Chaos Monkey, failure injection frameworks
- **Monitoring Tools:** Distributed tracing, resource monitoring
- **CI/CD:** GitHub Actions or equivalent

---

## Success Criteria

### Phase 36 Completion Criteria

- ✅ All P0 findings addressed
- ✅ All P1 findings addressed
- ✅ Critical reliability risks mitigated
- ✅ Comprehensive testing in place
- ✅ Production-ready monitoring
- ✅ Documented recovery procedures

### Reliability Targets

- **System Availability:** > 99.9%
- **Task Success Rate:** > 99%
- **Data Consistency:** > 99.9%
- **Recovery Time:** < 30 minutes
- **Data Loss Risk:** < 1%

### Operational Readiness

- ✅ Runbooks documented
- ✅ On-call procedures established
- ✅ Monitoring dashboards operational
- ✅ Alerting configured
- ✅ DR procedures tested

---

## Conclusion

This roadmap provides a structured approach to addressing the reliability gaps identified in the Phase 36.0 audit. By prioritizing critical risks (P0 findings) and building a foundation for comprehensive reliability improvements, the AOP platform can achieve production-grade reliability suitable for real-world multi-Agent DAG task execution.

The recommended starting point is **P36.1: Idempotency Keys and Exactly-Once Execution**, as it addresses the most critical reliability risks and provides the foundation for subsequent improvements.

---

**Roadmap End**

This roadmap is based on the findings documented in `p36-0-reliability-audit.md` and should be executed in sequence, with each phase building on the completion of previous phases.
