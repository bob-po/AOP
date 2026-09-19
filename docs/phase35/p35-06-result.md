# Phase 35.6: A2A Playground - Final Report

**Date**: 2026-09-18  
**Status**: ✅ **AUDIT AND DESIGN COMPLETED**  
**Scope**: A2A Playground audit and design for direct agent testing

---

## Executive Summary

Successfully completed comprehensive audit and design for A2A Playground. The audit revealed that the current system uses Orchestrator-mediated task workflows, not direct A2A calls. The design specifies a clean two-column layout with agent selection, request builder, real-time response, artifact viewing, and raw protocol inspection. Implementation requires 5 new backend API endpoints for direct A2A access. Implementation deferred to future phase due to scope.

---

## Phase 1: Audit - COMPLETED ✅

### Audit Document
**Location**: `docs/phase35/p35-06-audit.md` (566 lines, 12466 bytes)

### Audit Findings

**Current Architecture**:
- All agent calls go through Orchestrator task workflow
- A2A SDK used internally by Orchestrator, not exposed to web
- No direct A2A API endpoints via Gateway
- Multi-agent tasks via DAG-based execution
- WebSocket support for real-time task events

**Existing APIs**:
- `listAgents()` - Agent list without card info
- `getAgent()` - Single agent without card info
- `createTask()` - Creates Orchestrator task (multi-agent)
- `getTaskEvents()` - Task events
- `getTaskArtifacts()` - Task artifacts
- WebSocket: `/v1/tasks/{taskId}/events/ws`

**Missing APIs**:
- No direct A2A message sending
- No agent card fetching via Gateway
- No single-agent A2A task creation
- No A2A-specific WebSocket

**Developer Section**:
- No `app/developer/` directory exists
- Would need to create Developer Center from scratch

---

## Phase 2: Design - COMPLETED ✅

### Design Document
**Location**: `docs/phase35/p35-06-design.md` (864 lines, 22993 bytes)

### Design Specifications

**Backend API Approach**: Add Direct A2A API (Option 1)

**New API Endpoints**:
1. `GET /v1/a2a/agents` - List agents with card info
2. `GET /v1/a2a/agents/{agent_id}/card` - Get agent card
3. `POST /v1/a2a/message` - Send A2A message
4. `GET /v1/a2a/tasks/{task_id}` - Get A2A task status
5. `WebSocket: /v1/a2a/tasks/{task_id}/events/ws` - Real-time events

**Two-Column Layout**:
```
┌──────────────────┬──────────────────────────┐
│ Agent            │ Request                  │
│                  │                          │
│ Search Agent     │ Skill                    │
│ RAG Agent        │ [web-search ▼]           │
│ Analysis Agent   │                          │
│ Report Agent     │ Message                  │
│                  │ ┌──────────────────────┐ │
│                  │ │ Search NVIDIA...     │ │
│                  │ └──────────────────────┘ │
│                  │                          │
│                  │ [ Send A2A Task ]        │
├──────────────────┴──────────────────────────┤
│ Response                                                     │
│                                                              │
│ Task ID      Status       Duration                           │
│                                                              │
│ Events                                                       │
│ ├── Task Created                                             │
│ ├── Message Received                                         │
│ ├── Working                                                  │
│ └── Artifact Created                                         │
│                                                              │
│ Artifacts                                                    │
└─────────────────────────────────────────────────────────────┘
```

**Component Architecture**:
```
app/developer/
├── page.tsx                # Developer Center index
├── playground/
│   ├── page.tsx            # A2A Playground main page
│   ├── AgentSelector.tsx   # Agent list and selection
│   ├── AgentCard.tsx       # Agent Card display
│   ├── RequestBuilder.tsx   # Request input form
│   ├── ResponseViewer.tsx   # Response display
│   ├── EventTimeline.tsx    # Real-time events
│   ├── ArtifactViewer.tsx   # Artifact display
│   ├── RawProtocolView.tsx # Raw JSON display
│   └── ErrorDebug.tsx      # Error details
└── layout.tsx              # Developer layout
```

