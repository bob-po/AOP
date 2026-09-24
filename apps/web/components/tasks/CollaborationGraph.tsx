"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MarkerType,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type OnNodesChange,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  apiErrorMessage,
  getCollaborationGraph,
  type CollaborationGraph,
  type CollaborationNode,
} from "@/lib/api";
import { CollaborationStream } from "./CollaborationStream";

/** Align with TaskFlowDag STATUS_COLOR */
const STATUS_COLOR: Record<string, string> = {
  pending: "#4a665c",
  ready: "#ffb454",
  running: "#3dffa8",
  success: "#7eaea0",
  waiting_for_user: "#fbbf24",
  failed: "#ff6b6b",
  retrying: "#ffb454",
  cancelled: "#6b7280",
  REGISTERED: "#4a665c",
  READY: "#3dffa8",
  BUSY: "#ffb454",
  DRAINING: "#fbbf24",
  OFFLINE: "#6b7280",
  SUCCEEDED: "#7eaea0",
  FAILED: "#ff6b6b",
  RUNNING: "#3dffa8",
};

function statusColor(s?: string) {
  if (!s) return STATUS_COLOR.pending;
  return STATUS_COLOR[s] || STATUS_COLOR[s.toLowerCase()] || STATUS_COLOR.pending;
}

function taskNodeId(taskId: string | undefined, nodes: CollaborationNode[]): string | null {
  if (!taskId) return null;
  const exact = `task:${taskId}`;
  if (nodes.some((n) => n.id === exact)) return exact;
  if (nodes.some((n) => n.id === taskId)) return taskId;
  const byField = nodes.find((n) => n.type === "task" && n.task_id === taskId);
  return byField?.id || null;
}

