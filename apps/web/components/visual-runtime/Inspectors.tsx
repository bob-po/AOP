"use client";

import type { ReactNode } from "react";
import type {
  Agent,
  ArtifactItem,
  PreflightAgent,
  VisualGraphNode,
  VisualGraphSnapshot,
  VisualRuntimeEvent,
} from "@/lib/api";

/** UTC clock — locale `toLocale*` hydrates differently on Node vs browser. */
export function formatUtcClock(iso?: string | null): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return iso;
  return new Date(ms).toISOString().slice(11, 19) + "Z";
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_1fr] gap-2 border-b border-white/5 py-2">
      <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-400">
        {label}
      </div>
      <div className="truncate font-sans text-sm text-mist-100">{value ?? "—"}</div>
    </div>
  );
}

export function AgentInspector({
  node,
  agent,
  readiness,
  events,
  onPause,
  onRetry,
  onInspect,
}: {
  node: VisualGraphNode;
  agent?: Agent | null;
  readiness?: PreflightAgent | null;
  events: VisualRuntimeEvent[];
  onPause?: () => void;
  onRetry?: () => void;
  onInspect?: () => void;
}) {
  const meta = node.metadata || {};
  const agentEvents = events.filter((e) => e.agent_id === node.agent_id);
  const started = agentEvents.find(
    (e) => e.event_type.includes("started") || e.event_type.includes("delegated"),
  );
  const retries = agentEvents.filter((e) => e.event_type.includes("retry")).length;
  const latencyMs = (() => {
    const t0 = started?.timestamp ? Date.parse(started.timestamp) : NaN;
    const last = agentEvents[agentEvents.length - 1]?.timestamp;
    const t1 = last ? Date.parse(last) : NaN;
    if (!Number.isFinite(t0) || !Number.isFinite(t1) || t1 < t0) return null;
    return ((t1 - t0) / 1000).toFixed(2) + "s";
  })();

  return (
    <div className="space-y-1">
      <div className="mb-3 font-display text-lg text-mist-100">Agent</div>
      <Row label="Name" value={agent?.name || node.label} />
      <Row label="ID" value={node.agent_id || node.id} />
      <Row label="Status" value={(node.status || "").toUpperCase()} />
      {String(node.status || "").toLowerCase() === "waiting_for_agent" ? (
        <Row label="Approval" value="waiting for peer agent" />
      ) : String(node.status || "").toLowerCase() === "waiting_for_user" ||
        String(node.status || "").toLowerCase() === "waiting" ? (
        <Row label="Approval" value="waiting for operator (Tasks)" />
      ) : null}
      {readiness ? (
        <Row
          label="Runner"
          value={
            readiness.runner_ready
              ? "ready"
              : readiness.reachable
                ? `stub · ${readiness.runner_reason || "CLI / key missing"}`
                : `offline · ${readiness.runner_reason || "unreachable"}`
          }
        />
      ) : null}
      <Row
        label="Capabilities"
        value={(agent?.skills || (meta.skills as string[]) || []).join(", ") || "—"}
      />
      <Row label="Execution" value={node.execution_id || "—"} />
      <Row label="Parent" value={node.parent_id || "—"} />
      <Row label="Visits" value={String(meta.visit_count ?? 1)} />
      <Row label="Latency" value={latencyMs || "—"} />
      <Row label="Calls" value={String(agentEvents.length)} />
      <Row label="Retry" value={String(retries)} />
      <Row
        label="Started"
        value={
          formatUtcClock(started?.timestamp)
        }
      />
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onPause}
          className="rounded-lg border border-white/15 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-200 hover:border-signal/40 hover:text-signal"
        >
          Pause
        </button>
        <button
          type="button"
          onClick={onRetry}
          className="rounded-lg border border-white/15 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-200 hover:border-signal/40 hover:text-signal"
        >
          Retry
        </button>
        <button
          type="button"
          onClick={onInspect}
          className="rounded-lg border border-white/15 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-200 hover:border-signal/40 hover:text-signal"
        >
          Inspect Execution
        </button>
      </div>
    </div>
  );
}

