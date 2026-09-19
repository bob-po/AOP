# Phase 35.4: Router v3 Audit Report

**Date**: 2026-09-18  
**Objective**: Audit current Router implementation for Agent Selection Engine upgrade  
**Scope**: Router v2, Agent Registry, agent_runs metrics, Router Preview API

---

## Executive Summary

Conducted comprehensive audit of current Router v2 implementation. The router already has solid foundations with skill matching, online filtering, priority-based selection, and smart scoring (latency, success rate, priority). However, opportunities exist for enhanced capability matching, resource-aware filtering, configurable scoring policies, and improved failover mechanisms.

---

## Current Router Architecture

### Component Overview

**Location**: `apps/orchestrator/router/`

**Files**:
- `__init__.py`: Core AgentRouter implementation (369 lines)
- `engine.py`: Application-facing RoutingEngine wrapper (45 lines)

**Architecture**:
```
RoutingEngine (application layer)
    ↓ delegates to
AgentRouter (core logic)
    ↓ data sources
PostgreSQL (agents, agent_skills, agent_endpoints, agent_runs)
Redis (agent:skill:{skill} sets for fast lookup)
```

---

## Current Capabilities

### 1. Skill Matching ✅

**Implementation**: `_candidates_from_redis()`, `_candidates_from_pg()`

**Sources**:
- **Primary**: Redis sets `agent:skill:{skill}` for fast lookup
- **Fallback**: PostgreSQL `agent_skills` table

**Query**:
```sql
SELECT a.id, a.agent_key, a.name, a.status, a.priority,
       e.url AS endpoint,
       array_agg(s.skill_id) AS skills
FROM agents a
JOIN agent_skills s ON s.agent_id = a.id
LEFT JOIN agent_endpoints e ON e.agent_id = a.id AND e.is_primary = true
WHERE a.tenant_id = %s
  AND s.skill_id = %s
```

**Status**: ✅ **Solid** - Dual-source with Redis caching for performance

---

### 2. Online Status Filtering ✅

**Implementation**: `ONLINE_STATUSES = {"online", "running"}`

**Filtering Logic**:
```python
online = [
    c for c in candidates
    if c["status"] in ONLINE_STATUSES
    and c.get("endpoint")
    and c["agent_id"] not in excluded
]
```

**Agent Statuses** (from schema):
- created, registered, verified, online, running, offline, degraded, disabled

**Status**: ✅ **Good** - Simple and effective online filtering

**Gaps**:
- No separate "enabled" vs "online" distinction
- No health check integration
- No degraded state handling

---

### 3. Priority-Based Selection ✅

**Implementation**: Priority field in agents table

**Sorting**:
- **Smart mode**: `(-score, priority, name)`
- **Smart off**: `(priority, name)`

**Priority Range**: 1 (best) to 200 (worst), default 100

**Status**: ✅ **Good** - Priority is respected in both modes

**Gaps**:
- Priority is hardcoded in scoring formula
- No configurable priority weights

---

### 4. Smart Scoring ✅

**Implementation**: `_score()` method with metrics from `agent_runs`

**Metrics Window**: Configurable via `ROUTER_METRICS_HOURS` (default 24h)

**Metrics Sources**:
```sql
SELECT agent_id,
       COUNT(*) AS request_count,
       COUNT(*) FILTER (WHERE status = 'success') AS success_count,
       COUNT(*) FILTER (WHERE status = 'failed') AS failure_count,
       AVG(latency_ms) AS avg_latency_ms
FROM agent_runs
WHERE agent_id = ANY(%s)
  AND created_at >= %s
GROUP BY agent_id
```

**Scoring Formula** (Smart Mode):
```python
success_rate = (success_count / request_count) if request_count > 0 else 0.85
latency_score = max(0.0, min(1.0, 1.0 - (avg_latency_ms / 5000.0)))
priority_score = max(0.0, min(1.0, 1.0 - ((priority - 1) / 199.0)))
availability = 1.0 if status in ONLINE_STATUSES else 0.0

total = (
    availability * 0.10
    + success_rate * 0.35
    + latency_score * 0.30
    + priority_score * 0.25
)
```

**Hardcoded Weights**:
- Availability: 10%
- Success Rate: 35%
- Latency: 30%
- Priority: 25%

**Status**: ✅ **Good** - Well-thought-out scoring with cold-start handling

**Gaps**:
- Weights are hardcoded
- No cost consideration
- No resource awareness
- No tenant-specific policies

---

### 5. Availability Scoring ✅

**Implementation**: Binary availability check

**Logic**:
```python
availability = 1.0 if status in ONLINE_STATUSES else 0.0
```

**Status**: ⚠️ **Basic** - Binary availability, no nuanced health

**Gaps**:
- No health check integration
- No degraded state consideration
- No concurrent request limits

---

### 6. Latency Scoring ✅

**Implementation**: Linear decay from 0ms to 5000ms

**Formula**:
```python
latency_score = max(0.0, min(1.0, 1.0 - (avg_latency_ms / 5000.0)))
```

**Cold Start**: 0.75 (default for agents with no samples)

