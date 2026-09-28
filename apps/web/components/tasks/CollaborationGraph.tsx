"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BezierEdge,
  Controls,
  Handle,
  Position,
  ReactFlow,
  SimpleBezierEdge,
  SmoothStepEdge,
  StepEdge,
  StraightEdge,
  type Edge,
  type EdgeMouseHandler,
  type EdgeTypes,
  type Node,
  type NodeMouseHandler,
  type NodeProps,
  type NodeTypes,
  type OnNodesChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  apiErrorMessage,
  getCollaborationGraph,
  listAgents,
  type Agent,
  type ArtifactItem,
  type CollaborationGraph,
  type CollaborationHandoffSummary,
  type CollaborationLink,
  type CollaborationNode,
} from "@/lib/api";
import { reactFlowOnError, useClientMounted } from "@/lib/reactFlow";
import { CollaborationStream } from "./CollaborationStream";

function fileNameFromUri(uri?: string): string {
  if (!uri) return "file";
  const clean = uri.split("?")[0] || uri;
  const parts = clean.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || uri;
}

/** Turn s3://… / ArtifactItem into a browser-openable HTTP URL. */
function resolveOpenUrl(
  ref: string | ArtifactItem | undefined | null,
  catalog: ArtifactItem[] = [],
): string | undefined {
  if (!ref) return undefined;
  if (typeof ref !== "string") {
    if (ref.url?.startsWith("http")) return ref.url;
    return resolveOpenUrl(ref.uri || ref.url, catalog);
  }
  const raw = ref.trim();
  if (!raw) return undefined;
  if (raw.startsWith("http://") || raw.startsWith("https://")) return raw;

  const byUri = catalog.find((a) => a.uri === raw || a.url === raw);
  if (byUri?.url?.startsWith("http")) return byUri.url;

  // s3://bucket/key → http://127.0.0.1:9000/bucket/key (or infer host from catalog)
  const m = raw.match(/^s3:\/\/([^/]+)\/(.+)$/);
  if (m) {
    const bucket = m[1];
    const key = m[2];
    const sample = catalog.find((a) => a.url?.startsWith("http"));
    if (sample?.url) {
      try {
        const u = new URL(sample.url);
        // sample: http://host:9000/bucket/tasks/...
        const path = u.pathname.replace(/^\//, "");
        if (path.startsWith(`${bucket}/`)) {
          return `${u.origin}/${bucket}/${key}`;
        }
        // sample already path-style under bucket
        return `${u.origin}/${bucket}/${key}`;
      } catch {
        /* fall through */
      }
    }
    return `http://127.0.0.1:9000/${bucket}/${key}`;
  }

  // Match by filename against catalog
  const name = fileNameFromUri(raw);
  const byName = catalog.find((a) => a.name === name && a.url?.startsWith("http"));
  return byName?.url;
}

function artifactHref(a: ArtifactItem, catalog: ArtifactItem[] = []): string | undefined {
  return resolveOpenUrl(a, catalog);
}

function ArtifactLink({
  href,
  label,
  title,
}: {
  href?: string;
  label: string;
  title?: string;
}) {
  if (!href) {
    return <span className="text-mist-400" title={title}>{label}</span>;
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-signal underline-offset-2 hover:underline"
      title={title || href}
    >
      {label}
    </a>
  );
}

/** Pastel fills by branch lane (git-style tracks), matching reference. */
const LANE_FILL = ["#93c5fd", "#c4b5fd", "#6ee7b7", "#fcd34d", "#fda4af", "#a5b4fc"];
const EDGE_STROKE = "#374151";
const NODE_STROKE = "#1f2937";

const COL_W = 176;
const ROW_H = 168;
const ORIGIN_X = 72;
const ORIGIN_Y = 96;
const NODE_SIZE = 36;

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
  detail?: string;
  /** All artifact file names listed under the node */
  fileLines?: string[];
  artCount?: number;
  fill: string;
  highlighted?: boolean;
  /** success / completed — green outer ring only, no "Completed" text */
  done?: boolean;
  failed?: boolean;
  running?: boolean;
};

type BranchCircleFlowNode = Node<CircleData, "branchCircle">;

/** Handoff reasons like "Completed claude-code" are status noise — ring conveys done. */
function isCompletionBlurb(text: string): boolean {
  return /^(completed|success|succeeded|done|finished)\b/i.test(text.trim());
}

