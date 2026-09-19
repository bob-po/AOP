# Phase 36 Production Deployment Guide

**Version:** 1.0  
**Date:** 2026-09-19  
**Scope:** P36.1, P36.2, P36.3, P36.5  
**Risk Level:** **MEDIUM**  
**Estimated Downtime:** 0 minutes (rolling deployment)

---

## Executive Summary

This guide provides step-by-step instructions for deploying Phase 36 core reliability features to production. The deployment includes:

- **P36.1:** Request tracking and idempotency
- **P36.2:** Outbox pattern for distributed transactions
- **P36.3:** Enhanced failure handling
- **P36.5:** Failover with idempotency

**Risk Assessment:** MEDIUM
- Database schema changes (backwards compatible)
- New code paths with fallbacks
- No breaking changes to existing APIs
- Zero-downtime rolling deployment

---

## Pre-Deployment Checklist

### Infrastructure Requirements
- [ ] PostgreSQL database accessible
- [ ] Redis available for outbox processing
- [ ] At least one Agent instance running
- [ ] MinIO/S3 for artifact storage
- [ ] Monitoring and alerting configured

### Database Preparation
- [ ] Take database backup
- [ ] Verify database connection
- [ ] Verify sufficient disk space
- [ ] Verify current migration status

### Application Preparation
- [ ] All code changes committed
- [ ] Tests passing (10/10 core tests)
- [ ] Documentation updated
- [ ] Rollback plan prepared

### Monitoring Preparation
- [ ] Set up request tracking metrics
- [ ] Set up outbox event backlog alerts
- [ ] Set up unknown status alerts
- [ ] Set up enhanced failure handling logs

---

## Deployment Steps

### Step 1: Database Backup

```bash
# Create database backup
pg_dump -h localhost -U aop -d aop > aop_backup_$(date +%Y%m%d_%H%M%S).sql

# Verify backup
ls -lh aop_backup_*.sql
```

### Step 2: Verify Current Migration Status

```bash
cd infrastructure/postgres
python migrate.py --status
```

Expected output:
```
000_schema_migrations applied
...
012_tenant_egress applied
013_request_tracking pending
014_outbox pending
015_enhanced_artifacts pending
016_node_idempotency pending
017_unknown_status pending
```

### Step 3: Apply Database Migrations

```bash
cd infrastructure/postgres
python migrate.py
```

Expected output:
```
apply 013_request_tracking (013_request_tracking.sql)
apply 014_outbox (014_outbox.sql)
apply 015_enhanced_artifacts (015_enhanced_artifacts.sql)
apply 016_node_idempotency (016_node_idempotency.sql)
apply 017_unknown_status (017_unknown_status.sql)
applied 5 migration(s)
```

### Step 4: Verify Migration Success

```bash
cd infrastructure/postgres
python migrate.py --status
```

Expected output:
```
...
013_request_tracking applied
014_outbox applied
015_enhanced_artifacts applied
016_node_idempotency applied
017_unknown_status applied
```

### Step 5: Deploy Application Code

#### Option A: Docker Compose

```bash
# Stop current services
docker-compose down

# Pull new code
git pull origin main

# Build new images
docker-compose build

# Start services
docker-compose up -d

# Verify health
docker-compose ps
```

#### Option B: Kubernetes

```bash
# Update deployment
kubectl set image deployment/orchestrator orchestrator=<new-image-tag>
kubectl set image deployment/worker worker=<new-image-tag>

# Rollout status
kubectl rollout status deployment/orchestrator
kubectl rollout status deployment/worker
```

#### Option C: Direct Deployment

```bash
# Stop services
systemctl stop aop-orchestrator
systemctl stop aop-worker

# Update code
git pull origin main

# Install dependencies
pip install -r requirements.txt

# Start services
systemctl start aop-orchestrator
systemctl start aop-worker

# Verify status
systemctl status aop-orchestrator
systemctl status aop-worker
```

### Step 6: Verify Deployment

#### Check Application Logs

