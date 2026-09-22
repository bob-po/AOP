"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  approveTask,
  cancelTask,
  createTask,
  evaluateTask,
  listTasks,
  rejectTask,
  type TaskSummary,
} from "@/lib/api";
import { useTaskLive } from "@/hooks/useTaskLive";
import { TaskFlowDag } from "@/components/tasks/TaskFlowDag";
import { TaskTrace } from "@/components/TaskTrace";
import { PptPreview } from "@/components/tasks/PptPreview";

const FILTERS = [
  { key: "", label: "全部" },
  { key: "running", label: "运行中" },
  { key: "waiting_for_user", label: "待审批" },
  { key: "completed", label: "成功" },
  { key: "failed", label: "失败" },
  { key: "cancelled", label: "已取消" },
];

function isReportSkill(skill: string) {
  return skill.toLowerCase().includes("report");
}

function isPptSkill(skill: string) {
  const s = skill.toLowerCase();
  return s === "ppt" || s === "ppt-generation" || s.includes("ppt-generation");
}

function isWideDetail(skill: string) {
  return isReportSkill(skill) || isPptSkill(skill);
}

function isPptxName(name: string | undefined) {
  const n = (name || "").replace(/\\/g, "/").toLowerCase();
  return n.endsWith(".pptx") || n.endsWith("deck.pptx") || n.endsWith("report.pptx");
}

const DIMENSION_LABELS: Record<string, string> = {
  structure: "结构",
  prose: "行文",
  citations: "引用",
  layout: "版式",
  execution: "执行",
  completeness: "完整",
  reliability: "可靠",
  artifacts: "产物",
  latency: "耗时",
};