export function TaskInspector({
  snapshot,
  events,
  stats,
  createdAt,
  artifacts,
  summary,
  onDownloadPackage,
  packageBusy,
}: {
  snapshot: VisualGraphSnapshot | null;
  events: VisualRuntimeEvent[];
  stats: { agents: number; executions: number; retries: number };
  createdAt?: string;
  artifacts?: ArtifactItem[];
  summary?: string | null;
  onDownloadPackage?: () => void | Promise<void>;
  packageBusy?: boolean;
}) {
  const t0 =
    createdAt ||
    snapshot?.task?.created_at ||
    events.find((e) => e.timestamp)?.timestamp;
  const terminal = ["completed", "failed", "cancelled"].includes(
    (snapshot?.status || "").toLowerCase(),
  );
  const duration = (() => {
    if (!t0) return "—";
    const start = Date.parse(t0);
    if (!Number.isFinite(start)) return "—";
    const lastEv = [...events]
      .reverse()
      .find((e) => e.timestamp && Number.isFinite(Date.parse(e.timestamp)));
    const finished =
      snapshot?.task?.finished_at ||
      snapshot?.task?.updated_at ||
      lastEv?.timestamp;
    const end = finished
      ? Date.parse(finished)
      : terminal
        ? start
        : Date.now();
    if (!Number.isFinite(end) || end < start) return "—";
    return ((end - start) / 1000).toFixed(1) + "s";
  })();
  const hops = (snapshot?.edges || []).filter((e) => e.type === "delegation").length;
  const seq = snapshot?.sequence ?? 0;

  return (
    <div className="space-y-1">
      <div className="mb-3 font-display text-lg text-mist-100">Task</div>
      <Row label="Task ID" value={snapshot?.task_id || "—"} />
      <Row label="Status" value={(snapshot?.status || "idle").toUpperCase()} />
      {(() => {
        const raw = String(snapshot?.task?.status || snapshot?.status || "").toLowerCase();
        const gate =
          raw === "waiting_for_agent"
            ? "Agent peer"
            : raw === "waiting_for_user" || raw === "waiting"
              ? "System / Tasks"
              : "";
        return gate ? <Row label="Approval" value={gate} /> : null;
      })()}
      <Row
        label="Created"
        value={t0 ? formatUtcClock(t0) : "—"}
      />
      <Row label="Agents" value={String(stats.agents)} />
      <Row label="Hops" value={String(hops || stats.executions)} />
      <Row label="Retries" value={String(stats.retries)} />
      <Row label="Duration" value={duration} />
      {seq > 0 ? <Row label="Sequence" value={String(seq)} /> : null}
      {onDownloadPackage ? (
        <div className="border-b border-white/5 py-2">
          <button
            type="button"
            disabled={packageBusy}
            onClick={() => void onDownloadPackage()}
            className="font-mono text-[11px] text-signal hover:underline disabled:opacity-50"
          >
            {packageBusy ? "Packing run…" : "Download run package"}
          </button>
          <div className="mt-0.5 font-mono text-[10px] text-mist-500">
            ZIP · report + citations + artifacts
          </div>
        </div>
      ) : null}
      {summary ? (
        <div className="border-b border-white/5 py-2">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-400">
            Result
          </div>
          <p className="mt-1 line-clamp-4 font-sans text-sm text-mist-100">{summary}</p>
        </div>
      ) : null}
      {artifacts && artifacts.length > 0 ? (
        <div className="py-2">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-400">
            Artifacts · {artifacts.length}
          </div>
          <ul className="mt-1 space-y-1">
            {artifacts.slice(0, 8).map((a) => {
              const label =
                (a.name || a.uri || a.url || "artifact")
                  .replace(/\\/g, "/")
                  .split("/")
                  .pop() || "artifact";
              const href = a.url || a.uri;
              return (
                <li key={`${href || label}-${a.node_id || ""}`} className="truncate">
                  {href ? (
                    <a
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono text-[11px] text-signal hover:underline"
                    >
                      {label}
                    </a>
                  ) : (
                    <span className="font-mono text-[11px] text-mist-300">{label}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function ExecutionTimeline({ events }: { events: VisualRuntimeEvent[] }) {
  return (
    <div className="mt-4">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
        Execution Timeline
      </div>
      <ul className="max-h-64 space-y-1.5 overflow-auto pr-1">
        {events.map((e) => {
          const t = formatUtcClock(e.timestamp);
          return (
            <li
              key={e.event_id || `${e.sequence}-${e.event_type}-${e.timestamp}`}
              className="flex gap-3 font-mono text-[11px]"
            >
              <span className="shrink-0 text-mist-400">{t}</span>
              <span className="text-signal">{e.event_type}</span>
              {e.agent_id ? (
                <span className="truncate text-mist-400">{e.agent_id}</span>
              ) : null}
            </li>
          );
        })}
        {events.length === 0 ? (
          <li className="font-mono text-xs text-mist-400">
            no recorded events yet
          </li>
        ) : null}
      </ul>
    </div>
  );
}

export function GraphReplayBar({
  events,
  cursor,
  playing,
  onPlay,
  onStop,
  onSeek,
}: {
  events: VisualRuntimeEvent[];
  cursor: number | null;
  playing: boolean;
  onPlay: () => void;
  onStop: () => void;
  onSeek: (seq: number) => void;
}) {
  const maxSeq = events.reduce((m, e) => Math.max(m, e.sequence ?? 0), 0);
  const t0 = events[0]?.timestamp ? Date.parse(events[0].timestamp) : NaN;

  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-white/10 px-4 py-2">
      <button
        type="button"
        onClick={playing ? onStop : onPlay}
        className="rounded-lg bg-signal/90 px-3 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-950 hover:bg-white"
      >
        {playing ? "■ Stop" : "▶ Replay"}
      </button>
      <input
        type="range"
        min={0}
        max={maxSeq || 1}
        value={cursor ?? maxSeq}
        onChange={(e) => onSeek(Number(e.target.value))}
        className="h-1 w-40 accent-signal md:w-64"
      />
      <div className="max-h-16 flex-1 overflow-auto font-mono text-[10px] text-mist-400">
        {events
          .filter((e) => cursor == null || (e.sequence ?? 0) <= (cursor ?? 0))
          .slice(-6)
          .map((e) => {
            const rel =
              Number.isFinite(t0) && e.timestamp
                ? ((Date.parse(e.timestamp) - t0) / 1000).toFixed(1) + "s"
                : "—";
            return (
              <div key={e.event_id || `${e.sequence}-${e.event_type}`}>
                {rel} · {e.event_type}
                {e.agent_id ? ` · ${e.agent_id}` : ""}
              </div>
            );
          })}
      </div>
    </div>
  );
}
