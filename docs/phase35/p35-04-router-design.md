# Phase 35.4: Router v3 Pipeline Design

**Date**: 2026-09-18  
**Objective**: Design Router v3 pipeline for capability-aware agent selection

---

## Executive Summary

Router v3 introduces a multi-stage pipeline for agent selection, moving from simple skill+online filtering to a comprehensive capability-aware selection engine. The pipeline maintains backward compatibility while adding advanced filtering, configurable scoring, and automatic failover.

---

## Router v3 Pipeline Architecture

### Complete Pipeline

```
Task Node (skill, input_mode, output_mode, tenant_id, requirements)
    ↓
[Stage 1] Skill Match
    ↓
[Stage 2] Capability Match
    ↓
[Stage 3] Input/Output Compatibility
    ↓
[Stage 4] Health Filter
    ↓
[Stage 5] Resource Filter
    ↓
[Stage 6] Tenant/Permission Filter
    ↓
[Stage 7] Policy Filter
    ↓
[Stage 8] Scoring (Configurable Policy)
    ↓
[Stage 9] Selection
    ↓
Selected Agent
```

---

## Stage Details

### Stage 1: Skill Match

**Purpose**: Find agents that support the requested skill

**Input**: Task Node with skill_id

**Filter**: `agent_skills.skill_id = task.skill_id`

**Output**: Candidates with matching skill

**Current Implementation**: ✅ Already implemented (Redis + PostgreSQL)

**Enhancement**: None required, current implementation is solid

---

### Stage 2: Capability Match

**Purpose**: Filter agents by required capabilities

**Input**: Task requirements (streaming, web_browsing, code_execution, etc.)

**Filter**: Agent capabilities from card_json

**Implementation**:
```python
required_capabilities = {
    "streaming": task.requires_streaming,
    "web_browsing": task.requires_web_browsing,
    "code_execution": task.requires_code_execution,
}

for candidate in candidates:
    agent_caps = parse_capabilities(candidate["card_json"])
    for cap, required in required_capabilities.items():
        if required and not agent_caps.get(cap, False):
            exclude(candidate, reason=f"missing capability: {cap}")
```

**Current Implementation**: ❌ Not implemented

**New Feature**: Parse card_json for capabilities

---

### Stage 3: Input/Output Compatibility

**Purpose**: Ensure agent can handle task input/output modes

**Input**: Task input_mode, output_mode

**Filter**: Agent skill input_modes, output_modes

**Implementation**:
```python
task_input_modes = task.input_modes or ["text"]
task_output_modes = task.output_modes or ["text"]

for candidate in candidates:
    skill_info = get_skill_info(candidate, task.skill_id)
    agent_input_modes = skill_info.get("input_modes", ["text"])
    agent_output_modes = skill_info.get("output_modes", ["text"])
    
    if not any(mode in agent_input_modes for mode in task_input_modes):
        exclude(candidate, reason="incompatible input modes")
    
    if not any(mode in agent_output_modes for mode in task_output_modes):
        exclude(candidate, reason="incompatible output modes")
```

**Current Implementation**: ❌ Not implemented

**New Feature**: Parse skill metadata from card_json

---

### Stage 4: Health Filter

**Purpose**: Filter agents by health status

**Input**: Health check status from agent health endpoint

**Filter**: Health status (ok, degraded, unhealthy)

**Implementation**:
```python
for candidate in candidates:
    health = check_agent_health(candidate["endpoint"])
    if health["status"] == "unhealthy":
        exclude(candidate, reason="unhealthy")
    elif health["status"] == "degraded" and policy.strict_health:
        exclude(candidate, reason="degraded (strict mode)")
```

**Current Implementation**: ⚠️ Only online status, no health check

**Enhancement**: Add health check integration with caching

---

### Stage 5: Resource Filter

**Purpose**: Filter agents by resource requirements

**Input**: Task resource requirements (CPU, memory, GPU)

**Filter**: Agent resource requirements from card_json

