"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getTask,
  getTaskArtifacts,
  getTaskEvaluation,
  getTaskEvents,
  invalidateTaskCache,
  type ArtifactItem,
  type MemoryEntry,
  type TaskDetail,
  type TaskEvaluation,
  type TaskEvent,
} from "@/lib/api";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

/** HTTP poll for task drawer. Graph WS lives in useVisualRuntime — do not open a second socket. */
export function useTaskLive(taskId: string | null) {
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [evaluation, setEvaluation] = useState<TaskEvaluation | null>(null);
  const [memories] = useState<MemoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const aliveRef = useRef(true);
  const shownIdRef = useRef<string | null>(null);

  const refresh = useCallback(async (id: string, extras = true) => {
    const [t, e] = await Promise.all([getTask(id), getTaskEvents(id)]);
    if (!aliveRef.current) return t;
    shownIdRef.current = id;
    setTask(t);
    setEvents(e.events || []);
    setError(null);
    if (!extras) return t;

    const jobs: Promise<void>[] = [
      getTaskArtifacts(id)
        .then((a) => {
          if (aliveRef.current && shownIdRef.current === id) {
            setArtifacts(a.artifacts || []);
          }
        })
        .catch(() => undefined),
    ];
    if (TERMINAL.has(t.status)) {
      jobs.push(
        getTaskEvaluation(id)
          .then((ev) => {
            if (aliveRef.current && shownIdRef.current === id) setEvaluation(ev);
          })
          .catch(() => {
            if (aliveRef.current && shownIdRef.current === id) setEvaluation(null);
          }),
      );
    } else if (aliveRef.current && shownIdRef.current === id) {
      setEvaluation(null);
    }
    await Promise.all(jobs);
    return t;
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    if (!taskId) {
      shownIdRef.current = null;
      setTask(null);
      setEvents([]);
      setArtifacts([]);
      setEvaluation(null);
      setError(null);
      return;
    }

    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick() {
      try {
        const t = await refresh(taskId!);
        if (!aliveRef.current) return;

        if (TERMINAL.has(t.status)) {
          return;
        }
      } catch (err) {
        if (aliveRef.current) {
          setError(err instanceof Error ? err.message : "poll failed");
        }
      }

      if (aliveRef.current) timer = setTimeout(tick, 8000);
    }

    void tick();
    return () => {
      aliveRef.current = false;
      if (timer) clearTimeout(timer);
    };
  }, [taskId, nonce, refresh]);

  return {
    task,
    events,
    artifacts,
    evaluation,
    memories,
    error,
    liveMode: "poll" as const,
    wsConnected: false,
    setTask,
    reload: () => {
      if (taskId) invalidateTaskCache(taskId);
      setNonce((n) => n + 1);
    },
  };
}