function layoutNodes(graph: CollaborationGraph): { nodes: Node[]; edges: Edge[] } {
  const agents = (graph.nodes || []).filter((n) => n.type === "agent");
  const tasks = (graph.nodes || []).filter((n) => n.type === "task");
  const allRaw = graph.nodes || [];
  const nodes: Node[] = [];

  agents.forEach((n, i) => {
    const col = i % 4;
    const row = Math.floor(i / 4);
    nodes.push({
      id: n.id,
      position: { x: 40 + col * 260, y: 40 + row * 160 },
      data: {
        raw: n,
        label: `${rawLabel(n)}\n[${n.state || "—"}] · t${n.active_tasks ?? n.task_count ?? 0}`,
      },
      type: "default",
      style: {
        background: "rgba(15, 23, 20, 0.92)",
        border: `1.5px solid ${statusColor(n.state || n.status)}`,
        borderRadius: 12,
        color: "#e8f0ea",
        fontSize: 11,
        padding: 10,
        minWidth: 140,
        whiteSpace: "pre-line",
      },
    });
  });

  // Place task nodes between callers/targets when possible
  tasks.forEach((n, i) => {
    const link = (graph.links || []).find(
      (l) => l.task_id && (n.id === `task:${l.task_id}` || n.task_id === l.task_id || n.id === l.task_id),
    );
    const srcIdx = agents.findIndex((a) => a.id === link?.source);
    const tgtIdx = agents.findIndex((a) => a.id === link?.target);
    let x = 80 + (i % 4) * 260;
    let y = 220 + Math.floor(i / 4) * 120;
    if (srcIdx >= 0 && tgtIdx >= 0) {
      const sx = 40 + (srcIdx % 4) * 260;
      const sy = 40 + Math.floor(srcIdx / 4) * 160;
      const tx = 40 + (tgtIdx % 4) * 260;
      const ty = 40 + Math.floor(tgtIdx / 4) * 160;
      x = (sx + tx) / 2;
      y = (sy + ty) / 2 + 50;
    }
    nodes.push({
      id: n.id,
      position: { x, y },
      data: {
        raw: n,
        label: `${n.skill || "task"}\nd${n.depth ?? "?"} · ${n.status || "—"}`,
      },
      style: {
        background: "rgba(20, 28, 24, 0.85)",
        border: `1px dashed ${statusColor(n.status)}`,
        borderRadius: 8,
        color: "#c5d4c9",
        fontSize: 10,
        padding: 8,
        minWidth: 120,
        whiteSpace: "pre-line",
      },
    });
  });

  const nodeIds = new Set(nodes.map((n) => n.id));
  const edges: Edge[] = [];

  for (const l of graph.links || []) {
    const st = (l.status || "").toLowerCase();
    const animated = st === "running" || st === "pending" || st === "ready";
    const stroke = statusColor(l.status);
    const mid = taskNodeId(l.task_id, allRaw);
    const base = {
      animated,
      style: { stroke, strokeWidth: 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
      labelStyle: { fill: "#7eaea0", fontSize: 9 },
    };

    if (mid && nodeIds.has(mid) && nodeIds.has(l.source) && nodeIds.has(l.target)) {
      // caller → task → target
      edges.push({
        ...base,
        id: `${l.id || "e"}:in`,
        source: l.source,
        target: mid,
        label: l.skill || undefined,
      });
      edges.push({
        ...base,
        id: `${l.id || "e"}:out`,
        source: mid,
        target: l.target,
      });
    } else if (nodeIds.has(l.source) && nodeIds.has(l.target)) {
      // fallback direct agent→agent
      edges.push({
        ...base,
        id: l.id || `${l.source}-${l.target}`,
        source: l.source,
        target: l.target,
        label: l.skill || undefined,
      });
    }
  }

  return { nodes, edges };
}

function rawLabel(n: CollaborationNode) {
  return n.label || n.id.slice(0, 10);
}

export function CollaborationGraphView({
  rootTaskId,
  denialCount,
  onOpenDenials,
}: {
  rootTaskId: string | null;
  denialCount?: number;
  onOpenDenials?: () => void;
}) {
  const [graph, setGraph] = useState<CollaborationGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CollaborationNode | null>(null);
  const [loading, setLoading] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);

  const load = useCallback(async () => {
    if (!rootTaskId) {
      setGraph(null);
      return;
    }
    setLoading(true);
    try {
      const g = await getCollaborationGraph(rootTaskId);
      setGraph(g);
      setError(null);
    } catch (err) {
      setGraph(null);
      setError(apiErrorMessage(err, "协作图不可用"));
    } finally {
      setLoading(false);
    }
  }, [rootTaskId]);

  const loadRef = useRef(load);
  loadRef.current = load;
  const hintTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onEventsHint = useCallback(() => {
    if (hintTimer.current) clearTimeout(hintTimer.current);
    hintTimer.current = setTimeout(() => {
      void loadRef.current();
    }, 800);
  }, []);

  // Initial load always; poll only when WS is down (avoid triple-polling with useTaskLive + stream)
  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!rootTaskId || wsConnected) return;
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load, rootTaskId, wsConnected]);

  useEffect(() => {
    return () => {
      if (hintTimer.current) clearTimeout(hintTimer.current);
    };
  }, []);

  const { nodes, edges } = useMemo(
    () => (graph ? layoutNodes(graph) : { nodes: [], edges: [] }),
    [graph],
  );

  const onNodeClick: NodeMouseHandler = useCallback((_e, node) => {
    setSelected((node.data?.raw as CollaborationNode) || null);
  }, []);

  // Silence reactflow v11 controlled-nodes warning when nodesDraggable={false}
  const onNodesChange: OnNodesChange = useCallback(() => undefined, []);

  if (!rootTaskId) {
    return (
      <div className="flex flex-1 items-center justify-center font-mono text-sm text-mist-400">
        选择任务查看运行时协作图
      </div>
    );
  }

  const empty = !loading && graph && (graph.node_count === 0 || !(graph.nodes || []).length);

  return (
    <div className="flex h-full min-h-[320px] flex-col">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          运行时协作图
        </span>
        {typeof denialCount === "number" && denialCount > 0 ? (
          <button
            type="button"
            onClick={onOpenDenials}
            className="rounded-lg border border-signal-warm/40 px-2 py-0.5 font-mono text-[10px] text-signal-warm hover:bg-signal-warm/10"
          >
            治理拒绝 {denialCount} 次
          </button>
        ) : null}
        {error ? <span className="font-mono text-[10px] text-signal-warm">{error}</span> : null}
      </div>

      {empty ? (
        <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-white/10 px-4 text-center font-mono text-xs text-mist-400">
          该任务暂无运行时调用边（协作图记录真实发生的 Agent→Agent 调用）
        </div>
      ) : (
        <div className="relative min-h-0 flex-1 rounded-xl border border-white/10 bg-ink-950/40">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onNodeClick={onNodeClick}
            fitView
            proOptions={{ hideAttribution: true }}
            nodesDraggable={false}
          >
            <Background color="rgba(255,255,255,0.04)" gap={18} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      )}

      {selected ? (
        <div className="mt-2 rounded-2xl border border-white/10 bg-ink-900/50 p-3">
          <div className="flex items-start justify-between">
            <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
              {selected.type === "agent" ? "Agent 节点" : "Task 节点"}
            </div>
            <button
              type="button"
              className="font-mono text-[10px] text-mist-400 hover:text-mist-200"
              onClick={() => setSelected(null)}
            >
              关闭
            </button>
          </div>
          <div className="mt-2 space-y-1 font-mono text-[11px] text-mist-200">
            <div>id · {selected.id}</div>
            {selected.state ? <div>state · {selected.state}</div> : null}
            {selected.status ? <div>status · {selected.status}</div> : null}
            {selected.skill ? <div>skill · {selected.skill}</div> : null}
            {selected.active_tasks != null ? <div>active_tasks · {selected.active_tasks}</div> : null}
            {selected.task_count != null ? <div>task_count · {selected.task_count}</div> : null}
            {selected.last_seen ? <div>last_seen · {selected.last_seen}</div> : null}
            {selected.depth != null ? <div>depth · {selected.depth}</div> : null}
          </div>
        </div>
      ) : null}

      <CollaborationStream
        rootTaskId={rootTaskId}
        onConnectionChange={setWsConnected}
        onEventsHint={onEventsHint}
      />
    </div>
  );
}