**Implementation**:
```python
task_resources = {
    "cpu_cores": task.required_cpu,
    "memory_mb": task.required_memory,
    "gpu_required": task.requires_gpu,
    "gpu_type": task.gpu_type,
}

for candidate in candidates:
    agent_resources = parse_resources(candidate["card_json"])
    
    if task_resources["cpu_cores"] and agent_resources.get("cpu_cores", 0) < task_resources["cpu_cores"]:
        exclude(candidate, reason="insufficient CPU")
    
    if task_resources["memory_mb"] and agent_resources.get("memory_mb", 0) < task_resources["memory_mb"]:
        exclude(candidate, reason="insufficient memory")
    
    if task_resources["gpu_required"] and not agent_resources.get("gpu_required", False):
        exclude(candidate, reason="GPU required but not available")
    
    if task_resources["gpu_type"] and agent_resources.get("gpu_type") != task_resources["gpu_type"]:
        exclude(candidate, reason=f"GPU type mismatch: need {task_resources['gpu_type']}")
```

**Current Implementation**: ❌ Not implemented

**New Feature**: Parse resource requirements from card_json

---

### Stage 6: Tenant/Permission Filter

**Purpose**: Filter agents by tenant and permissions

**Input**: Task tenant_id, user permissions

**Filter**: Agent tenant_id, permission checks

**Implementation**:
```python
for candidate in candidates:
    # Tenant filter
    if candidate["tenant_id"] != task.tenant_id and not policy.cross_tenant:
        exclude(candidate, reason="tenant mismatch")
    
    # Permission filter
    if not check_user_permission(user_id, candidate["agent_id"], "use"):
        exclude(candidate, reason="permission denied")
```

**Current Implementation**: ⚠️ Basic tenant_id filter, no permission checks

**Enhancement**: Add permission system

---

### Stage 7: Policy Filter

**Purpose**: Apply tenant-specific routing policies

**Input**: Tenant routing policy configuration

**Filter**: Policy rules (allowed_agents, blocked_agents, etc.)

**Implementation**:
```python
policy = load_tenant_policy(task.tenant_id)

for candidate in candidates:
    # Blocked agents
    if candidate["agent_id"] in policy.blocked_agents:
        exclude(candidate, reason="blocked by policy")
    
    # Allowed agents (whitelist mode)
    if policy.mode == "whitelist" and candidate["agent_id"] not in policy.allowed_agents:
        exclude(candidate, reason="not in whitelist")
    
    # Regional policy
    if policy.region and candidate.get("region") != policy.region:
        exclude(candidate, reason="region mismatch")
```

**Current Implementation**: ❌ Not implemented

**New Feature**: Policy system with tenant-specific rules

---

### Stage 8: Scoring (Configurable Policy)

**Purpose**: Score remaining candidates using configurable policy

**Input**: Scoring policy with weights

**Scoring Components**:
- Availability (agent online status, health)
- Priority (agent priority)
- Latency (avg_latency_ms from metrics)
- Success Rate (success_count / request_count)
- Cost (if available)

**Implementation**:
```python
policy = load_scoring_policy(task.tenant_id)

weights = {
    "availability": policy.weights.get("availability", 0.10),
    "priority": policy.weights.get("priority", 0.25),
    "latency": policy.weights.get("latency", 0.30),
    "success_rate": policy.weights.get("success_rate", 0.35),
    "cost": policy.weights.get("cost", 0.0),
}

for candidate in candidates:
    metrics = load_metrics(candidate["agent_id"])
    
    scores = {
        "availability": compute_availability(candidate, metrics),
        "priority": compute_priority(candidate),
        "latency": compute_latency_score(metrics),
        "success_rate": compute_success_rate(metrics),
        "cost": compute_cost_score(candidate, metrics),
    }
    
    total = sum(scores[k] * weights[k] for k in scores)
    candidate.score = total
    candidate.score_breakdown = scores
```

**Current Implementation**: ⚠️ Hardcoded weights, no cost

**Enhancement**: Make weights configurable, add cost scoring

---

### Stage 9: Selection

**Purpose**: Select highest-scoring agent

**Input**: Scored candidates

**Selection**: Sort by score (descending), then priority, then name

**Implementation**:
```python
candidates.sort(key=lambda c: (-c.score, c.priority, c.name))
selected = candidates[0] if candidates else None
```

