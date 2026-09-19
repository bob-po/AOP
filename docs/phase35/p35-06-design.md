# Phase 35.6: A2A Playground Design Document

**Date**: 2026-09-18  
**Objective**: Design A2A Playground for direct agent testing  
**Scope**: UI layout, backend APIs, component architecture

---

## Executive Summary

Designing a developer-facing A2A Playground that allows direct testing of agents without Orchestrator workflow overhead. The design includes a clean two-column layout with agent selection, request builder, real-time response, artifact viewing, and raw protocol inspection. Backend requires new direct A2A API endpoints to enable true single-agent testing.

---

## Architecture Decision

### Backend API Approach: Add Direct A2A API (Option 1)

**Rationale**:
- True direct A2A testing (not mediated by Orchestrator)
- Simple, single-agent workflow
- Matches developer expectations (similar to OpenAI Playground)
- Clean separation from task orchestration
- Can leverage existing A2A SDK in Gateway

---

## Backend API Design

### New API Endpoints

#### 1. List Agents with Card Info

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
- Fetch Agent Card from agent endpoint for each agent
- Merge card information into response
- Cache Agent Cards to avoid repeated fetches

#### 2. Get Agent Card

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

type AgentSkill = {
  id: string;
  name: string;
  description: string;
  inputModes: string[];
  outputModes: string[];
  examples: string[];
}
```

**Implementation**:
- Fetch agent from database
- Use A2A SDK to fetch Agent Card from agent endpoint
- Return full Agent Card JSON

#### 3. Send A2A Message

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

type Part = {
  type: "text" | "data" | "file";
  text?: string;
  data?: string;  // base64
  file?: {
    name: string;
    uri: string;
    mime_type: string;
  };
}
```

**Implementation**:
- Validate agent_id and skill_id
- Fetch agent endpoint from database
- Use A2A SDK to send message to agent
- Create internal A2A task record
- Return task_id and status

#### 4. Get A2A Task Status

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

type Message = {
  role: string;
  parts: Part[];
  message_id: string;
}

type Artifact = {
  name: string;
  parts: Part[];
}
```

**Implementation**:
- Query internal A2A task record
- Use A2A SDK to get task status from agent
- Return full task details

#### 5. WebSocket for Real-Time Events

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
- Adapt useWebSocket hook for A2A events
- Support event types: submitted, working, input_required, completed, failed, canceled, artifact_created

---

## UI Layout Design

### Two-Column Layout

```
┌─────────────────────────────────────────────────────────────┐
│ A2A Playground                                               │
├──────────────────┬──────────────────────────────────────────┤
│ Agent            │ Request                                  │
│                  │                                          │
│ Search Agent     │ Skill                                    │
│ RAG Agent        │ [web-search ▼]                           │
│ Analysis Agent   │                                          │
│ Report Agent     │ Message                                  │
│                  │ ┌──────────────────────────────────────┐ │
│                  │ │ Search NVIDIA robotics products      │ │
│                  │ └──────────────────────────────────────┘ │
│                  │                                          │
│                  │ [ Send A2A Task ]                        │
├──────────────────┴──────────────────────────────────────────┤
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

### Layout Specifications

**Left Column (Agent Selector)**: 280px fixed width
- Agent list with status indicators
- Agent selection with visual feedback
- Selected agent details

**Right Column (Request/Response)**: Flexible width
- Request builder (agent selected)
- Response viewer (task created)
- Events timeline
- Artifacts display

---

## Component Architecture

### New Components Structure

```
app/developer/
├── page.tsx                    # Developer Center index
├── playground/
│   ├── page.tsx              # A2A Playground main page
│   ├── AgentSelector.tsx     # Agent list and selection
│   ├── AgentCard.tsx         # Agent Card display
│   ├── RequestBuilder.tsx     # Request input form
│   ├── ResponseViewer.tsx     # Response display
│   ├── EventTimeline.tsx      # Real-time events
│   ├── ArtifactViewer.tsx     # Artifact display
│   ├── RawProtocolView.tsx   # Raw JSON display
│   └── ErrorDebug.tsx        # Error details
└── layout.tsx                 # Developer layout

components/developer/
├── DeveloperNav.tsx           # Developer navigation
└── A2APlayground.tsx          # Main playground component
```

### Component Hierarchy

```
DeveloperCenter
├── DeveloperNav
│   ├── API
│   ├── API Keys
│   ├── A2A Playground
│   └── Docs
└── A2APlayground
    ├── AgentSelector
    │   ├── AgentList
    │   └── AgentCard
    ├── RequestBuilder
    │   ├── SkillSelector
    │   └── MessageInput
    └── ResponseViewer
        ├── TaskHeader
        ├── EventTimeline
        ├── ArtifactViewer
        ├── RawProtocolView
        └── ErrorDebug
```

---

## Component Designs

### 1. Agent Selector

**Purpose**: List and select agents

**Display**:
```
┌─────────────────────────┐
│ Agents                  │
├─────────────────────────┤
│ ● Search Agent           │
│   ● online              │
│                         │
│ ○ RAG Agent             │
│   ● online              │
│                         │
│ ○ Analysis Agent        │
|   ● online              │
│                         │
│ ○ Report Agent          │
│   ● online              │
└─────────────────────────┘
```