**Status**: ✅ **Good** - Reasonable latency scoring

**Gaps**:
- No percentile-based scoring
- No recent vs historical latency distinction
- No timeout consideration

---

### 7. Success Rate Scoring ✅

**Implementation**: Simple success ratio

**Formula**:
```python
success_rate = (success_count / request_count) if request_count > 0 else 0.85
```

**Cold Start**: 0.85 (default for agents with no samples)

**Status**: ✅ **Good** - Reasonable cold-start handling

**Gaps**:
- No recent success rate weighting
- No error type consideration
- No confidence intervals

---

### 8. Exclusion Mechanism ✅

**Implementation**: `exclude_agent_ids` parameter

**Usage**:
```python
select(skill, exclude_agent_ids=["agent-id-1", "agent-id-2"])
```

**Status**: ✅ **Good** - Basic exclusion support

**Gaps**:
- No persistent exclusion lists
- No exclusion reasons
- No time-based exclusion

---

## Database Schema

### Agents Table

```sql
CREATE TABLE agents (
  id            UUID PRIMARY KEY,
  tenant_id     UUID REFERENCES tenants(id),
  agent_key     TEXT NOT NULL,
  name          TEXT NOT NULL,
  description   TEXT,
  protocol      TEXT NOT NULL DEFAULT 'A2A',
  status        TEXT NOT NULL DEFAULT 'created',
  current_version TEXT,
  card_json     JSONB,
  priority      INT NOT NULL DEFAULT 100,
  created_at    TIMESTAMPTZ NOT NULL,
  updated_at    TIMESTAMPTZ NOT NULL,
  UNIQUE (tenant_id, agent_key)
);
```

**Statuses**: created, registered, verified, online, running, offline, degraded, disabled

**Current Usage**:
- `status`: Online filtering
- `priority`: Priority-based selection
- `card_json`: Not currently used in routing
- `agent_key`: Not used in routing (uses id)

**Gaps**:
- `card_json` not parsed for capabilities
- No resource requirements fields
- No enabled/disabled distinction
- No tenant-specific configuration

---

### Agent Skills Table

```sql
CREATE TABLE agent_skills (
  agent_id UUID REFERENCES agents(id),
  skill_id TEXT NOT NULL,
  UNIQUE (agent_id, skill_id)
);
CREATE INDEX idx_agent_skills_skill_id ON agent_skills(skill_id);
```

**Current Usage**: Skill matching

**Gaps**:
- No skill metadata (examples, input modes, output modes)
- No requires_approval flag
- No skill versioning

---

### Agent Endpoints Table

```sql
CREATE TABLE agent_endpoints (
  agent_id UUID REFERENCES agents(id),
  url TEXT NOT NULL,
  auth_type TEXT NOT NULL DEFAULT 'none',
  is_primary BOOLEAN NOT NULL DEFAULT true
);
```

**Current Usage**: Primary endpoint selection

**Gaps**:
- No load balancing across endpoints
- No endpoint health checking
- No regional endpoint selection

---

### Agent Runs Table

```sql
CREATE TABLE agent_runs (
  id UUID PRIMARY KEY,
  tenant_id UUID REFERENCES tenants(id),
  task_id UUID REFERENCES tasks(id),
  node_id UUID REFERENCES task_nodes(id),
  agent_id UUID REFERENCES agents(id),
  a2a_task_id TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  request_json JSONB,
  response_json JSONB,
  latency_ms INT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
```

**Current Usage**: Metrics source for scoring

**Gaps**:
- No cost tracking
- No resource usage tracking
- No error categorization

---

## Router Preview API

### Endpoint

**Path**: `GET /v1/router/preview?skill={skill}`

**Implementation**: `main.py:router_preview()` → `TaskService.router_preview()` → `RoutingEngine.preview()`

**Response Format**:
```json
{
  "skill": "web-search",
  "smart": true,
  "metrics_window_hours": 24,
  "candidates": [
    {
      "agent_id": "...",
      "agent_key": "...",
      "name": "...",
      "status": "online",
      "endpoint": "...",
      "priority": 100,
      "score": 0.85,
      "score_breakdown": {
        "availability": 1.0,
        "success_rate": 0.95,
        "latency": 0.90,
        "priority": 0.50,
        "total": 0.85
      },
      "source": "redis+pg"
    }
  ],
  "selected": "..."
}
```

**Status**: ✅ **Good** - Developer-friendly debug interface

**Gaps**:
- No filter information in response
- No capability matching details
- No resource filter information
- No policy information

---

## Current Test Coverage

### Test File

**Location**: `apps/orchestrator/tests/test_router.py`

**Tests**:
1. `test_normalize_endpoint_maps_docker_hostnames` - Endpoint normalization
2. `test_score_prefers_high_success_low_latency` - Scoring logic
3. `test_score_cold_start_prior_when_no_samples` - Cold start handling
4. `test_smart_off_uses_priority_only` - Smart mode toggle
5. `test_hitl_skills_parsing` - HITL skills parsing

**Status**: ⚠️ **Limited** - Only 5 tests, focuses on scoring

