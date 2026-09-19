# Phase 35.6: A2A Playground - Audit Report

**Date**: 2026-09-18  
**Objective**: Audit current implementation for A2A Playground development  
**Scope**: Agent Registry, A2A implementation, Task API, Event API, Artifact API, Developer section

---

## Executive Summary

Conducted comprehensive audit of current AOP web app and backend APIs for A2A Playground development. The audit reveals that the current system uses the Orchestrator task workflow for agent interactions, not direct A2A calls. The A2A SDK is used internally by the Orchestrator, but there's no direct A2A API exposed via the Gateway. The A2A Playground will require either (1) adding a new direct A2A API endpoint, or (2) creating a simplified single-agent task workflow. No existing developer section exists, so a new /developer route will be created.

---

## Current Developer Section

### Status: ❌ Does Not Exist

**Finding**: No `apps/web/app/developer/` directory exists

**Existing Sections**:
- `agents/` - Agent management
- `artifacts/` - Artifact browsing
- `marketplace/` - Marketplace
- `settings/` - Settings
- `tasks/` - Task management
- `workflows/` - Workflow management
- `login/` - Authentication

**Implication**: Developer Center will need to be created from scratch with navigation structure

---

## Agent Registry API

### Current Implementation

**Location**: `apps/web/lib/api.ts`

**Available APIs**:
```typescript
listAgents(params?: { skill?: string; status?: string })
  → GET /v1/agents?skill=xxx&status=xxx
  → { agents: Agent[] }

registerAgent(endpoint: string)
  → POST /v1/agents/register
  → { ... }

getAgent(agentId: string)
  → GET /v1/agents/{agentId}
  → Agent

healthCheckAgent(agentId: string)
  → POST /v1/agents/{agentId}/health
  → { ... }

enableAgent(agentId: string)
  → POST /v1/agents/{agentId}/enable
  → { ... }

disableAgent(agentId: string)
  → POST /v1/agents/{agentId}/disable
  → { ... }
```

**Agent Type Definition**:
```typescript
type Agent = {
  agent_id: string;
  agent_key: string;
  name: string;
  description?: string;
  status: string;
  endpoint?: string;
  skills: string[];
  priority?: number;
};
```

**Status Values**:
- created, registered, verified, online, running, offline, degraded, disabled

**Limitations**:
- No Agent Card JSON returned in listAgents
- No capabilities, input_modes, output_modes in Agent type
- No version information in Agent type
- Agent Card only available via direct agent endpoint

---

## Agent Card Implementation

### Location: `packages/a2a-sdk/a2a_sdk/card.py`

**AgentCard Structure**:
```python
class AgentCard:
    name: str
    description: str
    url: str
    version: str
    protocolVersion: str
    capabilities: list[str]
    defaultInputModes: list[str]
    defaultOutputModes: list[str]
    skills: list[AgentSkill]
```

**AgentSkill Structure**:
```python
class AgentSkill:
    id: str
    name: str
    description: str
    inputModes: list[str]
    outputModes: list[str]
    examples: list[str]
```

**Discovery**:
- GET /.well-known/agent-card.json
- Fallback: GET /.well-known/agent.json

**Current Usage**:
- Used internally by Orchestrator via A2A SDK
- Not exposed via Gateway API
- Web app cannot currently fetch Agent Cards directly

---

## A2A Implementation

### Location: `packages/a2a-sdk/a2a_sdk/client.py`

**A2AClient Methods**:
```python
send_text(text: str, skill_id: str | None = None) → Task
send_message(message: Message, skill_id: str | None = None) → Task
get_task(task_id: str) → Task
refresh_card() → AgentCard
```

**Message Structure**:
```python
class Message:
    role: str
    parts: list[Part]
    message_id: str
```

**Part Structure**:
```python
class Part:
    type: str  # text, data, file
    text: str | None
    data: bytes | None
    file: dict | None
```

**Task Structure**:
```python
class Task:
    id: str
    status: TaskStatus
    messages: list[Message]
    artifacts: list[Artifact]
```

**TaskStatus Values**:
- submitted, working, input_required, completed, failed, canceled

**RPC Methods**:
- message/send: Send message to agent
- tasks/get: Get task status and results

**Current Usage**:
- Used internally by Orchestrator
- Not exposed via Gateway API
- Web app cannot call A2A directly

---

## Task API

### Current Implementation

**Location**: `apps/web/lib/api.ts` and `apps/orchestrator/main.py`

