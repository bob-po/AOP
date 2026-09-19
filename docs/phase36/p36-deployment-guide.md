# Phase 36 Deployment and Operations Guide

**Version:** 1.0  
**Date:** 2026-09-19  
**Purpose:** Guide for deploying and operating Phase 36 reliability enhancements

---

## Table of Contents

1. [Pre-Deployment Checklist](#pre-deployment-checklist)
2. [Database Migration](#database-migration)
3. [Service Deployment](#service-deployment)
4. [Configuration](#configuration)
5. [Monitoring Setup](#monitoring-setup)
6. [Testing and Validation](#testing-and-validation)
7. [Rollback Procedures](#rollback-procedures)
8. [Operational Procedures](#operational-procedures)
9. [Troubleshooting](#troubleshooting)

---

## Pre-Deployment Checklist

### Environment Preparation
- [ ] PostgreSQL database is accessible
- [ ] Redis is accessible
- [ ] MinIO/S3 is accessible
- [ ] All agents are running
- [ ] Orchestrator is running
- [ ] Gateway is running
- [ ] Backup of current database is taken
- [ ] Deployment window is scheduled
- [ ] Operations team is notified
- [ ] Monitoring dashboards are prepared

### Dependency Verification
- [ ] Python 3.11+ is installed
- [ ] Required Python packages are installed
- [ ] PostgreSQL client libraries are installed
- [ ] Redis client libraries are installed
- [ ] Network connectivity between components is verified

### Resource Verification
- [ ] Sufficient database storage for new tables
- [ ] Sufficient Redis memory for outbox pattern
- [ ] Sufficient disk space for artifact storage
- [ ] CPU capacity for additional background services
- [ ] Memory capacity for enhanced monitoring

---

## Database Migration

### Step 1: Backup Current Database

```bash
# Backup current database
pg_dump -h localhost -U aop -d aop > backup_before_p36_$(date +%Y%m%d).sql

# Verify backup
pg_restore --list backup_before_p36_$(date +%Y%m%d).sql
```

### Step 2: Apply Migrations in Order

```bash
cd infrastructure/postgres

# Check current migration status
python migrate.py --status

# Apply P36.1 migration (request tracking)
python migrate.py --apply 013_request_tracking.sql

# Apply P36.2 migration (outbox pattern)
python migrate.py --apply 014_outbox.sql

# Apply P36.4 migration (enhanced artifacts)
python migrate.py --apply 015_enhanced_artifacts.sql

# Verify all migrations applied
python migrate.py --status
```

### Step 3: Verify Migration Success

```sql
-- Verify a2a_requests table
SELECT COUNT(*) FROM a2a_requests;

-- Verify outbox_events table
SELECT COUNT(*) FROM outbox_events;

-- Verify artifact table enhancements
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'artifacts' 
  AND column_name IN ('status', 'reference_count', 'updated_at');
```

### Step 4: Create Indexes (if not auto-created)

```sql
-- Check if indexes exist
SELECT indexname FROM pg_indexes WHERE tablename = 'a2a_requests';
SELECT indexname FROM pg_indexes WHERE tablename = 'outbox_events';
SELECT indexname FROM pg_indexes WHERE tablename = 'artifacts';
```

---

## Service Deployment

### Step 1: Deploy Orchestrator Updates

```bash
# Stop current orchestrator
pkill -f "python.*orchestrator"

# Deploy updated code
# (Use your deployment process - git pull, docker build, etc.)

# Start orchestrator with P36.1 enabled
export P36_IDEMPOTENCY_ENABLED=true
python apps/orchestrator/main.py
```

### Step 2: Start Outbox Processor Service

```bash
# Start outbox processor as background service
nohup python apps/orchestrator/outbox_processor_service.py \
  > logs/outbox_processor.log 2>&1 &

# Verify it's running
ps aux | grep outbox_processor

# Check logs
tail -f logs/outbox_processor.log
```

### Step 3: Deploy Agent Updates

```bash
# All agents have been updated with idempotency
# Deploy each agent (example for search-agent)

cd agents/search-agent
docker build -t aop/search-agent:p36 .
docker stop search-agent
docker rm search-agent
docker run -d --name search-agent \
  -p 8001:8001 \
  -e AGENT_URL=http://localhost:8001/ \
  aop/search-agent:p36

# Repeat for all 8 agents
```

### Step 4: Verify Services

```bash
# Check orchestrator health
curl http://localhost:8090/health

# Check outbox processor
ps aux | grep outbox_processor

# Check all agents
for port in 8001 8002 8003 8004 8005 8006 8007 8008; do
  curl http://localhost:$port/health
done
```

---

## Configuration

### Environment Variables

#### Required (No new variables required)
```bash
# Existing variables still work
DATABASE_URL=postgresql://aop:aop@127.0.0.1:5432/aop
REDIS_URL=redis://localhost:6379
MINIO_ENDPOINT=http://localhost:9000
```

#### Optional (Feature flags)
```bash
# Enable/disable specific P36 features
P36_IDEMPOTENCY_ENABLED=true
P36_OUTBOX_ENABLED=true
P36_FAILURE_HANDLING_ENABLED=true
P36_CONCURRENCY_CONTROL_ENABLED=true
P36_OBSERVABILITY_ENABLED=true
P36_STARTUP_RECONCILIATION_ENABLED=true
```

#### Outbox Processor Configuration
```bash
# Outbox processor tuning
OUTBOX_POLL_INTERVAL=1.0      # Seconds between polls
OUTBOX_BATCH_SIZE=100         # Events per batch
OUTBOX_CLEANUP_DAYS=7         # Days to keep processed events
```

#### Concurrency Control Configuration
```bash
# Concurrency limits
CONCURRENCY_PER_NODE=1
CONCURRENCY_PER_SKILL=10
CONCURRENCY_PER_TASK=5
CONCURRENCY_GLOBAL=100
```

#### SLO Monitoring Configuration
```bash
# SLO thresholds
SLO_SUCCESS_RATE_THRESHOLD=0.95
SLO_FAILURE_RATE_THRESHOLD=0.05
```

### Application Configuration

Add to orchestrator startup:

```python
# apps/orchestrator/main.py
from recovery_and_dr import get_startup_reconciler
from enhanced_observability import get_distributed_metrics, get_slo_monitor

# Run startup reconciliation
if os.getenv("P36_STARTUP_RECONCILIATION_ENABLED", "true").lower() == "true":
    reconciler = get_startup_reconciler()
    issues = reconciler.run_full_reconciliation()
    if issues:
        print(f"Found {len(issues)} consistency issues")
        fixed = reconciler.auto_fix_critical_issues()
        print(f"Auto-fixed {sum(fixed.values())} critical issues")

# Start metrics collection
if os.getenv("P36_OBSERVABILITY_ENABLED", "true").lower() == "true":
    metrics = get_distributed_metrics()
    slo_monitor = get_slo_monitor()
    # Metrics collection happens automatically
```

---

## Monitoring Setup

### Prometheus Metrics

Create `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'aop_orchestrator'
    static_configs:
      - targets: ['localhost:8090']
    metrics_path: '/metrics'
  
  - job_name: 'aop_outbox_processor'
    static_configs:
      - targets: ['localhost:8091']
    metrics_path: '/metrics'
```

### Grafana Dashboard

Import dashboard from JSON (example panels):

1. **SLO Metrics Panel**
   - Success Rate (gauge)
   - Failure Rate (gauge)
   - Total Tasks (counter)

2. **Concurrency Panel**
   - Active Workers (gauge)
   - Concurrency Backpressure (gauge)
   - By-Skill Concurrency (heatmap)

3. **Idempotency Panel**
   - Cache Hit Rate (gauge)
   - Duplicate Executions (counter)
   - Request Tracking Accuracy (gauge)

4. **Outbox Panel**
   - Pending Events (gauge)
   - Processing Rate (gauge)
   - Failed Events (counter)

5. **Failure Handling Panel**
   - Circuit Breaker Status (gauge)
   - Error Distribution (pie chart)
   - Retry Count (counter)

### Alerting Rules

Create `alerting_rules.yml`:

```yaml
groups:
  - name: p36_alerts
    rules:
      - alert: HighFailureRate
        expr: slo_failure_rate > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High failure rate detected"
          description: "Failure rate is {{ $value }}% (threshold: 5%)"
      
      - alert: HighDuplicateExecution
        expr: duplicate_execution_rate > 0.005
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High duplicate execution rate"
          description: "Duplicate execution rate is {{ $value }}% (threshold: 0.5%)"
      
      - alert: OutboxBacklog
        expr: outbox_pending_events > 100
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Outbox backlog detected"
          description: "{{ $value }} pending outbox events"
      
      - alert: HighBackpressure
        expr: concurrency_backpressure > 0.8
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High concurrency backpressure"
          description: "Backpressure is {{ $value }} (threshold: 0.8)"
      
      - alert: ConsistencyIssues
        expr: consistency_issue_count > 10
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Consistency issues detected"
          description: "{{ $value }} consistency issues found"
```

---

## Testing and Validation

### Phase 1: Smoke Tests

```bash
# Test basic orchestrator functionality
curl -X POST http://localhost:8090/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"input": {"content": "test task"}, "plan": {"nodes": [{"node_key": "test", "skill": "web-search"}]}}'

# Verify task created
curl http://localhost:8090/v1/tasks/{task_id}

# Check request tracking
psql -U aop -d aop -c "SELECT * FROM a2a_requests LIMIT 5;"
```

### Phase 2: Idempotency Tests

```bash
# Run idempotency tests
cd apps/orchestrator
python -m pytest tests/test_request_tracking.py -v
python -m pytest tests/test_executor_idempotency.py -v
```

### Phase 3: Outbox Pattern Tests

```bash
# Create a test task
# Verify outbox event created
psql -U aop -d aop -c "SELECT * FROM outbox_events WHERE status = 'pending' LIMIT 5;"

# Wait for outbox processor to process
sleep 5

# Verify event processed
psql -U aop -d aop -c "SELECT * FROM outbox_events WHERE status = 'processed' LIMIT 5;"
```

### Phase 4: Failure Handling Tests

```bash
# Enable chaos engineering
python -c "
from tests.chaos_engineering import get_chaos_engine
chaos = get_chaos_engine()
chaos.enable()
chaos.add_scenario(FailureScenario(
    name='test_timeout',
    failure_type=FailureType.AGENT_TIMEOUT,
    probability=0.5
))
"

# Run test task with chaos enabled
# Verify circuit breaker and retry behavior
```

### Phase 5: Concurrency Tests

```bash
# Run concurrent tasks
python -c "
from tests.chaos_engineering import get_stress_test_runner
runner = get_stress_test_runner()
result = runner.run_concurrent_tasks(
    task_count=100,
    concurrent_limit=10,
    task_func=lambda i: None
)
print(result)
"

# Verify concurrency limits respected
```

### Phase 6: Startup Reconciliation Tests

```bash
# Simulate stale running nodes
psql -U aop -d aop -c "
UPDATE task_nodes 
SET started_at = now() - '25 hours'::interval 
WHERE status = 'running' 
LIMIT 5;
"

# Restart orchestrator
# Verify startup reconciliation auto-fixed issues
psql -U aop -d aop -c "SELECT * FROM task_nodes WHERE status = 'failed' AND error_message ILIKE '%auto-fixed%';"
```

---

## Rollback Procedures

### Partial Rollback (Single Phase)

#### Rollback P36.1 (Idempotency)
```bash
# Disable idempotency
export P36_IDEMPOTENCY_ENABLED=false

# Restart orchestrator
pkill -f "python.*orchestrator"
python apps/orchestrator/main.py

# Database remains unchanged (backward compatible)
```

#### Rollback P36.2 (Outbox)
```bash
# Stop outbox processor
pkill -f outbox_processor

# Disable outbox in job queue
export P36_OUTBOX_ENABLED=false

# Restart orchestrator
pkill -f "python.*orchestrator"
python apps/orchestrator/main.py
```

#### Rollback P36.3-P36.8
```bash
# Disable specific features
export P36_FAILURE_HANDLING_ENABLED=false
export P36_CONCURRENCY_CONTROL_ENABLED=false
export P36_OBSERVABILITY_ENABLED=false
export P36_STARTUP_RECONCILIATION_ENABLED=false

# Restart orchestrator
pkill -f "python.*orchestrator"
python apps/orchestrator/main.py
```

### Full Rollback

```bash
# Stop all services
pkill -f "python.*orchestrator"
pkill -f outbox_processor

# Restore database from backup
pg_restore -h localhost -U aop -d aop backup_before_p36_YYYYMMDD.sql

# Restart with original code
git checkout <commit-before-p36>
python apps/orchestrator/main.py
```

### Database Rollback Only

```sql
-- Drop new tables
DROP TABLE IF EXISTS a2a_requests CASCADE;
DROP TABLE IF EXISTS outbox_events CASCADE;

-- Revert artifact table changes
ALTER TABLE artifacts DROP COLUMN IF EXISTS status;
ALTER TABLE artifacts DROP COLUMN IF EXISTS reference_count;
ALTER TABLE artifacts DROP COLUMN IF EXISTS updated_at;
```

---

## Operational Procedures

### Daily Operations

#### Check System Health
```bash
# Check database consistency
python -c "
from recovery_and_dr import get_disaster_recovery_manager
dr = get_disaster_recovery_manager()
health = dr.get_system_health()
print(health)
"

# Check SLO compliance
python -c "
from enhanced_observability import get_distributed_metrics, get_slo_monitor
metrics = get_distributed_metrics()
slo_metrics = metrics.record_slo_metrics()
slo_monitor = get_slo_monitor()
alerts = slo_monitor.check_slo_compliance(slo_metrics)
print(alerts)
"
```

#### Monitor Outbox Processing
```bash
# Check pending events
psql -U aop -d aop -c "SELECT status, COUNT(*) FROM outbox_events GROUP BY status;"

# Check outbox processor logs
tail -f logs/outbox_processor.log
```

#### Check Concurrency
```bash
python -c "
from concurrency_control import get_concurrency_controller
cc = get_concurrency_controller()
stats = cc.get_concurrency_stats()
print(stats)
"
```

### Weekly Operations

#### Clean Up Old Data
```bash
# Clean up old outbox events
python -c "
from outbox import get_outbox_processor
processor = get_outbox_processor()
cleaned = processor.cleanup_old_events(days=7)
print(f'Cleaned {cleaned} old events')
"

# Clean up orphaned artifacts
python -c "
from artifacts.enhanced_artifact_store import get_enhanced_artifact_store
store = get_enhanced_artifact_store()
cleaned = store.cleanup_orphaned_artifacts()
print(f'Cleaned {cleaned} orphaned artifacts')
"
```

#### Review Consistency Issues
```bash
python -c "
from recovery_and_dr import get_startup_reconciler
reconciler = get_startup_reconciler()
issues = reconciler.run_full_reconciliation()
for issue in issues:
    print(f'{issue.severity}: {issue.description}')
"
```

### Monthly Operations

#### Performance Review
- Review SLO compliance metrics
- Review concurrency backpressure trends
- Review idempotency cache hit rates
- Review failure patterns

#### Capacity Planning
- Review database growth
- Review Redis memory usage
- Review artifact storage growth
- Adjust concurrency limits if needed

---

## Troubleshooting

### Common Issues

#### Issue: High Duplicate Execution Rate
**Symptoms:** Idempotency cache hit rate < 90%

**Solutions:**
1. Check if idempotency keys are being generated
2. Verify agent-side caching is working
3. Check network timeouts causing retries
4. Review circuit breaker status

```bash
# Check idempotency metrics
psql -U aop -d aop -c "SELECT status, COUNT(*) FROM a2a_requests GROUP BY status;"
```

#### Issue: Outbox Backlog
**Symptoms:** Pending outbox events > 100

**Solutions:**
1. Check if outbox processor is running
2. Check Redis connectivity
3. Increase outbox processor batch size
4. Check for stuck events

```bash
# Check outbox processor
ps aux | grep outbox_processor

# Check pending events
psql -U aop -d aop -c "SELECT * FROM outbox_events WHERE status = 'pending' ORDER BY created_at LIMIT 10;"
```

#### Issue: Concurrency Backpressure
**Symptoms:** Backpressure > 0.8

**Solutions:**
1. Check if concurrency limits are too low
2. Check for stuck running nodes
3. Increase global concurrency limit
4. Review worker health

```bash
# Check concurrency state
python -c "
from concurrency_control import get_concurrency_controller
cc = get_concurrency_controller()
stats = cc.get_concurrency_stats()
print(stats)
"
```

#### Issue: Stale Running Nodes
**Symptoms:** Nodes stuck in running state

**Solutions:**
1. Run startup reconciliation
2. Check worker health
3. Manually mark as failed if needed
4. Review stale reclaim configuration

```bash
# Run reconciliation
python -c "
from recovery_and_dr import get_startup_reconciler
reconciler = get_startup_reconciler()
issues = reconciler.run_full_reconciliation()
fixed = reconciler.auto_fix_critical_issues()
print(f'Fixed: {fixed}')
"
```

#### Issue: Artifact Orphanage
**Symptoms:** Reference count = 0 artifacts exist

**Solutions:**
1. Run garbage collection
2. Check two-phase upload implementation
3. Review artifact persistence logic

```bash
# Clean up orphaned artifacts
python -c "
from artifacts.enhanced_artifact_store import get_enhanced_artifact_store
store = get_enhanced_artifact_store()
cleaned = store.cleanup_orphaned_artifacts()
print(f'Cleaned {cleaned} artifacts')
"
```

### Emergency Procedures

#### Emergency: Database Connection Lost
```bash
# Stop all services
pkill -f "python.*orchestrator"
pkill -f outbox_processor

# Wait for database recovery
# Then restart services
python apps/orchestrator/main.py
nohup python apps/orchestrator/outbox_processor_service.py > logs/outbox_processor.log 2>&1 &
```

#### Emergency: Redis Connection Lost
```bash
# Outbox processor will retry automatically
# Monitor logs for connection errors
tail -f logs/outbox_processor.log

# If Redis is down for extended period:
# Disable outbox pattern temporarily
export P36_OUTBOX_ENABLED=false
pkill -f "python.*orchestrator"
python apps/orchestrator/main.py
```

#### Emergency: High Error Rate
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Check failure patterns
python -c "
from enhanced_failure_handling import get_failure_handler
fh = get_failure_handler()
# Review failure history
"

# If circuit breakers are open:
# Reset circuit breakers
python -c "
from enhanced_failure_handling import get_failure_handler
fh = get_failure_handler()
# Reset specific agent circuit breakers
"
```

---

## Appendix

### A. Migration Script Reference

```python
# infrastructure/postgres/migrate.py
# Usage:
#   python migrate.py --status          # Check status
#   python migrate.py --apply <file>    # Apply specific migration
#   python migrate.py --dry-run <file>  # Test migration
#   python migrate.py --rollback <file> # Rollback migration
```

### B. Service Ports Reference

| Service | Port | Purpose |
|---------|------|---------|
| Orchestrator | 8090 | Main orchestrator API |
| Outbox Processor | - | Background service (no HTTP) |
| Search Agent | 8001 | Web search skill |
| RAG Agent | 8002 | Knowledge search skill |
| Report Agent | 8003 | Report generation skill |
| Analysis Agent | 8004 | Business analysis skill |
| Image Agent | 8005 | Text-to-image skill |
| Video Agent | 8006 | Text-to-video skill |
| Code Agent | 8007 | Code execution skill |
| Browser Agent | 8008 | Browser automation skill |

### C. Database Schema Reference

#### a2a_requests Table
```sql
id UUID PRIMARY KEY
idempotency_key TEXT UNIQUE
task_id UUID REFERENCES tasks(id)
node_id UUID REFERENCES task_nodes(id)
agent_id UUID REFERENCES agents(id)
status TEXT (pending, running, completed, failed)
request_json JSONB
response_json JSONB
error_message TEXT
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
finished_at TIMESTAMPTZ
```

#### outbox_events Table
```sql
id UUID PRIMARY KEY
event_type TEXT
payload JSONB
target_stream TEXT
status TEXT (pending, processing, processed, failed)
attempts INT
last_error TEXT
created_at TIMESTAMPTZ
processed_at TIMESTAMPTZ
```

#### artifacts Table (Enhanced)
```sql
id UUID PRIMARY KEY
task_id UUID REFERENCES tasks(id)
node_key TEXT
name TEXT
content_type TEXT
size BIGINT
uri TEXT
status TEXT (pending, committed, failed)
reference_count INT
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

---

**End of Deployment and Operations Guide**