**Gaps**:
- No multi-agent testing
- No offline agent testing
- No disabled agent testing
- No failover testing
- No no-candidate testing
- No capability matching testing

---

## Missing Capabilities

### 1. Capability Matching ❌

**Required**: Filter agents by capabilities (streaming, web browsing, code execution)

**Current State**: No capability matching

**Impact**: Cannot filter agents based on task requirements

---

### 2. Input/Output Compatibility ❌

**Required**: Filter agents by supported input/output modes

**Current State**: No mode compatibility checking

**Impact**: Cannot ensure agent can handle task input/output types

---

### 3. Health Filter ❌

**Required**: Integrate health check status into filtering

**Current State**: Only online status, no health check integration

**Impact**: Cannot filter based on actual health vs online status

---

### 4. Resource Filter ❌

**Required**: Filter agents by resource requirements (CPU, memory, GPU)

**Current State**: No resource awareness

**Impact**: Cannot match agents to resource availability

---

### 5. Tenant/Permission Filter ❌

**Required**: Filter agents by tenant and permissions

**Current State**: Only tenant_id in queries, no permission checking

**Impact**: Cannot enforce tenant-specific agent access

---

### 6. Policy Filter ❌

**Required**: Apply tenant-specific routing policies

**Current State**: No policy system

**Impact**: Cannot implement tenant-specific routing rules

---

### 7. Configurable Scoring ❌

**Required**: Make scoring weights configurable

**Current State**: Hardcoded weights in `_score()`

**Impact**: Cannot tune scoring for different scenarios

---

### 8. Cost Scoring ❌

**Required**: Include cost in scoring decisions

**Current State**: No cost tracking or scoring

**Impact**: Cannot make cost-aware routing decisions

---

### 9. Concurrency Limits ❌

**Required**: Respect agent concurrency limits

**Current State**: No concurrency tracking

**Impact**: Cannot prevent agent overload

---

### 10. Failover Mechanism ❌

**Required**: Automatic failover to compatible agents on failure

**Current State**: Only manual exclusion via `exclude_agent_ids`

**Impact**: No automatic recovery from agent failures

---

## Configuration Mechanisms

### Environment Variables

**Current Variables**:
- `DATABASE_URL`: PostgreSQL connection
- `REDIS_URL`: Redis connection
- `ROUTER_SMART`: Enable/disable smart scoring (default: true)
- `ROUTER_METRICS_HOURS`: Metrics window (default: 24)
- `HITL_SKILLS`: Comma-separated skill list for HITL
- `AOP_RUNTIME`: Runtime mode (docker/host) for endpoint normalization

**Status**: ⚠️ **Basic** - Limited configuration options

**Gaps**:
- No scoring weight configuration
- No policy configuration
- No tenant-specific configuration
- No resource limit configuration

---

## Redis Integration

### Current Usage

**Data Structures**:
- `agent:skill:{skill}`: Set of agent_ids for skill

**Operations**:
- `SMEMBERS`: Get agent_ids for skill
- `SADD`: Add agent to skill set (registration)
- `SREM`: Remove agent from skill set (deregistration)

**Status**: ✅ **Good** - Fast skill lookup

**Gaps**:
- No agent health caching
- No metrics caching
- No capability caching

---

## Summary of Findings

### Strengths
1. ✅ Solid dual-source candidate discovery (Redis + PostgreSQL)
2. ✅ Well-implemented smart scoring with cold-start handling
3. ✅ Priority-based selection with proper sorting
4. ✅ Effective online status filtering
5. ✅ Developer-friendly Router Preview API
6. ✅ Good metrics collection from agent_runs
7. ✅ Exclusion mechanism for manual failover

### Weaknesses
1. ❌ No capability matching (streaming, browsing, execution)
2. ❌ No input/output compatibility checking
3. ❌ No health check integration
4. ❌ No resource awareness (CPU, memory, GPU)
5. ❌ No tenant/permission filtering
6. ❌ No policy system
7. ❌ Hardcoded scoring weights
8. ❌ No cost consideration
9. ❌ No concurrency limits
10. ❌ No automatic failover

### Priorities for Router v3
1. **HIGH**: Configurable scoring policies
2. **HIGH**: Capability matching
3. **HIGH**: Input/output compatibility
4. **MEDIUM**: Resource filtering
5. **MEDIUM**: Tenant/permission filtering
6. **MEDIUM**: Health check integration
7. **MEDIUM**: Failover mechanism
8. **LOW**: Cost scoring
9. **LOW**: Concurrency limits
10. **LOW**: Policy system

---

## Next Steps

1. **Design Router pipeline** with capability-aware filtering
2. **Implement Candidate Filter** with extended filtering criteria
3. **Implement configurable Scoring** with policy-based weights
4. **Update Router Preview** with detailed filter and policy information
5. **Implement Failover** with automatic compatible agent selection
6. **Add comprehensive Router tests** for all new capabilities
7. **Generate final result document** with v3 enhancements

---

**Audit Complete**  
**Next Phase**: Design Router v3 pipeline
