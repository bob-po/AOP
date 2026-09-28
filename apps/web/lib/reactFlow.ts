"use client";

import { useEffect, useState } from "react";

/**
 * React Flow needs browser layout metrics; defer mount until after hydration
 * to avoid SSR attribute mismatches (Next.js hydration error).
 */
export function useClientMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  return mounted;
}

/**
 * Suppress React Flow error 002 (stale nodeTypes/edgeTypes identity).
 * Harmless on @xyflow/react v12+ where Strict Mode no longer false-triggers it;
 * kept so custom handlers do not fall through to console.warn for code 002.
 */
export function reactFlowOnError(code: string, message: string): void {
  if (code === "002") return;
  console.warn(message);
}