**Current Implementation**: ✅ Already implemented

**Enhancement**: None required

---

## Candidate Filter Implementation

### New Class: CandidateFilter

**Purpose**: Encapsulate all filtering logic

**Location**: `apps/orchestrator/router/filter.py`

**Methods**:
```python
class CandidateFilter:
    def __init__(self, policy: RoutingPolicy, config: RouterConfig):
        self.policy = policy
        self.config = config
    
    def filter_candidates(
        self,
        candidates: list[dict],
        task: TaskNode,
        exclude_agent_ids: set[str] | None = None,
    ) -> list[dict]:
        """Apply all filter stages to candidates."""
        results = candidates.copy()
        
        # Stage 1: Skill Match (already done by caller)
        
        # Stage 2: Capability Match
        results = self._filter_by_capabilities(results, task)
        
        # Stage 3: Input/Output Compatibility
        results = self._filter_by_modes(results, task)
        
        # Stage 4: Health Filter
        results = self._filter_by_health(results)
        
        # Stage 5: Resource Filter
        results = self._filter_by_resources(results, task)
        
        # Stage 6: Tenant/Permission Filter
        results = self._filter_by_tenant(results, task)
        
        # Stage 7: Policy Filter
        results = self._filter_by_policy(results, task)
        
        # Manual exclusion
        if exclude_agent_ids:
            results = [c for c in results if c["agent_id"] not in exclude_agent_ids]
        
        return results
    
    def _filter_by_capabilities(self, candidates: list[dict], task: TaskNode) -> list[dict]:
        """Filter by required capabilities."""
        # Implementation
        pass
    
    def _filter_by_modes(self, candidates: list[dict], task: TaskNode) -> list[dict]:
        """Filter by input/output mode compatibility."""
        # Implementation
        pass
    
    def _filter_by_health(self, candidates: list[dict]) -> list[dict]:
        """Filter by health status."""
        # Implementation
        pass
    
    def _filter_by_resources(self, candidates: list[dict], task: TaskNode) -> list[dict]:
        """Filter by resource requirements."""
        # Implementation
        pass
    
    def _filter_by_tenant(self, candidates: list[dict], task: TaskNode) -> list[dict]:
        """Filter by tenant and permissions."""
        # Implementation
        pass
    
    def _filter_by_policy(self, candidates: list[dict], task: TaskNode) -> list[dict]:
        """Filter by tenant-specific policies."""
        # Implementation
        pass
```

---

## Scoring Policy Implementation

### New Class: ScoringPolicy

**Purpose**: Configurable scoring with policy-based weights

**Location**: `apps/orchestrator/router/scoring.py`

**Data Structure**:
```python
@dataclass
class ScoringWeights:
    availability: float = 0.10
    priority: float = 0.25
    latency: float = 0.30
    success_rate: float = 0.35
    cost: float = 0.0
    
    def validate(self) -> None:
        total = sum([
            self.availability,
            self.priority,
            self.latency,
            self.success_rate,
            self.cost,
        ])
        if not (0.99 <= total <= 1.01):  # Allow small floating point errors
            raise ValueError(f"Scoring weights must sum to 1.0, got {total}")

@dataclass
class ScoringPolicy:
    weights: ScoringWeights
    cold_start_success_rate: float = 0.85
    cold_start_latency_score: float = 0.75
    latency_cutoff_ms: int = 5000
    priority_max: int = 200
    enable_cost_scoring: bool = False
```

**Configuration Sources**:
1. Environment variables (default policy)
2. Database table (tenant-specific policies)
3. Redis cache (cached policies)

**Environment Variables**:
```bash
ROUTER_WEIGHT_AVAILABILITY=0.10
ROUTER_WEIGHT_PRIORITY=0.25
ROUTER_WEIGHT_LATENCY=0.30
ROUTER_WEIGHT_SUCCESS_RATE=0.35
ROUTER_WEIGHT_COST=0.0
```

