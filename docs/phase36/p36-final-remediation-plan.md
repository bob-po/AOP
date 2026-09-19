# Phase 36 Final Remediation Plan

**Plan Date:** 2026-09-19  
**Based On:** Phase 36 Final Reliability Audit  
**Objective:** Fix critical reliability issues and enable P36 guarantees

---

## Issue Summary

### P0 Issues (6) - CRITICAL
1. **P0-001:** Database migrations not applied - tables missing
2. **P0-002:** Idempotency key regenerated per execution (not per retry)
3. **P0-003:** No concurrent worker deduplication protection
4. **P0-004:** Request tracking non-functional (table missing)
5. **P0-005:** Outbox pattern non-functional (table missing)
6. **P0-006:** Enhanced artifacts non-functional (table missing)

### P1 Issues (8) - HIGH
1. **P1-001:** No worker lease/heartbeat mechanism
2. **P1-002:** No stable idempotency key across retries
3. **P1-003:** Request tracking ON CONFLICT handling incomplete
4. **P1-004:** No evidence of DAG duplicate progression protection
5. **P1-005:** Failover regenerates idempotency key
6. **P1-006:** No unknown result state handling
7. **P1-007:** No legacy agent compatibility tests
8. **P1-008:** No execution attempt independent tracking

### P2 Issues (5) - MEDIUM
1. **P2-001:** Chaos engineering tests not executed
2. **P2-002:** No stress test execution evidence
3. **P2-003:** No failure injection test execution
4. **P2-004:** No startup reconciliation tests
5. **P2-005:** No artifact consistency tests

---

## Remediation Plan

### Priority 1: Apply Database Migrations (P0-001, P0-004, P0-005, P0-006)

**Issue ID:** RM-001  
**Severity:** P0  
**Root Cause:** Migrations created but not applied to database

**Affected Modules:**
- Database schema
- All P36 features that depend on new tables

**Fix Strategy:**
1. Apply migration 013_request_tracking.sql
2. Apply migration 014_outbox.sql
3. Apply migration 015_enhanced_artifacts.sql
4. Verify table creation with SELECT queries

**Files to Modify:**
- None (run existing migrate.py)

**Commands:**
```bash
cd infrastructure/postgres
python migrate.py --apply 013_request_tracking.sql
python migrate.py --apply 014_outbox.sql
python migrate.py --apply 015_enhanced_artifacts.sql
python migrate.py --status
```

**Dependencies:** None (standalone operation)

**Test Strategy:**
```sql
-- Verify tables exist
SELECT table_name FROM information_schema.tables 
WHERE table_name IN ('a2a_requests', 'outbox_events');

-- Verify indexes
SELECT indexname FROM pg_indexes 
WHERE tablename IN ('a2a_requests', 'outbox_events', 'artifacts');
```

**Rollback Plan:**
```sql
DROP TABLE IF EXISTS a2a_requests CASCADE;
DROP TABLE IF EXISTS outbox_events CASCADE;
-- Revert artifact changes
ALTER TABLE artifacts DROP COLUMN IF EXISTS status;
ALTER TABLE artifacts DROP COLUMN IF EXISTS reference_count;
ALTER TABLE artifacts DROP COLUMN IF EXISTS updated_at;
```

---

### Priority 2: Fix Idempotency Key Generation (P0-002, P1-002)

**Issue ID:** RM-002  
**Severity:** P0  
**Root Cause:** Idempotency key generated per execution instead of per node retry

**Affected Modules:**
- `apps/orchestrator/executor/engine.py`
- `apps/orchestrator/scheduler/__init__.py`

**Current Problem:**
```python
# apps/orchestrator/executor/engine.py:246
idempotency_key = f"req_{uuid.uuid4().hex}"  # New UUID every time
```

**Fix Strategy:**
1. Generate stable idempotency key from (task_id, node_key)
2. Store idempotency key in task_nodes table
3. Use stored key for all retries
4. Generate new key only for new node executions

**Files to Modify:**
- `apps/orchestrator/executor/engine.py`
- `apps/orchestrator/scheduler/__init__.py`
- `infrastructure/postgres/init/016_node_idempotency.sql` (new migration)

**Implementation:**
```python
# Add idempotency_key column to task_nodes
# Generate key as: f"req_{task_id[:8]}_{node_key}"
# Store in task_nodes when node created
# Retrieve from task_nodes for retries
```

