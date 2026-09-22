"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
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
  createTask,
  getEvaluationOverview,
  getMetrics,
  getOverviewStats,
  listAgents,
  listEvaluations,
  type Agent,
  type EvaluationOverview,
  type MetricsSnapshot,
  type OverviewStats,
  type TaskEvaluation,
} from "@/lib/api";

const TEMPLATES = [
  { label: "产品调研", text: "帮我调研一款AI产品，搜索资料，RAG分析，生成宣传图，输出报告" },
  { label: "PPT生成", text: "搜索并检索知识库后，生成一份产品发布演示 PPT" },
  { label: "视频制作", text: "搜索 A2A Agent Orchestration 的公开资料并总结成宣传文案" },
];

function Kpi({
  label,
  value,
  href,
}: {
  label: string;
  value: string | number;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-xl border border-white/10 bg-ink-800/50 px-4 py-3 transition hover:border-signal/30 hover:bg-ink-800/80"
    >
      <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
        {label}
      </div>
      <div className="mt-2 font-display text-2xl text-mist-100">{value}</div>
    </Link>
  );
}

export function DashboardView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [evalStats, setEvalStats] = useState<EvaluationOverview | null>(null);
  const [recentEvals, setRecentEvals] = useState<TaskEvaluation[]>([]);
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [goal, setGoal] = useState(TEMPLATES[0].text);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const prefill = searchParams.get("prefill");
    if (prefill) setGoal(prefill);
  }, [searchParams]);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const [s, a, eo, el, m] = await Promise.all([
          getOverviewStats(),
          listAgents(),
          getEvaluationOverview().catch(() => null),
          listEvaluations({ limit: 5 }).catch(() => ({ evaluations: [] })),
          getMetrics(24).catch(() => null),
        ]);
        if (!alive) return;
        setStats(s);
        setAgents(a.agents || []);
        setEvalStats(eo);
        setRecentEvals(el.evaluations || []);
        setMetrics(m);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "load failed");
      }
    }
    load();
    const t = setInterval(load, 8000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const content = goal.trim();
    if (!content || loading) return;
    setLoading(true);
    setError(null);
    try {
      const task = await createTask(content);
      router.push(`/tasks/${task.task_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "create failed");
      setLoading(false);
    }
  }

  const online = agents.filter((a) => a.status === "online" || a.status === "running").length;
  const degraded = agents.filter((a) => a.status === "degraded").length;
  const offline = agents.length - online - degraded;

  return (
    <div className="space-y-6 px-4 py-6 md:px-8">
      <div>
        <h1 className="font-display text-3xl text-mist-100 md:text-4xl">平台总览</h1>
        <p className="mt-1 text-sm text-mist-400">观测控制面状态，并快速发起编排任务。</p>
      </div>

      {error ? (
        <div className="font-mono text-xs text-signal-warm">{error}</div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <Kpi label="总任务数" value={stats?.total_tasks ?? "—"} href="/tasks" />
        <Kpi label="运行中" value={stats?.running ?? "—"} href="/tasks?status=running" />
        <Kpi
          label="成功率"
          value={stats ? `${stats.success_rate}%` : "—"}
          href="/tasks?status=completed"
        />
        <Kpi
          label="平均评分"
          value={evalStats ? Math.round(evalStats.avg_score) : "—"}
          href="/tasks?status=completed"
        />
        <Kpi label="Agent 在线" value={stats?.agents_online ?? online} href="/agents" />
        <Kpi label="队列等待" value={stats?.queue_waiting ?? "—"} href="/tasks?status=running" />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
          <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
            任务执行趋势（近 7 日）
          </div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats?.trend || []}>
                <defs>
                  <linearGradient id="taskFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3dffa8" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#3dffa8" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis
                  dataKey="day"
                  tick={{ fill: "#7eaea0", fontSize: 10 }}
                  tickFormatter={(v: string) => v.slice(5)}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fill: "#7eaea0", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  width={28}
                />
                <Tooltip
                  contentStyle={{
                    background: "#152822",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="#3dffa8"
                  fill="url(#taskFill)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
          <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
            Agent 健康状态
          </div>
          <div className="flex flex-wrap gap-3 font-mono text-sm">
            <span className="text-signal">在线 {online}</span>
            <span className="text-signal-warm">降级 {degraded}</span>
            <span className="text-mist-400">离线 {Math.max(0, offline)}</span>
          </div>
          <ul className="mt-4 max-h-48 space-y-2 overflow-auto">
            {agents.slice(0, 8).map((a) => (
              <li
                key={a.agent_id}
                className="group flex items-center justify-between gap-2 rounded-lg border border-transparent px-2 py-1.5 hover:border-white/10 hover:bg-ink-800/60"
                title={`${a.endpoint || "no endpoint"} · skills: ${(a.skills || []).join(", ")}`}
              >
                <span className="truncate text-sm text-mist-100">{a.name}</span>
                <span
                  className={`font-mono text-[10px] uppercase ${
                    a.status === "online" || a.status === "running"
                      ? "text-signal"
                      : a.status === "degraded"
                        ? "text-signal-warm"
                        : "text-mist-400"
                  }`}
                >
                  {a.status}
                </span>
              </li>
            ))}
            {agents.length === 0 ? (
              <li className="font-mono text-xs text-mist-400">暂无注册 Agent</li>
            ) : null}
          </ul>

          <div className="mt-5 border-t border-white/10 pt-4">
            <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
              近期评分
            </div>
            {evalStats ? (
              <div className="mb-3 flex flex-wrap gap-2 font-mono text-[10px] text-mist-400">
                <span>A {evalStats.grade_a}</span>
                <span>B {evalStats.grade_b}</span>
                <span>C {evalStats.grade_c}</span>
                <span>D/F {evalStats.grade_df}</span>
              </div>
            ) : null}
            {metrics?.agent_runs ? (
              <div className="mb-3 font-mono text-[10px] text-mist-400">
                runs={metrics.agent_runs.total ?? 0} · sr=
                {Math.round(((metrics.agent_runs.success_rate as number) || 0) * 100)}% · mem=
                {metrics.memories?.total ?? 0} · hitl=
                {metrics.tasks?.waiting_for_user ?? 0}
              </div>
            ) : null}
            <ul className="max-h-36 space-y-2 overflow-auto">
              {recentEvals.map((ev) => (
                <li key={`${ev.task_id}-${ev.method}`}>
                  <Link
                    href={`/tasks/${ev.task_id}`}
                    className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 hover:bg-ink-800/60"
                  >
                    <span className="truncate text-sm text-mist-100">
                      {ev.task_title || ev.task_id.slice(0, 8)}
                    </span>
                    <span className="font-mono text-[11px] text-signal">
                      {ev.grade} · {ev.score}
                    </span>
                  </Link>
                </li>
              ))}
              {recentEvals.length === 0 ? (
                <li className="font-mono text-xs text-mist-400">暂无评估记录</li>
              ) : null}
            </ul>
          </div>
        </div>
      </div>

      <form
        onSubmit={onSubmit}
        className="rounded-2xl border border-white/10 bg-ink-800/50 p-5 shadow-glow"
      >
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          新建任务 · 快速发起
        </div>
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          rows={3}
          className="mt-3 w-full resize-none rounded-xl border border-white/10 bg-ink-950/40 px-4 py-3 text-sm text-mist-100 outline-none focus:border-signal/40"
          placeholder="输入你的目标…"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="submit"
            disabled={loading || !goal.trim()}
            className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-ink-950 transition hover:bg-white disabled:opacity-40"
          >
            {loading ? "提交中…" : "提交任务"}
          </button>
          <span className="font-mono text-[10px] text-mist-400">快捷模板：</span>
          {TEMPLATES.map((t) => (
            <button
              key={t.label}
              type="button"
              onClick={() => setGoal(t.text)}
              className="rounded-full border border-white/10 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-400 hover:border-signal/40 hover:text-signal"
            >
              {t.label}
            </button>
          ))}
        </div>
      </form>
    </div>
  );
}
