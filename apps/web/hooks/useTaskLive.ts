"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getTask,
  getTaskArtifacts,
  getTaskEvaluation,
  getTaskEvents,
  getTaskMemory,
  type ArtifactItem,
  type MemoryEntry,
  type TaskDetail,
  type TaskEvaluation,
  type TaskEvent,
} from "@/lib/api";
import { useWebSocket, type WebSocketMessage } from "@/hooks/useWebSocket";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

/** Live task view: WebSocket primary + HTTP poll fallback (Phase 14). */
export function useTaskLive(taskId: string | null) {
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [evaluation, setEvaluation] = useState<TaskEvaluation | null>(null);
  const [memories, setMemories] = useState<MemoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [liveMode, setLiveMode] = useState<"ws" | "poll">("poll");

  const terminalPollsRef = useRef(0);
  const aliveRef = useRef(true);

  const refresh = useCallback(async (id: string) => {
    const [t, e] = await Promise.all([getTask(id), getTaskEvents(id)]);
    if (!aliveRef.current) return t;
    setTask(t);
    setEvents(e.events || []);
    setError(null);

    try {
      const a = await getTaskArtifacts(id);
      if (aliveRef.current) setArtifacts(a.artifacts || []);
    } catch {
      // optional while running
    }

    try {
      const m = await getTaskMemory(id);
      if (aliveRef.current) setMemories(m.memories || []);
    } catch {
      if (aliveRef.current) setMemories([]);
    }

    if (TERMINAL.has(t.status)) {
      try {
        const ev = await getTaskEvaluation(id);
        if (aliveRef.current) setEvaluation(ev);
      } catch {
        if (aliveRef.current) setEvaluation(null);
      }
    } else if (aliveRef.current) {
      setEvaluation(null);
    }
    return t;
  }, []);

  const onWsMessage = useCallback(
    (message: WebSocketMessage) => {
      if (!taskId) return;
      if (message.type === "task_event" || message.type === "initial_events") {
        void refresh(taskId).catch((err) => {
          setError(err instanceof Error ? err.message : "refresh failed");
        });
      }
      if (message.type === "initial_state" && message.data) {
        // Prefer authoritative HTTP refresh for full node graph
        void refresh(taskId).catch(() => undefined);
      }
    },
    [taskId, refresh]
  );

  const { isConnected } = useWebSocket({
    taskId: taskId || undefined,
    enabled: Boolean(taskId),
    onMessage: onWsMessage,
  });

  useEffect(() => {
    setLiveMode(isConnected ? "ws" : "poll");
  }, [isConnected]);

  useEffect(() => {
    aliveRef.current = true;
    if (!taskId) {
      setTask(null);
      setEvents([]);
      setArtifacts([]);
      setEvaluation(null);
      setMemories([]);
      setError(null);
      return;
    }

    let timer: ReturnType<typeof setTimeout> | undefined;
    terminalPollsRef.current = 0;

    async function tick() {
      try {
        const t = await refresh(taskId!);
        if (!aliveRef.current) return;

        if (TERMINAL.has(t.status)) {
          let hasEval = false;
          try {
            const ev = await getTaskEvaluation(taskId!);
            hasEval = Boolean(ev);
            if (aliveRef.current) setEvaluation(ev);
          } catch {
            if (aliveRef.current) setEvaluation(null);
          }
          if (hasEval || terminalPollsRef.current >= 8) {
            return;
          }
          terminalPollsRef.current += 1;
          if (aliveRef.current) timer = setTimeout(tick, 1500);
          return;
        }
      } catch (err) {
        if (aliveRef.current) {
          setError(err instanceof Error ? err.message : "poll failed");
        }
      }

      // WS connected → slow backup poll; otherwise 1s fallback
      const delay = isConnected ? 8000 : 1000;
      if (aliveRef.current) timer = setTimeout(tick, delay);
    }

    void tick();
    return () => {
      aliveRef.current = false;
      if (timer) clearTimeout(timer);
    };
  }, [taskId, nonce, refresh, isConnected]);

  return {
    task,
    events,
    artifacts,
    evaluation,
    memories,
    error,
    liveMode,
    wsConnected: isConnected,
    setTask,
    reload: () => setNonce((n) => n + 1),
  };
}
