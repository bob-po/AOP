"use client";

import type { TaskEvent } from "@/lib/api";

function formatTs(ts?: string) {
  if (!ts) return "--:--:--";
  try {
    return new Date(ts).toLocaleTimeString();
  } catch {
    return ts;
  }
}

export function TaskTrace({ events }: { events: TaskEvent[] }) {
  return (
    <div className="h-full overflow-auto rounded-2xl border border-white/10 bg-ink-900/60 p-4">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.2em] text-mist-400">
        Live Trace
      </div>
      <ol className="space-y-3">
        {events.length === 0 ? (
          <li className="font-mono text-xs text-mist-400">Waiting for events…</li>
        ) : (
          events.map((ev, idx) => (
            <li key={`${ev.event_type}-${idx}`} className="animate-rise flex gap-3">
              <span className="w-20 shrink-0 font-mono text-[11px] text-signal-dim">
                {formatTs(ev.ts)}
              </span>
              <div className="min-w-0">
                <div className="font-mono text-xs text-mist-100">{ev.event_type}</div>
                {ev.message ? (
                  <div className="mt-0.5 text-sm text-mist-400">{ev.message}</div>
                ) : null}
              </div>
            </li>
          ))
        )}
      </ol>
    </div>
  );
}
