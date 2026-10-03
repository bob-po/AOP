"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import {
  cancelTask,
  pauseTask,
  recoverTask,
  resumeTask,
  type VisualGraphNode,
} from "@/lib/api";
import { useVisualRuntime } from "@/hooks/useVisualRuntime";
import { LiveAgentNetwork } from "./LiveAgentNetwork";
import {
  AgentInspector,
  ExecutionTimeline,
  TaskInspector,
} from "./Inspectors";

/**
 * Live Agent Network panel.
 * - embedded (Tasks page): graph + bottom timeline — 任务详情 drawer owns task ops
 * - full (Command Center): graph + side inspector
 */
export function TaskNetworkPanel({
  taskId,
  createdAt,
  onBusyChange,
  embedded = false,
}: {
  taskId: string;
  createdAt?: string;
  onBusyChange?: (busy: boolean) => void;
  embedded?: boolean;
}) {
  const { graph, events, isConnected, stats, refresh, error } =
    useVisualRuntime(taskId);
  const [selected, setSelected] = useState<VisualGraphNode | null>(null);
  const [ctrlError, setCtrlError] = useState<string | null>(null);

  const run = useCallback(
    async (fn: () => Promise<unknown>) => {
      onBusyChange?.(true);
      setCtrlError(null);
      try {
        await fn();
        await refresh();
      } catch (err) {
        setCtrlError(err instanceof Error ? err.message : "control failed");
      } finally {
        onBusyChange?.(false);
      }
    },
    [onBusyChange, refresh],
  );

  return (
    <div className="flex h-full min-h-[420px] flex-col rounded-xl border border-white/10 bg-ink-950/40">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-3 py-2">
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${isConnected ? "bg-signal" : "bg-signal-warm"}`}
          />
          <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
            Live Agent Network · {graph?.status || "…"}
            {(graph?.sequence ?? 0) > 0 ? ` · seq ${graph?.sequence}` : ""}
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Ctrl label="Pause" onClick={() => run(() => pauseTask(taskId))} />
          <Ctrl label="Resume" onClick={() => run(() => resumeTask(taskId))} />
          <Ctrl label="Retry" onClick={() => run(() => recoverTask(taskId))} />
          <Ctrl label="Cancel" onClick={() => run(() => cancelTask(taskId))} />
          {embedded ? (
            <Link
              href={`/?task=${encodeURIComponent(taskId)}`}
              className="rounded-lg border border-signal/30 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-signal hover:bg-signal/10"
            >
              Fullscreen
            </Link>
          ) : null}
        </div>
      </div>
      {(error || ctrlError) && (
        <div className="px-3 py-1 font-mono text-[11px] text-signal-warm">
          {error || ctrlError}
        </div>
      )}
      {embedded ? (
        <>
          <div className="min-h-[320px] flex-1">
            <LiveAgentNetwork
              snapshot={graph}
              selectedId={selected?.id}
              onSelect={setSelected}
            />
          </div>
          <div className="max-h-40 border-t border-white/10 px-3 py-2">
            <ExecutionTimeline events={events} />
          </div>
        </>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[1fr_300px]">
          <div className="min-h-[320px]">
            <LiveAgentNetwork
              snapshot={graph}
              selectedId={selected?.id}
              onSelect={setSelected}
            />
          </div>
          <div className="border-t border-white/10 p-3 lg:border-l lg:border-t-0">
            {selected?.type === "agent" ? (
              <AgentInspector
                node={selected}
                events={events}
                onPause={() => run(() => pauseTask(taskId))}
                onRetry={() => run(() => recoverTask(taskId))}
              />
            ) : (
              <TaskInspector
                snapshot={graph}
                events={events}
                stats={stats}
                createdAt={createdAt}
              />
            )}
            <ExecutionTimeline events={events} />
          </div>
        </div>
      )}
    </div>
  );
}

function Ctrl({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-lg border border-white/15 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-mist-300 hover:border-signal/40 hover:text-signal"
    >
      {label}
    </button>
  );
}