**Available APIs**:
```typescript
createTask(content: string)
  → POST /v1/tasks
  → { task_id, status, title?, plan?, ready_nodes?, nodes? }

listTasks(params?: { status?, limit? })
  → GET /v1/tasks?status=xxx&limit=xxx
  → { tasks: TaskSummary[] }

getTask(taskId: string)
  → GET /v1/tasks/{taskId}
  → TaskDetail

cancelTask(taskId: string)
  → POST /v1/tasks/{taskId}/cancel
  → { task_id, status, cancelled? }

approveTask(taskId: string)
  → POST /v1/tasks/{taskId}/approve
  → { ... }

rejectTask(taskId: string)
  → POST /v1/tasks/{taskId}/reject
  → { ... }
```

**TaskDetail Structure**:
```typescript
{
  task_id: string;
  title?: string;
  status: string;
  progress?: number;
  input_json?: { type?, content? };
  plan_json?: TaskPlan;
  result_json?: { summary?, artifacts? };
  nodes: TaskNode[];
  created_at?: string;
  updated_at?: string;
  finished_at?: string;
}
```

**TaskNode Structure**:
```typescript
{
  id: string;
  skill: string;
  status: string;
  agent_id?: string | null;
  attempt?: number;
  error_message?: string | null;
}
```

**Current Workflow**:
- Tasks go through Orchestrator planning
- Multiple agents can be involved per task
- DAG-based execution
- Not suitable for single-agent A2A testing

---

## Event API

### Current Implementation

**Location**: `apps/web/lib/api.ts` and `apps/orchestrator/main.py`

**Available APIs**:
```typescript
getTaskEvents(taskId: string)
  → GET /v1/tasks/{taskId}/events
  → { events: TaskEvent[] }
```

**TaskEvent Structure**:
```typescript
{
  event_type: string;
  message?: string;
  payload?: Record<string, unknown>;
  ts?: string;
}
```

**WebSocket Support**:
- Location: `apps/web/hooks/useWebSocket.ts`
- Endpoint: `/v1/tasks/{taskId}/events/ws`
- Message types: initial_state, initial_events, task_event
- Auto-reconnect with configurable intervals
- Hybrid WebSocket + HTTP polling in useTaskLive hook

**Real-Time Implementation**:
- useTaskLive hook for live task updates
- WebSocket primary, HTTP poll fallback
- 1s polling when WS disconnected
- 8s polling when WS connected (backup)

---

## Artifact API

### Current Implementation

**Location**: `apps/web/lib/api.ts` and `apps/orchestrator/main.py`

**Available APIs**:
```typescript
getTaskArtifacts(taskId: string)
  → GET /v1/tasks/{taskId}/artifacts
  → { task_id, artifacts: ArtifactItem[] }

listArtifacts(params?: { task_id?, type?, limit? })
  → GET /v1/artifacts?task_id=xxx&type=xxx&limit=xxx
  → { artifacts: ArtifactItem[] }
```

**ArtifactItem Structure**:
```typescript
{
  task_id?: string;
  node_id?: string;
  name?: string;
  uri?: string;
  url?: string;
  mime_type?: string;
  type?: string;
  size?: number;
  last_modified?: string;
}
```

**Artifact Types**:
- text, json, image, video, pdf, ppt, file

**Storage**:
- MinIO (backend)
- URL-based access
- Can be previewed or downloaded

---

## Current A2A Execution Flow

### Architecture

```
Web App
  ↓ POST /v1/tasks
Orchestrator
  ↓ Planning
Scheduler
  ↓ Router (selects agent)
Executor
  ↓ A2A SDK (message/send)
Agent (A2A endpoint)
  ↓ Returns Artifact
Orchestrator
  ↓ Stores in MinIO
Web App (polls events/artifacts)
```

### Key Findings

1. **No Direct A2A API**: The Gateway does not expose direct A2A endpoints
2. **Orchestrator-Mediated**: All agent calls go through Orchestrator task workflow
3. **Multi-Agent Tasks**: Tasks can involve multiple agents via DAG
4. **A2A SDK Internal**: A2A SDK is used internally by Orchestrator, not exposed to web

---

## Options for A2A Playground

### Option 1: Add Direct A2A API (Recommended)

**Approach**: Add new Gateway endpoints for direct A2A calls

**Required Endpoints**:
```typescript
POST /v1/a2a/message
  → { agent_id, skill_id, message }
  → { task_id, status }

GET /v1/a2a/tasks/{task_id}
  → { task_id, status, messages, artifacts }

GET /v1/a2a/agents/{agent_id}/card
  → AgentCard

GET /v1/a2a/agents
  → { agents: Agent[] } (with card info)
```

