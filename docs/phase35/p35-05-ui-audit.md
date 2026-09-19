# Phase 35.5: Task Workspace UI Audit Report

**Date**: 2026-09-18  
**Objective**: Audit current web app structure for Task Workspace upgrade  
**Scope**: apps/web/ - Task pages, components, API, real-time events

---

## Executive Summary

Conducted comprehensive audit of the current AOP web application. The app already has a solid foundation with Next.js 15, React 19, TypeScript, Tailwind CSS, ReactFlow for DAG visualization, and WebSocket support for real-time updates. The current TaskWorkspace component provides basic task viewing with DAG visualization and event tracing, but needs enhancement to become a full-featured Agent Task Workspace with three-column layout, node inspection, and HITL support.

---

## Technology Stack

### Core Framework
- **Next.js**: 15.1.0 (App Router)
- **React**: 19.0.0
- **TypeScript**: 5.7.2
- **Tailwind CSS**: 3.4.16

### Visualization Libraries
- **ReactFlow**: 11.11.4 (DAG graph visualization)
- **Recharts**: 3.10.1 (Charts)

### Build Tools
- **PostCSS**: 8.4.49
- **Autoprefixer**: 10.4.20

### Package Scripts
```json
{
  "dev": "next dev -p 3000",
  "build": "next build",
  "start": "next start -p 3000",
  "lint": "next lint"
}
```

---

## Current Page Structure

### App Directory Structure
```
apps/web/app/
├── agents/              # Agent management pages
├── artifacts/           # Artifact browsing pages
├── dashboard/           # Dashboard components
├── login/               # Authentication pages
├── marketplace/         # Marketplace pages
├── settings/            # Settings pages
├── shell/                # Shell/terminal components
├── tasks/                # Task pages
│   ├── page.tsx        # Task list page
│   └── [id]/           # Task detail page
│       └── page.tsx    # Individual task workspace
├── workflows/            # Workflow pages
├── layout.tsx           # Root layout
├── page.tsx            # Home page
└── globals.css          # Global styles
```

### Current Task Pages

**Task List Page** (`app/tasks/page.tsx`):
- Uses TasksWorkspace component
- Shows task list with filtering
- Suspense fallback for loading

**Task Detail Page** (`app/tasks/[id]/page.tsx`):
- Uses TasksWorkspace component with initialTaskId
- Suspense fallback for loading
- Route parameter: taskId

---

## Current Components

### Task-Related Components

**TaskWorkspace.tsx** (5150 bytes, 139 lines):
- Main task viewing component
- HTTP polling every 1 second
- Shows task summary, DAG, artifacts, trace
- Two-column layout (DAG + sidebar)
- Polling stops when task completed/failed
- Fetches artifacts on completion

**TaskDag.tsx** (5359 bytes, 162 lines):
- SVG-based DAG visualization
- Custom layout algorithm (layered by dependency depth)
- Node status colors:
  - pending: #4a665c
  - ready: #ffb454
  - running: #3dffa8 (with animation)
  - success: #7eaea0
  - failed: #ff6b6b
  - retrying: #ffb454
- Shows node ID, skill, and status
- Animated edges for running nodes

**TaskTrace.tsx** (1336 bytes, 41 lines):
- Timeline view of task events
- Shows event type, timestamp, message
- Simple list format
- No visual distinction between event types

**TaskMonitor.tsx** (4558 bytes, 132 lines):
- Alternative task monitoring component
- WebSocket-based real-time updates
- Shows connection status, task state, event log
- Has auto-reconnect functionality
- Color-coded event types

### Other Components

**AgentsPanel.tsx**: Agent management interface
**HomeComposer.tsx**: Home page composition
**MarketplacePanel.tsx**: Marketplace interface
**SiteNav.tsx**: Site navigation
**WorkflowsPanel.tsx**: Workflow management

---

## Current API Layer

### Location: `lib/api.ts` (19256 bytes)

