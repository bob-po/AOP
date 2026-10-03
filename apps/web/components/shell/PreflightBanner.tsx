"use client";

import Link from "next/link";
import { usePreflight } from "@/hooks/usePreflight";

const CHECKS: Array<{ key: "postgres" | "redis" | "worker" | "outbox"; label: string }> =
  [
    { key: "postgres", label: "Postgres" },
    { key: "redis", label: "Redis" },
    { key: "worker", label: "Worker" },
    { key: "outbox", label: "Outbox" },
  ];

export function PreflightBanner() {
  const { snapshot, error, loading } = usePreflight();

  if (loading && !snapshot && !error) return null;

  if (error && !snapshot) {
    return (
      <div className="border-b border-signal-warm/40 bg-signal-warm/10 px-4 py-2 md:px-6">
        <p className="font-mono text-[11px] text-signal-warm">
          连不上控制面（Gateway :8080）。先跑{" "}
          <code className="text-mist-100">python scripts/dev_up.py</code>
          {error ? ` · ${error}` : ""}
        </p>
        <Link
          href="/settings?tab=monitor"
          className="mt-1 inline-block font-mono text-[10px] uppercase tracking-[0.12em] text-signal hover:underline"
        >
          故障恢复清单
        </Link>
      </div>
    );
  }

  if (!snapshot) return null;

  const hitlCount = snapshot.waiting_hitl || 0;
  // Ready stack with only HITL waiting: still surface a thin Inbox strip.
  if (snapshot.status === "ready" && hitlCount <= 0) return null;

  const tone =
    snapshot.status === "blocked"
      ? "border-signal-warm/40 bg-signal-warm/10 text-signal-warm"
      : snapshot.status === "ready"
        ? "border-signal/25 bg-signal/5 text-mist-300"
        : "border-white/15 bg-white/5 text-mist-300";

  const hint = snapshot.hints[0];

  return (
    <div className={`border-b px-4 py-2 md:px-6 ${tone}`}>
      <div className="flex flex-wrap items-center gap-2">
        {snapshot.status !== "ready" ? (
          <span className="font-mono text-[10px] uppercase tracking-[0.18em]">
            {snapshot.status === "blocked" ? "不能跑" : "降级"}
          </span>
        ) : null}
        {snapshot.status !== "ready"
          ? CHECKS.map((c) => {
              const ok = snapshot.services[c.key]?.ok;
              return (
                <span
                  key={c.key}
                  className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
                    ok
                      ? "border-signal/30 text-signal"
                      : "border-signal-warm/40 text-signal-warm"
                  }`}
                >
                  {c.label} {ok ? "ok" : "down"}
                </span>
              );
            })
          : null}
        {snapshot.status !== "ready" ? (
          <span className="font-mono text-[10px] text-mist-400">
            Agents {snapshot.ready_agents}/{snapshot.registered_agents} ready
          </span>
        ) : null}
        {snapshot.warnings.includes("stuck_running") ? (
          <Link
            href="/tasks?status=running"
            className="rounded-full border border-signal-warm/40 px-2 py-0.5 font-mono text-[10px] text-signal-warm hover:bg-signal-warm/10"
          >
            Tasks 回收
          </Link>
        ) : null}
        {hitlCount > 0 || snapshot.warnings.includes("waiting_hitl") ? (
          <Link
            href="/inbox"
            className="rounded-full border border-signal/30 px-2 py-0.5 font-mono text-[10px] text-signal hover:bg-signal/10"
          >
            Inbox {hitlCount > 0 ? `· ${hitlCount}` : "待审批"}
          </Link>
        ) : null}
      </div>
      {hint && snapshot.status !== "ready" ? (
        <p className="mt-1 font-sans text-xs text-mist-200">{hint}</p>
      ) : null}
      {snapshot.status !== "ready" || snapshot.warnings.includes("stuck_running") ? (
        <Link
          href="/settings?tab=monitor"
          className="mt-1 inline-block font-mono text-[10px] uppercase tracking-[0.12em] text-signal hover:underline"
        >
          故障恢复清单
        </Link>
      ) : null}
    </div>
  );
}
