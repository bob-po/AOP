"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getPreflight, type PreflightSnapshot } from "@/lib/api";

type PreflightState = {
  snapshot: PreflightSnapshot | null;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
};

const PreflightContext = createContext<PreflightState | null>(null);

export function PreflightProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<PreflightSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const next = await getPreflight();
      setSnapshot(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "preflight failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      if (!alive) return;
      await refresh();
    })();
    const id = window.setInterval(() => {
      if (typeof document !== "undefined" && document.hidden) return;
      void refresh();
    }, 15000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [refresh]);

  const value = useMemo(
    () => ({ snapshot, error, loading, refresh }),
    [snapshot, error, loading, refresh],
  );

  return (
    <PreflightContext.Provider value={value}>{children}</PreflightContext.Provider>
  );
}

export function usePreflight(): PreflightState {
  const ctx = useContext(PreflightContext);
  if (!ctx) {
    return {
      snapshot: null,
      error: null,
      loading: false,
      refresh: async () => undefined,
    };
  }
  return ctx;
}
