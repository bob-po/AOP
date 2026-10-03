"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  apiErrorMessage,
  approveTask,
  getTask,
  getTaskArtifacts,
  listTasks,
  rejectTask,
  type ArtifactItem,
  type TaskDetail,
  type TaskNode,
  type TaskSummary,
} from "@/lib/api";
import { usePreflight } from "@/hooks/usePreflight";

function waitingNodes(task: TaskDetail | null): TaskNode[] {
  return (task?.nodes || []).filter(
    (n) => n.status === "waiting_for_user" || n.status === "waiting_for_agent",
  );
}

function approvalLabel(node?: TaskNode | null, planMode?: string): string {
  const mode = String(node?.hitl?.mode || planMode || "system").toLowerCase();
  if (mode === "agent") return "仅 Agent 审批";
  if (mode === "both") return "系统 + Agent 双审批";
  if (mode === "none") return "无审批";
  return "仅系统审批";
}

function shortId(id: string) {
  return id.slice(0, 8);
}

export function HitlInboxView() {
  const { snapshot, refresh: refreshPreflight } = usePreflight();
  const [queue, setQueue] = useState<TaskSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadQueue = useCallback(async () => {
    try {
      const data = await listTasks({ status: "waiting_for_user", limit: 50 });
      const tasks = data.tasks || [];
      setQueue(tasks);
      setError(null);
      setSelectedId((prev) => {
        if (prev && tasks.some((t) => t.task_id === prev)) return prev;
        return tasks[0]?.task_id || null;
      });
    } catch (err) {
      setError(apiErrorMessage(err, "加载待审批队列失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadQueue();
    const id = window.setInterval(() => void loadQueue(), 6000);
    return () => window.clearInterval(id);
  }, [loadQueue]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setArtifacts([]);
      setNote("");
      return;
    }
    let alive = true;
    setNote("");
    (async () => {
      try {
        const [t, arts] = await Promise.all([
          getTask(selectedId),
          getTaskArtifacts(selectedId).catch(() => ({ artifacts: [] as ArtifactItem[] })),
        ]);
        if (!alive) return;
        setDetail(t);
        setArtifacts(arts.artifacts || []);
      } catch (err) {
        if (alive) setError(apiErrorMessage(err, "加载任务失败"));
      }
    })();
    return () => {
      alive = false;
    };
  }, [selectedId]);

  const pending = waitingNodes(detail);
  const goal =
    detail?.input_json?.content ||
    detail?.plan_json?.goal ||
    detail?.title ||
    queue.find((t) => t.task_id === selectedId)?.title ||
    "";
  const systemPending = pending.filter((n) => n.status === "waiting_for_user");
  const canSystemApprove = systemPending.length > 0 || detail?.status === "waiting_for_user";

  const countHint = useMemo(() => {
    const n = snapshot?.waiting_hitl ?? queue.length;
    return n;
  }, [snapshot?.waiting_hitl, queue.length]);

  async function onApprove() {
    if (!selectedId || busy) return;
    setBusy(true);
    try {
      await approveTask(selectedId, undefined, note);
      setNote("");
      await loadQueue();
      await refreshPreflight();
    } catch (err) {
      setError(apiErrorMessage(err, "批准失败"));
    } finally {
      setBusy(false);
    }
  }

  async function onReject() {
    if (!selectedId || busy) return;
    setBusy(true);
    try {
      await rejectTask(selectedId, note.trim() || "rejected from Inbox");
      setNote("");
      await loadQueue();
      await refreshPreflight();
    } catch (err) {
      setError(apiErrorMessage(err, "拒绝失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-7rem)] flex-col lg:flex-row">
      <section className="w-full border-b border-white/10 lg:w-[340px] lg:border-b-0 lg:border-r">
        <div className="px-5 py-6">
          <h1 className="font-display text-3xl tracking-tight text-mist-100">Inbox</h1>
          <p className="mt-2 max-w-sm font-sans text-sm text-mist-400">
            人工审批队列。任务停在 waiting_for_user 时在这里批准或拒绝，而不是翻 Tasks 筛选。
          </p>
          <div className="mt-4 font-mono text-[11px] uppercase tracking-[0.18em] text-signal">
            {countHint} waiting
          </div>
        </div>
        <ul className="max-h-[50vh] overflow-y-auto border-t border-white/10 lg:max-h-[calc(100vh-16rem)]">
          {loading && queue.length === 0 ? (
            <li className="px-5 py-4 font-mono text-xs text-mist-400">loading…</li>
          ) : null}
          {!loading && queue.length === 0 ? (
            <li className="px-5 py-8 font-sans text-sm text-mist-400">
              队列为空。需要审批的节点出现时会列在这里。
            </li>
          ) : null}
          {queue.map((t) => {
            const active = t.task_id === selectedId;
            return (
              <li key={t.task_id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(t.task_id)}
                  className={`flex w-full flex-col gap-1 border-b border-white/5 px-5 py-3 text-left transition ${
                    active ? "bg-signal/10" : "hover:bg-white/5"
                  }`}
                >
                  <span className="font-mono text-[10px] text-mist-400">
                    {shortId(t.task_id)}
                  </span>
                  <span className="line-clamp-2 font-sans text-sm text-mist-100">
                    {t.title || "Untitled task"}
                  </span>
                  <span className="font-mono text-[10px] uppercase tracking-wider text-signal-warm">
                    waiting_for_user
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="flex flex-1 flex-col px-5 py-6 md:px-8">
        {error ? (
          <p className="mb-4 font-mono text-xs text-signal-warm">{error}</p>
        ) : null}

        {!selectedId ? (
          <div className="flex flex-1 items-center justify-center font-mono text-sm text-mist-400">
            选择一条待审批任务
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
                  Task · {shortId(selectedId)}
                </div>
                <h2 className="mt-1 max-w-2xl font-display text-2xl text-mist-100">
                  {detail?.title || "Review"}
                </h2>
              </div>
              <div className="flex gap-2">
                <Link
                  href={`/?task=${encodeURIComponent(selectedId)}`}
                  className="rounded-lg border border-white/15 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-mist-300 hover:border-signal/40 hover:text-signal"
                >
                  Network
                </Link>
                <Link
                  href={`/tasks/${encodeURIComponent(selectedId)}`}
                  className="rounded-lg border border-white/15 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-mist-300 hover:border-signal/40 hover:text-signal"
                >
                  Task detail
                </Link>
              </div>
            </div>

            <div className="mt-6 max-w-2xl">
              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-400">
                Goal
              </div>
              <p className="mt-2 whitespace-pre-wrap font-sans text-sm leading-relaxed text-mist-100">
                {goal || "—"}
              </p>
            </div>

            <div className="mt-8 max-w-2xl">
              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-400">
                Waiting nodes · {pending.length || "—"}
              </div>
              {pending.length === 0 ? (
                <p className="mt-2 font-sans text-sm text-mist-400">
                  任务状态为待审批，但节点列表尚未带回 waiting 节点。仍可批准整单。
                </p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {pending.map((n) => (
                    <li
                      key={n.id}
                      className="border border-white/10 bg-ink-900/40 px-4 py-3"
                    >
                      <div className="font-mono text-xs text-signal">{n.id}</div>
                      <div className="mt-1 font-sans text-sm text-mist-200">
                        {approvalLabel(n)}
                        {n.hitl?.approver_agent
                          ? ` · peer ${n.hitl.approver_agent}`
                          : ""}
                        {n.skill ? ` · ${n.skill}` : ""}
                      </div>
                      {n.hitl?.reason ? (
                        <p className="mt-2 font-sans text-xs text-mist-400">{n.hitl.reason}</p>
                      ) : null}
                      {n.error_message ? (
                        <p className="mt-2 font-mono text-[11px] text-signal-warm">
                          {n.error_message}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {artifacts.length > 0 ? (
              <div className="mt-8 max-w-2xl">
                <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-400">
                  Artifacts · {artifacts.length}
                </div>
                <ul className="mt-2 space-y-1">
                  {artifacts.slice(0, 12).map((a) => {
                    const label =
                      (a.name || a.uri || a.url || "artifact")
                        .replace(/\\/g, "/")
                        .split("/")
                        .pop() || "artifact";
                    const href = a.url || a.uri;
                    return (
                      <li key={`${href || label}-${a.node_id || ""}`}>
                        {href ? (
                          <a
                            href={href}
                            target="_blank"
                            rel="noreferrer"
                            className="font-mono text-[11px] text-signal hover:underline"
                          >
                            {label}
                          </a>
                        ) : (
                          <span className="font-mono text-[11px] text-mist-300">
                            {label}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ) : null}

            <div className="mt-10 max-w-2xl border-t border-white/10 pt-6">
              <label
                htmlFor="hitl-note"
                className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-400"
              >
                Operator note
              </label>
              <textarea
                id="hitl-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                placeholder="可选：批准时写入节点 hitl.input，拒绝时作为 reason"
                className="mt-2 w-full resize-none rounded-xl border border-white/15 bg-ink-900/60 px-4 py-3 text-sm text-mist-100 outline-none focus:border-signal/50"
              />
              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  type="button"
                  disabled={busy || !canSystemApprove}
                  onClick={() => void onApprove()}
                  className="rounded-xl bg-signal px-5 py-2.5 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-ink-950 disabled:opacity-40"
                >
                  {busy ? "…" : "系统批准 →"}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void onReject()}
                  className="rounded-xl border border-signal-warm/50 px-5 py-2.5 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-signal-warm disabled:opacity-40"
                >
                  Reject
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
