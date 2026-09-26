"use client";

import { memo, useEffect, useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import type { TaskNode, TaskPlan } from "@/lib/api";

/** Workflow node status colors (orchestrator task_nodes). */
const STATUS_COLOR: Record<string, string> = {
  pending: "#4a665c",
  ready: "#ffb454",
  running: "#3dffa8",
  success: "#7eaea0",
  waiting_for_user: "#fbbf24",
  failed: "#ff6b6b",
  retrying: "#ffb454",
  cancelled: "#6b7280",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "等待",
  ready: "就绪",
  running: "执行中",
  success: "完成",
  waiting_for_user: "待审批",
  failed: "失败",
  retrying: "重试",
  cancelled: "已取消",
};

/** Friendly labels for harness virtual agents (plan.skill == agent_key). */
const AGENT_LABEL: Record<string, string> = {
  "claude-code": "Claude Code",
  "deepseek-harness": "DeepSeek",
  pi: "Pi",
};

export function agentDisplayName(key?: string | null, fallbackName?: string | null): string {
  const k = (key || "").trim();
  if (fallbackName && fallbackName.trim()) return fallbackName.trim();
  if (!k) return "Agent";
  return AGENT_LABEL[k] || k;
}

type DagNodeData = {
  nodeId: string;
  agentKey: string;
  agentLabel: string;
  status: string;
  statusLabel: string;
  attempt?: number;
  selected?: boolean;
};

function DagNodeCard({ data }: NodeProps<DagNodeData>) {
  const color = STATUS_COLOR[data.status] || STATUS_COLOR.pending;
  const running = data.status === "running" || data.status === "waiting_for_user";
  return (
    <div
      className="min-w-[168px] max-w-[200px] rounded-xl border px-3 py-2.5"
      style={{
        background: "#152822",
        borderColor: color,
        boxShadow: running ? `0 0 18px ${color}55` : undefined,
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-signal/80 !w-2 !h-2 !border-0" />
      <div className="font-mono text-[9px] uppercase tracking-[0.14em] text-mist-400">
        {data.nodeId}
      </div>
      <div className="mt-1 truncate text-sm font-medium text-mist-100" title={data.agentKey}>
        {data.agentLabel}
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <span
          className="rounded px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.08em]"
          style={{ background: `${color}22`, color }}
        >
          {data.statusLabel}
        </span>
        {typeof data.attempt === "number" && data.attempt > 1 ? (
          <span className="font-mono text-[9px] text-mist-400">#{data.attempt}</span>
        ) : null}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-signal/80 !w-2 !h-2 !border-0" />
    </div>
  );
}

const nodeTypes = { dagNode: memo(DagNodeCard) };

type Props = {
  plan?: TaskPlan | null;
  nodes: TaskNode[];
  selectedNodeId?: string | null;
  onSelectNode?: (id: string | null) => void;
};

function buildLayout(plan: TaskPlan | null | undefined, nodes: TaskNode[]) {
  const planNodes =
    plan?.nodes ||
    nodes.map((n) => ({
      id: n.id,
      skill: n.agent_key || n.skill,
      depends_on: [] as string[],
    }));
  const ids = planNodes.map((n) => n.id);
  const deps = new Map<string, string[]>();
  for (const n of planNodes) deps.set(n.id, n.depends_on || []);

  const depth = new Map<string, number>();
  function d(id: string, stack = new Set<string>()): number {
    if (depth.has(id)) return depth.get(id)!;
    if (stack.has(id)) return 0;
    stack.add(id);
    const parents = deps.get(id) || [];
    const val = parents.length ? 1 + Math.max(...parents.map((p) => d(p, stack))) : 0;
    stack.delete(id);
    depth.set(id, val);
    return val;
  }
  ids.forEach((id) => d(id));

  const layers = new Map<number, string[]>();
  for (const id of ids) {
    const layer = depth.get(id) || 0;
    const arr = layers.get(layer) || [];
    arr.push(id);
    layers.set(layer, arr);
  }

  const statusMap = new Map(nodes.map((n) => [n.id, n]));
  const planSkill = new Map(planNodes.map((n) => [n.id, n.skill]));

  const rfNodes: Node<DagNodeData>[] = [];
  const rfEdges: Edge[] = [];
  const rowH = 130;
  const colW = 230;

  for (const [layer, layerIds] of layers) {
    layerIds.forEach((id, idx) => {
      const live = statusMap.get(id);
      const st = live?.status || "pending";
      const agentKey = live?.agent_key || planSkill.get(id) || live?.skill || id;
      rfNodes.push({
        id,
        type: "dagNode",
        position: { x: 40 + idx * colW, y: 40 + layer * rowH },
        data: {
          nodeId: id,
          agentKey,
          agentLabel: agentDisplayName(agentKey, live?.agent_name),
          status: st,
          statusLabel: STATUS_LABEL[st] || st,
          attempt: live?.attempt,
        },
        selected: false,
      });
    });
  }

  for (const n of planNodes) {
    for (const parent of n.depends_on || []) {
      const childStatus = statusMap.get(n.id)?.status;
      rfEdges.push({
        id: `${parent}-${n.id}`,
        source: parent,
        target: n.id,
        animated: childStatus === "running" || childStatus === "ready",
        style: { stroke: "#7eaea0" },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#7eaea0" },
      });
    }
  }

  return { rfNodes, rfEdges };
}

const LEGEND = [
  ["ready", "就绪"],
  ["running", "执行中"],
  ["success", "完成"],
  ["waiting_for_user", "待审批"],
  ["failed", "失败"],
] as const;

export function TaskFlowDag({ plan, nodes, selectedNodeId, onSelectNode }: Props) {
  const layout = useMemo(() => buildLayout(plan, nodes), [plan, nodes]);
  const [rfNodes, setNodes, onNodesChange] = useNodesState(layout.rfNodes);
  const [rfEdges, setEdges, onEdgesChange] = useEdgesState(layout.rfEdges);

  useEffect(() => {
    setNodes(layout.rfNodes);
    setEdges(layout.rfEdges);
  }, [layout, setNodes, setEdges]);

  useEffect(() => {
    setNodes((prev) =>
      prev.map((n) => ({
        ...n,
        selected: n.id === selectedNodeId,
        style:
          n.id === selectedNodeId
            ? { ...n.style, outline: "2px solid #3dffa8", outlineOffset: 2 }
            : { ...n.style, outline: undefined },
      })),
    );
  }, [selectedNodeId, setNodes]);

  return (
    <div className="relative h-full min-h-[360px] w-full overflow-hidden rounded-xl border border-white/10 bg-ink-950/40">
      <div className="pointer-events-none absolute left-3 top-3 z-10 flex flex-wrap gap-2">
        {LEGEND.map(([key, label]) => (
          <span
            key={key}
            className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-ink-900/80 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em] text-mist-300"
          >
            <span
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{ background: STATUS_COLOR[key] }}
            />
            {label}
          </span>
        ))}
      </div>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        onNodeClick={(_, node) => onSelectNode?.(node.id)}
        onPaneClick={() => onSelectNode?.(null)}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#3dffa822" gap={22} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => {
            const st = (n.data as DagNodeData | undefined)?.status;
            return STATUS_COLOR[st || ""] || "#7eaea0";
          }}
          maskColor="rgba(10,18,16,0.7)"
        />
      </ReactFlow>
    </div>
  );
}