```bash
# Orchestrator logs
docker-compose logs orchestrator | tail -100

# Worker logs
docker-compose logs worker | tail -100
```

Expected logs:
```
[orchestrator] Request tracking service initialized
[orchestrator] Outbox processor initialized
[orchestrator] Enhanced failure handling initialized
[worker] Using stable idempotency keys
[worker] Unknown result state handling enabled
```

#### Check Database Tables

```bash
# Connect to PostgreSQL
psql -h localhost -U aop -d aop

# Verify tables exist
\dt a2a_requests
\dt outbox_events

# Verify columns
\d task_nodes
```

Expected output:
```
 a2a_requests           | table
 outbox_events          | table

 Column            | Type
-------------------+--------
 idempotency_key   | text
```

#### Check Request Tracking

```sql
-- Verify a2a_requests table structure
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'a2a_requests';
```

### Step 7: Start Outbox Processor (if not auto-started)

The outbox processor should start automatically with the orchestrator. If manual startup is required:

```bash
# Start outbox processor
python -m orchestrator.outbox_processor_service
```

### Step 8: Run Smoke Tests

```bash
cd apps/orchestrator
python -m pytest tests/test_request_tracking_simple.py -v
python -m pytest tests/test_stable_idempotency.py -v
```

Expected output:
```
10 passed in 0.XXs
```

---

## Post-Deployment Verification

### Health Checks

#### 1. Application Health
```bash
curl http://localhost:8090/health
```

Expected: `{"status": "healthy"}`

#### 2. Database Connectivity
```bash
curl http://localhost:8090/api/health/database
```

Expected: `{"status": "connected"}`

#### 3. Redis Connectivity
```bash
curl http://localhost:8090/api/health/redis
```

Expected: `{"status": "connected"}`

### Functional Tests

#### 1. Create a Test Task
```bash
curl -X POST http://localhost:8090/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "test goal",
    "plan": {
      "title": "Test Plan",
      "nodes": [
        {
          "id": "node1",
          "skill": "web-search",
          "depends_on": []
        }
      ]
    }
  }'
```

#### 2. Verify Request Tracking
```sql
-- Check if request was tracked
SELECT * FROM a2a_requests ORDER BY created_at DESC LIMIT 5;
```

#### 3. Verify Outbox Events
```sql
-- Check if outbox events were written
SELECT * FROM outbox_events ORDER BY created_at DESC LIMIT 5;
```

---

## Monitoring

### Key Metrics to Monitor

#### Request Tracking Metrics
- Total requests tracked
- Duplicate requests detected
- Cached responses returned
- Request tracking errors

#### Outbox Metrics
- Outbox event rate
- Outbox backlog size
- Outbox processing lag
- Outbox delivery success rate

#### Enhanced Failure Handling Metrics
- Error classification counts
- Recovery strategy distribution
- Circuit breaker state changes
- Unknown result occurrences

### Alerts to Configure

#### Critical Alerts
- Request tracking service down
- Outbox backlog > 1000 events
- Outbox processing lag > 60 seconds
- Database connection failures

#### Warning Alerts
- Unknown result status rate > 5%
- Duplicate request rate > 1%
- Circuit breaker open rate > 10%
- Enhanced failure handling errors

### Dashboard Setup

Create monitoring dashboards for:
1. Request tracking overview
2. Outbox processing status
3. Enhanced failure handling summary
4. Overall system health

---

## Rollback Plan

### Immediate Rollback (Critical Issues)

If critical issues are detected:

1. **Stop Application**
   ```bash
   docker-compose down
   # or
   systemctl stop aop-orchestrator
   systemctl stop aop-worker
   ```

2. **Revert Code**
   ```bash
   git checkout <previous-commit>
   ```

3. **Rollback Migrations**
   ```bash
   # Manual rollback script
   psql -h localhost -U aop -d aop -f rollback_013_017.sql
   ```

4. **Restart Application**
   ```bash
   docker-compose up -d
   # or
   systemctl start aop-orchestrator
   systemctl start aop-worker
   ```