**Features**:
- List agents with status indicators
- Click to select agent
- Show selected agent with ●
- Show online/offline status
- Filter by status (online only default)

**Data Source**: GET /v1/a2a/agents

### 2. Agent Card Display

**Purpose**: Show selected agent details

**Display**:
```
┌─────────────────────────┐
│ Search Agent            │
│ v0.3.0                  │
│                         │
│ Description:            │
│ Web search agent with   │
│ URL fetching capability  │
│                         │
│ Endpoint:               │
│ http://search-agent:8001│
│                         │
│ Protocol:               │
│ A2A 0.3.0               │
│                         │
│ Capabilities:           │
│ • web_browsing          │
│                         │
│ Skills:                 │
│ • web-search            │
│ • url-fetch             │
│ • research              │
│                         │
│ Input Modes:            │
│ text                    │
│                         │
│ Output Modes:           │
│ text, json              │
└─────────────────────────┘
```

**Features**:
- Show agent name and version
- Show description
- Show endpoint
- Show protocol version
- Show capabilities
- Show skills with examples
- Show input/output modes

**Data Source**: GET /v1/a2a/agents/{agent_id}/card

### 3. Skill Selector

**Purpose**: Select skill for request

**Display**:
```
┌─────────────────────────┐
│ Skill                   │
│ [web-search ▼]          │
│                         │
│ Options:                │
│ • web-search            │
│ • url-fetch             │
│ • research              │
└─────────────────────────┘
```

**Features**:
- Dropdown with agent's skills
- Only show skills from selected agent
- Show skill description on hover
- Default to first skill

**Data Source**: AgentCard.skills

### 4. Request Builder

**Purpose**: Build A2A message request

**Display**:
```
┌─────────────────────────┐
│ Message                 │
│ ┌─────────────────────┐ │
│ │ Search NVIDIA       │ │
│ │ robotics products   │ │
│ └─────────────────────┘ │
│                         │
│ [Add Part] [Clear]      │
│                         │
│ [ Send A2A Task ]       │
└─────────────────────────┘
```

**Features**:
- Text input area
- Support for multiple parts
- Add part button (text, data, file)
- Clear button
- Send button (disabled until agent selected)
- Validation: agent selected, skill selected, message provided

**Message Format**:
```json
{
  "role": "user",
  "parts": [
    {
      "type": "text",
      "text": "Search NVIDIA robotics products"
    }
  ],
  "message_id": "uuid"
}
```

### 5. Response Viewer

**Purpose**: Display A2A task response

**Display**:
```
┌─────────────────────────┐
│ Task ID: abc-12345      │
│ Status: ● completed     │
│ Duration: 2.3s          │
├─────────────────────────┤
│ Events                  │
│ ├── Task Created        │
│ ├── Message Received    │
│ ├── Working             │
│ └── Artifact Created    │
├─────────────────────────┤
│ Artifacts               │
│ • result.json           │
│   [Preview] [Download]  │
└─────────────────────────┘
```

**Features**:
- Task ID (copyable)
- Status with indicator
- Duration calculation
- Events timeline
- Artifacts list with actions

**Data Source**: GET /v1/a2a/tasks/{task_id}

### 6. Event Timeline

**Purpose**: Show real-time task events

**Display**:
```
┌─────────────────────────┐
│ Events                  │
│ 14:23:45 ● Task Created │
│ 14:23:46 ● Message Rec. │
│ 14:23:47 ● Working      │
│ 14:23:48 ● Artifact Cre.│
│ 14:23:49 ● Completed    │
└─────────────────────────┘
```

**Features**:
- Timestamp with formatting
- Event type
- Status indicator
- Auto-scroll to latest
- Color coding by event type

**Data Source**: WebSocket /v1/a2a/tasks/{task_id}/events/ws

### 7. Artifact Viewer

**Purpose**: Display task artifacts

**Display**:
```
┌─────────────────────────┐
│ Artifacts               │
│                         │
│ 📄 result.json          │
│ 2.3 KB                  │
│ [Preview] [Download]    │
│                         │
│ 📊 data.json            │
│ 1.1 KB                  │
│ [Preview] [Download]    │
└─────────────────────────┘
```

**Features**:
- Type icon
- Name
- Size
- Preview button (opens modal)
- Download button
- Type-specific preview

**Artifact Types**:
- Text: Plain text preview
- JSON: Syntax highlighted preview
- Image: Image preview
- Video: Video player
- PDF: PDF viewer
- PPT: PowerPoint viewer
- File: Download only

### 8. Raw Protocol View

**Purpose**: Show raw A2A protocol

**Display**:
```
┌─────────────────────────┐
│ Raw A2A                 │
│                         │
│ Request JSON [▼]        │
│ ┌─────────────────────┐ │
│ │ {                   │ │
│ │   "role": "user",   │ │
│ │   "parts": [...]    │ │
│ │ }                   │ │
│ └─────────────────────┘ │
│ [Copy]                  │
│                         │
│ Response JSON [▼]       │
│ ┌─────────────────────┐ │
│ │ {                   │ │
│ │   "id": "abc-123",  │ │
│ │   "status": "...",  │ │
│ │   "artifacts": [...]│ │
│ │ }                   │ │
│ └─────────────────────┘ │
│ [Copy]                  │
└─────────────────────────┘
```

