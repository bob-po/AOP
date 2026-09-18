"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { createTask } from "@/lib/api";

const SUGGESTIONS = [
  { label: "Research", text: "帮我研究一个 AI 产品，搜索资料并结合知识库分析，然后生成一份报告" },
  { label: "RAG", text: "基于企业知识库回答：多 Agent 编排平台的核心模块有哪些？" },
  { label: "Search", text: "搜索 A2A Agent Orchestration 的公开资料并总结" },
  { label: "Report", text: "搜索并检索知识库后，生成一份产品分析报告" },
];

export function HomeComposer() {
  const router = useRouter();
  const [value, setValue] = useState(SUGGESTIONS[0].text);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const content = value.trim();
    if (!content || loading) return;
    setLoading(true);
    setError(null);
    try {
      const task = await createTask(content);
      router.push(`/tasks/${task.task_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create task");
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-6">
      <p className="animate-rise font-display text-4xl leading-tight text-mist-100 md:text-6xl">
        What can I do for you?
      </p>
      <p
        className="animate-rise mt-4 max-w-xl text-center text-sm text-mist-400 md:text-base"
        style={{ animationDelay: "80ms" }}
      >
        Describe a goal. The orchestrator will plan a Task DAG, route agents, and stream the trace.
      </p>

      <form
        onSubmit={onSubmit}
        className="animate-rise mt-10 w-full"
        style={{ animationDelay: "160ms" }}
      >
        <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-ink-800/70 shadow-glow backdrop-blur-md">
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={4}
            className="w-full resize-none bg-transparent px-5 pb-16 pt-5 font-sans text-base leading-relaxed text-mist-100 outline-none placeholder:text-mist-400/60"
            placeholder="帮我分析这个公司的业务并生成报告…"
          />
          <div className="absolute bottom-3 right-3 flex items-center gap-3">
            {error ? (
              <span className="max-w-[220px] truncate font-mono text-[10px] text-signal-warm">
                {error}
              </span>
            ) : null}
            <button
              type="submit"
              disabled={loading || !value.trim()}
              className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-ink-950 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? "Planning…" : "Run"}
            </button>
          </div>
        </div>
      </form>

      <div
        className="animate-rise mt-8 flex flex-wrap justify-center gap-3"
        style={{ animationDelay: "240ms" }}
      >
        {SUGGESTIONS.map((s) => (
          <button
            key={s.label}
            type="button"
            onClick={() => setValue(s.text)}
            className="rounded-full border border-white/10 px-4 py-1.5 font-mono text-[11px] uppercase tracking-[0.16em] text-mist-400 transition hover:border-signal/40 hover:text-signal"
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}