### Graceful Rollback (Non-Critical Issues)

If non-critical issues are detected:

1. **Disable New Features**
   ```bash
   # Set environment variables to disable features
   export REQUEST_TRACKING_ENABLED=false
   export OUTBOX_PROCESSING_ENABLED=false
   export ENHANCED_FAILURE_HANDLING_ENABLED=false
   ```

2. **Restart Application**
   ```bash
   docker-compose restart
   ```

---

## Troubleshooting

### Issue: Migration Fails

**Symptoms:** Migration error during Step 3

**Solutions:**
1. Check database connectivity
2. Verify sufficient permissions
3. Check for conflicting schema changes
4. Review migration logs

### Issue: Outbox Processor Not Starting

**Symptoms:** Outbox events not being processed

**Solutions:**
1. Check Redis connectivity
2. Verify outbox processor configuration
3. Check outbox processor logs
4. Manually start outbox processor

### Issue: High Unknown Result Rate

**Symptoms:** Many requests marked as 'unknown'

**Solutions:**
1. Check Agent timeout settings
2. Verify network connectivity
3. Review timeout error logs
4. Adjust timeout thresholds

### Issue: Duplicate Request Rate High

**Symptoms:** High duplicate request detection rate

**Solutions:**
1. Check idempotency key generation
2. Verify claim_running logic
3. Review concurrent worker behavior
4. Check for message redelivery issues

---

## Performance Considerations

### Expected Performance Impact

- **Request Tracking:** +2-5ms per request
- **Outbox Processing:** +1-3ms per event
- **Enhanced Failure Handling:** +1-2ms per failure
- **Overall Impact:** +5-10ms per operation

### Scaling Recommendations

- **Request Tracking:** Scale database if request rate > 1000/sec
- **Outbox Processing:** Scale processor if event rate > 500/sec
- **Enhanced Failure Handling:** Scale workers if failure rate > 100/sec

---

## Security Considerations

### Database Security
- Ensure database credentials are secured
- Use SSL/TLS for database connections
- Limit database user permissions
- Regularly rotate database credentials

### Application Security
- Secure outbox event payloads
- Sanitize error messages before logging
- Limit access to request tracking data
- Monitor for unauthorized access attempts

---

## Documentation Updates

After deployment, update:

1. [ ] API documentation with new endpoints
2. [ ] Operational runbooks
3. [ ] Monitoring dashboards
4. [ ] Troubleshooting guides
5. [ ] Team training materials

---

## Support Contacts

- **Primary:** DevOps Team
- **Secondary:** Database Team
- **Escalation:** Engineering Lead

---

## Appendix A: Migration SQL

### Migration 013 - Request Tracking
```sql
-- See infrastructure/postgres/init/013_request_tracking.sql
```

### Migration 014 - Outbox
```sql
-- See infrastructure/postgres/init/014_outbox.sql
```

### Migration 015 - Enhanced Artifacts
```sql
-- See infrastructure/postgres/init/015_enhanced_artifacts.sql
```

### Migration 016 - Node Idempotency
```sql
-- See infrastructure/postgres/init/016_node_idempotency.sql
```

### Migration 017 - Unknown Status
```sql
-- See infrastructure/postgres/init/017_unknown_status.sql
```

---

## Appendix B: Rollback SQL

```sql
-- Rollback Migration 017
ALTER TABLE a2a_requests DROP CONSTRAINT IF EXISTS a2a_requests_status_check;
ALTER TABLE a2a_requests ADD CONSTRAINT a2a_requests_status_check 
  CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'));

-- Rollback Migration 016
ALTER TABLE task_nodes DROP COLUMN IF EXISTS idempotency_key;
DROP INDEX IF EXISTS idx_task_nodes_idempotency_key;

-- Rollback Migration 015
-- Manual review required based on actual changes

-- Rollback Migration 014
DROP TABLE IF EXISTS outbox_events;

-- Rollback Migration 013
DROP TABLE IF EXISTS a2a_requests;
```

---

**End of Phase 36 Production Deployment Guide**
