# Phase 35.5: Task Workspace Design Document

**Date**: 2026-09-18  
**Objective**: Design comprehensive Task Workspace UI for Agent Task monitoring  
**Scope**: Three-column layout with enhanced visualization and interactivity

---

## Executive Summary

Designing a comprehensive Task Workspace that transforms the current basic task viewing interface into a professional AI infrastructure monitoring dashboard. The design maintains the existing technical foundation (Next.js, React, TypeScript, Tailwind, ReactFlow) while introducing a three-column layout, interactive DAG visualization, node inspection, enhanced trace timeline, artifact management, and HITL support.

---

## Design Principles

### Professional AI Infrastructure Style

**Visual Characteristics**:
- White/neutral background (not dark mode)
- Subtle borders (10-14px radius)
- Large whitespace for clarity
- Professional color palette (subtle, not neon)
- Minimal gradients
- Clean typography hierarchy

**Design Philosophy**:
- Information density balanced with readability
- Status indicators that are subtle but clear
- Real-time updates without overwhelming
- Developer-friendly technical content
- Traditional dashboard aesthetics, not consumer app

---

## Three-Column Layout Design

### Layout Structure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Task Header (Top Bar)                              │
├──────────────┬──────────────────────────────────────────────┬──────────────┤
│ Task Nav     │ Execution Graph (Center)                    │ Inspector    │
│              │                                              │              │
│ Overview     │ Planner                                      │ Node         │
│ Plan         │    ↓                                         │ Agent        │
│ Agents       │ Search ───┐                                  │ Skill        │
│ Artifacts    │           ├→ Analysis                         │ Status       │
│ Trace        │ RAG ──────┘       ↓                          │ Latency      │
│ Logs         │                 Report                          │ Input        │
│              │                                              │ Output       │
└──────────────┴──────────────────────────────────────────────┴──────────────┘
```

### Column Specifications

**Left Column (Task Nav)**: 250px fixed width
- Navigation tabs
- Task summary cards
- Quick access sections

**Center Column (Execution Graph)**: Flexible width
- DAG visualization (ReactFlow)
- Zoom and pan controls
- Mini-map for large DAGs
- Control panel for actions

**Right Column (Inspector)**: 320px fixed width
- Node details on selection
- Scrollable content
- JSON expand/collapse
- Action buttons (approve/reject for HITL)

### Responsive Breakpoints

**Desktop Priority**:
- 1440px: Full three-column layout
- 1280px: Three-column with narrower nav (200px)
- Below 1280px: Stack columns (Nav → Graph → Inspector)

**Mobile**:
- Stack all columns vertically
- Prioritize Graph and Inspector
- Collapse Nav into drawer

---

## Task Header Design

### Top Bar Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ← Task Workspace  | Search Agent Orchestration  | status ● │ [Cancel]    │
│                     │ ID: abc-12345  | 5m 23s    │ duration: 5m   │
│                     │ 4 agents    │ 5/7 nodes   │ agents: 4     │
│                     │ 5/7 nodes   │ ●●●○○○○    │ completed: 5 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Header Components

**Breadcrumbs**:
- Back to tasks list
- Task Workspace label
- Small, monospace, uppercase

**Task Title**:
- Large, display font
- Truncate with ellipsis if very long
- Maximum 2 lines

**Task ID**:
- Monospace, small
- Copy button on hover
- Full ID in tooltip

**Status Badge**:
- Subtle color coding:
  - running: subtle blue with pulsing dot
  - completed: subtle green
  - failed: subtle red
  - cancelled: subtle gray

**Duration**:
- Monospace, small
- Real-time updates
- Format: Xm Ys

**Node Counts**:
- Progress bar visualization
- Text: "X/Y nodes"
- Visual: ●●●○○○○

**Cancel Button**:
- Only when status is running
- Confirmation dialog
- Monospace button style

---

## Task Navigation Panel

### Tab Structure

```
┌──────────────┐
│ Overview     │
│ Plan         │
│ Agents       │
│ Artifacts    │
│ Trace        │
│ Logs         │
└──────────────┘
```

### Tab Contents

**Overview Tab**:
- Task summary card
- Status
- Created at
- Progress percentage
- Node counts
- Agent count
- Quick stats

**Plan Tab**:
- Plan details
- JSON view
- Skill list
- Dependency summary

**Agents Tab**:
- List of agents used
- Agent names
- Skills performed
- Execution counts
- Success/failure rates

**Artifacts Tab**:
- List of all artifacts
- Grouped by node
- Type icons
- Download buttons

**Trace Tab**:
- Event timeline
- Filter by event type
- Jump to specific event
- Real-time updates

**Logs Tab**:
- Raw log stream
- Searchable
- Auto-scroll toggle
- Download logs

---

## Execution Graph Design

### Visualization Technology

**Choice**: ReactFlow (already installed)

**Rationale**:
- Provides built-in interactivity
- Built-in zoom/pan
- Mini-map support
- Custom node types
- Background patterns
- Professional appearance

### Node Types

**Planner Node**:
- Icon: 🔷 or custom planner icon
- Color: Neutral gray
- Shape: Rectangular with rounded corners
- Status indicators on node

**Agent Node**:
- Icon: 🤖 or agent-specific icon
- Color: Subtle accent color
- Shape: Rectangular with rounded corners
- Skill name displayed
- Agent name in tooltip

**Human Approval Node**:
- Icon: 👤 or approval icon
- Color: Amber/warning color
- Shape: Diamond or distinct shape
- "Approval Required" label
- Approve/Reject buttons in inspector

**Artifact Node**:
- Icon: 📄 or type-specific icon
- Color: Neutral with type accent
- Shape: Smaller rectangular
- Type indicator

**Aggregator Node**:
- Icon: 📊 or aggregation icon
- Color: Neutral purple
- Shape: Hexagonal or distinct shape
- "Aggregation" label

### Node Status Styling

**SUCCESS**:
- Border: Subtle green (#10b981)
- Background: White
- Icon: Green checkmark
- No animation

**RUNNING**:
- Border: Subtle blue (#3b82f6)
- Background: White
- Icon: Blue spinner or loading indicator
- Animation: Subtle pulse on border

**FAILED**:
- Border: Subtle red (#ef4444)
- Background: White
- Icon: Red X or error icon
- No animation

**RETRYING**:
- Border: Subtle orange (#f59e0b)
- Background: White
- Icon: Retry icon
- Animation: Subtle pulse

**WAITING_FOR_USER**:
- Border: Amber (#f59e0b)
- Background: White
- Icon: Clock or hourglass
- Animation: Subtle pulse
- Highlight: Amber glow

**PENDING**:
- Border: Neutral gray (#9ca3af)
- Background: White
- Icon: Clock or hourglass
- No animation

**READY**:
- Border: Subtle blue (#60a5fa)
- Background: White
- Icon: Ready/play icon
- No animation

**CANCELLED**:
- Border: Neutral gray (#9ca3af)
- Background: White
- Icon: Cancel X
- Strikethrough on text

### Edge Styling

**Standard Edge**:
- Color: #d1d5db (subtle gray)
- Stroke width: 1.5px
- Smooth curves (Bézier)

**Active Edge**:
- Color: #3b82f6 (subtle blue)
- Stroke width: 2px
- Animated dash-array for running

**Completed Edge**:
- Color: #10b981 (subtle green)
- Stroke width: 2px
- Solid line

**Failed Edge**:
- Color: #ef4444 (subtle red)
- Stroke width: 2px
- Solid line

### Graph Controls

**Toolbar**:
- Zoom in/out buttons
- Fit to screen button
- Reset view button
- Layout toggle (left-to-right / top-to-bottom)
- Export as image button

**Mini-Map**:
- Bottom-right corner
- Shows overall structure
- Click to navigate
- Zoom indicator

---

## Node Inspector Design

### Panel Structure

```
┌──────────────┐
│ Node: abc-123 │
│              │
│ Agent        │
│ web-search   │
│ Status       │
│ RUNNING ●    │
│ ───────────── │
│ Agent:       │
│ search-agent │
│ Version:     │
│ 0.3.0        │
│ ───────────── │
│ Started At:   │
│ 14:23:45     │
│ Duration:    │
│ 2.3s         │
│ ───────────── │
│ Retry Count:  │
│ 0            │
│ ───────────── │
│ A2A Task ID: │
│ a2a-789      │
│ ───────────── │
│ [Input ▼]    │
│ {...}        │
│ ───────────── │
│ [Output ▼]   │
│ {...}        │
│ ───────────── │
│ Artifacts:    │
• report.txt   │
• data.json   │
│ ───────────── │
│ [Approve]    │
│ [Reject]     │
└──────────────┘
```

### Inspector Sections

**Node Identity**:
- Node ID (monospace, copyable)
- Skill name
- Status with icon
- Started/Completed timestamps
- Duration calculation

**Agent Information**:
- Agent name
- Agent key
- Agent version
- Agent ID (monospace, copyable)

**Execution Details**:
- Retry count
- A2A Task ID
- Last error (if failed)

**Input/Output**:
- Collapsible JSON display
- Syntax highlighting
- Copy button
- Format buttons (pretty/compact)

**Artifacts**:
- List of artifacts produced
- Type icons
- Preview/download buttons
- Size information

**HITL Actions**:
- Approve button (green)
- Reject button (red)
- Only shown for WAITING_FOR_USER status
- Confirm dialogs

---

## Trace Timeline Design

### Timeline Visualization

**Visual Structure**:
```
Timeline: ──────────────────────────────────────────►
          ●  ●      ●      ●      ●       ●
     Created  Plan  Search  RAG  Report  Aggr   Done
