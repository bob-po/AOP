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
  listAgents,
  type Agent,
  type CollaborationGraph,
  type CollaborationLink,
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
  completed: "#7eaea0",
  REGISTERED: "#4a665c",
  READY: "#3dffa8",
  BUSY: "#ffb454",
  DRAINING: "#fbbf24",
  OFFLINE: "#6b7280",
  SUCCEEDED: "#7eaea0",
  FAILED: "#ff6b6b",
  RUNNING: "#3dffa8",
};

const COL_W = 280;
const ROW_H = 150;
const ORIGIN_X = 40;
const ORIGIN_Y = 40;

function statusColor(s?: string) {
  if (!s) return STATUS_COLOR.pending;
  return STATUS_COLOR[s] || STATUS_COLOR[s.toLowerCase()] || STATUS_COLOR.pending;
}

function shortLabel(text: string, max = 28): string {
  const t = text.replace(/\s+/g, " ").trim();
  if (!t) return "";
  if (t.length <= max) return t;
  return `${t.slice(0, Math.max(0, max - 1))}…`;
}

type AgentIndex = {
  /** key or uuid → canonical uuid (or original id) */
  canonical: Map<string, string>;
  /** canonical id → display name */
  names: Map<string, string>;
  /** canonical id → agent_key */
  keys: Map<string, string>;
};

function buildAgentIndex(agents: Agent[]): AgentIndex {
  const canonical = new Map<string, string>();
  const names = new Map<string, string>();
  const keys = new Map<string, string>();
  for (const a of agents) {
    const id = a.agent_id;
    if (!id) continue;
    canonical.set(id, id);
    if (a.agent_key) canonical.set(a.agent_key, id);
    names.set(id, a.name || a.agent_key || id);
    if (a.agent_key) keys.set(id, a.agent_key);
  }
  return { canonical, names, keys };
}

function canonId(raw: string | undefined, index: AgentIndex): string {
  if (!raw) return "";
  return index.canonical.get(raw) || raw;
}

function taskNodeId(taskId: string | undefined, nodes: CollaborationNode[]): string | null {
  if (!taskId) return null;
  const exact = `task:${taskId}`;
  if (nodes.some((n) => n.id === exact)) return exact;
  if (nodes.some((n) => n.id === taskId)) return taskId;
  const byField = nodes.find((n) => n.type === "task" && n.task_id === taskId);
  return byField?.id || null;
}

/**
 * Normalize graph: merge agent_key ↔ UUID aliases, dedupe task nodes.
 * Layout: left→right by call depth so each hop reads caller → task → target.
 */