### Task APIs
```typescript
createTask(content: string)
listTasks(params?: { status?, limit? })
getTask(taskId: string)
cancelTask(taskId: string)
getTaskEvents(taskId: string)
getTaskArtifacts(taskId: string)
```

### Agent APIs
```typescript
listAgents(params?: { skill?, status? })
registerAgent(endpoint: string)
getAgent(agentId: string)
healthCheckAgent(agentId: string)
enableAgent(agentId: string)
disableAgent(agentId: string)
```

### Artifact APIs
```typescript
listArtifacts(params?: { task_id?, type?, limit? })
```

### Workflow APIs
```typescript
listWorkflows(status?: string)
createWorkflow(body)
runWorkflow(workflowId, content, title?)
```

### Marketplace APIs
```typescript
listMarketplace(q?: string)
installMarketplacePackage(packageId, endpoint?)
```

### Evaluation APIs
```typescript
getTaskEvaluation(taskId: string)  // inferred from useTaskLive
```

### Memory APIs
```typescript
getTaskMemory(taskId: string)  // inferred from useTaskLive
```

### HITL APIs (Not found in current API)
```typescript
// Expected but not found:
POST /v1/tasks/{id}/approve
POST /v1/tasks/{id}/reject
```

---

## Data Structures

### TaskNode
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

### TaskPlan
```typescript
{
  title?: string;
  goal?: string;
  nodes: Array<{
    id: string;
    skill: string;
    depends_on?: string[];
  }>;
}
```

### TaskDetail
```typescript
{
  task_id: string;
  title?: string;
  status: string;
  progress?: number;
  input_json?: { type?: string; content?: string };
  plan_json?: TaskPlan;
  result_json?: {
    summary?: string;
    artifacts?: Array<Record<string, unknown>>;
  };
  nodes: TaskNode[];
  created_at?: string;
  updated_at?: string;
  finished_at?: string;
}
```

### TaskEvent
```typescript
{
  event_type: string;
  message?: string;
  payload?: Record<string, unknown>;
  ts?: string;
}
```

### ArtifactItem
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

---

## Real-Time Event Mechanism

### WebSocket Implementation

**Location**: `hooks/useWebSocket.ts` (6283 bytes, 235 lines)

**Features**:
- WebSocket connection management
- Auto-reconnect with configurable interval (default 3000ms)
- Max reconnect attempts (default 8)
- Message parsing and error handling
- Task-specific and global WebSocket support
- Dynamic URL construction from API_BASE

**Connection Flow**:
```
WebSocket Connect → onopen → set isConnected
     ↓
Message → onmessage → parse → onMessage callback
     ↓
Error → onerror → set connectionError
     ↓
Close → onclose → attempt reconnect (if not client disconnect)
```

**WebSocket Endpoints**:
- Task-specific: `/v1/tasks/{taskId}/events/ws`
- Global: `/v1/events/ws`

### Live Task Hook

**Location**: `hooks/useTaskLive.ts` (4448 bytes, 160 lines)

**Features**:
- Hybrid WebSocket + HTTP polling
- WebSocket primary, HTTP poll fallback
- 1s polling interval when WS disconnected
- 8s polling interval when WS connected (backup)
- Stops polling when task terminal (completed/failed/cancelled)
- Fetches: task, events, artifacts, memory, evaluation
- Smart terminal state handling (max 8 polls after terminal)

**Data Sources**:
- `getTask(taskId)`
- `getTaskEvents(taskId)`
- `getTaskArtifacts(taskId)`
- `getTaskMemory(taskId)`
- `getTaskEvaluation(taskId)`

**Reconnection Logic**:
- If WS connected: 8s backup poll
- If WS disconnected: 1s fallback poll
- Terminal state: up to 8 polls after completion

---

## Current DAG Implementation

### TaskDag Component

**Visualization Method**: Custom SVG-based layout