```

**Event Types**:
- Task created
- Planner started
- Planner completed
- Node started
- Node completed
- Node failed
- Node retrying
- Task completed
- Task failed
- Task cancelled

**Event Categorization**:
- **Lifecycle Events**: Task lifecycle transitions
- **Execution Events**: Node execution events
- **Error Events**: Failures and retries
- **HITL Events**: Approval/rejection events
- **Artifact Events**: Artifact creation

**Visual Distinction**:
- Lifecycle: Blue dots
- Execution: Green dots
- Error: Red dots
- HITL: Amber dots
- Artifact: Purple dots

**Timeline Features**:
- Auto-scroll to latest event
- Filter by event type
- Click event to show details
- Jump to event in log view
- Real-time updates via WebSocket

---

## Artifacts Display Design

### Artifact Cards

**Card Structure**:
```
┌─────────────────────────┐
│ 📄 report.txt            │
│ 2.3 KB                  │
│ [Preview] [Download] [Open] │
└─────────────────────────┘
```

**Artifact Types**:
- **Text**: 📄 icon, plain text preview
- **JSON**: 📊 icon, syntax highlighted preview
- **Image**: 🖼️ icon, image preview
- **Video**: 🎬 icon, video player
- **PDF**: 📕 icon, PDF viewer
- **PPT**: 📊 icon, PowerPoint viewer
- **File**: 📎 icon, download only

**Preview Modal**:
- Open in modal on preview click
- Rendered preview based on type
- Full-screen toggle
- Download button in modal

**Download Behavior**:
- Direct download on click
- Open in new tab if preview not available
- Support for large files (streaming)

---

## HITL Interface Design

### Approval Panel

**When Node Status**: WAITING_FOR_USER

**Display in Inspector**:
```
┌─────────────────────────┐
│ Approval Required        │
│                          │
│ Node: abc-123           │
│ Skill: report-generation │
│                          │
│ [Approve] [Reject]       │
└─────────────────────────┘
```

**Approve Button**:
- Green background, white text
- Monospace font
- Confirmation dialog
- Success feedback

**Reject Button**:
- Red background, white text
- Monospace font
- Confirmation dialog
- Success feedback

**Confirmation Dialog**:
- Title: "Approve Node?"
- Message: "Node abc-123 (report-generation) is waiting for approval"
- Buttons: [Confirm] [Cancel]

**API Integration**:
```typescript
POST /v1/tasks/{taskId}/approve
POST /v1/tasks/{taskId}/reject
```

---

## Error State Display

### Error Information in Inspector

**When Node Status**: FAILED

**Display in Inspector**:
```
┌─────────────────────────┐
│ Error Details             │
│                          │
│ Error Code:              │
│ EXECUTION_FAILED         │
│                          │
│ Message:                  │
│ Agent timeout             │
│                          │
│ Retry Count:              │
│ 2/3                      │
│                          │
│ Failover:                 │
│ search-agent → rag-agent  │
│                          │
│ Selected Agent:           │
│ rag-agent (v0.4.0)       │
└─────────────────────────┘
```

**Error Code Categorization**:
- INVALID_REQUEST
- UNSUPPORTED_SKILL
- AUTH_FAILED
- TASK_NOT_FOUND
- EXECUTION_FAILED
- TIMEOUT
- RESOURCE_EXHAUSTED
- INTERNAL_ERROR

**Visual Styling**:
- Error code: Monospace, subtle red
- Message: Regular text, dark gray
- Retry count: Progress bar (X/Y)
- Failover: Arrow diagram (→)

---

## Responsive Design

### Desktop Breakpoints

**1440px+**:
- Full three-column layout
- Nav: 250px fixed
- Inspector: 320px fixed
- Graph: Flexible remaining width

**1280px - 1439px**:
- Three-column layout
- Nav: 200px (narrower)
- Inspector: 280px (narrower)
- Graph: Flexible remaining width

**1024px - 1279px**:
- Stacked layout
- Nav: Top horizontal tabs
- Graph: Main area
- Inspector: Right sidebar (280px)

**768px - 1023px**:
- Stacked layout
- Nav: Top horizontal tabs
- Graph: Main area
- Inspector: Bottom panel (collapsible)

**< 768px**:
- Single column
- Nav: Drawer (off-canvas)
- Graph: Main area
- Inspector: Modal overlay

---

## Component Architecture

### New Components Structure

```
components/tasks/
├── TaskWorkspace.tsx          # Main workspace component (enhanced)
├── TaskHeader.tsx            # Task header with enhanced info
├── TaskNav.tsx               # Navigation panel with tabs
├── ExecutionGraph.tsx         # ReactFlow-based DAG (interactive)
├── NodeInspector.tsx          # Node details panel
├── TraceTimeline.tsx          # Enhanced trace timeline
├── ArtifactCard.tsx           # Artifact display card
├── HitLApprovalPanel.tsx      # HITL approval interface
└── ErrorDetails.tsx           # Error state display
```

### Component Hierarchy

```
TaskWorkspace
├── TaskHeader
├── TaskNav
│   ├── OverviewTab
│   ├── PlanTab
│   ├── AgentsTab
│   ├── ArtifactsTab
│   ├── TraceTab
│   └── LogsTab
├── ExecutionGraph
└── NodeInspector
    ├── NodeInfo
    ├── AgentInfo
    ├── ExecutionDetails
    ├── InputOutput
    ├── Artifacts
    ├── ErrorDetails
    └── HitLApprovalPanel
