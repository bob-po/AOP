"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  apiErrorMessage,
  getCollaborationEvents,
  type ExecutionEventDict,
} from "@/lib/api";
import { useWebSocket, type WebSocketMessage } from "@/hooks/useWebSocket";

function seqOf(ev: ExecutionEventDict): number {
  const p = ev.payload as Record<string, unknown> | undefined;
  const s = ev.sequence ?? p?.sequence;
  return typeof s === "number" ? s : 0;
}

export function CollaborationStream({
  rootTaskId,
  onConnectionChange,
  onEventsHint,
}: {
  rootTaskId: string | null;
  onConnectionChange?: (connected: boolean) => void;
  /** Fired when snapshot/event arrives (parent may refresh graph). */
  onEventsHint?: () => void;
}) {
  const [events, setEvents] = useState<ExecutionEventDict[]>([]);
  const [pollError, setPollError] = useState<string | null>(null);
  const [liveMode, setLiveMode] = useState<"ws" | "poll">("poll");

  const mergeEvents = useCallback((incoming: ExecutionEventDict[]) => {
    setEvents((prev) => {
      const map = new Map<string, ExecutionEventDict>();
      for (const e of [...prev, ...incoming]) {
        const key =
          (e.event_id as string) ||
          `${e.event_type}-${e.timestamp}-${seqOf(e)}-${e.task_id || ""}`;
        map.set(key, e);
      }
      return Array.from(map.values()).sort((a, b) => seqOf(a) - seqOf(b));
    });
  }, []);

  const onMessage = useCallback(
    (message: WebSocketMessage) => {
      const data = message as unknown as Record<string, unknown>;
      const type = message.type || (data.type as string);
      if (type === "ping") return;
      if (type === "snapshot") {
        const list = (data.events as ExecutionEventDict[]) || [];
        mergeEvents(list);
        setLiveMode("ws");
        setPollError(null);
        onEventsHint?.();
        return;
      }
      if (type === "event") {
        const ev = (data.event as ExecutionEventDict) || (data as ExecutionEventDict);
        mergeEvents([ev]);
        setLiveMode("ws");
        onEventsHint?.();
      }
    },
    [mergeEvents, onEventsHint],
  );

  const path = rootTaskId
    ? `/v1/collaboration/stream/${encodeURIComponent(rootTaskId)}`
    : undefined;

  const { isConnected } = useWebSocket({
    path,
    enabled: Boolean(rootTaskId && path),
    onMessage,
  });

  useEffect(() => {
    if (isConnected) setLiveMode("ws");
    else setLiveMode("poll");
    onConnectionChange?.(isConnected);
  }, [isConnected, onConnectionChange]);

  // HTTP poll fallback only when WS down (2.5s); when WS up, rely on push + rare parent refresh
  useEffect(() => {
    if (!rootTaskId) {
      setEvents([]);
      return;
    }
    let alive = true;
    async function poll() {
      try {
        const res = await getCollaborationEvents(rootTaskId!);
        if (!alive) return;
        mergeEvents(res.events || []);
        setPollError(null);
      } catch (err) {
        if (alive) setPollError(apiErrorMessage(err, "协作事件不可用"));
      }
    }
    poll();
    if (isConnected) return () => { alive = false; };
    const t = setInterval(poll, 2500);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [rootTaskId, isConnected, mergeEvents]);

  const rows = useMemo(() => events.slice(-40).reverse(), [events]);

  if (!rootTaskId) return null;

  return (
    <div className="mt-3 rounded-2xl border border-white/10 bg-ink-900/50 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          协作事件流
        </div>
        <span
          className={`font-mono text-[10px] uppercase tracking-[0.12em] ${
            isConnected ? "text-signal" : "text-mist-400"
          }`}
        >
          {liveMode === "ws" ? "live·ws" : "live·poll"}
        </span>
      </div>
      {pollError && !rows.length ? (
        <p className="font-mono text-[11px] text-mist-400">{pollError}</p>
      ) : null}
      {!rows.length && !pollError ? (
        <p className="font-mono text-[11px] text-mist-400">暂无协作事件</p>
      ) : (
        <ul className="max-h-40 space-y-1 overflow-y-auto font-mono text-[10px] text-mist-300">
          {rows.map((e, i) => (
            <li key={`${e.event_id || i}-${seqOf(e)}`} className="border-b border-white/5 py-1">
              <span className="text-mist-400">#{seqOf(e) || "—"}</span>{" "}
              <span className="text-signal">{e.event_type || "event"}</span>{" "}
              <span className="text-mist-400">{e.timestamp || ""}</span>
              {e.agent_id ? <span> · {String(e.agent_id).slice(0, 8)}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