**Layout Algorithm**:
1. Calculate dependency depth for each node
2. Group nodes by depth (layers)
3. Position nodes within each layer (horizontal distribution)
4. Draw edges as curved cubic Bézier curves
5. Animate edges for running nodes (dash-array animation)

**Node Status Mapping**:
- pending → #4a665c (gray-green)
- ready → #ffb454 (orange)
- running → #3dffa8 (green, animated)
- success → #7eaea0 (subtle green)
- failed → #ff6b6b (red)
- retrying → #ffb454 (orange)

**Node Display**:
- Rectangular node cards (140x56px, 14px radius)
- Node ID (top line)
- Skill (middle line)
- Status (bottom line, colored)
- Running nodes have pulsing circle animation

**Edge Display**:
- Curved edges between dependent nodes
- Active edges: rgba(61,255,168,0.55) green
- Inactive edges: rgba(126,174,160,0.25) subtle
- Running edges: animated dash-array

**Advantages**:
- Custom layout algorithm
- Clear visual hierarchy
- Status-based coloring
- Running animation

**Limitations**:
- Not interactive (no node selection)
- No zoom/pan
- Fixed width (640px)
- No click handlers

---

## Current Trace Implementation

### TaskTrace Component

**Visualization Method**: Simple timeline list

**Display Format**:
- Event timestamp (formatted time)
- Event type (font-mono)
- Event message (if present)

**Features**:
- Real-time updates via polling/WebSocket
- Scrollable container
- Loading state when no events

**Limitations**:
- No visual distinction between event types
- No event categorization
- No filter capabilities
- Simple text-only display

---

## Current Design System

### Color Palette

**Mist Colors** (Backgrounds, Text):
- mist-100: Light backgrounds
- mist-200: Mid backgrounds
- mist-400: Secondary text
- mist-100: Primary text

**Signal Colors** (Accents):
- signal: Primary accent
- signal-dim: Dimmed accent

**Status Colors** (In components):
- success: #7eaea0 (subtle green)
- failure: #ff6b6b (red)
- warning: #ffb454 (orange)
- info: #3dffa8 (green)

**Background Colors**:
- ink-800/50: Semi-transparent dark backgrounds
- ink-900/60: Semi-transparent dark backgrounds

### Typography

**Font Families**:
- font-mono: Monospace for technical content
- font-display: Display font for headings

**Font Sizes**:
- text-[10px]: Tiny labels
- text-xs: Small text
- text-sm: Regular text
- text-base: Body text
- text-3xl: Large headings
- text-4xl: Extra large headings

**Tracking**:
- tracking-[0.2em]: Letter spacing for uppercase labels

### Borders & Spacing

**Borders**:
- border-white/10: Subtle white borders
- rounded-xl: 12px radius
- rounded-2xl: 16px radius

**Spacing**:
- p-4: Standard padding
- p-5: Increased padding
- space-y-4: Vertical spacing
- gap-6: Grid gaps

---

## Can Be Reused Components

### UI Primitives

**Existing Patterns**:
- Rounded cards with subtle borders
- Two-column layouts (DAG + sidebar)
- Font-mono technical text
- Color-coded status indicators
- Loading states with Suspense
- Error message displays

**Component Structure**:
- Separation of concerns (TaskDag, TaskTrace, TaskWorkspace)
- Reusable API layer
- Custom hooks for real-time updates
- SVG-based visualization

### State Management

**Current State Management**:
- React useState for local component state
- No global state management (Zustand, TanStack Query)
- Custom hooks for WebSocket and live updates
- Direct API calls with fetch

**State Management Opportunities**:
- Could add Zustand for global task state
- Could add TanStack Query for API caching
- Current approach works well for single-task view

---

## Current Task Workspace Features

### TaskWorkspace Component Features

**Task Header**:
- Task ID display (first 8 characters)
- Back navigation to new task
- Task goal/title display
- Status badge
- Progress percentage
- Node counts (total, done, active, failed)

**Task Graph**:
- Custom SVG DAG visualization
- Node status coloring
- Running node animation
- Dependency edges

