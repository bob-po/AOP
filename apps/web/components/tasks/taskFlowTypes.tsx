"use client";

/**
 * Stable React Flow type maps for TaskFlowDag.
 * Must live in a module that rarely hot-reloads with the parent, so RF error #002
 * does not fire when TasksWorkspace re-renders.
 */
import { memo } from "react";
import {
  BezierEdge,
  Handle,
  Position,
  SimpleBezierEdge,
  SmoothStepEdge,
  StepEdge,
  StraightEdge,
  type EdgeTypes,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";

import { STATUS_COLOR } from "./taskFlowStatus";

export type DagNodeData = {
  nodeId: string;
  agentKey: string;
  agentLabel: string;
  status: string;
  statusLabel: string;
  attempt?: number;
  selected?: boolean;
};

type DagFlowNode = Node<DagNodeData, "dagNode">;

function DagNodeCard({ data }: NodeProps<DagFlowNode>) {
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

const DagNode = memo(DagNodeCard);

/** Module-level singletons — never recreate inside a component render. */
export const TASK_FLOW_NODE_TYPES = Object.freeze({
  dagNode: DagNode,
}) as unknown as NodeTypes;
export const TASK_FLOW_EDGE_TYPES = Object.freeze({
  default: BezierEdge,
  straight: StraightEdge,
  step: StepEdge,
  smoothstep: SmoothStepEdge,
  simplebezier: SimpleBezierEdge,
}) as EdgeTypes;
