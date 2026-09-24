"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  apiErrorMessage,
  getBillingUsage,
  getDefaultTenantId,
  getTenantBudget,
  getTenantCost,
  getTenantPolicy,
  getTenantQuota,
  setTenantPolicy,
  type SchedulingPolicyDoc,
  type TenantBudget,
} from "@/lib/api";

function scopeRows(budget: TenantBudget | null) {
  if (!budget) return [];
  return (["tenant", "day", "month", "task"] as const).map((scope) => {
    const s = budget[scope];
    return {
      scope,
      limit: s?.limit,
      spent: s?.spent,
      remaining: s?.remaining,
    };
  });
}

export function TenantPanel() {
  const tenantId = getDefaultTenantId();
  const [quota, setQuota] = useState<Record<string, unknown> | null>(null);
  const [budget, setBudget] = useState<TenantBudget | null>(null);
  const [cost, setCost] = useState<Record<string, unknown> | null>(null);
  const [billingTrend, setBillingTrend] = useState<Array<{ day: string; cost: number; tasks: number }>>([]);
  const [policy, setPolicy] = useState<SchedulingPolicyDoc>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    const results = await Promise.allSettled([
      getTenantQuota(tenantId),
      getTenantBudget(tenantId),
      getTenantCost(tenantId),
      getTenantPolicy(tenantId),
      getBillingUsage(30),
    ]);
    const msgs: string[] = [];
    if (results[0].status === "fulfilled") setQuota(results[0].value as Record<string, unknown>);
    else {
      setQuota(null);
      msgs.push(apiErrorMessage(results[0].reason));
    }
    if (results[1].status === "fulfilled") setBudget(results[1].value);
    else {
      setBudget(null);
      msgs.push(apiErrorMessage(results[1].reason));
    }
    if (results[2].status === "fulfilled") setCost(results[2].value as Record<string, unknown>);
    else {
      setCost(null);
      msgs.push(apiErrorMessage(results[2].reason));
    }
    if (results[3].status === "fulfilled") setPolicy(results[3].value.policy || {});
    else {
      msgs.push(apiErrorMessage(results[3].reason));
    }
    if (results[4].status === "fulfilled") {
      const daily = results[4].value.daily_tasks || [];
      setBillingTrend(
        daily.map((d) => ({
          day: d.day,
          tasks: d.tasks,
          cost: Number(d.tasks || 0), // proxy volume trend when cost series absent
        })),
      );
    } else {
      setBillingTrend([]);
    }
    if (msgs.length) setError([...new Set(msgs)].join(" · "));
  }, [tenantId]);

  useEffect(() => {
    load();
  }, [load]);

  const trend = useMemo(() => {
    if (billingTrend.length) return billingTrend;
    const t = (cost?.trend as Array<{ day: string; cost: number }>) || [];
    if (t.length) return t.map((x) => ({ ...x, tasks: 0 }));
    return [];
  }, [billingTrend, cost]);

  async function onSavePolicy(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setSaved(false);
    try {
      const res = await setTenantPolicy(tenantId, policy);
      setPolicy(res.policy || policy);
      setSaved(true);
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const qLimits = (quota as { limits?: Record<string, unknown>; usage?: Record<string, unknown>; headroom?: Record<string, unknown> }) || {};

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-5">
        <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
          Default Tenant
        </div>
        <div className="mt-2 font-mono text-sm text-mist-100">{tenantId}</div>
        <p className="mt-2 text-sm text-mist-400">名称：Default · Phase 5 配额 / 预算 / 成本 / 调度策略</p>
      </div>

      {error ? <p className="font-mono text-xs text-signal-warm">{error}</p> : null}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
          <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">配额 Quota</div>
          {quota ? (
            <div className="mt-3 space-y-1 font-mono text-[11px] text-mist-200">
              <div>tasks_today · {String((qLimits.usage as Record<string, unknown>)?.tasks_today ?? "—")}</div>
              <div>concurrent · {String((qLimits.usage as Record<string, unknown>)?.concurrent_tasks ?? "—")}</div>
              <div>
                headroom tasks · {String((qLimits.headroom as Record<string, unknown>)?.tasks_today ?? "—")}
              </div>
            </div>
          ) : (
            <p className="mt-3 font-mono text-xs text-mist-400">配额数据不可用</p>
          )}
        </div>

        <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
          <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">预算 Budget</div>
          {budget ? (
            <ul className="mt-3 space-y-1 font-mono text-[11px] text-mist-200">
              {scopeRows(budget).map((r) => (
                <li key={r.scope}>
                  {r.scope}: limit {r.limit ?? "—"} · spent {r.spent ?? "—"} · rem {r.remaining ?? "—"}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 font-mono text-xs text-mist-400">预算数据不可用</p>
          )}
        </div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">成本 Cost</div>
        <div className="mt-2 font-display text-2xl text-mist-100">
          ${Number(cost?.estimated_cost ?? 0).toFixed(4)}
        </div>
        <div className="mt-3 h-40">
          {trend.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={trend}>
                <defs>
                  <linearGradient id="tenantCost" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3dffa8" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#3dffa8" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis
                  dataKey="day"
                  tick={{ fill: "#7eaea0", fontSize: 10 }}
                  tickFormatter={(v: string) => String(v).slice(5)}
                  axisLine={false}
                />
                <YAxis tick={{ fill: "#7eaea0", fontSize: 10 }} width={36} axisLine={false} />
                <Tooltip
                  contentStyle={{
                    background: "#0f1714",
                    border: "1px solid rgba(255,255,255,0.1)",
                    fontSize: 11,
                  }}
                />
                <Area
                  type="monotone"
                  dataKey={billingTrend.length ? "tasks" : "cost"}
                  name={billingTrend.length ? "tasks/day" : "cost"}
                  stroke="#3dffa8"
                  fill="url(#tenantCost)"
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <p className="font-mono text-xs text-mist-400">暂无成本/用量趋势（billing/usage）</p>
          )}
        </div>
      </div>

      <form onSubmit={onSavePolicy} className="rounded-2xl border border-white/10 bg-ink-900/50 p-4 space-y-3">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          调度策略 Policy
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {(
            [
              ["max_cost", "max_cost"],
              ["max_latency_ms", "max_latency_ms"],
              ["priority", "priority"],
              ["tenant_weight", "tenant_weight"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="block">
              <span className="font-mono text-[10px] uppercase text-mist-400">{label}</span>
              <input
                type="number"
                step="any"
                value={policy[key] ?? ""}
                onChange={(e) =>
                  setPolicy((p) => ({
                    ...p,
                    [key]: e.target.value === "" ? undefined : Number(e.target.value),
                  }))
                }
                className="mt-1 w-full rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 text-sm text-mist-100"
              />
            </label>
          ))}
        </div>
        <div className="flex flex-wrap gap-4">
          <label className="flex items-center gap-2 font-mono text-[11px] text-mist-300">
            <input
              type="checkbox"
              checked={Boolean(policy.require_gpu)}
              onChange={(e) => setPolicy((p) => ({ ...p, require_gpu: e.target.checked }))}
            />
            require_gpu
          </label>
          <label className="flex items-center gap-2 font-mono text-[11px] text-mist-300">
            <input
              type="checkbox"
              checked={Boolean(policy.require_streaming)}
              onChange={(e) => setPolicy((p) => ({ ...p, require_streaming: e.target.checked }))}
            />
            require_streaming
          </label>
        </div>
        <button
          type="submit"
          disabled={busy}
          className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase text-ink-950 disabled:opacity-40"
        >
          保存策略
        </button>
        {saved ? <span className="ml-2 font-mono text-[10px] text-signal">已保存</span> : null}
      </form>
    </div>
  );
}
