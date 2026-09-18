"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  getTask,
  getTaskArtifacts,
  getTaskEvents,
  type TaskDetail,
  type TaskEvent,
} from "@/lib/api";
import { TaskDag } from "@/components/TaskDag";
import { TaskTrace } from "@/components/TaskTrace";

export function TaskWorkspace({ taskId }: { taskId: string }) {
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [artifacts, setArtifacts] = useState<
    Array<{ node_id?: string; name?: string; uri?: string; url?: string }>
  >([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick() {
      try {
        const [t, e] = await Promise.all([getTask(taskId), getTaskEvents(taskId)]);
        if (!alive) return;
        setTask(t);
        setEvents(e.events || []);
        setError(null);
        if (t.status === "completed" || t.status === "failed") {
          try {
            const a = await getTaskArtifacts(taskId);
            if (alive) setArtifacts(a.artifacts || []);
          } catch {
            // optional
          }
          return;
        }
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "poll failed");
      }
      if (alive) timer = setTimeout(tick, 1000);
    }

    tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [taskId]);

  const counts = useMemo(() => {
    const nodes = task?.nodes || [];
    return {
      total: nodes.length,
      success: nodes.filter((n) => n.status === "success").length,
      running: nodes.filter((n) => n.status === "running" || n.status === "ready").length,
      failed: nodes.filter((n) => n.status === "failed").length,
    };
  }, [task]);

  const goal = task?.input_json?.content || task?.plan_json?.goal || task?.title || "";

  return (
    <div className="mx-auto max-w-7xl px-6 pb-16 pt-4 md:px-10">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link href="/" className="font-mono text-[10px] uppercase tracking-[0.2em] text-mist-400 hover:text-signal">
            ← New task
          </Link>
          <h1 className="mt-2 font-display text-3xl text-mist-100 md:text-4xl">
            Task <span className="text-signal-dim">{taskId.slice(0, 8)}</span>
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-mist-400">{goal}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-ink-800/50 px-4 py-3 font-mono text-xs text-mist-200">
          <div>
            Status{" "}
            <span className="text-signal">{task?.status || "…"}</span>
            {typeof task?.progress === "number" ? ` · ${task.progress}%` : ""}
          </div>
          <div className="mt-1 text-mist-400">
            Nodes {counts.total} · Done {counts.success} · Active {counts.running} · Failed{" "}
            {counts.failed}
          </div>
        </div>
      </div>

      {error ? (
        <div className="mb-4 rounded-xl border border-signal-warm/30 bg-signal-warm/10 px-4 py-3 font-mono text-xs text-signal-warm">
          {error}
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-4">
          <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-mist-400">
            Task Graph
          </div>
          <TaskDag plan={task?.plan_json} nodes={task?.nodes || []} />

          {task?.result_json?.summary ? (
            <div className="rounded-2xl border border-white/10 bg-ink-900/60 p-5">
              <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.2em] text-mist-400">
                Aggregated Result
              </div>
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-mist-200">
                {task.result_json.summary.slice(0, 2500)}
                {task.result_json.summary.length > 2500 ? "…" : ""}
              </pre>
            </div>
          ) : null}

          {artifacts.length > 0 ? (
            <div className="rounded-2xl border border-white/10 bg-ink-900/60 p-5">
              <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.2em] text-mist-400">
                Artifacts
              </div>
              <ul className="space-y-2 font-mono text-xs text-mist-200">
                {artifacts.map((a) => (
                  <li key={`${a.node_id}-${a.name}-${a.uri}`}>
                    <span className="text-signal-dim">{a.node_id}</span>/{a.name}
                    <div className="truncate text-mist-400">{a.uri}</div>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>

        <TaskTrace events={events} />
      </div>
    </div>
  );
}