**Aggregated Result**:
- Displays result_json.summary
- Truncated at 2500 characters
- Preformatted text display

**Artifacts**:
- Lists artifacts with node_id, name, uri
- Simple list format
- No preview/download functionality

**Trace**:
- Timeline view of events
- Real-time updates
- Timestamp formatting

### TaskMonitor Component Features

**Connection Status**:
- WebSocket connection indicator
- Auto-reconnect toggle
- Connect/Disconnect buttons
- Connection error display

**Task State**:
- Status badge
- Created timestamp
- Title display

**Latest Event**:
- Event type and data
- JSON formatted payload

**Event Log**:
- List of all events
- Color-coded by type
- Timestamps
- Scrollable container

---

## Missing Features for Task Workspace

### 1. Three-Column Layout ❌
**Current**: Two-column layout (DAG + sidebar)
**Required**: Three-column layout (Nav + Graph + Inspector)

### 2. Task Navigation Panel ❌
**Current**: No dedicated navigation panel
**Required**: Overview, Plan, Agents, Artifacts, Trace, Logs tabs

### 3. Node Inspector ❌
**Current**: No node selection or inspection
**Required**: Click node → show details in right panel

### 4. Enhanced Trace Timeline ❌
**Current**: Simple list format
**Required**: Visual timeline with event categorization

### 5. Artifact Preview/Download ❌
**Current**: Simple list display
**Required**: Preview, download, open for different artifact types

### 6. HITL Approval/Reject ❌
**Current**: No HITL UI
**Required**: Approve/Reject buttons for WAITING_FOR_USER nodes

### 7. Error State Display ❌
**Current**: Limited error display
**Required**: Error code, message, retry count, failover info

### 8. Agent Version Display ❌
**Current**: No agent version info
**Required**: Show agent version in node inspector

### 9. A2A Task ID Display ❌
**Current**: No A2A task ID display
**Required**: Show A2A task ID in node inspector

### 10. Input/Output Display ❌
**Current**: No input/output node details
**Required**: Show input and output JSON in node inspector

### 11. Enhanced Task Header ❌
**Current**: Basic header with limited info
**Required**: Duration, agent count, cancel button

### 12. Graph Interactivity ❌
**Current**: No node selection
**Required**: Click handlers for node inspection

---

## WebSocket Implementation Details

### Connection URL Construction

**Function**: `buildWsUrl(path, apiKey)`

**Logic**:
- Derives from NEXT_PUBLIC_API_BASE
- Converts http:// to ws://
- Converts https:// to wss://
- Appends path to base URL
- Adds api_key query parameter if provided

**Example**:
```
API_BASE: http://127.0.0.1:8080
Task: abc-123
Path: /v1/tasks/abc-123/events/ws
Result: ws://127.0.0.1:8080/v1/tasks/abc-123/events/ws?api_key=xxx
```

### Message Types

**WebSocketMessage**:
```typescript
{
  type: string;
  task_id?: string;
  event_type?: string;
  data?: unknown;
  timestamp?: number;
  message?: string;
}
```

**Event Types**:
- initial_state: Initial task state
- initial_events: Batch of historical events
- task_event: Individual task event
- system_event: Global system event

---

## ReactFlow Integration

### Current Usage

**Status**: ✅ Installed (ReactFlow 11.11.4)

**Current Implementation**: Not used for DAG visualization

**Current DAG Implementation**: Custom SVG-based layout in TaskDag.tsx

**ReactFlow Opportunity**:
- Could replace custom SVG for interactive DAG
- Provides built-in node selection
- Provides zoom/pan
- Provides drag-and-drop
- Provides mini-map
- Provides background patterns

**Migration Consideration**:
- Current custom SVG works well for read-only display
- ReactFlow would add interactivity
- Would require layout algorithm porting
- Could maintain current design with ReactFlow nodes

---

## Design Tokens

### Current Design System

