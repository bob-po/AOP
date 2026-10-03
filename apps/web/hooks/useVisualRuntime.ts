"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getTaskVisualGraph,
  type VisualGraphSnapshot,
  type VisualRuntimeEvent,
} from "@/lib/api";
import { useWebSocket, type WebSocketMessage } from "@/hooks/useWebSocket";

type VisualWsMessage = WebSocketMessage & {
  root_task_id?: string;
  sequence?: number;
  graph?: VisualGraphSnapshot;
  events?: VisualRuntimeEvent[];
  event?: VisualRuntimeEvent;
};

const TERMINAL = new Set(["completed", "failed", "cancelled", "canceled"]);
const POLL_MS_LIVE = 2000;
const POLL_MS_DISCONNECTED = 1500;

function isTerminalStatus(status: string | undefined | null): boolean {
  return TERMINAL.has(String(status || "").toLowerCase());
}

/**
 * Visual Runtime live state: Snapshot + incremental events.
 * HTTP graph (Postgres SoT) is authoritative; WS is acceleration only.
 * UI disconnect must never stop Agent Runtime — this is observation only.
 */
export function useVisualRuntime(taskId: string | null) {
  const [graph, setGraph] = useState<VisualGraphSnapshot | null>(null);
  const [events, setEvents] = useState<VisualRuntimeEvent[]>([]);
  const [sequence, setSequence] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const seenIds = useRef<Set<string>>(new Set());
  const lastSeq = useRef(0);
  const graphRef = useRef<VisualGraphSnapshot | null>(null);

  const reset = useCallback(() => {
    seenIds.current = new Set();
    lastSeq.current = 0;
    graphRef.current = null;
    setGraph(null);
    setEvents([]);
    setSequence(0);
    setError(null);
  }, []);

  const applySnapshot = useCallback((snap: VisualGraphSnapshot) => {
    // Ignore stale / empty overwrite when we already have a richer snapshot
    const prev = graphRef.current;
    const nextSeq = snap.sequence || 0;
    if (
      prev &&
      (prev.nodes?.length || 0) > 0 &&
      (snap.nodes?.length || 0) === 0 &&
      nextSeq <= (prev.sequence || 0)
    ) {
      return;
    }
    if (prev && nextSeq < (prev.sequence || 0) && !isTerminalStatus(snap.status)) {
      return;
    }
    graphRef.current = snap;
    setGraph(snap);
    const evs = snap.events || [];
    seenIds.current = new Set(
      evs.map((e) => e.event_id).filter((id): id is string => !!id),
    );
    lastSeq.current = snap.sequence || 0;
    setEvents(evs);
    setSequence(snap.sequence || 0);
  }, []);

  // HTTP snapshot bootstrap / reconnect recovery
  useEffect(() => {
    if (!taskId) {
      reset();
      return;
    }
    let alive = true;
    (async () => {
      try {
        const snap = await getTaskVisualGraph(taskId);
        if (!alive) return;
        applySnapshot(snap);
        setError(null);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "graph load failed");
      }
    })();
    return () => {
      alive = false;
    };
  }, [taskId, applySnapshot, reset]);

  const onMessage = useCallback(
    (message: WebSocketMessage) => {
      const data = message as VisualWsMessage;
      const type = data.type;
      if (type === "snapshot" && data.graph) {
        applySnapshot(data.graph);
        return;
      }
      if (type === "graph" && data.graph) {
        applySnapshot(data.graph);
        return;
      }
      if (type === "event" && data.event) {
        const ev = data.event;
        const seq = ev.sequence ?? data.sequence;
        if (typeof seq === "number" && seq <= lastSeq.current && seenIds.current.has(ev.event_id || "")) {
          return;
        }
        if (ev.event_id && seenIds.current.has(ev.event_id)) return;
        if (ev.event_id) seenIds.current.add(ev.event_id);
        if (typeof seq === "number") {
          lastSeq.current = Math.max(lastSeq.current, seq);
          setSequence(lastSeq.current);
        }
        setEvents((prev) => [...prev, ev]);
      }
    },
    [applySnapshot],
  );

  // Prefer /ws/tasks/{id}; Gateway also proxies /v1/tasks/*/visual/ws
  const path = taskId
    ? `/ws/tasks/${encodeURIComponent(taskId)}`
    : undefined;

  const { isConnected } = useWebSocket({
    path,
    enabled: !!taskId,
    onMessage,
    maxReconnectAttempts: 40,
    reconnectInterval: 2000,
  });

  const refresh = useCallback(async () => {
    if (!taskId) return;
    const snap = await getTaskVisualGraph(taskId);
    applySnapshot(snap);
  }, [taskId, applySnapshot]);

  // Durable poll: keep Console honest when WS lags, drops, or never connects.
  // Stop once Postgres reports a terminal status (one extra tick after terminal).
  useEffect(() => {
    if (!taskId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      if (!alive) return;
      const status = graphRef.current?.status || graphRef.current?.task?.status;
      const terminal = isTerminalStatus(status);
      // Still poll briefly after terminal so late artifacts/events land
      const justTerminal =
        terminal && (graphRef.current?.nodes?.length || 0) > 0;
      try {
        const snap = await getTaskVisualGraph(taskId);
        if (!alive) return;
        applySnapshot(snap);
        setError(null);
        const done = isTerminalStatus(snap.status || snap.task?.status);
        if (done && (snap.nodes?.length || 0) > 0) {
          // Final settle poll once more then stop
          if (justTerminal) return;
          timer = setTimeout(tick, POLL_MS_LIVE);
          return;
        }
      } catch (err) {
        if (alive && !graphRef.current) {
          setError(err instanceof Error ? err.message : "graph poll failed");
        }
      }
      if (!alive) return;
      const interval = isConnected ? POLL_MS_LIVE : POLL_MS_DISCONNECTED;
      timer = setTimeout(tick, interval);
    };

    timer = setTimeout(tick, isConnected ? POLL_MS_LIVE : 400);
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [taskId, isConnected, applySnapshot]);

  const stats = useMemo(() => {
    const nodes = graph?.nodes || [];
    const agents = nodes.filter((n) => n.type === "agent");
    const retries = events.filter(
      (e) =>
        e.event_type.includes("retry") ||
        e.original_event_type?.includes("retry"),
    ).length;
    return {
      agents: agents.length,
      executions: nodes.filter((n) => n.type === "execution" || n.execution_id).length || agents.length,
      retries,
      tools: nodes.filter((n) => n.type === "tool").length,
    };
  }, [graph, events]);

  const displayStatus =
    graph?.task?.status && isTerminalStatus(graph.task.status)
      ? String(graph.task.status).toLowerCase() === "canceled"
        ? "cancelled"
        : String(graph.task.status).toLowerCase()
      : graph?.status;

  return {
    graph: graph
      ? { ...graph, status: displayStatus || graph.status }
      : null,
    events,
    sequence,
    isConnected,
    error,
    stats,
    refresh,
    setGraph,
  };
}
