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

/**
 * Visual Runtime live state: Snapshot + incremental events.
 * UI disconnect must never stop Agent Runtime — this is observation only.
 */
export function useVisualRuntime(taskId: string | null) {
  const [graph, setGraph] = useState<VisualGraphSnapshot | null>(null);
  const [events, setEvents] = useState<VisualRuntimeEvent[]>([]);
  const [sequence, setSequence] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const seenIds = useRef<Set<string>>(new Set());
  const lastSeq = useRef(0);

  const reset = useCallback(() => {
    seenIds.current = new Set();
    lastSeq.current = 0;
    setGraph(null);
    setEvents([]);
    setSequence(0);
    setError(null);
  }, []);

  const applySnapshot = useCallback((snap: VisualGraphSnapshot) => {
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
        setGraph(data.graph);
        if (typeof data.sequence === "number") {
          lastSeq.current = Math.max(lastSeq.current, data.sequence);
          setSequence(lastSeq.current);
        }
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

  return {
    graph,
    events,
    sequence,
    isConnected,
    error,
    stats,
    refresh,
    setGraph,
  };
}