**Colors**:
- Backgrounds: #152822 (ink-900), #1a1a2e (ink-800)
- Borders: rgba(255,255,255,0.1) (white/10)
- Text: #e8f2ee (mist-100), #7eaea0 (success), #ff6b6b (failure)
- Accents: #3dffa8 (running), #ffb454 (ready)

**Typography**:
- Headings: font-display
- Body: Default system font
- Technical: font-mono
- Uppercase labels: tracking-[0.2em]

**Spacing**:
- Cards: p-4, p-5
- Layout: gap-4, gap-6
- Grid: grid-cols-[1.4fr_1fr]

**Borders**:
- Cards: border border-white/10
- Radius: rounded-xl, rounded-2xl

---

## Professional AI Infrastructure Style

### Current Style Characteristics

**Strengths**:
- Dark theme with subtle colors
- Monospace technical typography
- Color-coded status indicators
- Clean, minimal design
- Subtle borders and shadows
- Large whitespace

**Alignment with Professional AI Infrastructure**:
- ✅ Dark theme suitable for developer tools
- ✅ Monospace fonts for technical content
- ✅ Color coding for status and states
- ✅ Clean, professional appearance
- ✅ Subtle animations (running nodes)

**Areas for Enhancement**:
- More subtle gradients (currently minimal)
- More whitespace in three-column layout
- Better hierarchy with visual separation
- Professional color palette refinement

---

## Component Reusability Assessment

### Highly Reusable Components

**TaskDag.tsx**:
- ✅ Well-structured SVG visualization
- ✅ Clear separation of concerns
- ✅ Can be enhanced with interactivity
- ✅ Can be ported to ReactFlow if needed

**TaskTrace.tsx**:
- ⚠️ Simple implementation
- ✅ Can be enhanced with visual timeline
- ✅ Can be extracted as reusable component

**useTaskLive.ts**:
- ✅ Excellent WebSocket + polling hybrid
- ✅ Comprehensive data fetching
- ✅ Perfect for real-time updates
- ✅ Should be reused unchanged

**useWebSocket.ts**:
- ✅ Robust WebSocket management
- ✅ Auto-reconnect logic
- ✅ Error handling
- ✅ Should be reused unchanged

**API Layer (lib/api.ts)**:
- ✅ Comprehensive API coverage
- ✅ Type-safe TypeScript types
- ✅ Consistent error handling
- ✅ Should be reused unchanged

### Components Needing Enhancement

**TaskWorkspace.tsx**:
- ❌ Needs three-column layout
- ❌ Needs node selection logic
- ❌ needs navigation panel
- ❌ needs enhanced inspector

**TaskMonitor.tsx**:
- ⚠️ Alternative implementation
- ❌ Not currently used in main workspace
- Could be merged or repurposed

---

## Technical Debt

### Missing APIs

**HITL APIs**:
```typescript
// Expected but not found:
POST /v1/tasks/{id}/approve
POST /v1/tasks/{id}/reject
```

**Node Details API**:
```typescript
// Expected but not found:
GET /v1/tasks/{id}/nodes/{nodeId}
```

**Agent Runs API**:
```typescript
// Expected but not found:
GET /v1/tasks/{id}/runs
GET /v1/tasks/{id}/nodes/{nodeId}/runs
```

### State Management

**Current**: Component-level useState

**Opportunity**: Add Zustand for global state
- Shared task state across components
- Shared connection state
- Shared navigation state

---

## Next Steps

1. **Design Task Workspace layout** with three-column structure
2. **Implement Task Header** with enhanced information
3. **Enhance Execution Graph** with interactivity (click handlers)
4. **Implement Node Inspector** panel
5. **Implement Trace timeline** with visual enhancements
6. **Implement Artifacts display** with preview/download
7. **Implement HITL approval/reject** UI
8. **Handle error states** with detailed information
9. **Make responsive layout** for desktop first
10. **Run tests, lint, build**
11. **Generate final result document**

---

**Audit Complete**  
**Next Phase**: Design Task Workspace layout