**Implementation**:
```python
class ScoringEngine:
    def __init__(self, policy: ScoringPolicy):
        self.policy = policy
    
    def score_candidate(
        self,
        candidate: dict,
        metrics: dict,
    ) -> dict[str, float]:
        """Score a single candidate using policy weights."""
        scores = {
            "availability": self._score_availability(candidate),
            "priority": self._score_priority(candidate),
            "latency": self._score_latency(metrics),
            "success_rate": self._score_success_rate(metrics),
            "cost": self._score_cost(candidate, metrics) if self.policy.enable_cost_scoring else 0.0,
        }
        
        total = sum(
            scores[k] * getattr(self.policy.weights, k)
            for k in scores
        )
        
        scores["total"] = total
        return scores
    
    def _score_availability(self, candidate: dict) -> float:
        """Score based on availability (online + health)."""
        if candidate["status"] not in ONLINE_STATUSES:
            return 0.0
        # TODO: Integrate health check
        return 1.0
    
    def _score_priority(self, candidate: dict) -> float:
        """Score based on priority (1 best, max worst)."""
        priority = int(candidate.get("priority") or 100)
        return max(0.0, min(1.0, 1.0 - ((priority - 1) / (self.policy.priority_max - 1))))
    
    def _score_latency(self, metrics: dict) -> float:
        """Score based on latency (lower is better)."""
        req = int(metrics.get("request_count") or 0)
        avg_lat = float(metrics.get("avg_latency_ms") or 0.0)
        
        if req == 0:
            return self.policy.cold_start_latency_score
        
        return max(0.0, min(1.0, 1.0 - (avg_lat / self.policy.latency_cutoff_ms)))
    
    def _score_success_rate(self, metrics: dict) -> float:
        """Score based on success rate (higher is better)."""
        req = int(metrics.get("request_count") or 0)
        ok = int(metrics.get("success_count") or 0)
        
        if req == 0:
            return self.policy.cold_start_success_rate
        
        return ok / req
    
    def _score_cost(self, candidate: dict, metrics: dict) -> float:
        """Score based on cost (lower is better)."""
        # TODO: Implement cost scoring when cost data available
        return 0.0
```

---

## Failover Implementation

### New Class: FailoverEngine

**Purpose**: Automatic failover to compatible agents on failure

**Location**: `apps/orchestrator/router/failover.py`

**Implementation**:
```python
class FailoverEngine:
    def __init__(self, router: AgentRouter, filter: CandidateFilter):
        self.router = router
        self.filter = filter
    
    def select_failover_agent(
        self,
        failed_agent_id: str,
        skill: str,
        task: TaskNode,
        exclude_agent_ids: set[str] | None = None,
    ) -> RoutedAgent | None:
        """Select a compatible failover agent."""
        exclude = set(exclude_agent_ids or [])
        exclude.add(failed_agent_id)
        
        # Get candidates for the skill
        candidates = self.router._candidates_from_pg(skill)
        
        # Aggregate with excluded agents
        all_excluded = exclude | set(exclude_agent_ids or [])
        
        # Apply filters
        filtered = self.filter.filter_candidates(
            candidates,
            task,
            exclude_agent_ids=all_excluded,
        )
        
        if not filtered:
            return None
        
        # Score and select
        scored = self._score_candidates(filtered)
        scored.sort(key=lambda c: (-c["score"], c["priority"], c["name"]))
        
        return scored[0] if scored else None
    
    def _score_candidates(self, candidates: list[dict]) -> list[dict]:
        """Score candidates for failover selection."""
        # Use same scoring as main router
        # Implementation
        pass
```

**Integration Point**: Called by Executor when agent execution fails

---

## Router Preview Enhancement

### Enhanced Response Format

**Current Response**:
```json
{
  "skill": "web-search",
  "smart": true,
  "metrics_window_hours": 24,
  "candidates": [...],
  "selected": "..."
}
```