export function TasksWorkspace({ initialTaskId }: { initialTaskId?: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const statusFilter = searchParams.get("status") || "";

  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initialTaskId || null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [detailNodeId, setDetailNodeId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const { task, events, artifacts, evaluation, memories, error: liveError, reload, liveMode, wsConnected } =
    useTaskLive(selectedId);

  const loadList = useCallback(async () => {
    try {
      const data = await listTasks({
        status: statusFilter || undefined,
        limit: 80,
      });
      setTasks(data.tasks || []);
      setListError(null);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "list failed");
    }
  }, [statusFilter]);

  useEffect(() => {
    loadList();
    const t = setInterval(loadList, 8000);
    return () => clearInterval(t);
  }, [loadList]);

  useEffect(() => {
    if (initialTaskId) setSelectedId(initialTaskId);
  }, [initialTaskId]);

  useEffect(() => {
    if (!selectedId && tasks.length > 0) {
      setSelectedId(tasks[0].task_id);
    }
  }, [tasks, selectedId]);

  function selectTask(id: string) {
    setSelectedId(id);
    setSelectedNodeId(null);
    setDetailNodeId(null);
    router.replace(`/tasks/${id}${statusFilter ? `?status=${statusFilter}` : ""}`);
  }

  async function onCancel() {
    if (!selectedId || busy) return;
    setBusy(true);
    try {
      await cancelTask(selectedId);
      await loadList();
    } catch (err) {
      setListError(err instanceof Error ? err.message : "cancel failed");
    } finally {
      setBusy(false);
    }
  }

  async function onRetry() {
    if (!task || busy) return;
    const content = task.input_json?.content || task.plan_json?.goal || "";
    if (!content.trim()) return;
    setBusy(true);
    try {
      const created = await createTask(content.trim());
      selectTask(created.task_id);
      await loadList();
    } catch (err) {
      setListError(err instanceof Error ? err.message : "retry failed");
    } finally {
      setBusy(false);
    }
  }

  async function onEvaluate() {
    if (!selectedId || busy) return;
    setBusy(true);
    try {
      await evaluateTask(selectedId);
      reload();
      await loadList();
    } catch (err) {
      setListError(err instanceof Error ? err.message : "evaluate failed");
    } finally {
      setBusy(false);
    }
  }

  async function onApprove() {
    if (!selectedId || busy) return;
    setBusy(true);
    try {
      await approveTask(selectedId);
      reload();
      await loadList();
    } catch (err) {
      setListError(err instanceof Error ? err.message : "approve failed");
    } finally {
      setBusy(false);
    }
  }

  async function onReject() {
    if (!selectedId || busy) return;
    setBusy(true);
    try {
      await rejectTask(selectedId);
      reload();
      await loadList();
    } catch (err) {
      setListError(err instanceof Error ? err.message : "reject failed");
    } finally {
      setBusy(false);
    }
  }

  const detailNode = useMemo(
    () => (task?.nodes || []).find((n) => n.id === detailNodeId) || null,
    [task, detailNodeId],
  );

  const reportPreviewUrl = useMemo(() => {
    if (!detailNode || !isReportSkill(detailNode.skill)) return null;
    const owned = artifacts.filter((item) => item.node_id === detailNode.id);
    const html = owned.find((item) =>
      (item.name || "").replace(/\\/g, "/").endsWith("report.html"),
    );
    const text = owned.find((item) => (item.name || "").endsWith("output.txt"));
    return html?.url || text?.url || null;
  }, [artifacts, detailNode]);

  const pptArtifact = useMemo(() => {
    if (!detailNode || !isPptSkill(detailNode.skill)) return null;
    const owned = artifacts.filter((item) => item.node_id === detailNode.id);
    const deck =
      owned.find((item) => (item.name || "").replace(/\\/g, "/").endsWith("deck.pptx")) ||
      owned.find((item) => isPptxName(item.name));
    return deck?.url ? deck : null;
  }, [artifacts, detailNode]);

  const goal = task?.input_json?.content || task?.plan_json?.goal || task?.title || "";

  function copyArtifactsToClipboard() {
    if (artifacts.length === 0) return;

    const grouped = artifacts.reduce((acc, a) => {
      const node = a.node_id || "unknown";
      if (!acc[node]) acc[node] = [];
      acc[node].push(a);
      return acc;
    }, {} as Record<string, typeof artifacts>);

    let text = `Task: ${task?.task_id || "unknown"}\n`;
    text += `Goal: ${goal}\n\n`;

    Object.entries(grouped).forEach(([nodeId, nodeArtifacts]) => {
      text += `Node: ${nodeId}\n`;
      nodeArtifacts.forEach((a) => {
        text += `  - ${a.name || a.uri}\n`;
        text += `    URL: ${a.url || a.uri}\n`;
      });
      text += "\n";
    });

    navigator.clipboard.writeText(text).catch(() => undefined);
  }

  function openNodeDetail(nodeId: string) {
    setSelectedNodeId(nodeId);
    setDetailNodeId(nodeId);
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] min-h-[560px] flex-col lg:flex-row">
      {/* Left list */}
      <aside className="flex w-full shrink-0 flex-col border-b border-white/10 lg:w-72 lg:border-b-0 lg:border-r">
        <div className="border-b border-white/10 px-3 py-3">
          <div className="font-display text-lg text-mist-100">任务</div>
          <div className="mt-2 flex flex-wrap gap-1">
            {FILTERS.map((f) => (
              <Link
                key={f.key || "all"}
                href={f.key ? `/tasks?status=${f.key}` : "/tasks"}
                className={`rounded-full px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] ${
                  statusFilter === f.key
                    ? "bg-signal/15 text-signal"
                    : "text-mist-400 hover:text-mist-100"
                }`}
              >
                {f.label}
              </Link>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-auto">
          {listError ? (
            <div className="p-3 font-mono text-[11px] text-signal-warm">{listError}</div>
          ) : null}
          {tasks.length === 0 ? (
            <div className="p-4 font-mono text-xs text-mist-400">暂无任务</div>
          ) : null}
          {tasks.map((t) => (
            <button
              key={t.task_id}
              type="button"
              onClick={() => selectTask(t.task_id)}
              className={`block w-full border-b border-white/5 px-3 py-3 text-left transition hover:bg-white/5 ${
                selectedId === t.task_id ? "bg-signal/10" : ""
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] text-mist-400">
                  {t.task_id.slice(0, 8)}
                </span>
                <span
                  className={`font-mono text-[10px] uppercase ${
                    t.status === "completed"
                      ? "text-signal"
                      : t.status === "failed"
                        ? "text-red-400"
                        : t.status === "waiting_for_user"
                          ? "text-amber-300"
                          : t.status === "running"
                            ? "text-signal-warm"
                            : "text-mist-400"
                  }`}
                >
                  {t.status === "waiting_for_user" ? "待审批" : t.status}
                </span>
              </div>
              <div className="mt-1 truncate text-sm text-mist-100">
                {t.title || "Untitled task"}
              </div>
              {typeof t.progress === "number" ? (
                <div className="mt-1 font-mono text-[10px] text-mist-400">{t.progress}%</div>
              ) : null}
            </button>
          ))}
        </div>
      </aside>

      {/* Center DAG */}
      <section className="flex min-w-0 flex-1 flex-col p-3">
        <div className="mb-2 flex items-center justify-between">
          <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
            DAG 画布
          </div>
          {selectedId ? (
            <span className="font-mono text-[10px] text-mist-400">{selectedId}</span>
          ) : null}
          <span
            className={`font-mono text-[10px] uppercase tracking-[0.12em] ${
              wsConnected ? "text-signal" : "text-mist-400"
            }`}
            title={wsConnected ? "WebSocket live" : "HTTP poll fallback"}
          >
            {liveMode === "ws" ? "live·ws" : "live·poll"}
          </span>
        </div>
        {selectedId ? (
          <TaskFlowDag
            plan={task?.plan_json}
            nodes={task?.nodes || []}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-white/10 font-mono text-sm text-mist-400">
            选择左侧任务查看 DAG
          </div>
        )}
        {liveError ? (
          <div className="mt-2 font-mono text-[11px] text-signal-warm">{liveError}</div>
        ) : null}
      </section>

      {/* Right drawer */}
      <aside
        className={`flex w-full shrink-0 flex-col border-t border-white/10 lg:border-l lg:border-t-0 ${
          detailNode && isWideDetail(detailNode.skill) ? "lg:w-[40rem]" : "lg:w-80"
        }`}
      >
        <div className="border-b border-white/10 px-4 py-3">
          <div className="font-display text-lg text-mist-100">任务详情</div>
          {task ? (
            <div className="mt-2 space-y-1 font-mono text-[11px] text-mist-400">
              <div>
                状态 <span className="text-signal">{task.status}</span>
                {typeof task.progress === "number" ? ` · ${task.progress}%` : ""}
              </div>
              <p className="line-clamp-3 text-mist-200">{goal}</p>
            </div>
          ) : (
            <p className="mt-2 font-mono text-xs text-mist-400">未选择任务</p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!task || busy || ["completed", "failed", "cancelled"].includes(task?.status || "")}
              onClick={onCancel}
              className="rounded-lg border border-white/15 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-mist-200 hover:border-signal-warm/40 disabled:opacity-40"
            >
              取消
            </button>
            <button
              type="button"
              disabled={!task || busy}
              onClick={onRetry}
              className="rounded-lg bg-signal/90 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-950 disabled:opacity-40"
            >
              整任务重试
            </button>
            <button
              type="button"
              disabled={
                !task ||
                busy ||
                !["completed", "failed", "cancelled"].includes(task?.status || "")
              }
              onClick={onEvaluate}
              className="rounded-lg border border-signal/30 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-signal hover:bg-signal/10 disabled:opacity-40"
            >
              评分
            </button>
            <button
              type="button"
              disabled={!task || busy || task?.status !== "waiting_for_user"}
              onClick={onApprove}
              className="rounded-lg bg-amber-300/90 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-950 disabled:opacity-40"
            >
              批准
            </button>
            <button
              type="button"
              disabled={!task || busy || task?.status !== "waiting_for_user"}
              onClick={onReject}
              className="rounded-lg border border-red-400/40 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-red-300 hover:bg-red-400/10 disabled:opacity-40"
            >
              驳回
            </button>
          </div>
          {task?.status === "waiting_for_user" ? (
            <p className="mt-2 font-mono text-[10px] text-amber-200/90">
              人工审批闸门：报告节点已产出，批准后继续下游或完成任务。
            </p>
          ) : null}
        </div>

        <div className="flex-1 space-y-4 overflow-auto p-4">
          {memories.length > 0 ? (
            <div className="rounded-xl border border-white/10 bg-ink-900/50 p-3">
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
                Working Memory
              </div>
              <ul className="mt-2 max-h-40 space-y-2 overflow-auto">
                {memories.slice(0, 8).map((m) => (
                  <li key={m.memory_key} className="rounded-lg border border-white/5 px-2 py-1.5">
                    <div className="font-mono text-[10px] text-signal-dim">{m.memory_key}</div>
                    <p className="mt-0.5 line-clamp-3 text-[11px] text-mist-300">{m.content}</p>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {evaluation ? (
            <div className="rounded-xl border border-signal/20 bg-signal/5 p-3">
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
                Evaluation
              </div>
              <div className="mt-2 flex items-baseline gap-3">
                <span className="font-display text-3xl text-signal">{evaluation.grade}</span>
                <span className="font-mono text-lg text-mist-100">{evaluation.score}</span>
                <span className="font-mono text-[10px] text-mist-400">{evaluation.method}</span>
              </div>
              {evaluation.summary ? (
                <p className="mt-2 text-xs text-mist-300">{evaluation.summary}</p>
              ) : null}
              {evaluation.dimensions ? (
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {Object.entries(evaluation.dimensions).map(([k, v]) => (
                    <div
                      key={k}
                      className="rounded-lg border border-white/10 bg-ink-900/40 px-2 py-1.5"
                    >
                      <div className="font-mono text-[9px] uppercase tracking-[0.12em] text-mist-400">
                        {DIMENSION_LABELS[k] ?? k}
                      </div>
                      <div className="font-mono text-sm text-mist-100">{v}</div>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {task ? (
            <div className="flex justify-end">
              <button
                type="button"
                disabled={artifacts.length === 0}
                onClick={() => copyArtifactsToClipboard()}
                className="rounded border border-white/15 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.12em] text-mist-300 hover:bg-white/5 disabled:opacity-40"
              >
                复制全部
              </button>
            </div>
          ) : null}

          {detailNode ? (
            <div className="rounded-xl border border-white/10 bg-ink-900/50 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => setDetailNodeId(null)}
                  className="font-mono text-[10px] text-mist-400 hover:text-mist-100"
                >
                  ← 返回
                </button>
                <span className="truncate font-mono text-[10px] text-mist-200">
                  {detailNode.id} · {detailNode.skill}
                </span>
              </div>
              {isPptSkill(detailNode.skill) ? (
                pptArtifact?.url ? (
                  <PptPreview url={pptArtifact.url} name={pptArtifact.name} />
                ) : (
                  <p className="text-xs text-mist-400">
                    PPT 还在生成，预览会在 deck.pptx 产出后出现。
                  </p>
                )
              ) : isReportSkill(detailNode.skill) ? (
                reportPreviewUrl ? (
                  <iframe
                    title="报告预览"
                    src={reportPreviewUrl}
                    sandbox="allow-same-origin"
                    className="h-[520px] w-full rounded-lg border border-white/10 bg-white"
                  />
                ) : (
                  <p className="text-xs text-mist-400">报告还在生成，预览会在 report.html 产出后出现。</p>
                )
              ) : (
                <div>
                  <div className="text-sm text-mist-100">{detailNode.skill}</div>
                  <div className="mt-1 font-mono text-[11px] text-mist-400">
                    status={detailNode.status} · attempt={detailNode.attempt ?? 0}
                  </div>
                  {detailNode.error_message ? (
                    <p className="mt-2 text-xs text-red-300">{detailNode.error_message}</p>
                  ) : null}
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {(task?.nodes || []).map((node) => (
                <div
                  key={node.id}
                  className={`relative rounded-xl border bg-ink-900/50 p-3 ${
                    selectedNodeId === node.id ? "border-signal/40" : "border-white/10"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => openNodeDetail(node.id)}
                    className="absolute right-3 top-3 font-mono text-[10px] text-signal-dim underline underline-offset-2 hover:text-signal"
                  >
                    详情
                  </button>
                  <div className="pr-10 font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
                    节点 {node.id}
                  </div>
                  <div className="mt-2 text-sm text-mist-100">{node.skill}</div>
                  <div className="mt-1 font-mono text-[11px] text-mist-400">
                    status={node.status} · attempt={node.attempt ?? 0}
                  </div>
                  {node.error_message ? (
                    <p className="mt-2 text-xs text-red-300">{node.error_message}</p>
                  ) : null}
                </div>
              ))}
            </div>
          )}

          <div>
            <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
              Live Trace
            </div>
            <TaskTrace events={events} />
          </div>

          {task?.result_json?.summary ? (
            <div>
              <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
                Result
              </div>
              <pre className="whitespace-pre-wrap rounded-xl border border-white/10 bg-ink-900/40 p-3 text-xs text-mist-200">
                {String(task.result_json.summary).slice(0, 1200)}
              </pre>
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
