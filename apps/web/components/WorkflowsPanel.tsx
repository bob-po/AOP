"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { listWorkflows, runWorkflow, type Workflow } from "@/lib/api";

export function WorkflowsPanel() {
  const router = useRouter();
  const [items, setItems] = useState<Workflow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [goal, setGoal] = useState(
    "帮我研究一个 AI 产品，搜索资料并结合知识库分析，然后生成一份报告",
  );

  useEffect(() => {
    let alive = true;
    listWorkflows()
      .then((data) => {
        if (alive) {
          setItems(data.workflows || []);
          setError(null);
        }
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : "failed");
      });
    return () => {
      alive = false;
    };
  }, []);

  async function onRun(wf: Workflow) {
    if (running) return;
    setRunning(wf.workflow_id);
    setError(null);
    try {
      const task = await runWorkflow(wf.workflow_id, goal.trim(), wf.name);
      router.push(`/tasks/${task.task_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "run failed");
      setRunning(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 pb-16 pt-6 md:px-10">
      <h1 className="font-display text-4xl text-mist-100">Workflows</h1>
      <p className="mt-2 max-w-2xl text-sm text-mist-400">
        Reusable Task DAGs. Run skips the Planner and executes the published graph directly.
      </p>

      <label className="mt-8 block">
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          Run input
        </span>
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          rows={3}
          className="mt-2 w-full rounded-2xl border border-white/10 bg-ink-800/70 px-4 py-3 text-sm text-mist-100 outline-none focus:border-signal/40"
        />
      </label>

      {error ? (
        <div className="mt-4 font-mono text-xs text-signal-warm">{error}</div>
      ) : null}

      <div className="mt-10 divide-y divide-white/10 border-y border-white/10">
        {items.length === 0 && !error ? (
          <div className="py-8 font-mono text-sm text-mist-400">No workflows yet.</div>
        ) : null}
        {items.map((wf) => {
          const nodes = wf.dag?.nodes || [];
          return (
            <div
              key={wf.workflow_id}
              className="grid gap-4 py-6 md:grid-cols-[1.4fr_1fr_auto] md:items-center"
            >
              <div>
                <div className="font-display text-xl text-mist-100">{wf.name}</div>
                <div className="mt-1 font-mono text-[11px] text-mist-400">
                  {wf.workflow_key} · v{wf.version || "?"} · {wf.status}
                </div>
                {wf.description ? (
                  <p className="mt-2 text-sm text-mist-400">{wf.description}</p>
                ) : null}
              </div>
              <div className="font-mono text-[11px] text-mist-400">
                {nodes.map((n) => n.id).join(" → ") || "empty dag"}
              </div>
              <button
                type="button"
                disabled={!!running || !goal.trim()}
                onClick={() => onRun(wf)}
                className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-ink-950 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                {running === wf.workflow_id ? "Starting…" : "Run"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