function layoutNodes(
  graph: CollaborationGraph,
  index: AgentIndex,
  highlightNodeKey?: string | null,
): { nodes: Node[]; edges: Edge[] } {
  const rawNodes = graph.nodes || [];
  const rawLinks = graph.links || [];

  // --- canonicalize agents & rebuild node lists ---
  const agentMeta = new Map<string, CollaborationNode>();
  for (const n of rawNodes) {
    if (n.type !== "agent") continue;
    const id = canonId(n.id, index);
    if (!id) continue;
    const prev = agentMeta.get(id);
    const label =
      index.names.get(id) ||
      prev?.label ||
      n.label ||
      index.keys.get(id) ||
      id;
    agentMeta.set(id, {
      ...prev,
      ...n,
      id,
      type: "agent",
      label: String(label),
      agent_key: index.keys.get(id) || (n.agent_key as string | undefined),
    });
  }

  const taskMeta = new Map<string, CollaborationNode>();
  for (const n of rawNodes) {
    if (n.type !== "task") continue;
    const tid = n.task_id || (n.id.startsWith("task:") ? n.id.slice(5) : n.id);
    const id = `task:${tid}`;
    if (taskMeta.has(id)) continue;
    taskMeta.set(id, {
      ...n,
      id,
      type: "task",
      task_id: tid,
      label: n.skill || n.label || tid,
    });
  }

  const links: CollaborationLink[] = rawLinks.map((l) => ({
    ...l,
    source: canonId(l.source, index),
    target: canonId(l.target, index),
  }));

  // Ensure agents referenced only on links still appear
  for (const l of links) {
    for (const aid of [l.source, l.target]) {
      if (!aid || agentMeta.has(aid)) continue;
      agentMeta.set(aid, {
        id: aid,
        type: "agent",
        label: index.names.get(aid) || index.keys.get(aid) || aid,
        agent_key: index.keys.get(aid),
      });
    }
    if (l.task_id) {
      const id = `task:${l.task_id}`;
      if (!taskMeta.has(id)) {
        taskMeta.set(id, {
          id,
          type: "task",
          task_id: l.task_id,
          label: l.skill || l.task_id,
          skill: l.skill,
          depth: l.depth,
          status: l.status,
        });
      }
    }
  }

  // --- rank agents by call depth (left → right) ---
  // level 0: agents that call but are never targeted (or roots)
  // level d: agents first appearing as target of a depth-d hop
  const agentLevel = new Map<string, number>();
  const sortedLinks = [...links].sort(
    (a, b) => (a.depth ?? 0) - (b.depth ?? 0) || String(a.id).localeCompare(String(b.id)),
  );

  for (const l of sortedLinks) {
    if (l.source && !agentLevel.has(l.source)) agentLevel.set(l.source, 0);
    if (l.target) {
      const d = Math.max(1, Number(l.depth) || 1);
      const prev = agentLevel.get(l.target);
      agentLevel.set(l.target, prev == null ? d : Math.min(prev, d));
    }
  }
  // callers that are also targets keep target level; bump pure callers stay 0
  for (const l of sortedLinks) {
    if (!l.source || !l.target) continue;
    const src = agentLevel.get(l.source) ?? 0;
    const tgt = agentLevel.get(l.target) ?? src + 1;
    // ensure target is to the right of source
    if (tgt <= src) agentLevel.set(l.target, src + 1);
  }

  // slot agents within each level (vertical)
  const byLevel = new Map<number, string[]>();
  for (const id of agentMeta.keys()) {
    const lvl = agentLevel.get(id) ?? 0;
    agentLevel.set(id, lvl);
    const list = byLevel.get(lvl) || [];
    list.push(id);
    byLevel.set(lvl, list);
  }
  for (const list of byLevel.values()) {
    list.sort((a, b) => {
      const na = agentMeta.get(a)?.label || a;
      const nb = agentMeta.get(b)?.label || b;
      return String(na).localeCompare(String(nb));
    });
  }

  const agentPos = new Map<string, { x: number; y: number }>();
  for (const [lvl, ids] of byLevel) {
    ids.forEach((id, i) => {
      agentPos.set(id, {
        x: ORIGIN_X + lvl * COL_W * 2,
        y: ORIGIN_Y + i * ROW_H,
      });
    });
  }

  // tasks sit on the half-column between caller and target; stagger by hop index
  const hopIndex = new Map<string, number>();
  const hopsAtPair = new Map<string, number>();
  for (const l of sortedLinks) {
    const mid = l.task_id ? `task:${l.task_id}` : "";
    if (!mid) continue;
    const pair = `${l.source}->${l.target}`;
    const n = hopsAtPair.get(pair) || 0;
    hopsAtPair.set(pair, n + 1);
    hopIndex.set(mid, n);
  }

  const taskPos = new Map<string, { x: number; y: number }>();
  for (const l of sortedLinks) {
    if (!l.task_id) continue;
    const mid = `task:${l.task_id}`;
    const sp = agentPos.get(l.source);
    const tp = agentPos.get(l.target);
    if (!sp || !tp) {
      taskPos.set(mid, { x: ORIGIN_X + COL_W, y: ORIGIN_Y });
      continue;
    }
    const stagger = (hopIndex.get(mid) || 0) * 36;
    taskPos.set(mid, {
      x: (sp.x + tp.x) / 2,
      y: (sp.y + tp.y) / 2 + stagger,
    });
  }

  // fallback place for tasks without a matching link
  let orphan = 0;
  for (const id of taskMeta.keys()) {
    if (taskPos.has(id)) continue;
    taskPos.set(id, {
      x: ORIGIN_X + COL_W,
      y: ORIGIN_Y + (byLevel.get(0)?.length || 1) * ROW_H + orphan * 100,
    });
    orphan += 1;
  }

  const nodes: Node[] = [];
  for (const [id, n] of agentMeta) {
    const pos = agentPos.get(id) || { x: ORIGIN_X, y: ORIGIN_Y };
    const key = index.keys.get(id) || (n.agent_key as string | undefined);
    const title = n.label || index.names.get(id) || key || id.slice(0, 10);
    nodes.push({
      id,
      position: pos,
      data: {
        raw: n,
        label: `${title}${key && key !== title ? `\n${key}` : ""}\n[${n.state || n.status || "—"}]`,
      },
      type: "default",
      style: {
        background: "rgba(15, 23, 20, 0.92)",
        border: `1.5px solid ${statusColor(n.state || n.status)}`,
        borderRadius: 12,
        color: "#e8f0ea",
        fontSize: 11,
        padding: 10,
        minWidth: 148,
        maxWidth: 200,
        whiteSpace: "pre-line",
        textAlign: "center",
      },
    });
  }

  const highlightSkill = (highlightNodeKey || "").trim().toLowerCase();
  for (const [id, n] of taskMeta) {
    const pos = taskPos.get(id) || { x: ORIGIN_X + COL_W, y: ORIGIN_Y };
    const skill = String(n.skill || n.label || "").toLowerCase();
    const nodeKeyHint = String(n.task_id || id).toLowerCase();
    const highlighted =
      !!highlightSkill &&
      (skill === highlightSkill ||
        nodeKeyHint.includes(highlightSkill) ||
        String(n.label || "").toLowerCase() === highlightSkill);
    nodes.push({
      id,
      position: pos,
      data: {
        raw: n,
        label: `${n.skill || "task"}\nd${n.depth ?? "?"} · ${n.status || "—"}`,
      },
      type: "default",
      style: {
        background: highlighted ? "rgba(61, 255, 168, 0.12)" : "rgba(30, 42, 36, 0.95)",
        border: highlighted
          ? "2px solid #3dffa8"
          : `1.5px dashed ${statusColor(n.status)}`,
        borderRadius: 8,
        color: "#c5d4c9",
        fontSize: 10,
        padding: 8,
        minWidth: 120,
        maxWidth: 160,
        whiteSpace: "pre-line",
        textAlign: "center",
        boxShadow: highlighted ? "0 0 0 1px rgba(61,255,168,0.35)" : undefined,
      },
    });
  }

  const nodeIds = new Set(nodes.map((n) => n.id));
  const allRaw = [...agentMeta.values(), ...taskMeta.values()];
  const edges: Edge[] = [];

  for (const l of links) {
    const st = (l.status || "").toLowerCase();
    const animated = st === "running" || st === "pending" || st === "ready";
    const stroke = statusColor(l.status);
    const mid = taskNodeId(l.task_id, allRaw);
    const base = {
      animated,
      style: { stroke, strokeWidth: 1.8 },
      markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
      labelStyle: { fill: "#7eaea0", fontSize: 9 },
      labelBgStyle: { fill: "rgba(10,16,14,0.85)" },
      labelBgPadding: [4, 2] as [number, number],
      labelBgBorderRadius: 4,
    };

    // Prefer handoff.reason ("why call me"); fall back to skill
    const edgeLabel = shortLabel(
      String(l.reason || l.skill || "").trim(),
      28,
    ) || undefined;
    const edgeHot =
      !!highlightSkill &&
      (String(l.skill || "").toLowerCase() === highlightSkill ||
        String(l.reason || "").toLowerCase().includes(highlightSkill) ||
        (mid != null &&
          String(taskMeta.get(mid)?.skill || "").toLowerCase() === highlightSkill));
    const edgeStyle = {
      ...base,
      style: {
        stroke: edgeHot ? "#3dffa8" : stroke,
        strokeWidth: edgeHot ? 2.6 : 1.8,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: edgeHot ? "#3dffa8" : stroke,
      },
      labelStyle: {
        fill: edgeHot ? "#3dffa8" : "#7eaea0",
        fontSize: 9,
      },
    };

    if (mid && nodeIds.has(mid) && nodeIds.has(l.source) && nodeIds.has(l.target)) {
      edges.push({
        ...edgeStyle,
        id: `${l.id || "e"}:in`,
        source: l.source,
        target: mid,
        label: edgeLabel,
      });
      edges.push({
        ...edgeStyle,
        id: `${l.id || "e"}:out`,
        source: mid,
        target: l.target,
      });
    } else if (nodeIds.has(l.source) && nodeIds.has(l.target)) {
      edges.push({
        ...edgeStyle,
        id: l.id || `${l.source}-${l.target}`,
        source: l.source,
        target: l.target,
        label: edgeLabel,
      });
    }
  }

  return { nodes, edges };
}