**Dependencies:** Requires database migration

**Test Strategy:**
1. Test same node with multiple retries uses same key
2. Test different nodes use different keys
3. Test concurrent workers with same key

**Rollback Plan:**
Revert idempotency key column addition, use old generation logic

---

### Priority 3: Add Concurrent Worker Deduplication (P0-003)

**Issue ID:** RM-003  
**Severity:** P0  
**Root Cause:** No distributed lock before idempotency key generation

**Affected Modules:**
- `apps/orchestrator/executor/engine.py`
- `apps/orchestrator/scheduler/__init__.py`

**Current Problem:**
```python
# apps/orchestrator/executor/engine.py:239-246
claimed = self.scheduler.claim_running(task_id, node_key, routed.agent_id, attempt)
# ... happens AFTER idempotency key generation
idempotency_key = f"req_{uuid.uuid4().hex}"
```

**Fix Strategy:**
1. Move claim_running BEFORE idempotency key generation
2. Add SELECT FOR UPDATE SKIP LOCKED to claim_running
3. Ensure atomic claim + key generation
4. Handle claim failure gracefully

**Files to Modify:**
- `apps/orchestrator/executor/engine.py`
- `apps/orchestrator/scheduler/__init__.py`

**Implementation:**
```python
# Move claim before key generation
claimed = self.scheduler.claim_running_with_lock(task_id, node_key, routed.agent_id, attempt)
if not claimed:
    return  # Skip, another worker won the race
# Now safe to use or generate idempotency key
idempotency_key = self.scheduler.get_or_generate_idempotency_key(task_id, node_key)
```

**Dependencies:** Requires RM-002 (stable idempotency key)

**Test Strategy:**
1. Simulate concurrent workers with same node
2. Verify only one worker executes
3. Verify idempotency key is consistent

**Rollback Plan:**
Revert claim_running changes, use old order

---

### Priority 4: Fix Request Tracking ON CONFLICT Handling (P1-003)

**Issue ID:** RM-004  
**Severity:** P1  
**Root Cause:** ON CONFLICT DO NOTHING returns NULL, not existing request

**Affected Modules:**
- `apps/orchestrator/request_tracking/__init__.py`

**Current Problem:**
```python
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING id::text  # Returns NULL on conflict
```

**Fix Strategy:**
1. Change DO NOTHING to DO UPDATE SET updated_at = now()
2. Always return the existing or new record
3. Handle both INSERT and UPDATE cases

**Files to Modify:**
- `apps/orchestrator/request_tracking/__init__.py`

**Implementation:**
```python
INSERT INTO a2a_requests (...) VALUES (...)
ON CONFLICT (idempotency_key) 
DO UPDATE SET updated_at = now()
RETURNING id::text, status, response_json
```

**Dependencies:** Requires RM-001 (database migration)

**Test Strategy:**
1. Test duplicate request returns existing
2. Test status is preserved
3. Test response_json is preserved

**Rollback Plan:**
Revert to DO NOTHING behavior

---

### Priority 5: Add Unknown Result State (P1-006)

**Issue ID:** RM-005  
**Severity:** P1  
**Root Cause:** No explicit unknown/indeterminate state for timed-out Agent calls

**Affected Modules:**
- `apps/orchestrator/request_tracking/__init__.py`
- `apps/orchestrator/executor/engine.py`

**Fix Strategy:**
1. Add 'unknown' status to a2a_requests
2. Mark requests as unknown on timeout
3. Implement status resolution logic
4. Don't retry 'unknown' without explicit check

**Files to Modify:**
- `apps/orchestrator/request_tracking/__init__.py`
- `infrastructure/postgres/init/017_unknown_status.sql` (new migration)

**Dependencies:** Requires RM-001 (database migration)

**Test Strategy:**
1. Test timeout marks request as unknown
2. Test unknown status resolution
3. Test unknown prevents duplicate execution

**Rollback Plan:**
Remove unknown status, use failed instead

---

### Priority 6: Add Worker Lease/Heartbeat (P1-001)

**Issue ID:** RM-006  
**Severity:** P1  
**Root Cause:** No worker lease or heartbeat mechanism

**Affected Modules:**
- `apps/orchestrator/executor/engine.py`
- `apps/orchestrator/scheduler/__init__.py`

