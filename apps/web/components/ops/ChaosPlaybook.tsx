"use client";

import Link from "next/link";
import type { RecoverStep } from "@/lib/api";

const FALLBACK: RecoverStep[] = [
  {
    id: "orchestrator",
    title: "Orchestrator 被杀掉",
    symptom: "预检失败、Gateway 502、页面像掉线",
    fix: "重启 uvicorn main:app --port 8090，或 python scripts/dev_up.py",
    console: "起来后打开原任务，点 Retry。DAG 在 Postgres 里。",
  },
  {
    id: "worker",
    title: "Worker 被杀掉",
    symptom: "节点停在 ready / running，预检 Worker down",
    fix: "python worker.py 或 python scripts/dev_up.py",
    console: "Worker 变绿后对该任务点 Retry。",
  },
  {
    id: "outbox",
    title: "Outbox 被杀掉",
    symptom: "新任务卡在 ready，outbox pending",
    fix: "python outbox_processor_service.py 或 python scripts/dev_up.py",
    console: "心跳恢复后会自动投递；仍卡住则 Retry。",
  },
  {
    id: "stuck_running",
    title: "任务卡在 running",
    symptom: "进程已死但任务仍占配额",
    fix: "不必改数据库。",
    console: "Tasks / Network 上点 Retry 或 Cancel。",
  },
  {
    id: "control_plane",
    title: "Gateway 连不上",
    symptom: "顶栏连不上 :8080",
    fix: "重启 Gateway 或 python scripts/dev_up.py",
    console: "刷新 Console。",
  },
];

export function ChaosPlaybook({
  steps,
  compact = false,
}: {
  steps?: RecoverStep[] | null;
  compact?: boolean;
}) {
  const list = steps && steps.length > 0 ? steps : FALLBACK;
  const shown = compact ? list.filter((s) => s.active) : list;
  if (shown.length === 0) return null;

  return (
    <div className={compact ? "space-y-2" : "space-y-3"}>
      {!compact ? (
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
            Chaos 恢复
          </div>
          <p className="mt-1 text-sm text-mist-400">
            中途杀掉 Worker / Outbox / Orchestrator 后，不要改 SQL。先把进程拉起来，再在
            Console 点 Retry。
          </p>
        </div>
      ) : null}
      <ul className="space-y-2">
        {shown.map((s) => (
          <li
            key={s.id}
            className={`rounded-xl border px-3 py-2 ${
              s.active
                ? "border-signal-warm/40 bg-signal-warm/5"
                : "border-white/10 bg-ink-900/40"
            }`}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-sm text-mist-100">{s.title}</span>
              {s.active ? (
                <span className="font-mono text-[10px] uppercase text-signal-warm">
                  正在发生
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-[12px] text-mist-400">{s.symptom}</p>
            <p className="mt-1 font-mono text-[11px] text-mist-300">进程：{s.fix}</p>
            <p className="mt-0.5 text-[12px] text-mist-200">Console：{s.console}</p>
          </li>
        ))}
      </ul>
      {compact ? (
        <Link
          href="/settings?tab=monitor"
          className="inline-block font-mono text-[10px] uppercase tracking-[0.12em] text-signal hover:underline"
        >
          完整清单
        </Link>
      ) : (
        <Link
          href="/tasks?status=running"
          className="inline-block font-mono text-[10px] uppercase tracking-[0.12em] text-signal hover:underline"
        >
          打开卡住的任务
        </Link>
      )}
    </div>
  );
}
