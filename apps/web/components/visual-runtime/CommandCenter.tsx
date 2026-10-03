"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  cancelTask,
  createTask,
  getTask,
  listAgents,
  pauseTask,
  recoverTask,
  resumeTask,
  type Agent,
  type VisualGraphNode,
} from "@/lib/api";
import { useVisualRuntime } from "@/hooks/useVisualRuntime";
import { LiveAgentNetwork } from "./LiveAgentNetwork";
import {
  AgentInspector,
  ExecutionTimeline,
  GraphReplayBar,
  TaskInspector,
} from "./Inspectors";

const PROMPTS = [
  "Research Vidu S2 and generate a technical report",
  "使用目前所有的 agent，调研 ui2v 这个网页，整理公开资料并输出研究摘要",
  "Discover agents for research and summarize A2A OS architecture",
];

export function CommandCenter() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [goal, setGoal] = useState(PROMPTS[0]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState<VisualGraphNode | null>(null);
  const [createdAt, setCreatedAt] = useState<string | undefined>();
  const [replayCursor, setReplayCursor] = useState<number | null>(null);
  const [replaying, setReplaying] = useState(false);
  const replayTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const { graph, events, isConnected, stats, refresh, error: liveError } =
    useVisualRuntime(taskId);

  useEffect(() => {
    const tid = searchParams.get("task");
    if (tid) setTaskId(tid);
    const prefill = searchParams.get("prefill");
    if (prefill) setGoal(prefill);
  }, [searchParams]);

  useEffect(() => {
    listAgents()
      .then((r) => setAgents(r.agents || []))
      .catch(() => setAgents([]));
  }, []);

  useEffect(() => {
    if (!taskId) return;
    getTask(taskId)
      .then((t) => setCreatedAt(t.created_at as string | undefined))
      .catch(() => undefined);
  }, [taskId]);

  useEffect(() => {
    return () => {
      if (replayTimer.current) clearInterval(replayTimer.current);
    };
  }, []);

  const agentForSelected = useMemo(() => {
    if (!selected?.agent_id) return null;
    return (
      agents.find(
        (a) =>
          a.agent_id === selected.agent_id ||
          a.agent_key === selected.agent_id ||
          a.name === selected.label,
      ) || null
    );
  }, [agents, selected]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const content = goal.trim();
    if (!content || loading) return;
    setLoading(true);
    setError(null);
    setSelected(null);
    setReplayCursor(null);
    setReplaying(false);
    try {
      const task = await createTask(content);
      setTaskId(task.task_id);
      router.replace(`/?task=${encodeURIComponent(task.task_id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "create failed");
    } finally {
      setLoading(false);
    }
  }

  const onPause = useCallback(async () => {
    if (!taskId) return;
    try {
      await pauseTask(taskId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "pause failed");
    }
  }, [taskId, refresh]);

  const onResume = useCallback(async () => {
    if (!taskId) return;
    try {
      await resumeTask(taskId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "resume failed");
    }
  }, [taskId, refresh]);

  const onRetry = useCallback(async () => {
    if (!taskId) return;
    try {
      await recoverTask(taskId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "retry failed");
    }
  }, [taskId, refresh]);

  const onCancel = useCallback(async () => {
    if (!taskId) return;
    try {
      await cancelTask(taskId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "cancel failed");
    }
  }, [taskId, refresh]);

  const startReplay = useCallback(() => {
    if (!events.length) return;
    setReplaying(true);
    setReplayCursor(0);
    if (replayTimer.current) clearInterval(replayTimer.current);
    const max = events.reduce((m, e) => Math.max(m, e.sequence ?? 0), 0);
    let cur = 0;
    replayTimer.current = setInterval(() => {
      cur += 1;
      if (cur > max) {
        if (replayTimer.current) clearInterval(replayTimer.current);
        setReplaying(false);
        setReplayCursor(null);
        return;
      }
      setReplayCursor(cur);
    }, 450);
  }, [events]);

  const stopReplay = useCallback(() => {
    if (replayTimer.current) clearInterval(replayTimer.current);
    setReplaying(false);
    setReplayCursor(null);
  }, []);

  const active = !!taskId;

  return (
    <div className="relative flex min-h-[calc(100vh-4rem)] flex-col">
      {/* Ambient field */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-1/2 top-[18%] h-[520px] w-[520px] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,rgba(61,255,168,0.14),transparent_68%)] blur-2xl" />
        <div className="absolute bottom-0 left-0 right-0 h-48 bg-gradient-to-t from-ink-950/90 to-transparent" />
      </div>

      <div className="relative z-10 flex flex-1 flex-col lg:flex-row">
        <section className="relative min-h-[52vh] flex-1 lg:min-h-0">
          {!active ? (
            <div className="flex h-full flex-col items-center justify-center px-6 pb-36 pt-16 text-center">
              <div className="font-display text-5xl tracking-tight text-mist-100 md:text-6xl">
                A2A OS
              </div>
              <p className="mt-4 max-w-md font-sans text-sm text-mist-400 md:text-base">
                What do you want to build?
              </p>
              <div className="mt-10 h-40 w-40 rounded-full border border-signal/30 bg-signal/5 shadow-[0_0_80px_rgba(61,255,168,0.15)]" />
              <p className="mt-8 font-mono text-[10px] uppercase tracking-[0.22em] text-mist-400">
                Live Agent Network · idle
              </p>
            </div>
          ) : (
            <>
              <div className="absolute left-4 top-4 z-20 flex items-center gap-3">
                <span
                  className={`h-2 w-2 rounded-full ${isConnected ? "bg-signal" : "bg-signal-warm"}`}
                />
                <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
                  Live Agent Network · {graph?.status || "running"} · seq{" "}
                  {graph?.sequence ?? 0}
                </span>
              </div>
              <div className="absolute right-4 top-4 z-20 flex gap-2">
                <ControlBtn label="Pause" onClick={onPause} />
                <ControlBtn label="Resume" onClick={onResume} />
                <ControlBtn label="Retry" onClick={onRetry} />
                <ControlBtn label="Cancel" onClick={onCancel} />
                <ControlBtn
                  label="Tasks"
                  onClick={() =>
                    router.push(`/tasks/${encodeURIComponent(taskId!)}`)
                  }
                />
              </div>
              <LiveAgentNetwork
                snapshot={graph}
                selectedId={selected?.id}
                onSelect={setSelected}
                replayCursor={replayCursor}
              />
            </>
          )}
        </section>

        {active ? (
          <aside className="z-20 w-full border-t border-white/10 bg-ink-950/70 px-4 py-4 backdrop-blur-md lg:w-[340px] lg:border-l lg:border-t-0">
            {selected?.type === "agent" ? (
              <AgentInspector
                node={selected}
                agent={agentForSelected}
                events={events}
                onPause={onPause}
                onRetry={onRetry}
                onInspect={() =>
                  router.push(`/tasks/${encodeURIComponent(taskId!)}`)
                }
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
          </aside>
        ) : null}
      </div>

      {active && events.length > 0 ? (
        <div className="relative z-20 bg-ink-950/80 backdrop-blur-md">
          <GraphReplayBar
            events={events}
            cursor={replayCursor}
            playing={replaying}
            onPlay={startReplay}
            onStop={stopReplay}
            onSeek={(seq) => {
              setReplaying(false);
              if (replayTimer.current) clearInterval(replayTimer.current);
              setReplayCursor(seq);
            }}
          />
        </div>
      ) : null}

      {/* Command bar */}
      <div className="relative z-30 border-t border-white/10 bg-ink-950/85 px-4 py-4 backdrop-blur-md md:px-8">
        {(error || liveError) && (
          <div className="mb-2 font-mono text-xs text-signal-warm">
            {error || liveError}
          </div>
        )}
        <form
          onSubmit={onSubmit}
          className="mx-auto flex max-w-4xl items-end gap-3"
        >
          <div className="flex-1">
            <label className="sr-only" htmlFor="a2a-command">
              Ask A2A OS
            </label>
            <textarea
              id="a2a-command"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              rows={2}
              placeholder="Ask A2A OS…"
              className="w-full resize-none rounded-xl border border-white/15 bg-ink-900/60 px-4 py-3 text-sm text-mist-100 outline-none transition focus:border-signal/50"
            />
            <div className="mt-2 flex flex-wrap gap-2">
              {PROMPTS.map((p) => (
                <button
                  key={p.slice(0, 24)}
                  type="button"
                  onClick={() => setGoal(p)}
                  className="truncate rounded-full border border-white/10 px-3 py-1 font-mono text-[10px] text-mist-400 hover:border-signal/30 hover:text-signal"
                >
                  {p.length > 42 ? `${p.slice(0, 42)}…` : p}
                </button>
              ))}
            </div>
          </div>
          <button
            type="submit"
            disabled={loading || !goal.trim()}
            className="shrink-0 rounded-xl bg-signal px-5 py-3 font-mono text-xs font-semibold uppercase tracking-[0.18em] text-ink-950 transition hover:bg-white disabled:opacity-40"
          >
            {loading ? "…" : "Run →"}
          </button>
        </form>
      </div>
    </div>
  );
}

function ControlBtn({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-lg border border-white/10 bg-ink-900/70 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-300 backdrop-blur hover:border-signal/40 hover:text-signal"
    >
      {label}
    </button>
  );
}