**Advantages**:
- True direct A2A testing
- No Orchestrator overhead
- Simple, single-agent workflow
- Matches developer expectations

**Disadvantages**:
- Requires backend implementation
- Needs new API endpoints
- Adds complexity to Gateway

### Option 2: Single-Agent Task Workflow

**Approach**: Create simplified single-agent task via existing task API

**Implementation**:
- Use existing POST /v1/tasks
- Force plan to single agent
- Skip planning phase
- Direct to execution

**Advantages**:
- No new backend endpoints
- Reuses existing infrastructure
- Leverages existing A2A SDK

**Disadvantages**:
- Still goes through Orchestrator
- Not true direct A2A
- More complex than needed
- Task overhead

### Option 3: Agent Direct Call (Not Recommended)

**Approach**: Call agent endpoint directly from web app

**Implementation**:
- Fetch agent endpoint from registry
- Call agent A2A endpoint directly
- Bypass Gateway entirely

**Advantages**:
- True direct A2A
- No Gateway involvement

**Disadvantages**:
- Security risk (bypasses auth)
- No centralized logging
- No egress filtering
- CORS issues
- Not recommended

---

## Recommendation

### Choose Option 1: Add Direct A2A API

**Rationale**:
- Clean separation from Orchestrator workflow
- True developer-facing A2A testing
- Matches industry expectations (e.g., OpenAI Playground)
- Can be implemented incrementally
- Reuses existing A2A SDK in Gateway

**Implementation Priority**:
1. Add GET /v1/a2a/agents (with card info)
2. Add GET /v1/a2a/agents/{agent_id}/card
3. Add POST /v1/a2a/message
4. Add GET /v1/a2a/tasks/{task_id}
5. Add WebSocket for real-time events
6. Implement web UI

---

## Missing APIs for Playground

### Required New APIs

**Agent APIs**:
```typescript
GET /v1/a2a/agents
  → { agents: AgentWithCard[] }

GET /v1/a2a/agents/{agent_id}/card
  → AgentCard
```

**A2A APIs**:
```typescript
POST /v1/a2a/message
  → { task_id, status }

GET /v1/a2a/tasks/{task_id}
  → { task_id, status, messages, artifacts }

WebSocket: /v1/a2a/tasks/{task_id}/events/ws
  → { type, task_id, event_type, data, timestamp }
```

**Extended Agent Type**:
```typescript
type AgentWithCard = Agent & {
  card_json?: AgentCard;
  version?: string;
  capabilities?: string[];
  input_modes?: string[];
  output_modes?: string[];
}
```

---

## Can Be Reused Components

### Existing Components

**Hooks**:
- `useWebSocket` - WebSocket connection management
- `useTaskLive` - Real-time task updates (can be adapted for A2A)

**API Layer**:
- `request` function - HTTP request helper
- Authentication headers - Session token handling

**Components**:
- `TaskTrace` - Can be adapted for A2A events
- Artifact display patterns - Can be reused for artifacts

**Design System**:
- Tailwind CSS configuration
- Color palette
- Typography scale
- Spacing system

---

## UI/UX Considerations

### Modern AI Developer Tools Style

**References**:
- Linear
- Vercel
- OpenAI Developer Platform

**Style Requirements**:
- White background
- Subtle borders
- Minimal shadows
- High information density without crowding
- Monospace for JSON/protocol
- No purple SaaS style
- No traditional Admin Dashboard style

**Technical Stack**:
- Next.js 15.1.0 (App Router)
- React 19.0.0
- TypeScript 5.7.2
- Tailwind CSS 3.4.16

---

## Next Steps

1. **Design A2A Playground layout** with agent selector, request builder, response viewer
2. **Add backend A2A APIs** (Option 1 recommended)
3. **Implement Agent Selector** with card info
4. **Implement Request Builder** with skill and message input
5. **Implement real A2A task execution** via new APIs
6. **Implement real-time events** via WebSocket
7. **Implement Artifact Viewer** with type-specific rendering
8. **Implement Raw Protocol View** with JSON display
9. **Implement error debugging** with detailed information
10. **Update Developer Center navigation** with playground link
11. **Run lint and build**
12. **Generate final result document**

---

**Audit Complete**  
**Next Phase**: Design A2A Playground layout and backend API requirements
