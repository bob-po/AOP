"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  disableAgent,
  drainAgent,
  enableAgent,
  getAgentCapacity,
  getAgentReliability,
  getAgentRuntimeHealth,
  getAgentStats,
  healthCheckAgent,
  heartbeatAgent,
  listAgents,
  previewRouter,
  registerAgent,
  apiErrorMessage,
  type Agent,
  type AgentCapacity,
  type AgentPerformance,
  type AgentReliability,
  type AgentRuntimeHealth,
} from "@/lib/api";
import { MarketplacePanel } from "@/components/MarketplacePanel";

type Tab = "registry" | "market" | "routing";
type ViewMode = "cards" | "list";

const LIFE_COLOR: Record<string, string> = {
  REGISTERED: "text-mist-400",
  READY: "text-signal",
  BUSY: "text-signal-warm",
  DRAINING: "text-amber-300",
  OFFLINE: "text-mist-400",
};

export function AgentsPageView() {
  const [tab, setTab] = useState<Tab>("registry");
  const [view, setView] = useState<ViewMode>("cards");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [perf, setPerf] = useState<AgentPerformance[]>([]);
  const [routerSkill, setRouterSkill] = useState("web-research");
  const [routerPreview, setRouterPreview] = useState<{
    smart: boolean;
    selected: string | null;
    candidates: Array<{
      agent_id: string;
      agent_key: string;
      name: string;
      score: number;
      priority: number;
      score_breakdown?: Record<string, number>;
    }>;
  } | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showRegister, setShowRegister] = useState(false);
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:8001");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Agent | null>(null);
  const [lifeHealth, setLifeHealth] = useState<AgentRuntimeHealth | null>(null);
  const [capacity, setCapacity] = useState<AgentCapacity | null>(null);
  const [reliability, setReliability] = useState<AgentReliability | null>(null);
  const [capNote, setCapNote] = useState<string | null>(null);
  const [relNote, setRelNote] = useState<string | null>(null);
  const [lifeError, setLifeError] = useState<string | null>(null);

  useEffect(() => {
    if (!selected) {
      setLifeHealth(null);
      setCapacity(null);
      setReliability(null);
      setCapNote(null);
      setRelNote(null);
      setLifeError(null);
      return;
    }
    let alive = true;
    const id = selected.agent_id;
    (async () => {
      const [h, c, r] = await Promise.allSettled([
        getAgentRuntimeHealth(id),
        getAgentCapacity(id),
        getAgentReliability(id),
      ]);
      if (!alive) return;
      if (h.status === "fulfilled") {
        setLifeHealth(h.value);
        setLifeError(null);
      } else {
        setLifeHealth(null);
        setLifeError(apiErrorMessage(h.reason, "生命周期健康不可用"));
      }
      if (c.status === "fulfilled") {
        setCapacity(c.value);
        setCapNote(null);
      } else {
        setCapacity(null);
        setCapNote("容量数据暂不可用（Gateway 需代理 GET /v1/agents/{id}/capacity）");
      }
      if (r.status === "fulfilled") {
        setReliability(r.value);
        setRelNote(null);
      } else {
        setReliability(null);
        setRelNote("可靠性数据暂不可用（Gateway 需代理 GET /v1/agents/{id}/reliability）");
      }
    })();
    return () => {
      alive = false;
    };
  }, [selected]);

  async function load() {
    try {
      const [data, stats] = await Promise.all([
        listAgents(status ? { status } : undefined),
        getAgentStats(50).catch(() => ({ agents: [] as AgentPerformance[] })),
      ]);
      setAgents(data.agents || []);
      setPerf(stats.agents || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed");
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [status]);

  useEffect(() => {
    if (tab !== "routing") return;
    let alive = true;
    previewRouter(routerSkill)
      .then((p) => {
        if (alive) setRouterPreview(p);
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : "router preview failed");
      });
    return () => {
      alive = false;
    };
  }, [tab, routerSkill]);

  const perfById = useMemo(() => {
    const m = new Map<string, AgentPerformance>();
    for (const p of perf) m.set(p.agent_id, p);
    return m;
  }, [perf]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return agents;
    return agents.filter(
      (a) =>
        a.name.toLowerCase().includes(needle) ||
        a.agent_key.toLowerCase().includes(needle) ||
        (a.skills || []).some((s) => s.toLowerCase().includes(needle)),
    );
  }, [agents, q]);

  const chartData = useMemo(
    () =>
      perf.slice(0, 8).map((p) => ({
        name: p.agent_key.slice(0, 10),
        success: Math.round((p.success_rate || 0) * 100),
        latency: Math.round(p.avg_latency_ms || 0),
      })),
    [perf],
  );

  async function onRegister(e: FormEvent) {
    e.preventDefault();
    if (!endpoint.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await registerAgent(endpoint.trim());
      setShowRegister(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "register failed");
    } finally {
      setBusy(false);
    }
  }

  async function onHealth(a: Agent) {
    setBusy(true);
    try {
      await healthCheckAgent(a.agent_id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "health failed");
    } finally {
      setBusy(false);
    }
  }

  async function onToggle(a: Agent) {
    setBusy(true);
    try {
      if (a.status === "disabled" || a.status === "offline") {
        await enableAgent(a.agent_id);
      } else {
        await disableAgent(a.agent_id);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "toggle failed");
    } finally {
      setBusy(false);
    }
  }

  const metricData = selected
    ? (() => {
        const p = perfById.get(selected.agent_id);
        return [
          { name: "requests", value: p?.request_count ?? 0 },
          { name: "success%", value: Math.round((p?.success_rate || 0) * 100) },
          { name: "latency", value: Math.round(p?.avg_latency_ms || 0) },
          { name: "priority", value: selected.priority || 0 },
        ];
      })()
    : [];

  return (
    <div className="relative px-4 py-6 md:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl text-mist-100">Agent 注册中心</h1>
          <p className="mt-1 text-sm text-mist-400">
            虚拟 Agent = harness × 角色。注册表、市场一键部署、智能路由与运行指标。
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowRegister(true)}
          className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-ink-950"
        >
          注册新 Agent
        </button>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        {(["registry", "market", "routing"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`rounded-full px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.14em] ${
              tab === t ? "bg-signal/15 text-signal" : "text-mist-400"
            }`}
          >
            {t === "registry" ? "注册表" : t === "market" ? "市场" : "智能路由"}
          </button>
        ))}
      </div>

      {error ? <div className="mt-4 font-mono text-xs text-signal-warm">{error}</div> : null}

      {tab === "market" ? (
        <div className="mt-4">
          <MarketplacePanel embedded />
        </div>
      ) : tab === "routing" ? (
        <div className="mt-6 grid gap-4 lg:grid-cols-[1fr_1.2fr]">
          <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
              Router Preview
            </div>
            <input
              value={routerSkill}
              onChange={(e) => setRouterSkill(e.target.value)}
              className="mt-3 w-full rounded-xl border border-white/10 bg-ink-950 px-3 py-2 font-mono text-sm text-mist-100 outline-none focus:border-signal/40"
              placeholder="skill id"
            />
            <div className="mt-3 font-mono text-[11px] text-mist-400">
              smart={String(routerPreview?.smart ?? "—")} · selected=
              {(routerPreview?.selected || "—").slice(0, 8)}
            </div>
            <ul className="mt-4 max-h-72 space-y-2 overflow-auto">
              {(routerPreview?.candidates || []).map((c, i) => (
                <li
                  key={c.agent_id}
                  className="rounded-lg border border-white/10 px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm text-mist-100">
                      #{i + 1} {c.name}
                    </span>
                    <span className="font-mono text-[11px] text-signal">
                      score {c.score.toFixed(3)}
                    </span>
                  </div>
                  <div className="mt-1 font-mono text-[10px] text-mist-400">
                    priority={c.priority}
                    {c.score_breakdown
                      ? ` · sr=${(c.score_breakdown.success_rate ?? 0).toFixed(2)} lat=${(c.score_breakdown.latency ?? 0).toFixed(2)}`
                      : ""}
                  </div>
                </li>
              ))}
              {(routerPreview?.candidates || []).length === 0 ? (
                <li className="font-mono text-xs text-mist-400">无在线候选</li>
              ) : null}
            </ul>
          </div>
          <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
            <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
              近窗成功率 / 延迟
            </div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <XAxis dataKey="name" tick={{ fill: "#7eaea0", fontSize: 10 }} />
                  <YAxis tick={{ fill: "#7eaea0", fontSize: 10 }} width={28} />
                  <Tooltip
                    contentStyle={{
                      background: "#152822",
                      border: "1px solid rgba(255,255,255,0.1)",
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="success" fill="#3dffa8" radius={[6, 6, 0, 0]} />
                  <Bar dataKey="latency" fill="#ffb454" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索 Agent / skill"
              className="rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 text-sm text-mist-100 outline-none focus:border-signal/40"
            />
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-xs text-mist-200"
            >
              <option value="">全部状态</option>
              <option value="online">在线</option>
              <option value="degraded">降级</option>
              <option value="offline">离线</option>
              <option value="disabled">禁用</option>
            </select>
            <div className="ml-auto flex gap-1">
              {(["cards", "list"] as ViewMode[]).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setView(v)}
                  className={`rounded-lg px-3 py-1.5 font-mono text-[10px] uppercase ${
                    view === v ? "bg-white/10 text-signal" : "text-mist-400"
                  }`}
                >
                  {v === "cards" ? "卡片" : "列表"}
                </button>
              ))}
            </div>
          </div>

          {view === "cards" ? (
            <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {filtered.map((a) => (
                <div
                  key={a.agent_id}
                  className="rounded-2xl border border-white/10 bg-ink-900/50 p-4 transition hover:border-signal/25"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-display text-xl text-mist-100">{a.name}</div>
                      <div className="mt-1 font-mono text-[11px] text-mist-400">{a.agent_key}</div>
                    </div>
                    <StatusPill status={a.status} />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {(a.skills || []).slice(0, 6).map((s) => (
                      <span
                        key={s}
                        className="rounded-full border border-signal/20 px-2 py-0.5 font-mono text-[10px] text-signal-dim"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                  <div className="mt-3 truncate font-mono text-[10px] text-mist-400">
                    {a.endpoint || "no endpoint"}
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => setSelected(a)}
                      className="rounded-lg border border-white/15 px-2.5 py-1 font-mono text-[10px] uppercase text-mist-200"
                    >
                      详情
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onHealth(a)}
                      className="rounded-lg border border-white/15 px-2.5 py-1 font-mono text-[10px] uppercase text-mist-200"
                    >
                      健康检测
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onToggle(a)}
                      className="rounded-lg border border-white/15 px-2.5 py-1 font-mono text-[10px] uppercase text-mist-200"
                    >
                      {a.status === "disabled" ? "启用" : "禁用"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-6 divide-y divide-white/10 border-y border-white/10">
              {filtered.map((a) => (
                <div
                  key={a.agent_id}
                  className="grid gap-3 py-4 md:grid-cols-[1.2fr_1fr_auto] md:items-center"
                >
                  <div>
                    <div className="font-display text-lg text-mist-100">{a.name}</div>
                    <div className="font-mono text-[11px] text-mist-400">{a.agent_key}</div>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {(a.skills || []).map((s) => (
                      <span key={s} className="font-mono text-[10px] text-signal-dim">
                        {s}
                      </span>
                    ))}
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusPill status={a.status} />
                    <button
                      type="button"
                      onClick={() => setSelected(a)}
                      className="font-mono text-[10px] uppercase text-mist-400 hover:text-signal"
                    >
                      详情
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {showRegister ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4">
          <form
            onSubmit={onRegister}
            className="w-full max-w-md rounded-2xl border border-white/10 bg-ink-900 p-5"
          >
            <div className="font-display text-xl text-mist-100">注册 Agent</div>
            <p className="mt-1 text-sm text-mist-400">填入 A2A Endpoint，自动拉取 Agent Card。</p>
            <input
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              className="mt-4 w-full rounded-xl border border-white/10 bg-ink-950 px-3 py-2 font-mono text-sm text-mist-100 outline-none focus:border-signal/40"
              placeholder="http://127.0.0.1:8001"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowRegister(false)}
                className="rounded-lg px-3 py-2 font-mono text-xs text-mist-400"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={busy}
                className="rounded-lg bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase text-ink-950 disabled:opacity-40"
              >
                注册
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {selected ? (
        <div className="fixed inset-y-0 right-0 z-40 w-full max-w-md border-l border-white/10 bg-ink-950/95 p-5 shadow-2xl backdrop-blur">
          <div className="flex items-start justify-between">
            <div>
              <div className="font-display text-2xl text-mist-100">{selected.name}</div>
              <div className="mt-1 font-mono text-[11px] text-mist-400">{selected.agent_key}</div>
            </div>
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="font-mono text-xs text-mist-400 hover:text-signal"
            >
              关闭
            </button>
          </div>
          <StatusPill status={selected.status} />
          <p className="mt-3 text-sm text-mist-400">{selected.description || "无描述"}</p>
          <div className="mt-4 font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
            Skills
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {(selected.skills || []).map((s) => (
              <span key={s} className="rounded-full border border-white/10 px-2 py-0.5 text-xs text-mist-200">
                {s}
              </span>
            ))}
          </div>
          <div className="mt-4 truncate font-mono text-[11px] text-mist-400">
            {selected.endpoint || "—"}
          </div>

          <div className="mt-5 rounded-2xl border border-white/10 bg-ink-900/50 p-3">
            <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
              生命周期 / 容量 / 可靠性
            </div>
            {lifeError ? (
              <p className="mt-2 font-mono text-[10px] text-signal-warm">{lifeError}</p>
            ) : null}
            <div className="mt-2 space-y-1 font-mono text-[11px] text-mist-200">
              <div>
                state ·{" "}
                <span className={LIFE_COLOR[String(lifeHealth?.state || "")] || "text-mist-400"}>
                  {lifeHealth?.state || "—"}
                </span>
              </div>
              <div>active_tasks · {lifeHealth?.active_tasks ?? "—"}</div>
              <div>last_seen · {lifeHealth?.last_seen || "—"}</div>
              <div>
                queue_depth · {capacity?.queue_depth ?? "—"} · accepts{" "}
                {capacity ? String(capacity.accepts) : "—"}
                {capacity?.reason ? ` (${capacity.reason})` : ""}
              </div>
              <div>
                availability ·{" "}
                {reliability?.availability != null
                  ? Number(reliability.availability).toFixed(3)
                  : "—"}{" "}
                · success_rate ·{" "}
                {reliability?.success_rate != null
                  ? Number(reliability.success_rate).toFixed(3)
                  : "—"}{" "}
                · n={reliability?.sample_size ?? "—"}
              </div>
            </div>
            {(capNote || relNote) && (
              <p className="mt-2 font-mono text-[10px] text-mist-400">{capNote || relNote}</p>
            )}
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  if (!selected || busy) return;
                  setBusy(true);
                  try {
                    const h = await heartbeatAgent(selected.agent_id);
                    setLifeHealth(h);
                  } catch (err) {
                    setLifeError(apiErrorMessage(err));
                  } finally {
                    setBusy(false);
                  }
                }}
                className="rounded-lg border border-white/15 px-2 py-1 font-mono text-[10px] uppercase text-mist-200 disabled:opacity-40"
              >
                Heartbeat
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  if (!selected || busy) return;
                  setBusy(true);
                  try {
                    const h = await drainAgent(selected.agent_id);
                    setLifeHealth(h);
                  } catch (err) {
                    setLifeError(apiErrorMessage(err));
                  } finally {
                    setBusy(false);
                  }
                }}
                className="rounded-lg border border-signal-warm/40 px-2 py-1 font-mono text-[10px] uppercase text-signal-warm disabled:opacity-40"
              >
                Drain
              </button>
            </div>
          </div>

          <div className="mt-6 h-40">
            <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
              运行指标（agent_runs）
            </div>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={metricData}>
                <XAxis dataKey="name" tick={{ fill: "#7eaea0", fontSize: 10 }} />
                <YAxis tick={{ fill: "#7eaea0", fontSize: 10 }} width={28} />
                <Tooltip
                  contentStyle={{
                    background: "#152822",
                    border: "1px solid rgba(255,255,255,0.1)",
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="value" fill="#3dffa8" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const color =
    status === "online" || status === "running"
      ? "text-signal"
      : status === "degraded"
        ? "text-signal-warm"
        : "text-mist-400";
  return (
    <span className={`inline-block font-mono text-[10px] uppercase tracking-[0.14em] ${color}`}>
      {status}
    </span>
  );
}