**Fix Strategy:**
1. Add worker_lease table to track active workers
2. Implement heartbeat mechanism
3. Expire stale leases
4. Fail if lease expired during execution

**Files to Modify:**
- `apps/orchestrator/executor/engine.py`
- `apps/orchestrator/scheduler/__init__.py`
- `infrastructure/postgres/init/018_worker_leases.sql` (new migration)

**Dependencies:** Requires database migration

**Test Strategy:**
1. Test worker lease acquisition
2. Test heartbeat refresh
3. Test lease expiration
4. Test stale worker rejection

**Rollback Plan:**
Drop worker_lease table, disable lease checks

---

### Priority 7: Add Critical Tests (P2-001 to P2-005)

**Issue ID:** RM-007  
**Severity:** P2  
**Root Cause:** Tests exist but not executed or are blocked

**Affected Modules:**
- `apps/orchestrator/tests/`

**Fix Strategy:**
1. Apply database migrations to unblock tests
2. Run existing request tracking tests
3. Run existing executor idempotency tests
4. Add concurrent worker test
5. Add worker crash recovery test
6. Add timeout handling test

**Files to Modify:**
- `apps/orchestrator/tests/test_request_tracking.py` (modify if needed)
- `apps/orchestrator/tests/test_executor_idempotency.py` (modify if needed)
- `apps/orchestrator/tests/test_concurrent_workers.py` (new)
- `apps/orchestrator/tests/test_worker_recovery.py` (new)

**Dependencies:** Requires RM-001 (database migration)

**Test Strategy:**
1. Run pytest with database connection
2. Verify all tests pass
3. Add to CI/CD pipeline

**Rollback Plan:**
N/A (tests only)

---

## Implementation Order

### Phase 1: Database Foundation (Blocking)
1. RM-001: Apply database migrations
2. RM-007: Unblock and run existing tests

### Phase 2: Core Idempotency (P0)
3. RM-002: Fix idempotency key generation
4. RM-003: Add concurrent worker deduplication
5. RM-004: Fix ON CONFLICT handling

### Phase 3: Enhanced Reliability (P1)
6. RM-005: Add unknown result state
7. RM-006: Add worker lease/heartbeat

### Phase 4: Testing Validation (P2)
8. RM-007: Add and execute critical tests

---

## Estimated Effort

| Phase | Effort | Risk | Dependencies |
|-------|--------|------|--------------|
| Phase 1 | 1 day | Low | None |
| Phase 2 | 2-3 days | Medium | Phase 1 |
| Phase 3 | 2-3 days | Medium | Phase 1, 2 |
| Phase 4 | 2-3 days | Low | Phase 1, 2, 3 |

**Total:** 7-10 days

---

## Success Criteria

### Phase 1 Success
- ✅ All P36 migrations applied
- ✅ Tables exist and have correct schema
- ✅ Existing tests can run

### Phase 2 Success
- ✅ Idempotency key stable per node retry
- ✅ Concurrent workers protected
- ✅ Request tracking handles conflicts

### Phase 3 Success
- ✅ Unknown result state implemented
- ✅ Worker lease mechanism functional
- ✅ Heartbeat refreshing works

### Phase 4 Success
- ✅ All critical tests pass
- ✅ Concurrent worker test passes
- ✅ Worker recovery test passes

---

## Risk Assessment

### High Risk
- **RM-002:** Changing idempotency key generation could break existing workflows
- **RM-003:** Adding locks could introduce performance bottlenecks

### Medium Risk
- **RM-006:** Worker lease adds complexity and failure modes
- **RM-005:** Unknown state may confuse existing logic

### Low Risk
- **RM-001:** Database migration (well-tested migration utility)
- **RM-004:** SQL change (simple)
- **RM-007:** Tests only

---

## Rollback Strategy

If any P0 fix causes issues:
1. Rollback database changes using migration backup
2. Revert code changes to commit c0a89d2
3. System returns to pre-P36 state (functional but without P36 guarantees)

---

## Next Steps

1. **Immediate:** Apply database migrations (RM-001)
2. **Today:** Run existing tests (RM-007)
3. **This Week:** Fix idempotency key generation (RM-002)
4. **This Week:** Add concurrent worker protection (RM-003)
5. **Next Week:** Implement remaining P1 fixes

---

**End of Phase 36 Final Remediation Plan**