```

---

## State Management Approach

### State Management Strategy

**Current**: Component-level useState

**Proposed**: Add Zustand for shared state

**Zustand Store Structure**:
```typescript
interface TaskWorkspaceState {
  taskId: string | null;
  task: TaskDetail | null;
  selectedNodeId: string | null;
  selectedTab: 'overview' | 'plan' | 'agents' | 'artifacts' | 'trace' | 'logs';
  isLive: boolean;
  wsConnected: boolean;
  graphZoom: number;
  graphFit: boolean;
}

interface TaskWorkspaceActions {
  setTaskId: (id: string) => void;
  selectNode: (nodeId: string) => void;
  selectTab: (tab: string) => void;
  setLiveMode: (live: boolean) => void;
  setGraphZoom: (zoom: number) => void;
  setGraphFit: (fit: boolean) => void;
}

const useTaskWorkspaceStore = create<TaskWorkspaceState, TaskWorkspaceActions>(
  immer(set => ({
    setTaskId: (id) => set({ taskId: id }),
    selectNode: (nodeId) => set({ selectedNodeId: nodeId }),
    selectTab: (tab) => set({ selectedTab: tab }),
    setLiveMode: (live) => set({ isLive: live }),
    setGraphZoom: (zoom) => set({ graphZoom: zoom }),
    setGraphFit: (fit) => set({ graphFit: fit }),
  }))
))
```

**Benefits**:
- Shared state across components
- Persistent selection on tab switch
- Shared graph zoom/fit state
- Easy to add derived state

---

## API Requirements

### Required New APIs

**HITL APIs** (missing from current API):
```typescript
POST /v1/tasks/{taskId}/approve
POST /v1/tasks/{taskId}/reject
```

**Node Details API** (missing from current API):
```typescript
GET /v1/tasks/{taskId}/nodes/{nodeId}
```

**Agent Runs API** (missing from current API):
```typescript
GET /v1/tasks/{taskId}/runs
GET /vactive/tasks/{taskId}/nodes/{nodeId}/runs
```

**Alternative: Extend Existing APIs**

**Option 1**: Add node details to TaskDetail
- Include node details in nodes array
- Add agent_runs information to nodes

**Option 2**: Query existing tables directly
- Nodes can query agent_runs via node_id
- Artifacts can be fetched from node output_json

**Recommendation**: Option 1 (extend existing APIs)

---

## Implementation Priorities

### Phase 1: Foundation (Highest Priority)
1. ✅ Complete audit (DONE)
2. ✅ Design document (IN PROGRESS)
3. Implement three-column layout
4. Implement Task Header
5. Implement Task Nav with tabs
6. Update TaskWorkspace main component

### Phase 2: Graph Enhancement (High Priority)
1. Migrate TaskDag to ReactFlow
2. Add node click handlers
3. Implement node selection state
4. Add mini-map
5. Add zoom/pan controls
6. Add layout toggle

### Phase 3: Inspector (High Priority)
1. Implement Node Inspector panel
2. Add node details display
3. Add agent information
4. Add input/output JSON display
5. Add artifact list per node
6. Add error details

### Phase 4: Trace Enhancement (Medium Priority)
1. Enhance TaskTrace with visual timeline
2. Add event categorization
3. Add event filtering
4. Add real-time updates

### Phase 5: Artifacts (Medium Priority)
1. Implement ArtifactCard component
2. Add preview functionality
3. Add download functionality
3. Add type-specific previews

### Phase 6: HITL (Medium Priority)
1. Implement HitLApprovalPanel
2. Add approve/reject buttons
3. Add confirmation dialogs
4. Integrate with API (when available)

### Phase 7: Error States (Medium Priority)
1. Implement ErrorDetails component
2. Add error code display
3. Add retry count display
4. Add failover information

### Phase 8: Responsive (Lower Priority)
1. Implement responsive breakpoints
2. Add drawer navigation for mobile
3. Stack columns for medium screens
4. Optimize for 1280px+

### Phase 9: Testing (Required)
1. npm test
2. npm run lint
3. npm run build

---

## Design Tokens

### Color Palette (White/Neutral Theme)

**Backgrounds**:
- Background: #ffffff (white)
- Background subtle: #f8fafc (neutral-50)
- Background elevated: #ffffff (white with shadow)
- Background secondary: #f1f5f9 (neutral-100)

**Borders**:
- Border subtle: #e2e8f0 (neutral-200)
- Border focus: #3b82f6 (blue-500)
- Border error: #ef4444 (red-500)
- Border success: #10b981 (green-500)
- Border warning: #f59e0b (amber-500)

**Text**:
- Text primary: #0f172a (slate-900)
- Text secondary: #475569 (slate-600)
- Text tertiary: #64748b (slate-500)
- Text muted: #94a3b8 (slate-400)

**Status Colors (Subtle)**:
- Running: #dbeafe (blue-100)
- Success: #dcfce7 (green-100)
- Failed: #fee2e2 (red-100)
- Waiting: #fef3c7 (amber-100)
- Pending: #f1f5f9 (neutral-100)
- Ready: #dbeafe (blue-100)
- Cancelled: #f1f5f9 (neutral-100)

**Accents**:
- Primary: #3b82f6 (blue-600)
- Primary hover: #2563eb (blue-700)
- Primary soft: #dbeafe (blue-100)

### Typography

**Font Families**:
- Sans-serif: Inter or system-ui
- Monospace: JetBrains Mono or system-monospace
- Display: Inter

**Font Sizes**:
- Text-xs: 12px
- Text-sm: 14px
- Text-base: 16px
- Text-lg: 18px
- Text-xl: 20px
- Text-2xl: 24px
- Text-3xl: 30px
- Text-4xl: 36px

**Font Weights**:
- Normal: 400
- Medium: 500
- Semibold: 600
- Bold: 700

### Spacing

**Spacing Scale**:
- Space-1: 4px
- Space-2: 8px
- Space-3: 12px
- Space-4: 16px
- Space-5: 20px
- Space-6: 24px
- Space-8: 32px
- Space-10: 40px
- Space-12: 48px

**Borders**:
- Radius-sm: 6px
- Radius-md: 8px
- Radius-lg: 12px
- Radius-xl: 16px
- Radius-2xl: 24px

**Shadows**:
- Shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05)
- Shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1)
- Shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1)
- Shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1)

---

## Implementation Approach

### Incremental Implementation Strategy

**Phase 1: Layout Foundation**
1. Update TaskWorkspace to three-column layout
2. Implement TaskNav with tabs
3. Implement TaskHeader
4. Update existing components to new layout
5. Test layout responsiveness

**Phase 2: Graph Migration**
1. Create ExecutionGraph component with ReactFlow
2. Migrate layout algorithm from TaskDag
3. Add node click handlers
4. Add zoom/pan controls
5. Add mini-map
6. Test graph functionality

**Phase 3: Inspector**
1. Create NodeInspector component
2. Implement node details display
3. Add agent information
4. Add input/output JSON
5. Add artifact list
6. Test inspector functionality

**Phase 4: Enhancement
1. Enhance TraceTimeline
2. Implement ArtifactCard
3. Implement HitLApprovalPanel
4. Implement ErrorDetails
5. Add state management (Zustand)
6. Test enhanced features

**Phase 5: Integration**
1. Integrate all components
2. Test full task lifecycle
3. Test real-time updates
4. Test responsive behavior
5. Performance optimization

---

## Backward Compatibility

### Maintaining Compatibility

**Existing Pages**:
- Keep current TaskWorkspace as fallback
- Create new TaskWorkspaceV3 as new component
- Route to new component via feature flag

**Existing Components**:
- Keep TaskDag for simple DAG viewing (if needed)
- Keep TaskTrace for simple trace viewing (if needed)
- Keep useTaskLive hook unchanged
- Keep API layer unchanged

**API Compatibility**:
- No breaking changes to existing APIs
- Add new APIs as needed
- Extend existing APIs with optional fields

---

## Performance Considerations

### Optimization Strategies

**Graph Rendering**:
- Lazy load large DAGs
- Virtualization for 100+ nodes
- Debounce graph updates
- Memoize node positions

**Real-time Updates**:
- WebSocket priority over polling
- Throttle state updates
- Batch event processing
- Debounce WebSocket messages

**Artifact Loading**:
- Lazy load artifact previews
- Progressive image loading
- Chunk large file downloads
- Cache artifact metadata

---

## Security Considerations

### API Security
- Maintain existing authentication
- Use session tokens from localStorage
- Validate task access permissions
- Sanitize JSON display

### XSS Prevention
- Use React's built-in XSS protection
- Sanitize JSON display before rendering
- Validate URLs before opening in new tabs
- Escape user-generated content

---

## Summary

The Task Workspace design transforms the current basic task viewing interface into a professional AI infrastructure monitoring dashboard with:

**Key Features**:
- Three-column layout (Nav + Graph + Inspector)
- Interactive DAG visualization with ReactFlow
- Node inspection with detailed information
- Enhanced trace timeline with visual indicators
- Artifact management with preview/download
- HITL approval/reject interface
- Error state display with detailed diagnostics
- Responsive design for desktop-first approach

**Technical Foundation**:
- Next.js 15.1.0 with App Router
- React 19.0.0 with TypeScript
- Tailwind CSS 3.4.16
- ReactFlow 11.11.4 for DAG visualization
- WebSocket support for real-time updates
- Professional white/neutral design theme

**Implementation Strategy**:
- Incremental implementation in 5 phases
- Maintain backward compatibility
- Add Zustand for state management
- Extend existing APIs where needed
- Test at each phase

**Design Alignment**:
- Professional AI infrastructure style
- Subtle, not flashy
- Information-dense but readable
- Real-time updates without overwhelming
- Developer-friendly technical content

---

**Design Complete**  
**Next Phase**: Implement layout foundation
