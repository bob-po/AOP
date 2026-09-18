"use client";

import { useEffect, useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";
import type { TaskNode, TaskPlan } from "@/lib/api";

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

type Props = {
  plan?: TaskPlan | null;
  nodes: TaskNode[];
  selectedNodeId?: string | null;
  onSelectNode?: (id: string | null) => void;
};

function buildLayout(plan: TaskPlan | null | undefined, nodes: TaskNode[]) {
  const planNodes =
    plan?.nodes || nodes.map((n) => ({ id: n.id, skill: n.skill, depends_on: [] as string[] }));
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
  const skillMap = new Map(planNodes.map((n) => [n.id, n.skill]));

  const rfNodes: Node[] = [];
  const rfEdges: Edge[] = [];
  const rowH = 120;
  const colW = 220;

  for (const [layer, layerIds] of layers) {
    layerIds.forEach((id, idx) => {
      const st = statusMap.get(id)?.status || "pending";
      const color = STATUS_COLOR[st] || STATUS_COLOR.pending;
      rfNodes.push({
        id,
        position: { x: 40 + idx * colW, y: 40 + layer * rowH },
        data: {
          label: `${skillMap.get(id) || id}\n${st}`,
        },
        style: {
          background: "#152822",
          border: `1.5px solid ${color}`,
          borderRadius: 12,
          color: "#e8f2ee",
          fontSize: 11,
          fontFamily: "IBM Plex Mono, monospace",
          padding: 10,
          width: 160,
          whiteSpace: "pre-line",
          boxShadow:
            st === "running" || st === "waiting_for_user"
              ? `0 0 18px ${color}55`
              : undefined,
        },
      });
    });
  }

  for (const n of planNodes) {
    for (const parent of n.depends_on || []) {
      rfEdges.push({
        id: `${parent}-${n.id}`,
        source: parent,
        target: n.id,
        animated: statusMap.get(n.id)?.status === "running",
        style: { stroke: "#7eaea0" },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#7eaea0" },
      });
    }
  }

  return { rfNodes, rfEdges };
}

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
      })),
    );
  }, [selectedNodeId, setNodes]);

  return (
    <div className="h-full min-h-[360px] w-full overflow-hidden rounded-xl border border-white/10 bg-ink-950/40">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
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
          nodeColor={(n) => (n.style?.border as string)?.replace("1.5px solid ", "") || "#7eaea0"}
          maskColor="rgba(10,18,16,0.7)"
        />
      </ReactFlow>
    </div>
  );
}