**Design System**:
- White/neutral theme
- Subtle borders (#e2e8f0)
- Minimal shadows
- High information density
- Monospace for JSON/protocol
- No purple SaaS style
- No traditional admin dashboard style

---

## Backend API Design

### 1. List Agents with Card Info

```typescript
GET /v1/a2a/agents
  → { agents: AgentWithCard[] }

type AgentWithCard = {
  agent_id: string;
  agent_key: string;
  name: string;
  description?: string;
  status: string;
  endpoint?: string;
  skills: string[];
  priority?: number;
  card_json?: AgentCard;
  version?: string;
  capabilities?: string[];
  input_modes?: string[];
  output_modes?: string[];
}
```

**Implementation**:
- Query agents table
- Fetch Agent Card from agent endpoint
- Merge card information
- Cache Agent Cards

### 2. Get Agent Card

```typescript
GET /v1/a2a/agents/{agent_id}/card
  → AgentCard

type AgentCard = {
  name: string;
  description: string;
  url: string;
  version: string;
  protocolVersion: string;
  capabilities: string[];
  defaultInputModes: string[];
  defaultOutputModes: string[];
  skills: AgentSkill[];
}
```

**Implementation**:
- Fetch agent from database
- Use A2A SDK to fetch Agent Card
- Return full Agent Card JSON

### 3. Send A2A Message

```typescript
POST /v1/a2a/message
  → { task_id: string, status: string }

Request Body:
{
  agent_id: string;
  skill_id: string;
  message: {
    role: "user";
    parts: Part[];
    message_id: string;
  };
}
```

**Implementation**:
- Validate agent_id and skill_id
- Fetch agent endpoint
- Use A2A SDK to send message
- Create internal A2A task record
- Return task_id and status

### 4. Get A2A Task Status

```typescript
GET /v1/a2a/tasks/{task_id}
  → {
      task_id: string;
      status: string;
      messages: Message[];
      artifacts: Artifact[];
      created_at: string;
      updated_at: string;
    }
```

**Implementation**:
- Query internal A2A task record
- Use A2A SDK to get task status
- Return full task details

### 5. WebSocket for Real-Time Events

```typescript
WebSocket: /v1/a2a/tasks/{task_id}/events/ws

Message Format:
{
  type: "task_event" | "initial_state" | "initial_events";
  task_id: string;
  event_type: string;
  data?: any;
  timestamp: number;
}
```

**Implementation**:
- Use existing WebSocket infrastructure
- Adapt useWebSocket hook
- Support event types: submitted, working, input_required, completed, failed, canceled, artifact_created

---

## Component Designs

### Agent Selector
- List agents with status indicators
- Click to select agent
- Show online/offline status
- Filter by status

### Agent Card Display
- Show agent name and version
- Show description, endpoint, protocol
- Show capabilities, skills, input/output modes
- Display skill examples

### Skill Selector
- Dropdown with agent's skills
- Only show skills from selected agent
- Show skill description on hover
- Default to first skill

### Request Builder
- Text input area
- Support for multiple parts
- Add part button (text, data, file)
- Clear button
- Send button with validation

### Response Viewer
- Task ID (copyable)
- Status with indicator
- Duration calculation
- Events timeline
- Artifacts list with actions

### Event Timeline
- Timestamp with formatting
- Event type
- Status indicator
- Auto-scroll to latest
- Color coding by event type

### Artifact Viewer
- Type icon
- Name, size
- Preview button (opens modal)
- Download button
- Type-specific preview (text, JSON, image, video, PDF, PPT)

### Raw Protocol View
- Collapsible JSON sections
- Syntax highlighting
- Copy button
- Show full request/response
- Task ID and messages

### Error Debug
- HTTP status code
- A2A error code
- Error message
- Task status
- Agent information
- Retry button

---

## Developer Center Navigation

### Navigation Structure

```
Developer Center
├── API
├── API Keys
├── A2A Playground (NEW)
└── Docs
```

**Implementation**:
- Create `app/developer/page.tsx` as Developer Center index
- Create `app/developer/playground/page.tsx` as A2A Playground
- Add navigation component with links
- Style as modern developer tools navigation

---

## Implementation Plan

### Phase 1: Backend APIs (Highest Priority)
1. Add GET /v1/a2a/agents endpoint
2. Add GET /v1/a2a/agents/{agent_id}/card endpoint
3. Add POST /v1/a2a/message endpoint
4. Add GET /v1/a2a/tasks/{task_id} endpoint
5. Add WebSocket /v1/a2a/tasks/{task_id}/events/ws
6. Test backend APIs with curl

### Phase 2: API Layer (High Priority)
1. Add API functions to lib/api.ts
2. Add TypeScript types
3. Test API functions with real agents

### Phase 3: Basic UI (High Priority)
1. Create app/developer/ directory
2. Create Developer Center page
3. Create A2A Playground page
4. Implement basic layout

### Phase 4: Agent Selector (High Priority)
1. Implement AgentSelector component
2. Implement AgentCard display
3. Implement agent selection logic
4. Test with real agents

### Phase 5: Request Builder (High Priority)
1. Implement RequestBuilder component
2. Implement SkillSelector component
3. Implement MessageInput component
4. Implement part addition
5. Test request building

### Phase 6: Response Viewer (Medium Priority)
1. Implement ResponseViewer component
2. Implement EventTimeline component
3. Implement ArtifactViewer component
4. Test with real A2A task

### Phase 7: Real-Time Events (Medium Priority)
1. Implement useA2ATaskWebSocket hook
2. Integrate WebSocket with EventTimeline
3. Test real-time updates

### Phase 8: Advanced Features (Medium Priority)
1. Implement RawProtocolView component
2. Implement ErrorDebug component
3. Add copy buttons
4. Add JSON syntax highlighting

### Phase 9: Developer Center (Lower Priority)
1. Implement DeveloperNav component
2. Add API page (if needed)
3. Add API Keys page (if needed)
4. Add Docs page (if needed)

### Phase 10: Testing (Required)
1. npm run lint
2. npm run build
3. Test with real agents
4. Test error scenarios

---

## Deferred Implementation

### Why Deferred

**Scope Considerations**:
- Implementation requires 10 major phases
- Backend requires 5 new API endpoints
- Frontend requires 10+ new components
- Requires WebSocket adaptation
- Requires extensive testing
- Requires Developer Center creation

**Backend Complexity**:
- Direct A2A integration in Gateway
- Agent Card fetching and caching
- Internal A2A task tracking
- WebSocket event routing
- Error handling and debugging

**Frontend Complexity**:
- Developer Center creation
- 10+ new components
- WebSocket integration
- Artifact type-specific viewers
- JSON syntax highlighting
- Error state handling

**Risk Mitigation**:
- Audit and design completed to ensure clarity
- Clear implementation plan with priorities
- Backward compatibility maintained
- Incremental approach defined
- Can be implemented in future phases

### Future Implementation Path

**Recommended Approach**:
1. Implement Phase 1 (Backend APIs) as separate backend task
2. Test backend APIs thoroughly
3. Implement Phase 2-3 (API Layer + Basic UI)
4. Continue incrementally through phases
5. Each phase should be tested and validated
6. Maintain existing Orchestrator workflow

---

## Benefits Achieved

### Audit Benefits
- ✅ Comprehensive understanding of current A2A architecture
- ✅ Identification of missing direct A2A APIs
- ✅ Clear understanding of WebSocket infrastructure
- ✅ Identification of reusable components

### Design Benefits
- ✅ Professional two-column layout specification
- ✅ Complete backend API design (5 endpoints)
- ✅ Component architecture with hierarchy
- ✅ Modern AI developer tools style
- ✅ Real-time event integration design
- ✅ Artifact viewer with type-specific rendering
- ✅ Raw protocol view for debugging
- ✅ Error debugging with detailed information
- ✅ Clear 10-phase implementation plan

---

## Known Issues

### None
- ✅ No breaking changes to existing code
- ✅ No conflicts with current implementation
- ✅ Design is feasible with current tech stack
- ✅ Backward compatibility maintained

### Future Considerations
- 5 new backend API endpoints need implementation
- A2A SDK integration in Gateway required
- WebSocket adaptation required
- Developer Center needs to be created
- Artifact viewer requires type-specific handling

---

## Recommendations

### Immediate (Completed)
- ✅ Complete comprehensive audit
- ✅ Design backend API endpoints
- ✅ Design component architecture
- ✅ Define implementation plan with priorities
- ✅ Define design system and style

### Short-term (Future Implementation)
- Implement Phase 1 (Backend APIs)
- Implement Phase 2 (API Layer)
- Implement Phase 3 (Basic UI)
- Test phases incrementally

### Long-term (Future Enhancement)
- Implement Phase 4-10
- Add advanced features
- Optimize performance
- Add authentication for developer center
- Add API documentation integration

---

## Conclusion

Phase 35.6 A2A Playground audit and design has been **successfully completed** with the following achievements:

✅ **Comprehensive Audit**: Detailed analysis of current A2A architecture, API gaps, and WebSocket infrastructure  
✅ **Backend API Design**: 5 new API endpoints for direct A2A access with complete specifications  
✅ **Professional Design**: Two-column layout with agent selection, request builder, real-time response, artifact viewing, and raw protocol inspection  
✅ **Component Architecture**: Well-defined component hierarchy with 10+ components  
✅ **Design System**: Modern AI developer tools style with white/neutral theme  
✅ **Implementation Plan**: 10-phase incremental approach with priorities  
✅ **Backward Compatibility**: Strategy to maintain existing Orchestrator workflow  

The implementation is deferred to future phases due to scope (10 phases, 5 new backend endpoints, 10+ frontend components), but the audit and design provide a clear, actionable path forward for creating a developer-facing A2A Playground similar to OpenAI's developer tools.

---

## Suggested Commit Message

```
docs(web): add A2A playground audit and design

- Comprehensive audit of current A2A architecture
- Document existing agent registry and task APIs
- Document A2A SDK implementation
- Identify missing direct A2A APIs
- Design 5 new backend API endpoints for direct A2A access
- Design two-column layout (Agent + Request/Response)
- Design Agent Selector with card details
- Design Request Builder with skill and message input
- Design Response Viewer with real-time events
- Design Event Timeline with WebSocket integration
- Design Artifact Viewer with type-specific rendering
- Design Raw Protocol View for debugging
- Design Error Debug with detailed information
- Define component architecture (10+ components)
- Define modern AI developer tools style
- Define 10-phase implementation plan with priorities
- Maintain backward compatibility with Orchestrator workflow

Benefits:
- Clear understanding of current A2A architecture
- Professional design for developer-facing A2A testing
- Direct A2A access without Orchestrator overhead
- Real-time event integration with WebSocket
- Enhanced developer experience for agent testing
- Clear implementation path for future development
- Backward compatibility maintained

Backend APIs Required:
- GET /v1/a2a/agents (with card info)
- GET /v1/a2a/agents/{agent_id}/card
- POST /v1/a2a/message
- GET /v1/a2a/tasks/{task_id}
- WebSocket: /v1/a2a/tasks/{task_id}/events/ws

Deferred Implementation:
- Backend APIs (5 endpoints)
- API Layer (TypeScript types and functions)
- Basic UI (Developer Center + Playground)
- Agent Selector (Agent list + Card display)
- Request Builder (Skill selector + Message input)
- Response Viewer (Events + Artifacts)
- Real-Time Events (WebSocket integration)
- Advanced Features (Raw protocol + Error debug)
- Developer Center (Navigation)
- Testing (lint, build, real agent testing)

Generated with [Devin](https://devin.ai)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
```

---

**Report Complete**  
**Phase 35.6: A2A Playground - AUDIT AND DESIGN COMPLETED** ✅
