"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiErrorMessage, getTaskCostBreakdown, type CostBreakdown } from "@/lib/api";

function tokenTotal(agg: {
  tokens?: unknown;
  input_tokens?: unknown;
  output_tokens?: unknown;
} | null | undefined) {
  if (!agg) return null;
  if (agg.tokens != null && agg.tokens !== "") return Number(agg.tokens);
  const hasIn = agg.input_tokens != null;
  const hasOut = agg.output_tokens != null;
  if (!hasIn && !hasOut) return null;
  return Number(agg.input_tokens || 0) + Number(agg.output_tokens || 0);
}

export function CostPanel({ taskId }: { taskId: string | null }) {
  const [data, setData] = useState<CostBreakdown | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!taskId) {
      setData(null);
      return;
    }
    try {
      const v = await getTaskCostBreakdown(taskId);
      setData(v);
      setError(null);
    } catch (err) {
      setData(null);
      setError(apiErrorMessage(err, "成本数据不可用"));
    }
  }, [taskId]);

  useEffect(() => {
    load();
  }, [load]);

  const chartData = useMemo(() => {
    const by = data?.by_agent || {};
    return Object.entries(by).map(([agent, agg]) => ({
      agent: agent.slice(0, 8),
      cost: Number(agg?.estimated_cost ?? 0),
    }));
  }, [data]);

  if (!taskId) {
    return <p className="font-mono text-xs text-mist-400">未选择任务</p>;
  }

  const empty =
    !error &&
    data &&
    !(data.items || []).length &&
    !Object.keys(data.by_agent || {}).length &&
    !(data.total && Number(data.total.estimated_cost || 0) > 0);

  return (
    <div className="space-y-3">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">成本</div>
      {error ? <p className="font-mono text-[11px] text-signal-warm">{error}</p> : null}
      {empty ? (
        <p className="font-mono text-xs text-mist-400">该任务暂无成本记录</p>
      ) : null}
      {data && !empty ? (
        <>
          <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
              total estimated
            </div>
            <div className="mt-1 font-display text-2xl text-mist-100">
              ${Number(data.total?.estimated_cost ?? 0).toFixed(4)}
            </div>
            <div className="mt-1 font-mono text-[10px] text-mist-400">
              tokens {tokenTotal(data.total) ?? "—"} · gpu_s{" "}
              {data.total?.gpu_seconds ?? "—"} · wall_ms {data.total?.wall_time_ms ?? "—"}
            </div>
          </div>
          {chartData.length ? (
            <div className="h-40 rounded-2xl border border-white/10 bg-ink-900/50 p-3">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 8 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" horizontal={false} />
                  <XAxis type="number" tick={{ fill: "#7eaea0", fontSize: 10 }} axisLine={false} />
                  <YAxis
                    type="category"
                    dataKey="agent"
                    width={56}
                    tick={{ fill: "#7eaea0", fontSize: 10 }}
                    axisLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#0f1714",
                      border: "1px solid rgba(255,255,255,0.1)",
                      fontSize: 11,
                    }}
                  />
                  <Bar dataKey="cost" fill="#3dffa8" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : null}
          <div className="overflow-x-auto rounded-2xl border border-white/10">
            <table className="w-full min-w-[480px] text-left font-mono text-[10px] text-mist-300">
              <thead className="bg-ink-900/80 text-mist-400">
                <tr>
                  <th className="px-2 py-1.5">agent</th>
                  <th className="px-2 py-1.5">attempt</th>
                  <th className="px-2 py-1.5">tokens</th>
                  <th className="px-2 py-1.5">gpu/cpu s</th>
                  <th className="px-2 py-1.5">wall_ms</th>
                  <th className="px-2 py-1.5">est.$</th>
                </tr>
              </thead>
              <tbody>
                {(data.items || []).map((it, i) => (
                  <tr key={i} className="border-t border-white/5">
                    <td className="px-2 py-1">{(it.agent_id || "—").slice(0, 10)}</td>
                    <td className="px-2 py-1">{it.attempt ?? "—"}</td>
                    <td className="px-2 py-1">{tokenTotal(it) ?? "—"}</td>
                    <td className="px-2 py-1">
                      {it.gpu_seconds ?? "—"}/{it.cpu_seconds ?? "—"}
                    </td>
                    <td className="px-2 py-1">{it.wall_time_ms ?? "—"}</td>
                    <td className="px-2 py-1">{Number(it.estimated_cost ?? 0).toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
