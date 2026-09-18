"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { listArtifacts, type ArtifactItem } from "@/lib/api";

const TYPES = ["", "json", "text", "image", "video", "pdf"];

export function ArtifactsPageView() {
  const router = useRouter();
  const [items, setItems] = useState<ArtifactItem[]>([]);
  const [taskId, setTaskId] = useState("");
  const [type, setType] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ArtifactItem | null>(null);

  async function load() {
    try {
      const data = await listArtifacts({
        task_id: taskId.trim() || undefined,
        type: type || undefined,
        limit: 120,
      });
      setItems(data.artifacts || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
    }
  }

  useEffect(() => {
    load();
  }, [type]);

  const filtered = useMemo(() => items, [items]);

  function copyUri(uri?: string) {
    if (!uri) return;
    void navigator.clipboard.writeText(uri);
  }

  function reuse(a: ArtifactItem) {
    const hint = `请基于产物 ${a.uri || a.url || a.name} 继续处理：`;
    router.push(`/?prefill=${encodeURIComponent(hint)}`);
  }

  const isImage = (a: ArtifactItem) =>
    (a.mime_type || "").startsWith("image/") || /\.(png|jpe?g|webp|gif)$/i.test(a.name || "");
  const isVideo = (a: ArtifactItem) =>
    (a.mime_type || "").startsWith("video/") || /\.(mp4|webm)$/i.test(a.name || "");

  return (
    <div className="px-4 py-6 md:px-8">
      <div>
        <h1 className="font-display text-3xl text-mist-100">产物仓库</h1>
        <p className="mt-1 text-sm text-mist-400">MinIO 中任务产出物的统一浏览与复用。</p>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <input
          value={taskId}
          onChange={(e) => setTaskId(e.target.value)}
          placeholder="按 Task ID 筛选"
          className="rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-xs text-mist-100 outline-none focus:border-signal/40"
        />
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 font-mono text-xs text-mist-200"
        >
          {TYPES.map((t) => (
            <option key={t || "all"} value={t}>
              {t ? t.toUpperCase() : "全部类型"}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={load}
          className="rounded-xl border border-white/15 px-3 py-2 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-200"
        >
          刷新
        </button>
      </div>

      {error ? <div className="mt-3 font-mono text-xs text-signal-warm">{error}</div> : null}

      <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {filtered.length === 0 ? (
          <div className="font-mono text-sm text-mist-400">暂无产物</div>
        ) : null}
        {filtered.map((a, i) => (
          <div
            key={`${a.uri}-${i}`}
            className="overflow-hidden rounded-2xl border border-white/10 bg-ink-900/50"
          >
            <button
              type="button"
              className="block w-full bg-ink-950/50 text-left"
              onClick={() => setPreview(a)}
            >
              {isImage(a) && a.url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={a.url} alt={a.name || ""} className="h-36 w-full object-cover" />
              ) : isVideo(a) && a.url ? (
                <video src={a.url} className="h-36 w-full object-cover" muted />
              ) : (
                <div className="flex h-36 items-center justify-center font-mono text-xs text-mist-400">
                  {(a.type || a.mime_type || "file").toUpperCase()}
                </div>
              )}
            </button>
            <div className="p-3">
              <div className="truncate text-sm text-mist-100">{a.name}</div>
              <div className="mt-1 truncate font-mono text-[10px] text-mist-400">
                task {a.task_id?.slice(0, 8) || "—"} · {a.node_id || "—"}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {a.url ? (
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-lg border border-white/15 px-2 py-1 font-mono text-[10px] uppercase text-mist-200"
                  >
                    下载
                  </a>
                ) : null}
                <button
                  type="button"
                  onClick={() => copyUri(a.uri || a.url)}
                  className="rounded-lg border border-white/15 px-2 py-1 font-mono text-[10px] uppercase text-mist-200"
                >
                  复制 URI
                </button>
                <button
                  type="button"
                  onClick={() => reuse(a)}
                  className="rounded-lg border border-white/15 px-2 py-1 font-mono text-[10px] uppercase text-mist-200"
                >
                  关联新任务
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {preview ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4">
          <div className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-2xl border border-white/10 bg-ink-950 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="font-display text-xl text-mist-100">{preview.name}</div>
              <button
                type="button"
                onClick={() => setPreview(null)}
                className="font-mono text-xs text-mist-400 hover:text-signal"
              >
                关闭
              </button>
            </div>
            {isImage(preview) && preview.url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview.url} alt="" className="max-h-[70vh] w-full object-contain" />
            ) : isVideo(preview) && preview.url ? (
              <video src={preview.url} controls className="w-full" />
            ) : (
              <pre className="overflow-auto rounded-xl border border-white/10 bg-ink-900 p-3 font-mono text-xs text-mist-200">
                {preview.uri}
                {"\n"}
                {preview.url}
                {"\n"}
                {preview.mime_type}
              </pre>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