function statusKind(status?: string | null): "done" | "failed" | "running" | "other" {
  const s = (status || "").toLowerCase();
  if (["success", "completed", "succeeded", "done", "finished"].includes(s)) return "done";
  if (["failed", "error", "cancelled", "canceled"].includes(s)) return "failed";
  if (["running", "pending", "submitted", "ready", "working"].includes(s)) return "running";
  return "other";
}

function BranchCircle({ data }: NodeProps<BranchCircleFlowNode>) {
  const size = NODE_SIZE;
  const ring = data.done
    ? "#3dffa8"
    : data.failed
      ? "#f87171"
      : data.highlighted
        ? "#3dffa8"
        : data.running
          ? "#fbbf24"
          : NODE_STROKE;
  const ringW = data.done || data.failed || data.highlighted ? 3 : 2.5;
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2.5 !w-2.5 !border-0 !bg-[#374151]"
      />
      <div
        title={[data.title, data.subtitle, data.detail].filter(Boolean).join(" · ")}
        className="h-full w-full rounded-full"
        style={{
          background: data.fill,
          border: `${ringW}px solid ${ring}`,
          boxShadow: data.done
            ? "0 0 0 3px rgba(61,255,168,0.28)"
            : data.highlighted
              ? "0 0 0 3px rgba(61,255,168,0.25)"
              : data.failed
                ? "0 0 0 3px rgba(248,113,113,0.22)"
                : "none",
        }}
      />
      {(data.artCount || 0) > 0 ? (
        <span className="pointer-events-none absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-signal px-1 font-mono text-[9px] font-semibold text-ink-950">
          {data.artCount}
        </span>
      ) : null}
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2.5 !w-2.5 !border-0 !bg-[#374151]"
      />
      <div
        className="pointer-events-none absolute left-1/2 top-[calc(100%+10px)] w-[11rem] -translate-x-1/2 text-center font-mono text-[10px] leading-snug text-mist-300"
      >
        <div className="truncate">{data.title}</div>
        {data.subtitle ? (
          <div className="mt-0.5 truncate text-mist-400">{data.subtitle}</div>
        ) : null}
        {data.detail ? (
          <div className="mt-0.5 truncate text-signal/90">{data.detail}</div>
        ) : null}
        {(data.fileLines || []).length ? (
          <div className="mt-1 space-y-0.5">
            {data.fileLines!.map((name) => (
              <div key={name} className="truncate text-[9px] text-signal/85">
                {name}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

const BranchCircleNode = memo(BranchCircle);
/** Module-level + frozen — React Flow #002 if recreated each render. */
const NODE_TYPES = Object.freeze({
  branchCircle: BranchCircleNode,
}) as unknown as NodeTypes;
const EDGE_TYPES = Object.freeze({
  default: BezierEdge,
  straight: StraightEdge,
  step: StepEdge,
  smoothstep: SmoothStepEdge,
  simplebezier: SimpleBezierEdge,
}) as EdgeTypes;
const FIT_VIEW_OPTIONS = Object.freeze({ padding: 0.35, minZoom: 0.45, maxZoom: 1.35 });
const DEFAULT_EDGE_OPTIONS = Object.freeze({ type: "default" as const });

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
function collectNodeFiles(meta: CollaborationNode, catalog: ArtifactItem[]): string[] {
  const names = new Set<string>();
  if (Array.isArray(meta.artifacts)) {
    for (const a of meta.artifacts as ArtifactItem[]) {
      const n = a.name || fileNameFromUri(a.uri || a.url);
      if (n && n.toLowerCase() !== "meta.json") names.add(n);
    }
  }
  if (Array.isArray(meta.artifact_ids)) {
    for (const uri of meta.artifact_ids as string[]) {
      const n = fileNameFromUri(uri);
      if (n && n.toLowerCase() !== "meta.json") names.add(n);
    }
  }
  const planKey = String(meta.plan_node_id || "").toLowerCase();
  const skill = String(meta.skill || meta.label || "").toLowerCase();
  const tid = String(meta.task_id || "");
  const tidTail = tid.includes(":") ? tid.split(":").pop()!.toLowerCase() : "";
  for (const a of catalog) {
    const nid = String(a.node_id || "").toLowerCase();
    if (!nid) continue;
    if (nid === planKey || nid === skill || nid === tidTail || skill.includes(nid)) {
      const n = a.name || fileNameFromUri(a.uri || a.url);
      if (n && n.toLowerCase() !== "meta.json") names.add(n);
    }
  }
  return Array.from(names);
}

function layoutNodes(
  graph: CollaborationGraph,
  index: AgentIndex,
  highlightNodeKey?: string | null,
): { nodes: Node[]; edges: Edge[] } {
  const rawNodes = graph.nodes || [];
  const rawLinks = graph.links || [];
  const catalog = graph.artifacts || [];

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
      ? shortLabel(String(meta.skill || meta.label || "task"), 22)
      : shortLabel(String(meta.label || key || id.slice(0, 8)), 22);
    const handoffReason =
      typeof meta.handoff_reason === "string"
        ? meta.handoff_reason
        : typeof (meta.handoff as { reason?: string } | undefined)?.reason === "string"
          ? String((meta.handoff as { reason?: string }).reason)
          : "";
    const fileLines = isTask ? collectNodeFiles(meta, catalog) : [];
    const artCount = fileLines.length;
    const kind = statusKind(String(meta.status || ""));
    // Done → green ring only; never print Completed/success as label text
    const subtitle = isTask
      ? kind === "done"
        ? undefined
        : kind === "other"
          ? undefined
          : shortLabel(String(meta.status || ""), 24)
      : shortLabel(key && key !== title ? key : "", 24);
    const meaningfulHandoff =
      handoffReason && !isCompletionBlurb(handoffReason) ? handoffReason : "";
    // Handoff reason as detail; file names listed under node via fileLines
    const detail = isTask && meaningfulHandoff ? shortLabel(meaningfulHandoff, 28) : undefined;
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
        detail: detail || undefined,
        fileLines: fileLines.length ? fileLines : undefined,
        artCount: isTask ? artCount : 0,
        fill: fillForLane(ln),
        highlighted,
        done: kind === "done",
        failed: kind === "failed",
        running: kind === "running",
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

    // Only label the inbound hop into a task node when the link carries a real
    // upstream handoff. Never label orchestrator dispatch or task→agent hops.
    const fromMeta = agentMeta.get(s.from) || taskMeta.get(s.from);
    const fromKey = String(
      (fromMeta as CollaborationNode | undefined)?.agent_key ||
        (fromMeta as CollaborationNode | undefined)?.label ||
        s.from,
    ).toLowerCase();
    const isOrch =
      s.from === "orchestrator" ||
      fromKey === "orchestrator" ||
      s.from.endsWith(":orchestrator");
    const intoTask = s.to.startsWith("task:");
    const outOfTask = s.from.startsWith("task:");
    const linkKind = String(s.link.kind || "");
    const isHandoffLink =
      linkKind === "handoff" ||
      (!isOrch &&
        intoTask &&
        !outOfTask &&
        Array.isArray(s.link.artifact_ids) &&
        s.link.artifact_ids.length > 0);

    const reasonRaw = String(s.link.reason || "").trim();
    const reason =
      isHandoffLink && reasonRaw && !isCompletionBlurb(reasonRaw) ? reasonRaw : "";
    const passArts =
      isHandoffLink && Array.isArray(s.link.artifact_ids) ? s.link.artifact_ids : [];
    const passNames = passArts
      .map(fileNameFromUri)
      .filter((n) => n && n.toLowerCase() !== "meta.json");
    const edgeLabel = reason
      ? shortLabel(reason, 36)
      : passNames.length
        ? shortLabel(passNames.join(" · "), 40)
        : "";

    edges.push({
      id: eid,
      source: s.from,
      target: s.to,
      type: sameLane ? "straight" : "default",
      animated,
      label: edgeLabel || undefined,
      labelStyle: {
        fill: "#7eaea0",
        fontSize: 10,
        fontFamily: "IBM Plex Mono, monospace",
      },
      labelBgStyle: { fill: "#0a1210", fillOpacity: 0.9 },
      labelBgPadding: [6, 3] as [number, number],
      labelBgBorderRadius: 4,
      data: {
        reason: reason || undefined,
        skill: s.link.skill,
        artifact_ids: passArts,
        handoff: isHandoffLink ? s.link.handoff : undefined,
        status: s.link.status,
        task_id: s.link.task_id,
        kind: isHandoffLink ? "handoff" : "dispatch",
      },
      style: {
        stroke: EDGE_STROKE,
        strokeWidth: 2.6,
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
  compact = false,
  showEventStream = true,
  showLists,
}: {
  rootTaskId: string | null;
  denialCount?: number;
  onOpenDenials?: () => void;
  highlightNodeKey?: string | null;
  /** Taller canvas for standalone surfaces (e.g. Artifacts page). */
  compact?: boolean;
  /** When false, keep live graph WS but hide the event log panel. */
  showEventStream?: boolean;
  /** Bottom handoff / final-artifact lists. Default off in compact mode. */
  showLists?: boolean;
}) {
  const listsVisible = showLists ?? !compact;
  // Pin identities for this component instance (survives parent re-renders / HMR churn)
  const nodeTypes = useRef(NODE_TYPES).current;
  const edgeTypes = useRef(EDGE_TYPES).current;
  const mounted = useClientMounted();
  const [graph, setGraph] = useState<CollaborationGraph | null>(null);
  const [agentIndex, setAgentIndex] = useState<AgentIndex>(() => buildAgentIndex([]));
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CollaborationNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<{
    reason?: string;
    skill?: string;
    artifact_ids?: string[];
    status?: string;
    task_id?: string;
  } | null>(null);
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

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    if (!rootTaskId) {
      setGraph(null);
      return;
    }
    if (!opts?.silent) setLoading(true);
    try {
      const g = await getCollaborationGraph(rootTaskId);
      setGraph(g);
      setError(null);
    } catch (err) {
      if (!opts?.silent) setGraph(null);
      setError(apiErrorMessage(err, "协作图不可用"));
    } finally {
      if (!opts?.silent) setLoading(false);
    }
  }, [rootTaskId]);

  const loadRef = useRef(load);
  loadRef.current = load;
  const hintTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onEventsHint = useCallback(() => {
    if (hintTimer.current) clearTimeout(hintTimer.current);
    hintTimer.current = setTimeout(() => {
      void loadRef.current({ silent: true });
    }, 200);
  }, []);

  const onGraphUpdate = useCallback((g: CollaborationGraph) => {
    setGraph(g);
    setError(null);
    setLoading(false);
  }, []);

  useEffect(() => {
    setSelected(null);
    setSelectedEdge(null);
    load();
  }, [load]);

  // Keep graph live even if WS graph push lags (artifacts land after events)
  useEffect(() => {
    if (!rootTaskId) return;
    const intervalMs = wsConnected ? 4000 : 2000;
    const t = setInterval(() => void loadRef.current({ silent: true }), intervalMs);
    return () => clearInterval(t);
  }, [rootTaskId, wsConnected]);

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
    setSelectedEdge(null);
    setSelected((node.data?.raw as CollaborationNode) || null);
  }, []);

  const onEdgeClick: EdgeMouseHandler = useCallback((_e, edge) => {
    setSelected(null);
    const d = (edge.data || {}) as {
      reason?: string;
      skill?: string;
      artifact_ids?: string[];
      status?: string;
      task_id?: string;
    };
    setSelectedEdge({
      reason: d.reason || (typeof edge.label === "string" ? edge.label : undefined),
      skill: d.skill,
      artifact_ids: d.artifact_ids,
      status: d.status,
      task_id: d.task_id,
    });
  }, []);

  const onNodesChange: OnNodesChange = useCallback(() => undefined, []);
  const onPaneClick = useCallback(() => {
    setSelected(null);
    setSelectedEdge(null);
  }, []);

  const handoffs: CollaborationHandoffSummary[] = graph?.handoffs || [];
  const finalArtifacts: ArtifactItem[] = graph?.final_artifacts || [];
  const allArtifacts: ArtifactItem[] = graph?.artifacts || [];

  if (!rootTaskId) {
    return (
      <div className="flex flex-1 items-center justify-center font-mono text-sm text-mist-400">
        选择任务查看运行时协作图
      </div>
    );
  }

  const empty = !loading && graph && (graph.node_count === 0 || !(graph.nodes || []).length);

  return (
    <div
      className={`flex h-full flex-col ${compact ? "min-h-[560px]" : "min-h-[480px]"}`}
    >
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          运行时协作图
        </span>
        <span className="font-mono text-[10px] text-mist-400/80">
          {compact
            ? "按对话结构浏览节点产物 · 点击节点查看文件"
            : "Git 分支布局 · 边标注 = 中间传递 · 叶节点产物 = 最终结果"}
        </span>
        <span
          className={`font-mono text-[10px] uppercase tracking-[0.12em] ${
            wsConnected ? "text-signal" : "text-mist-400"
          }`}
        >
          {wsConnected ? "live·ws" : "live·poll"}
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

      <div
        className={`relative flex-1 overflow-hidden rounded-xl border border-white/10 bg-ink-950/40 ${
          compact ? "min-h-[440px]" : "min-h-[380px]"
        }`}
      >
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
        {empty ? (
          <div className="absolute inset-0 z-[5] flex items-center justify-center bg-ink-950/70 px-4 text-center font-mono text-xs text-mist-400">
            该任务暂无运行时调用边（协作图记录真实发生的 Agent→Agent 调用）
          </div>
        ) : null}
        {(selected || selectedEdge) && (
          <div
            role="dialog"
            aria-label="协作图详情"
            className="absolute right-3 top-3 z-20 w-[min(20rem,calc(100%-1.5rem))] max-h-[min(22rem,calc(100%-1.5rem))] overflow-y-auto rounded-xl border border-white/15 bg-ink-900/95 p-3 shadow-[0_12px_40px_rgba(0,0,0,0.45)] backdrop-blur-md"
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
                {selectedEdge
                  ? "边 · 中间传递"
                  : selected?.type === "agent"
                    ? "Agent 节点"
                    : "Task 节点"}
              </div>
              <button
                type="button"
                className="shrink-0 font-mono text-[10px] text-mist-400 hover:text-mist-200"
                onClick={onPaneClick}
              >
                关闭
              </button>
            </div>
            {selectedEdge ? (
              <div className="mt-2 space-y-1 font-mono text-[11px] text-mist-200">
                {selectedEdge.reason && !isCompletionBlurb(selectedEdge.reason) ? (
                  <div>reason · {selectedEdge.reason}</div>
                ) : null}
                {selectedEdge.skill ? <div>skill · {selectedEdge.skill}</div> : null}
                {selectedEdge.task_id ? (
                  <div className="break-all">task · {selectedEdge.task_id}</div>
                ) : null}
                {(selectedEdge.artifact_ids || []).length ? (
                  <div className="mt-2">
                    <div className="font-mono text-[9px] uppercase tracking-[0.12em] text-mist-400">
                      传递文件
                    </div>
                    <ul className="mt-1 space-y-1">
                      {(selectedEdge.artifact_ids || []).map((uri) => (
                        <li key={uri}>
                          <ArtifactLink
                            href={resolveOpenUrl(uri, allArtifacts)}
                            label={fileNameFromUri(uri)}
                            title={uri}
                          />
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : selected ? (
              <div className="mt-2 space-y-1 font-mono text-[11px] text-mist-200">
                <div className="break-all">id · {selected.id}</div>
                {selected.label ? <div>label · {selected.label}</div> : null}
                {selected.agent_key ? (
                  <div>agent_key · {String(selected.agent_key)}</div>
                ) : null}
                {selected.state ? <div>state · {selected.state}</div> : null}
                {selected.skill ? <div>skill · {selected.skill}</div> : null}
                {selected.depth != null ? <div>depth · {selected.depth}</div> : null}
                {selected.is_leaf ? (
                  <div className="text-signal">leaf · 最终结果节点</div>
                ) : null}
                {typeof selected.handoff_reason === "string" &&
                selected.handoff_reason &&
                !isCompletionBlurb(String(selected.handoff_reason)) ? (
                  <div className="mt-2 rounded-lg border border-white/5 bg-ink-950/50 p-2">
                    <div className="font-mono text-[9px] uppercase tracking-[0.12em] text-mist-400">
                      中间传递
                    </div>
                    <p className="mt-1 text-mist-200">{String(selected.handoff_reason)}</p>
                  </div>
                ) : null}
                {Array.isArray(selected.artifacts) &&
                (selected.artifacts as ArtifactItem[]).length ? (
                  <div className="mt-2">
                    <div className="font-mono text-[9px] uppercase tracking-[0.12em] text-mist-400">
                      节点产物
                    </div>
                    <ul className="mt-1 space-y-1">
                      {(selected.artifacts as ArtifactItem[]).map((a, i) => (
                        <li key={`${a.uri || a.name}-${i}`}>
                          <ArtifactLink
                            href={artifactHref(a, allArtifacts)}
                            label={a.name || fileNameFromUri(a.uri || a.url)}
                            title={a.uri || a.url}
                          />
                          {a.node_id ? (
                            <span className="ml-2 text-mist-400">@{a.node_id}</span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : Array.isArray(selected.artifact_ids) &&
                  (selected.artifact_ids as string[]).length ? (
                  <div className="mt-2">
                    <div className="font-mono text-[9px] uppercase tracking-[0.12em] text-mist-400">
                      节点产物
                    </div>
                    <ul className="mt-1 space-y-1">
                      {(selected.artifact_ids as string[]).map((uri) => (
                        <li key={uri}>
                          <ArtifactLink
                            href={resolveOpenUrl(uri, allArtifacts)}
                            label={fileNameFromUri(uri)}
                            title={uri}
                          />
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
        {mounted ? (
          <ReactFlow
            nodes={empty ? [] : nodes}
            edges={empty ? [] : edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={onNodesChange}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            onPaneClick={onPaneClick}
            fitView
            fitViewOptions={FIT_VIEW_OPTIONS}
            nodesDraggable={false}
            minZoom={0.3}
            maxZoom={1.5}
            defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
            onError={reactFlowOnError}
          >
            <Background color="rgba(255,255,255,0.04)" gap={20} />
            <Controls showInteractive={false} />
          </ReactFlow>
        ) : null}
      </div>

      {listsVisible ? (
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-ink-900/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
                中间传递 · Handoff
              </div>
              <span className="font-mono text-[10px] text-mist-400">{handoffs.length}</span>
            </div>
            {handoffs.length === 0 ? (
              <p className="mt-2 font-mono text-[11px] text-mist-400">
                {loading ? "加载中…" : "等待节点完成时实时出现"}
              </p>
            ) : (
              <ul className="mt-2 max-h-36 space-y-2 overflow-auto">
                {handoffs.map((h, i) => (
                  <li
                    key={`${h.node_key}-${i}`}
                    className="rounded-lg border border-white/5 bg-ink-950/40 px-2 py-1.5 font-mono text-[10px] text-mist-200"
                  >
                    <div className="text-mist-100">
                      {h.skill || h.node_key || "node"}
                    </div>
                    {h.reason && !isCompletionBlurb(String(h.reason)) ? (
                      <p className="mt-0.5 text-mist-300">{h.reason}</p>
                    ) : null}
                    {(h.artifact_ids || []).length ? (
                      <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-mist-400">
                        <span>files ·</span>
                        {(h.artifact_ids || []).map((uri) => (
                          <ArtifactLink
                            key={uri}
                            href={resolveOpenUrl(uri, allArtifacts)}
                            label={fileNameFromUri(uri)}
                            title={uri}
                          />
                        ))}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="rounded-2xl border border-white/10 bg-ink-900/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
                最终产物 · Results
              </div>
              <span className="font-mono text-[10px] text-mist-400">
                {(finalArtifacts.length ? finalArtifacts : allArtifacts).length}
              </span>
            </div>
            {(finalArtifacts.length ? finalArtifacts : allArtifacts).length === 0 ? (
              <p className="mt-2 font-mono text-[11px] text-mist-400">
                {loading ? "加载中…" : "叶节点产物将实时汇入此处"}
              </p>
            ) : (
              <ul className="mt-2 max-h-36 space-y-1.5 overflow-auto">
                {(finalArtifacts.length ? finalArtifacts : allArtifacts).map((a, i) => {
                  const href = artifactHref(a, allArtifacts);
                  return (
                    <li
                      key={`${a.uri || a.name}-${i}`}
                      className="flex items-center justify-between gap-2 font-mono text-[10px]"
                    >
                      <span className="min-w-0 truncate text-mist-200">
                        <ArtifactLink
                          href={href}
                          label={a.name || fileNameFromUri(a.uri || href)}
                          title={a.uri || href}
                        />
                        {a.node_id ? (
                          <span className="ml-1 text-mist-400">@{a.node_id}</span>
                        ) : null}
                      </span>
                      {href ? (
                        <a
                          href={href}
                          target="_blank"
                          rel="noreferrer"
                          className="shrink-0 text-signal underline-offset-2 hover:underline"
                        >
                          打开
                        </a>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      ) : null}

      <CollaborationStream
        rootTaskId={rootTaskId}
        onConnectionChange={setWsConnected}
        onEventsHint={onEventsHint}
        onGraphUpdate={onGraphUpdate}
        silent={!showEventStream}
      />
    </div>
  );
}