**Features**:
- Collapsible JSON sections
- Syntax highlighting
- Copy button
- Show full request/response
- Task ID and messages

### 9. Error Debug

**Purpose**: Show error details

**Display**:
```
┌─────────────────────────┐
│ Error                   │
│                         │
│ HTTP Status: 500        │
│                         │
│ A2A Error Code:         │
│ EXECUTION_FAILED        │
│                         │
│ Message:                │
│ Agent timeout           │
│                         │
│ Task Status: failed      │
│                         │
│ Agent: search-agent     │
│ Endpoint: http://...    │
└─────────────────────────┘
```

**Features**:
- HTTP status code
- A2A error code
- Error message
- Task status
- Agent information
- Retry button

---

## API Layer Extensions

### New API Functions

**Location**: `apps/web/lib/api.ts`

```typescript
// A2A Agent APIs
export function listA2AAgents(params?: { status?: string })
  → { agents: AgentWithCard[] }

export function getA2AAgentCard(agentId: string)
  → AgentCard

// A2A Task APIs
export function sendA2AMessage(body: {
  agent_id: string;
  skill_id: string;
  message: Message;
})
  → { task_id: string; status: string }

export function getA2ATask(taskId: string)
  → A2ATask

// Type Extensions
export type AgentWithCard = Agent & {
  card_json?: AgentCard;
  version?: string;
  capabilities?: string[];
  input_modes?: string[];
  output_modes?: string[];
}

export type A2ATask = {
  task_id: string;
  status: string;
  messages: Message[];
  artifacts: Artifact[];
  created_at: string;
  updated_at: string;
}

export type Message = {
  role: string;
  parts: Part[];
  message_id: string;
}

export type Part = {
  type: "text" | "data" | "file";
  text?: string;
  data?: string;
  file?: {
    name: string;
    uri: string;
    mime_type: string;
  };
}

export type AgentCard = {
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

export type AgentSkill = {
  id: string;
  name: string;
  description: string;
  inputModes: string[];
  outputModes: string[];
  examples: string[];
}
```

---

## State Management

### State Requirements

**State Needed**:
- Selected agent ID
- Selected agent card
- Selected skill ID
- Message parts
- Current task ID
- Task status
- Task events
- Task artifacts
- WebSocket connection status

**Approach**: Component-level useState (no global state needed for single-page playground)

---

## WebSocket Integration

### Adapt useWebSocket Hook

**New Hook**: `useA2ATaskWebSocket(taskId: string)`

**Implementation**:
- Adapt existing useWebSocket
- Use A2A WebSocket endpoint: `/v1/a2a/tasks/{taskId}/events/ws`
- Support event types: submitted, working, input_required, completed, failed, canceled, artifact_created
- Auto-reconnect with existing logic

---

## Design System

### Modern AI Developer Tools Style

**Color Palette (White/Neutral)**:
- Background: #ffffff (white)
- Background subtle: #f8fafc (neutral-50)
- Border: #e2e8f0 (neutral-200)
- Border focus: #3b82f6 (blue-500)
- Text primary: #0f172a (slate-900)
- Text secondary: #475569 (slate-600)
- Text monospace: #1e293b (slate-800)

**Typography**:
- Sans-serif: Inter or system-ui
- Monospace: JetBrains Mono or system-monospace
- Font sizes: text-xs (12px), text-sm (14px), text-base (16px)

**Borders**:
- Radius: rounded-lg (8px), rounded-xl (12px)
- Shadows: shadow-sm, shadow
- Spacing: space-2 (8px), space-4 (16px), space-6 (24px)

**Style Guidelines**:
- No purple SaaS gradients
- No traditional admin dashboard styling
- Clean, minimal design
- High information density
- Monospace for JSON/protocol
- Subtle borders and shadows

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

## Summary

The A2A Playground design provides a clean, developer-friendly interface for direct agent testing. The design includes:

**Key Features**:
- Two-column layout (Agent + Request/Response)
- Agent selection with card details
- Skill selector based on agent capabilities
- Request builder with multiple part support
- Real-time response with event timeline
- Artifact viewer with type-specific rendering
- Raw protocol view for debugging
- Error debugging with detailed information

**Backend Requirements**:
- 5 new API endpoints for direct A2A access
- WebSocket support for real-time events
- Agent Card integration
- A2A SDK usage in Gateway

**Technical Stack**:
- Next.js 15.1.0 with App Router
- React 19.0.0 with TypeScript
- Tailwind CSS 3.4.16
- Existing WebSocket infrastructure
- Existing A2A SDK

**Design Alignment**:
- Modern AI developer tools style
- White/neutral theme
- Subtle borders and shadows
- High information density
- Monospace for JSON/protocol

---

**Design Complete**  
**Next Phase**: Implement backend APIs (Phase 1)
