"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiErrorMessage,
  getTaskExecution,
  recoverTask,
  type ExecutionRecord,
  type TaskExecutionView,
} from "@/lib/api";

function recoveryBadge(rec: TaskExecutionView["recovery"]) {
  const cls =
    typeof rec === "string"
      ? rec
      : (rec && typeof rec === "object" && (rec.class || rec.recovery_class)) || "UNKNOWN";
  const c = String(cls).toUpperCase();
  const color =
    c === "TERMINAL"
      ? "text-mist-400 border-white/15"
      : c === "RECOVERABLE"
        ? "text-signal-warm border-signal-warm/40"
        : c === "RUNNING"
          ? "text-signal border-signal/40"
          : "text-mist-400 border-white/10";
  return (
    <span className={`rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase ${color}`}>
      {c}
    </span>
  );
}

function RecordCard({ title, rec }: { title: string; rec: ExecutionRecord | null }) {
  if (!rec) {
    return (
      <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">{title}</div>
        <p className="mt-2 font-mono text-xs text-mist-400">无记录</p>
      </div>
    );
  }
  const token = rec.ownership_token ? String(rec.ownership_token) : "";
  const tokenShort = token ? `${token.slice(0, 10)}…` : "—";
  return (
    <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">{title}</div>
      <div className="mt-3 space-y-1.5 font-mono text-[11px] text-mist-200">
        <div>
          state · <span className="text-signal">{rec.state || "—"}</span>
        </div>
        <div>
          attempt · {rec.attempt ?? "—"} / {rec.max_retries ?? "—"}
        </div>
        <div>agent · {rec.agent_id || "—"}</div>
        <div>operation · {rec.operation || "—"}</div>
        <div title={token}>ownership · {tokenShort}</div>
        <div>started · {rec.started_at || rec.created_at || "—"}</div>
        <div>updated · {rec.updated_at || rec.finished_at || "—"}</div>
        {rec.error ? <div className="text-red-400">error · {String(rec.error)}</div> : null}
        {rec.visited_agents?.length ? (
          <div>visited · {rec.visited_agents.join(" → ")}</div>
        ) : null}
        {rec.branch_lineage != null ? (
          <div className="break-all text-mist-400">
            lineage · {JSON.stringify(rec.branch_lineage).slice(0, 120)}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ExecutionPanel({
  taskId,
  busy,
  onRecovered,
}: {
  taskId: string | null;
  busy?: boolean;
  onRecovered?: () => void;
}) {
  const [data, setData] = useState<TaskExecutionView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  const load = useCallback(async () => {
    if (!taskId) {
      setData(null);
      return;
    }
    try {
      const v = await getTaskExecution(taskId);
      setData(v);
      setError(null);
    } catch (err) {
      setData(null);
      setError(apiErrorMessage(err, "执行记录不可用"));
    }
  }, [taskId]);

  useEffect(() => {
    load();
  }, [load]);

  async function onRecover() {
    if (!taskId || acting || busy) return;
    setActing(true);
    try {
      await recoverTask(taskId);
      await load();
      onRecovered?.();
    } catch (err) {
      setError(apiErrorMessage(err, "恢复失败"));
    } finally {
      setActing(false);
    }
  }

  if (!taskId) {
    return <p className="font-mono text-xs text-mist-400">未选择任务</p>;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          执行记录
        </div>
        <div className="flex items-center gap-2">
          {data ? recoveryBadge(data.recovery) : null}
          <button
            type="button"
            disabled={busy || acting}
            onClick={onRecover}
            className="rounded-lg border border-white/15 px-2 py-1 font-mono text-[10px] uppercase text-mist-200 hover:border-signal/40 disabled:opacity-40"
          >
            恢复
          </button>
        </div>
      </div>
      {error ? <p className="font-mono text-[11px] text-signal-warm">{error}</p> : null}
      {!data && !error ? (
        <p className="font-mono text-xs text-mist-400">加载中…</p>
      ) : null}
      {data ? (
        <div className="grid gap-3">
          <RecordCard title="execute" rec={data.execute} />
          <RecordCard title="delegate" rec={data.delegate} />
        </div>
      ) : null}
    </div>
  );
}
