"use client";

import { useMemo } from "react";
import type { TaskNode, TaskPlan } from "@/lib/api";

type Props = {
  plan?: TaskPlan | null;
  nodes: TaskNode[];
};

const STATUS_COLOR: Record<string, string> = {
  pending: "#4a665c",
  ready: "#ffb454",
  running: "#3dffa8",
  success: "#7eaea0",
  failed: "#ff6b6b",
  retrying: "#ffb454",
};

export function TaskDag({ plan, nodes }: Props) {
  const statusMap = useMemo(() => {
    const m = new Map<string, string>();
    for (const n of nodes) m.set(n.id, n.status);
    return m;
  }, [nodes]);

  const layout = useMemo(() => {
    const planNodes = plan?.nodes || nodes.map((n) => ({ id: n.id, skill: n.skill, depends_on: [] as string[] }));
    const ids = planNodes.map((n) => n.id);
    const deps = new Map<string, string[]>();
    for (const n of planNodes) deps.set(n.id, n.depends_on || []);

    // layer by longest dependency chain
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

    const width = 640;
    const rowH = 110;
    const maxLayer = Math.max(0, ...layers.keys());
    const height = (maxLayer + 1) * rowH + 40;
    const positions = new Map<string, { x: number; y: number }>();

    for (const [layer, layerIds] of layers) {
      const count = layerIds.length;
      layerIds.forEach((id, i) => {
        const x = ((i + 1) / (count + 1)) * width;
        const y = 40 + layer * rowH;
        positions.set(id, { x, y });
      });
    }

    const edges: Array<{ from: string; to: string }> = [];
    for (const n of planNodes) {
      for (const dep of n.depends_on || []) {
        edges.push({ from: dep, to: n.id });
      }
    }

    const meta = new Map(planNodes.map((n) => [n.id, n]));
    return { width, height, positions, edges, meta, ids };
  }, [plan, nodes]);

  return (
    <div className="overflow-x-auto rounded-2xl border border-white/10 bg-ink-900/60 p-4">
      <svg
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="min-w-[520px] w-full"
        role="img"
        aria-label="Task DAG"
      >
        {layout.edges.map((e) => {
          const a = layout.positions.get(e.from);
          const b = layout.positions.get(e.to);
          if (!a || !b) return null;
          const midY = (a.y + b.y) / 2;
          const active =
            statusMap.get(e.from) === "success" ||
            statusMap.get(e.to) === "running" ||
            statusMap.get(e.to) === "ready";
          return (
            <path
              key={`${e.from}-${e.to}`}
              d={`M ${a.x} ${a.y + 28} C ${a.x} ${midY}, ${b.x} ${midY}, ${b.x} ${b.y - 28}`}
              fill="none"
              stroke={active ? "rgba(61,255,168,0.55)" : "rgba(126,174,160,0.25)"}
              strokeWidth={active ? 2 : 1.5}
              strokeDasharray={statusMap.get(e.to) === "running" ? "6 4" : undefined}
              className={statusMap.get(e.to) === "running" ? "animate-dash" : undefined}
            />
          );
        })}

        {layout.ids.map((id) => {
          const p = layout.positions.get(id)!;
          const status = statusMap.get(id) || "pending";
          const skill = layout.meta.get(id)?.skill || id;
          const color = STATUS_COLOR[status] || STATUS_COLOR.pending;
          const running = status === "running";
          return (
            <g key={id} transform={`translate(${p.x}, ${p.y})`}>
              {running ? (
                <circle r={34} fill="none" stroke={color} strokeOpacity={0.35} className="animate-pulse-soft" />
              ) : null}
              <rect
                x={-70}
                y={-28}
                width={140}
                height={56}
                rx={14}
                fill="#152822"
                stroke={color}
                strokeWidth={1.8}
              />
              <text
                textAnchor="middle"
                y={-4}
                fill="#e8f2ee"
                style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}
              >
                {id}
              </text>
              <text
                textAnchor="middle"
                y={14}
                fill="#7eaea0"
                style={{ fontFamily: "var(--font-mono)", fontSize: 10 }}
              >
                {skill}
              </text>
              <text
                textAnchor="middle"
                y={42}
                fill={color}
                style={{ fontFamily: "var(--font-mono)", fontSize: 10 }}
              >
                {status}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