**Enhanced Response**:
```json
{
  "skill": "web-search",
  "policy": {
    "weights": {
      "availability": 0.10,
      "priority": 0.25,
      "latency": 0.30,
      "success_rate": 0.35,
      "cost": 0.0
    },
    "strict_health": false,
    "cross_tenant": false
  },
  "metrics_window_hours": 24,
  "filters": {
    "skill_match": {"total": 5, "passed": 5},
    "capability_match": {"total": 5, "passed": 4, "excluded": [{"agent_id": "...", "reason": "missing capability: web_browsing"}]},
    "mode_compatibility": {"total": 4, "passed": 4},
    "health_filter": {"total": 4, "passed": 4},
    "resource_filter": {"total": 4, "passed": 4},
    "tenant_filter": {"total": 4, "passed": 4},
    "policy_filter": {"total": 4, "passed": 4}
  },
  "candidates": [
    {
      "agent_id": "...",
      "agent_key": "...",
      "name": "...",
      "status": "online",
      "endpoint": "...",
      "priority": 100,
      "capabilities": {"streaming": false, "web_browsing": true},
      "resources": {"cpu_cores": 1.0, "memory_mb": 512},
      "score": 0.85,
      "score_breakdown": {
        "availability": 1.0,
        "priority": 0.50,
        "latency": 0.90,
        "success_rate": 0.95,
        "cost": 0.0,
        "total": 0.85
      },
      "source": "redis+pg"
    }
  ],
  "selected": "..."
}
```

**Benefits**:
- Shows filtering pipeline results
- Shows policy configuration
- Shows agent capabilities and resources
- Helps debugging routing decisions

---

## Configuration Management

### Configuration Sources (Priority Order)

1. **Environment Variables** (default policy)
2. **Database Table** (tenant-specific policies)
3. **Redis Cache** (cached policies)

### New Database Table (Optional)

```sql
CREATE TABLE routing_policies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id),
  policy_name TEXT NOT NULL,
  policy_config JSONB NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, policy_name)
);
```

### Policy Configuration Format

```json
{
  "weights": {
    "availability": 0.10,
    "priority": 0.25,
    "latency": 0.30,
    "success_rate": 0.35,
    "cost": 0.0
  },
  "strict_health": false,
  "cross_tenant": false,
  "blocked_agents": [],
  "allowed_agents": [],
  "mode": "allowlist",
  "region": null
}
```

---

## Backward Compatibility

### Maintained Compatibility

1. **Existing Router API**: No changes to `select()`, `rank()`, `preview()` signatures
2. **Existing Scoring**: Default weights match current hardcoded weights
3. **Existing Filtering**: Online status filtering unchanged
4. **Existing Metrics**: agent_runs usage unchanged
5. **Existing Tests**: Existing tests continue to pass

### Gradual Migration Path

1. **Phase 1**: Add new components (CandidateFilter, ScoringEngine, FailoverEngine)
2. **Phase 2**: Integrate with existing Router behind feature flags
3. **Phase 3**: Enable new features gradually
4. **Phase 4**: Deprecate old approaches

---

## Implementation Plan

### Step 1: Create New Components
- `router/filter.py`: CandidateFilter class
- `router/scoring.py`: ScoringEngine, ScoringPolicy classes
- `router/failover.py`: FailoverEngine class

### Step 2: Integrate with Existing Router
- Modify `AgentRouter` to use new components
- Add feature flags for new features
- Maintain backward compatibility

### Step 3: Update Router Preview
- Enhance response format with filter details
- Add policy information
- Show agent capabilities and resources

### Step 4: Implement Failover
- Add FailoverEngine integration
- Update Executor to call failover on failure
- Add failover tests

### Step 5: Add Comprehensive Tests
- Multi-agent skill tests
- Offline/disabled agent tests
- Incompatible mode tests
- Resource filter tests
- Failover tests
- Policy tests

### Step 6: Documentation
- Update API documentation
- Add configuration guide
- Add troubleshooting guide

---

## Summary

Router v3 introduces a comprehensive, capability-aware agent selection pipeline while maintaining full backward compatibility. The design allows for gradual migration and extensive configurability.

**Key Enhancements**:
1. Multi-stage filtering pipeline
2. Configurable scoring policies
3. Capability and resource awareness
4. Automatic failover mechanism
5. Enhanced debugging via Router Preview

**Backward Compatibility**: ✅ Fully maintained
**Configuration**: ✅ Environment variable + database + Redis
**Testing**: ✅ Comprehensive test coverage planned

---

**Design Complete**  
**Next Phase**: Implement Candidate Filter
