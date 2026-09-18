"use client";

import { useEffect, useState } from "react";
import { listAgents, type Agent } from "@/lib/api";

export function AgentsPanel() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await listAgents();
        if (alive) {
          setAgents(data.agents || []);
          setError(null);
        }
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "failed");
      }
    }
    load();
    const t = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <div className="mx-auto max-w-5xl px-6 pb-16 pt-6 md:px-10">
      <h1 className="font-display text-4xl text-mist-100">Agents</h1>
      <p className="mt-2 text-sm text-mist-400">
        Registry snapshot — skill map for the orchestrator router.
      </p>

      {error ? (
        <div className="mt-6 font-mono text-xs text-signal-warm">{error}</div>
      ) : null}

      <div className="mt-10 divide-y divide-white/10 border-y border-white/10">
        {agents.length === 0 && !error ? (
          <div className="py-8 font-mono text-sm text-mist-400">No agents registered.</div>
        ) : null}
        {agents.map((a) => (
          <div
            key={a.agent_id}
            className="grid gap-3 py-6 md:grid-cols-[1.2fr_1fr_auto] md:items-center"
          >
            <div>
              <div className="font-display text-xl text-mist-100">{a.name}</div>
              <div className="mt-1 font-mono text-[11px] text-mist-400">{a.agent_key}</div>
              {a.description ? (
                <p className="mt-2 max-w-xl text-sm text-mist-400">{a.description}</p>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              {(a.skills || []).map((s) => (
                <span
                  key={s}
                  className="rounded-full border border-signal/20 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-signal-dim"
                >
                  {s}
                </span>
              ))}
            </div>
            <div className="font-mono text-xs uppercase tracking-[0.16em]">
              <span
                className={
                  a.status === "online" || a.status === "running"
                    ? "text-signal"
                    : "text-mist-400"
                }
              >
                {a.status}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
