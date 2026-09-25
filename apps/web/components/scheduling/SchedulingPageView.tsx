"use client";

import { FormEvent, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  apiErrorMessage,
  getRecoveryPlan,
  listSchedulingCandidates,
  previewSchedule,
  selectSchedule,
  simulateSchedule,
  type DiscoverCandidate,
  type RecoveryPlan,
  type SchedulePreviewResult,
} from "@/lib/api";

const SCORE_KEYS = [
  "capability",
  "availability",
  "reliability",
  "latency",
  "resource",
  "cost",
  "queue",
] as const;

export function SchedulingPageView() {
  const [skill, setSkill] = useState("web-research");
  const [candidates, setCandidates] = useState<DiscoverCandidate[]>([]);
  const [excluded, setExcluded] = useState<Array<{ agent_id?: string; reason?: string }>>([]);
  const [candError, setCandError] = useState<string | null>(null);
  const [preview, setPreview] = useState<SchedulePreviewResult | null>(null);
  const [selectResult, setSelectResult] = useState<SchedulePreviewResult | null>(null);
  const [estCost, setEstCost] = useState(0.1);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [recoveryForm, setRecoveryForm] = useState({
    error_code: "TIMEOUT",
    agent_id: "",
    agent_state: "OFFLINE",
  });
  const [recovery, setRecovery] = useState<RecoveryPlan | null>(null);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);

  const [simBody, setSimBody] = useState('{"skill":"web-research","estimated_cost":0.1}');
  const [simResult, setSimResult] = useState<Record<string, unknown> | null>(null);
  const [simError, setSimError] = useState<string | null>(null);

  async function loadCandidates(e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    try {
      const res = await listSchedulingCandidates(skill.trim(), 20);
      setCandidates(res.candidates || []);
      setExcluded(res.excluded || []);
      setCandError(null);
    } catch (err) {
      setCandidates([]);
      setExcluded([]);
      setCandError(apiErrorMessage(err, "调度数据不可用：网关未重建或接口未部署"));
    } finally {
      setBusy(false);
    }
  }

  const stackData = candidates.map((c) => {
    const b = (c.score_breakdown || {}) as Record<string, number>;
    const row: Record<string, string | number> = {
      name: (c.agent_key || c.agent_id || "?").slice(0, 12),
      score: Number(c.score ?? 0),
    };
    for (const k of SCORE_KEYS) {
      row[k] = Number(b[k] ?? 0);
    }
    return row;
  });

  async function onPreview() {
    setBusy(true);
    setActionError(null);
    try {
      const res = await previewSchedule({
        skill,
        requirement: { skill },
        estimated_cost: estCost,
        agents: candidates,
      });
      setPreview(res);
    } catch (err) {
      setPreview(null);
      setActionError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onSelect() {
    if (!window.confirm("确认提交调度选择？将计入预算检查。")) return;
    setBusy(true);
    setActionError(null);
    try {
      const res = await selectSchedule({
        skill,
        requirement: { skill },
        estimated_cost: estCost,
        agents: candidates,
      });
      setSelectResult(res);
    } catch (err) {
      setSelectResult(null);
      setActionError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onRecovery(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await getRecoveryPlan({
        error_code: recoveryForm.error_code || undefined,
        agent_id: recoveryForm.agent_id || undefined,
        agent_state: recoveryForm.agent_state || undefined,
      });
      setRecovery(res);
      setRecoveryError(null);
    } catch (err) {
      setRecovery(null);
      setRecoveryError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onSimulate(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setSimError(null);
    let body: Record<string, unknown>;
    try {
      body = JSON.parse(simBody) as Record<string, unknown>;
      if (!body || typeof body !== "object" || Array.isArray(body)) {
        throw new Error("JSON 必须是对象");
      }
    } catch (err) {
      setSimResult(null);
      setSimError(
        err instanceof SyntaxError
          ? `JSON 解析失败：${err.message}`
          : apiErrorMessage(err, "JSON 无效"),
      );
      setBusy(false);
      return;
    }
    try {
      const res = await simulateSchedule(body);
      setSimResult(res);
      setSimError(null);
    } catch (err) {
      setSimResult(null);
      setSimError(apiErrorMessage(err, "模拟失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 px-4 py-6 md:px-8">
      <div>
        <h1 className="font-display text-3xl text-mist-100">智能调度</h1>
        <p className="mt-2 max-w-3xl font-mono text-[11px] leading-relaxed text-mist-400">
          当前打分 = 0.25·capability + 0.15·availability + 0.20·reliability + 0.15·latency +
          0.15·resource − 0.05·cost − 0.05·queue + 公平性微调（能力 + 负载 + 可靠性 + 成本）
        </p>
      </div>

      {/* Candidates */}
      <section className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          候选与打分
        </div>
        <form onSubmit={loadCandidates} className="mt-3 flex flex-wrap gap-2">
          <input
            value={skill}
            onChange={(e) => setSkill(e.target.value)}
            className="rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-sm text-mist-100"
            placeholder="skill"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase text-ink-950 disabled:opacity-40"
          >
            拉取候选
          </button>
        </form>
        {candError ? <p className="mt-2 font-mono text-xs text-signal-warm">{candError}</p> : null}
        {!candidates.length && !candError ? (
          <p className="mt-3 font-mono text-xs text-mist-400">输入 skill 后拉取调度候选</p>
        ) : null}
        {candidates.length ? (
          <>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[480px] text-left font-mono text-[10px] text-mist-300">
                <thead className="text-mist-400">
                  <tr>
                    <th className="px-2 py-1">agent</th>
                    <th className="px-2 py-1">score</th>
                    <th className="px-2 py-1">status</th>
                    <th className="px-2 py-1">skills</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c) => (
                    <tr key={c.agent_id} className="border-t border-white/5">
                      <td className="px-2 py-1">{c.agent_key || c.agent_id}</td>
                      <td className="px-2 py-1 text-signal">{Number(c.score ?? 0).toFixed(3)}</td>
                      <td className="px-2 py-1">{c.status || "—"}</td>
                      <td className="px-2 py-1">{(c.skills || []).slice(0, 3).join(",")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {excluded.length ? (
              <p className="mt-2 font-mono text-[10px] text-mist-400">
                excluded: {excluded.map((e) => `${e.agent_id}:${e.reason}`).join(" · ")}
              </p>
            ) : null}
            <div className="mt-4 h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={stackData}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis dataKey="name" tick={{ fill: "#7eaea0", fontSize: 10 }} />
                  <YAxis tick={{ fill: "#7eaea0", fontSize: 10 }} width={32} />
                  <Tooltip
                    contentStyle={{
                      background: "#0f1714",
                      border: "1px solid rgba(255,255,255,0.1)",
                      fontSize: 11,
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Bar dataKey="capability" stackId="a" fill="#3dffa8" />
                  <Bar dataKey="availability" stackId="a" fill="#7eaea0" />
                  <Bar dataKey="reliability" stackId="a" fill="#ffb454" />
                  <Bar dataKey="latency" stackId="a" fill="#4a665c" />
                  <Bar dataKey="resource" stackId="a" fill="#6b7280" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>
        ) : null}
      </section>

      {/* Preview / Select */}
      <section className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          预览 vs 提交
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="block">
            <span className="font-mono text-[10px] uppercase text-mist-400">estimated_cost</span>
            <input
              type="number"
              step="0.01"
              value={estCost}
              onChange={(e) => setEstCost(Number(e.target.value))}
              className="mt-1 block rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-sm text-mist-100"
            />
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={onPreview}
            className="rounded-xl border border-white/15 px-4 py-2 font-mono text-xs uppercase text-mist-200 disabled:opacity-40"
          >
            Preview
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onSelect}
            className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase text-ink-950 disabled:opacity-40"
          >
            Select
          </button>
        </div>
        {actionError ? <p className="mt-2 font-mono text-xs text-signal-warm">{actionError}</p> : null}
        {preview ? (
          <pre className="mt-3 max-h-40 overflow-auto rounded-xl border border-white/10 bg-ink-950/50 p-3 font-mono text-[10px] text-mist-300">
            {JSON.stringify(preview, null, 2)}
          </pre>
        ) : null}
        {selectResult ? (
          <div
            className={`mt-3 rounded-xl border p-3 font-mono text-[11px] ${
              selectResult.reason === "budget_exceeded" || !selectResult.selected
                ? "border-signal-warm/40 text-signal-warm"
                : "border-signal/40 text-signal"
            }`}
          >
            selected={String((selectResult.selected as DiscoverCandidate)?.agent_key || selectResult.selected || "null")}{" "}
            · reason={selectResult.reason || "—"}
            {selectResult.budget ? (
              <pre className="mt-2 text-mist-300">{JSON.stringify(selectResult.budget, null, 2)}</pre>
            ) : null}
          </div>
        ) : null}
      </section>

      {/* Recovery */}
      <section className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          失败恢复规划
        </div>
        <form onSubmit={onRecovery} className="mt-3 flex flex-wrap gap-2">
          <input
            value={recoveryForm.error_code}
            onChange={(e) => setRecoveryForm((f) => ({ ...f, error_code: e.target.value }))}
            placeholder="error_code"
            className="rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-xs text-mist-100"
          />
          <input
            value={recoveryForm.agent_id}
            onChange={(e) => setRecoveryForm((f) => ({ ...f, agent_id: e.target.value }))}
            placeholder="agent_id"
            className="rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-xs text-mist-100"
          />
          <input
            value={recoveryForm.agent_state}
            onChange={(e) => setRecoveryForm((f) => ({ ...f, agent_state: e.target.value }))}
            placeholder="agent_state"
            className="rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-xs text-mist-100"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl border border-white/15 px-3 py-2 font-mono text-[10px] uppercase text-mist-200"
          >
            规划
          </button>
        </form>
        {recoveryError ? <p className="mt-2 font-mono text-xs text-signal-warm">{recoveryError}</p> : null}
        {recovery ? (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <div className="rounded-xl border border-white/10 px-3 py-2 font-mono text-[11px] text-mist-300">
              class · {recovery.classification || "—"}
            </div>
            <span className="text-mist-400">→</span>
            <div
              className={`rounded-xl border px-3 py-2 font-mono text-[11px] uppercase ${
                recovery.action === "abort"
                  ? "border-red-400/40 text-red-300"
                  : recovery.action === "reselect"
                    ? "border-signal-warm/40 text-signal-warm"
                    : "border-signal/40 text-signal"
              }`}
            >
              {recovery.action || "—"}
            </div>
            {(recovery.exclude_agent_ids || []).length ? (
              <div className="font-mono text-[10px] text-mist-400">
                exclude: {(recovery.exclude_agent_ids || []).join(", ")}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {/* Simulator */}
      <section className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          模拟器（无副作用）
        </div>
        <form onSubmit={onSimulate} className="mt-3 space-y-2">
          <textarea
            value={simBody}
            onChange={(e) => setSimBody(e.target.value)}
            rows={4}
            className="w-full rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-xs text-mist-100"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl border border-white/15 px-4 py-2 font-mono text-xs uppercase text-mist-200 disabled:opacity-40"
          >
            Simulate
          </button>
        </form>
        {simError ? <p className="mt-2 font-mono text-xs text-signal-warm">{simError}</p> : null}
        {simResult ? (
          <pre className="mt-3 max-h-48 overflow-auto rounded-xl border border-white/10 bg-ink-950/50 p-3 font-mono text-[10px] text-mist-300">
            {JSON.stringify(simResult, null, 2)}
          </pre>
        ) : null}
      </section>
    </div>
  );
}
