"use client";

import { useEffect, useRef, useState } from "react";

type Props = {
  url: string;
  name?: string;
};

function proxyUrl(url: string) {
  return `/api/artifacts/proxy?url=${encodeURIComponent(url)}`;
}

export function PptPreview({ url, name }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let disposer: { destroy?: () => void } | null = null;

    async function run() {
      setLoading(true);
      setError(null);
      const el = hostRef.current;
      if (!el) return;
      el.innerHTML = "";

      try {
        const width = Math.max(320, Math.floor(el.clientWidth || 640));
        const height = Math.round((width * 9) / 16);
        const { init } = await import("pptx-preview");
        const viewer = init(el, { width, height });
        disposer = viewer as { destroy?: () => void };

        const res = await fetch(proxyUrl(url));
        if (!res.ok) {
          throw new Error(`加载失败 (${res.status})`);
        }
        const buf = await res.arrayBuffer();
        if (cancelled) return;
        await viewer.preview(buf);
        if (!cancelled) setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "预览失败");
          setLoading(false);
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
      try {
        disposer?.destroy?.();
      } catch {
        /* ignore */
      }
    };
  }, [url]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[10px] text-mist-300">
          {name || "deck.pptx"}
        </span>
        <a
          href={proxyUrl(url)}
          download={name || "deck.pptx"}
          className="shrink-0 rounded border border-white/15 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.12em] text-mist-200 hover:bg-white/5"
        >
          下载
        </a>
      </div>
      {loading ? (
        <p className="font-mono text-[11px] text-mist-400">正在渲染 PPT…</p>
      ) : null}
      {error ? (
        <div className="space-y-2">
          <p className="text-xs text-signal-warm">{error}</p>
          <p className="text-xs text-mist-400">可直接下载后用 PowerPoint / WPS 打开。</p>
        </div>
      ) : null}
      <div
        ref={hostRef}
        className="max-h-[560px] overflow-auto rounded-lg border border-white/10 bg-ink-950"
      />
    </div>
  );
}
