"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  apiErrorMessage,
  governanceCheck,
  listGovernanceDenials,
  type GovernanceCheckResult,
  type GovernanceDenial,
} from "@/lib/api";

export function GovernancePanel({
  initialRootTaskId,
}: {
  initialRootTaskId?: string | null;
}) {
  const [denials, setDenials] = useState<GovernanceDenial[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filterRoot, setFilterRoot] = useState(initialRootTaskId || "");
  const [filterCode, setFilterCode] = useState("");
  const [checkResult, setCheckResult] = useState<GovernanceCheckResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    root_task_id: initialRootTaskId || "",
    caller_agent_id: "",
    target_agent_id: "",
    claimed_depth: 1,
  });

  useEffect(() => {
    if (initialRootTaskId) {
      setFilterRoot(initialRootTaskId);
      setForm((f) => ({ ...f, root_task_id: initialRootTaskId }));
    }
  }, [initialRootTaskId]);

  const load = useCallback(async () => {
    try {
      const res = await listGovernanceDenials({
        root_task_id: filterRoot || undefined,
        code: filterCode || undefined,
        limit: 50,
      });
      setDenials(res.denials || []);
      setError(null);
    } catch (err) {
      setDenials([]);
      setError(apiErrorMessage(err, "治理审计不可用"));
    }
  }, [filterRoot, filterCode]);

  useEffect(() => {
    load();
  }, [load]);

  async function onCheck(e: FormEvent) {
    e.preventDefault();
    if (!form.caller_agent_id.trim() || !form.target_agent_id.trim()) return;
    setBusy(true);
    try {
      const res = await governanceCheck({
        root_task_id: form.root_task_id || undefined,
        caller_agent_id: form.caller_agent_id.trim(),
        target_agent_id: form.target_agent_id.trim(),
        claimed_depth: form.claimed_depth,
      });
      setCheckResult(res);
      setError(null);
    } catch (err) {
      setCheckResult(null);
      setError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const resultTone =
    checkResult?.code === "QUEUED" || checkResult?.queued
      ? "border-signal-warm/40 bg-signal-warm/5"
      : checkResult?.allowed
        ? "border-signal/40 bg-signal/5"
        : "border-red-400/40 bg-red-400/5";

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          治理拒绝审计
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            value={filterRoot}
            onChange={(e) => setFilterRoot(e.target.value)}
            placeholder="root_task_id"
            className="rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-xs text-mist-100"
          />
          <input
            value={filterCode}
            onChange={(e) => setFilterCode(e.target.value)}
            placeholder="code"
            className="rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-xs text-mist-100"
          />
          <button
            type="button"
            onClick={load}
            className="rounded-xl border border-white/15 px-3 py-2 font-mono text-[10px] uppercase text-mist-200"
          >
            刷新
          </button>
        </div>
        {error ? <p className="mt-2 font-mono text-xs text-signal-warm">{error}</p> : null}
        {!denials.length && !error ? (
          <p className="mt-3 font-mono text-xs text-mist-400">暂无治理拒绝记录</p>
        ) : (
          <ul className="mt-3 max-h-72 space-y-2 overflow-y-auto">
            {denials.map((d, i) => (
              <li
                key={i}
                className="rounded-xl border border-white/10 bg-ink-950/40 px-3 py-2 font-mono text-[11px] text-mist-300"
              >
                <div className="flex flex-wrap gap-2">
                  <span className="text-signal-warm">{d.code || "DENY"}</span>
                  <span className="text-mist-400">{d.created_at || d.timestamp || ""}</span>
                </div>
                <div className="mt-1 text-mist-200">{d.reason || "—"}</div>
                <div className="mt-1 text-mist-400">
                  root={d.root_task_id || "—"} · caller={d.caller_agent_id || "—"} · target=
                  {d.target_agent_id || "—"}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <form onSubmit={onCheck} className="rounded-2xl border border-white/10 bg-ink-900/50 p-4 space-y-3">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          发起一次授权检查
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {(
            [
              ["root_task_id", "root_task_id"],
              ["caller_agent_id", "caller_agent_id *"],
              ["target_agent_id", "target_agent_id *"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="block sm:col-span-1">
              <span className="font-mono text-[10px] uppercase text-mist-400">{label}</span>
              <input
                value={form[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                className="mt-1 w-full rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-xs text-mist-100"
              />
            </label>
          ))}
          <label className="block">
            <span className="font-mono text-[10px] uppercase text-mist-400">claimed_depth</span>
            <input
              type="number"
              value={form.claimed_depth}
              onChange={(e) => setForm((f) => ({ ...f, claimed_depth: Number(e.target.value) }))}
              className="mt-1 w-full rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-xs text-mist-100"
            />
          </label>
        </div>
        <button
          type="submit"
          disabled={busy}
          className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase text-ink-950 disabled:opacity-40"
        >
          Check
        </button>
        {checkResult ? (
          <div className={`rounded-xl border p-3 ${resultTone}`}>
            <div className="font-mono text-[11px] text-mist-100">
              {checkResult.queued || checkResult.code === "QUEUED"
                ? "QUEUED"
                : checkResult.allowed
                  ? "ALLOWED"
                  : "DENIED"}{" "}
              · {checkResult.code || "—"}
            </div>
            <p className="mt-1 font-mono text-[11px] text-mist-300">{checkResult.reason || ""}</p>
          </div>
        ) : null}
      </form>
    </div>
  );
}
