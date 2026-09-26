"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  Position,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type NodeProps,
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

/** Pastel fills by branch lane (git-style tracks), matching reference. */
const LANE_FILL = ["#93c5fd", "#c4b5fd", "#6ee7b7", "#fcd34d", "#fda4af", "#a5b4fc"];
const EDGE_STROKE = "#374151";
const NODE_STROKE = "#1f2937";

const COL_W = 96;
const ROW_H = 88;
const ORIGIN_X = 48;
const ORIGIN_Y = 120;
const NODE_SIZE = 28;

type AgentIndex = {
  canonical: Map<string, string>;
  names: Map<string, string>;
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

type CircleData = {
  raw: CollaborationNode;
  title: string;
  subtitle?: string;
  fill: string;
  highlighted?: boolean;
};

function BranchCircle({ data }: NodeProps<CircleData>) {
  const size = NODE_SIZE;
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-0 !bg-[#374151]"
      />
      <div
        title={[data.title, data.subtitle].filter(Boolean).join(" · ")}
        className="h-full w-full rounded-full"
        style={{
          background: data.fill,
          border: `${data.highlighted ? 3 : 2.5}px solid ${data.highlighted ? "#3dffa8" : NODE_STROKE}`,
          boxShadow: data.highlighted ? "0 0 0 3px rgba(61,255,168,0.25)" : "none",
        }}
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-0 !bg-[#374151]"
      />
      <div
        className="pointer-events-none absolute left-1/2 top-[calc(100%+6px)] w-[7.5rem] -translate-x-1/2 text-center font-mono text-[9px] leading-tight text-mist-300"
      >
        <div className="truncate">{data.title}</div>
        {data.subtitle ? (
          <div className="truncate text-mist-400">{data.subtitle}</div>
        ) : null}
      </div>
    </div>
  );
}

const nodeTypes = { branchCircle: memo(BranchCircle) };

function shortLabel(text: string, max = 22): string {
  const t = text.replace(/\s+/g, " ").trim();
  if (!t) return "";
  if (t.length <= max) return t;
  return `${t.slice(0, Math.max(0, max - 1))}…`;
}

/**
 * Git-branch layout: left→right columns, horizontal lanes.
 * Main trunk on lane 0; each fork from a node that already continues on its
 * lane opens a new lane above/below (odd → up, even → down).
 */
function layoutNodes(
  graph: CollaborationGraph,
  index: AgentIndex,
  highlightNodeKey?: string | null,
): { nodes: Node[]; edges: Edge[] } {
  const rawNodes = graph.nodes || [];
  const rawLinks = graph.links || [];

  const agentMeta = new Map<string, CollaborationNode>();
  for (const n of rawNodes) {
    if (n.type !== "agent") continue;
    const id = canonId(n.id, index);
    if (!id) continue;
    const prev = agentMeta.get(id);
    const label =
      index.names.get(id) || prev?.label || n.label || index.keys.get(id) || id;
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

  // Expand each hop into agent → task → agent chain segments
  type Seg = { from: string; to: string; link: CollaborationLink };
  const segs: Seg[] = [];
  const sortedLinks = [...links].sort(
    (a, b) => (a.depth ?? 0) - (b.depth ?? 0) || String(a.id).localeCompare(String(b.id)),
  );
  for (const l of sortedLinks) {
    if (!l.source || !l.target) continue;
    const mid = l.task_id ? `task:${l.task_id}` : null;
    if (mid && taskMeta.has(mid)) {
      segs.push({ from: l.source, to: mid, link: l });
      segs.push({ from: mid, to: l.target, link: l });
    } else {
      segs.push({ from: l.source, to: l.target, link: l });
    }
  }

  // adjacency for children
  const children = new Map<string, string[]>();
  for (const s of segs) {
    const list = children.get(s.from) || [];
    if (!list.includes(s.to)) list.push(s.to);
    children.set(s.from, list);
  }

  // Roots: agents that appear as source but never as target among agents
  const targeted = new Set(segs.map((s) => s.to));
  const roots = [...agentMeta.keys()].filter((id) => !targeted.has(id));
  if (roots.length === 0 && agentMeta.size) {
    roots.push([...agentMeta.keys()][0]);
  }

  const col = new Map<string, number>();
  const lane = new Map<string, number>();
  const usedLanesAtCol = new Map<number, Set<number>>();

  function reserveLane(c: number, preferred: number): number {
    const used = usedLanesAtCol.get(c) || new Set();
    if (!used.has(preferred)) {
      used.add(preferred);
      usedLanesAtCol.set(c, used);
      return preferred;
    }
    // spiral: 0, -1, 1, -2, 2, ...
    for (let k = 1; k < 32; k++) {
      for (const cand of [-k, k]) {
        if (!used.has(cand)) {
          used.add(cand);
          usedLanesAtCol.set(c, used);
          return cand;
        }
      }
    }
    used.add(preferred + 100);
    usedLanesAtCol.set(c, used);
    return preferred + 100;
  }

  // Place roots on main lane
  roots.forEach((id, i) => {
    col.set(id, i);
    lane.set(id, 0);
    reserveLane(i, 0);
  });

  // BFS along segs
  const placed = new Set(roots);
  const queue = [...roots];

  while (queue.length) {
    const cur = queue.shift()!;
    const kids = children.get(cur) || [];
    const parentCol = col.get(cur) ?? 0;
    const parentLane = lane.get(cur) ?? 0;

    kids.forEach((child, kidIdx) => {
      if (placed.has(child) && (col.get(child) ?? -1) > parentCol) {
        return;
      }
      const nextCol = parentCol + 1;
      let nextLane = parentLane;
      if (kidIdx === 0) {
        nextLane = parentLane;
      } else {
        const forkNum = kidIdx;
        const sign = forkNum % 2 === 1 ? -1 : 1;
        nextLane = parentLane + sign * Math.ceil(forkNum / 2);
      }
      nextLane = reserveLane(nextCol, nextLane);
      const prevCol = col.get(child);
      if (prevCol == null || nextCol >= prevCol) {
        col.set(child, nextCol);
        lane.set(child, nextLane);
      }
      if (!placed.has(child)) {
        placed.add(child);
        queue.push(child);
      }
    });
  }

  // Place any leftover nodes
  let orphanCol = Math.max(0, ...col.values(), 0) + 1;
  for (const id of [...agentMeta.keys(), ...taskMeta.keys()]) {
    if (col.has(id)) continue;
    col.set(id, orphanCol++);
    lane.set(id, reserveLane(col.get(id)!, 1));
  }

  // Normalize lanes so main is visually centered (shift so min lane → keep relative)
  const laneVals = [...lane.values()];
  const minLane = laneVals.length ? Math.min(...laneVals) : 0;

  const highlightSkill = (highlightNodeKey || "").trim().toLowerCase();

  function fillForLane(ln: number): string {
    const idx = Math.abs(ln - minLane) % LANE_FILL.length;
    return LANE_FILL[idx];
  }

  const nodes: Node[] = [];
  const allMeta = new Map<string, CollaborationNode>([
    ...agentMeta.entries(),
    ...taskMeta.entries(),
  ]);

  for (const [id, meta] of allMeta) {
    const c = col.get(id) ?? 0;
    const ln = lane.get(id) ?? 0;
    const x = ORIGIN_X + c * COL_W;
    const y = ORIGIN_Y + (ln - minLane) * ROW_H;
    const isTask = meta.type === "task";
    const key = isTask
      ? String(meta.skill || meta.label || "")
      : index.keys.get(id) || String(meta.agent_key || "");
    const title = isTask
      ? shortLabel(String(meta.skill || meta.label || "task"), 16)
      : shortLabel(String(meta.label || key || id.slice(0, 8)), 16);
    const subtitle = isTask
      ? shortLabel(`d${meta.depth ?? "·"} · ${meta.status || "—"}`, 18)
      : shortLabel(key && key !== title ? key : String(meta.state || meta.status || ""), 18);
    const skill = String(meta.skill || meta.label || "").toLowerCase();
    const highlighted =
      !!highlightSkill &&
      (skill === highlightSkill ||
        String(meta.task_id || id).toLowerCase().includes(highlightSkill) ||
        key.toLowerCase() === highlightSkill);

    nodes.push({
      id,
      type: "branchCircle",
      position: { x, y },
      data: {
        raw: meta,
        title,
        subtitle: subtitle || undefined,
        fill: fillForLane(ln),
        highlighted,
      },
      draggable: false,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    });
  }

  const nodeIds = new Set(nodes.map((n) => n.id));
  const edges: Edge[] = [];
  const seenEdge = new Set<string>();

  for (const s of segs) {
    if (!nodeIds.has(s.from) || !nodeIds.has(s.to)) continue;
    const eid = `${s.from}->${s.to}`;
    if (seenEdge.has(eid)) continue;
    seenEdge.add(eid);

    const st = (s.link.status || "").toLowerCase();
    const animated = st === "running" || st === "pending" || st === "submitted" || st === "ready";
    const fromLane = lane.get(s.from) ?? 0;
    const toLane = lane.get(s.to) ?? 0;
    const sameLane = fromLane === toLane;

    edges.push({
      id: eid,
      source: s.from,
      target: s.to,
      type: sameLane ? "straight" : "bezier",
      animated,
      style: {
        stroke: EDGE_STROKE,
        strokeWidth: 3.2,
      },
    });
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
  highlightNodeKey?: string | null;
}) {
  const [graph, setGraph] = useState<CollaborationGraph | null>(null);
  const [agentIndex, setAgentIndex] = useState<AgentIndex>(() => buildAgentIndex([]));
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
        /* registry optional */
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
    () => (graph ? layoutNodes(graph, agentIndex, highlightNodeKey) : { nodes: [], edges: [] }),
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
          Git 分支布局 · 主线 / 上下分叉 = Agent 委派与 spawn
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
          <div className="pointer-events-none absolute left-3 top-3 z-10 flex gap-3 font-mono text-[9px] text-mist-400">
            {LANE_FILL.slice(0, 3).map((c, i) => (
              <span key={c} className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full border border-[#1f2937]"
                  style={{ background: c }}
                />
                {i === 0 ? "主线" : i === 1 ? "分支" : "分支"}
              </span>
            ))}
          </div>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onNodeClick={onNodeClick}
            fitView
            fitViewOptions={{ padding: 0.25 }}
            proOptions={{ hideAttribution: true }}
            nodesDraggable={false}
            minZoom={0.35}
            defaultEdgeOptions={{ type: "bezier" }}
          >
            <Background color="rgba(255,255,255,0.04)" gap={20} />
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