export function CollaborationGraphView({
  rootTaskId,
  denialCount,
  onOpenDenials,
  highlightNodeKey,
}: {
  rootTaskId: string | null;
  denialCount?: number;
  onOpenDenials?: () => void;
  /** Plan node_key / skill to emphasize (checkpoint time-travel) */
  highlightNodeKey?: string | null;
}) {
  const [graph, setGraph] = useState<CollaborationGraph | null>(null);
  const [agentIndex, setAgentIndex] = useState<AgentIndex>(() =>
    buildAgentIndex([]),
  );
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CollaborationNode | null>(null);
  const [loading, setLoading] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listAgents()
      .then((r) => {
        if (!cancelled) setAgentIndex(buildAgentIndex(r.agents || []));
      })
      .catch(() => {
        /* registry optional for layout */
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
    () =>
      graph
        ? layoutNodes(graph, agentIndex, highlightNodeKey)
        : { nodes: [], edges: [] },
    [graph, agentIndex, highlightNodeKey],
  );

  const onNodeClick: NodeMouseHandler = useCallback((_e, node) => {
    setSelected((node.data?.raw as CollaborationNode) || null);
  }, []);

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
        <span className="font-mono text-[10px] text-mist-400/80">
          {graph?.source === "plan_synthesis"
            ? "由 Plan DAG 合成 · Agent → Task → Agent（按依赖深度从左到右）"
            : "Agent → Task → Agent（按调用深度从左到右）"}
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
            fitViewOptions={{ padding: 0.2 }}
            proOptions={{ hideAttribution: true }}
            nodesDraggable={false}
            minZoom={0.35}
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
            {selected.label ? <div>label · {selected.label}</div> : null}
            {selected.agent_key ? <div>agent_key · {String(selected.agent_key)}</div> : null}
            {selected.state ? <div>state · {selected.state}</div> : null}
            {selected.status ? <div>status · {selected.status}</div> : null}
            {selected.skill ? <div>skill · {selected.skill}</div> : null}
            {selected.active_tasks != null ? <div>active_tasks · {selected.active_tasks}</div> : null}
            {selected.task_count != null ? <div>task_count · {selected.task_count}</div> : null}
            {selected.last_seen ? <div>last_seen · {selected.last_seen}</div> : null}
            {selected.depth != null ? <div>depth · {selected.depth}</div> : null}
            {selected.type === "task" && selected.skill ? (
              <div className="text-mist-300">
                tip · 边上的绿色短文案是上游 handoff.reason（为何调用）
              </div>
            ) : null}
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
