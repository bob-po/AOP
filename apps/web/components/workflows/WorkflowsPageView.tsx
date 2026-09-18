"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ReactFlow, {
  Background,
  Controls,
  MarkerType,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  createWorkflow,
  listWorkflows,
  runWorkflow,
  type TaskPlan,
  type Workflow,
} from "@/lib/api";

function dagToFlow(dag?: TaskPlan | null): { nodes: Node[]; edges: Edge[] } {
  const planNodes = dag?.nodes || [];
  const nodes: Node[] = planNodes.map((n, i) => ({
    id: n.id,
    position: { x: 40 + (i % 3) * 200, y: 40 + Math.floor(i / 3) * 110 },
    data: { label: `${n.id}\n${n.skill}` },
    style: {
      background: "#152822",
      border: "1.5px solid #3dffa8",
      borderRadius: 12,
      color: "#e8f2ee",
      fontSize: 11,
      fontFamily: "IBM Plex Mono, monospace",
      padding: 10,
      width: 150,
      whiteSpace: "pre-line",
    },
  }));
  const edges: Edge[] = [];
  for (const n of planNodes) {
    for (const p of n.depends_on || []) {
      edges.push({
        id: `${p}-${n.id}`,
        source: p,
        target: n.id,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#7eaea0" },
        style: { stroke: "#7eaea0" },
      });
    }
  }
  return { nodes, edges };
}

function flowToDag(nodes: Node[], edges: Edge[], title: string): TaskPlan {
  const deps = new Map<string, string[]>();
  for (const e of edges) {
    const arr = deps.get(e.target) || [];
    arr.push(e.source);
    deps.set(e.target, arr);
  }
  return {
    title,
    nodes: nodes.map((n) => {
      const label = String(n.data?.label || n.id);
      const parts = label.split("\n");
      const skill = parts[1] || parts[0] || n.id;
      return {
        id: n.id,
        skill,
        depends_on: deps.get(n.id) || [],
      };
    }),
  };
}

export function WorkflowsPageView() {
  const router = useRouter();
  const [items, setItems] = useState<Workflow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [goal, setGoal] = useState(
    "帮我研究一个 AI 产品，搜索资料并结合知识库分析，然后生成一份报告",
  );
  const [running, setRunning] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("Custom Workflow");
  const [desc, setDesc] = useState("");
  const [skillInput, setSkillInput] = useState("web-search");
  const [nodeId, setNodeId] = useState("search");
  const [busy, setBusy] = useState(false);

  const initial = useMemo(
    () =>
      dagToFlow({
        title: "Custom",
        nodes: [
          { id: "search", skill: "web-search" },
          { id: "rag", skill: "knowledge-search" },
          { id: "report", skill: "report-generation", depends_on: ["search", "rag"] },
        ],
      }),
    [],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);

  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge({ ...connection, animated: false }, eds)),
    [setEdges],
  );

  async function reload() {
    const data = await listWorkflows();
    setItems(data.workflows || []);
  }

  useEffect(() => {
    reload().catch((err) => setError(err instanceof Error ? err.message : "failed"));
  }, []);

  async function onRun(wf: Workflow) {
    if (running) return;
    setRunning(wf.workflow_id);
    setError(null);
    try {
      const task = await runWorkflow(wf.workflow_id, goal.trim(), wf.name);
      router.push(`/tasks/${task.task_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "run failed");
      setRunning(null);
    }
  }

  function addNode() {
    const id = nodeId.trim() || `node-${nodes.length + 1}`;
    if (nodes.some((n) => n.id === id)) {
      setError("node id already exists");
      return;
    }
    setNodes((prev) => [
      ...prev,
      {
        id,
        position: { x: 60 + prev.length * 40, y: 60 + prev.length * 30 },
        data: { label: `${id}\n${skillInput.trim() || "skill"}` },
        style: {
          background: "#152822",
          border: "1.5px solid #3dffa8",
          borderRadius: 12,
          color: "#e8f2ee",
          fontSize: 11,
          fontFamily: "IBM Plex Mono, monospace",
          padding: 10,
          width: 150,
          whiteSpace: "pre-line",
        },
      },
    ]);
  }

  async function onSave() {
    setBusy(true);
    setError(null);
    try {
      const dag = flowToDag(nodes, edges, name);
      await createWorkflow({
        name,
        description: desc,
        dag,
        publish: true,
      });
      setEditing(false);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  function onExport() {
    const dag = flowToDag(nodes, edges, name);
    const blob = new Blob(
      [JSON.stringify({ name, description: desc, dag }, null, 2)],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name.replace(/\s+/g, "-").toLowerCase() || "workflow"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function onImportFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const raw = JSON.parse(String(reader.result || "{}"));
        if (raw.name) setName(String(raw.name));
        if (raw.description) setDesc(String(raw.description));
        const flow = dagToFlow(raw.dag || raw);
        setNodes(flow.nodes);
        setEdges(flow.edges);
        setEditing(true);
      } catch {
        setError("invalid workflow json");
      }
    };
    reader.readAsText(file);
  }

  return (
    <div className="px-4 py-6 md:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl text-mist-100">编排模板</h1>
          <p className="mt-1 text-sm text-mist-400">
            预制 DAG 工作流。可视化编辑后保存，一键启动任务。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <label className="cursor-pointer rounded-xl border border-white/15 px-3 py-2 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-300">
            导入 JSON
            <input
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onImportFile(f);
              }}
            />
          </label>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-ink-950"
          >
            新建工作流
          </button>
        </div>
      </div>

      <label className="mt-6 block max-w-3xl">
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400">
          运行输入
        </span>
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          rows={2}
          className="mt-2 w-full rounded-xl border border-white/10 bg-ink-800/60 px-4 py-3 text-sm text-mist-100 outline-none focus:border-signal/40"
        />
      </label>

      {error ? <div className="mt-3 font-mono text-xs text-signal-warm">{error}</div> : null}

      <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((wf) => {
          const n = wf.dag?.nodes || [];
          return (
            <div
              key={wf.workflow_id}
              className="rounded-2xl border border-white/10 bg-ink-900/50 p-4"
            >
              <div className="font-display text-xl text-mist-100">{wf.name}</div>
              <div className="mt-1 font-mono text-[11px] text-mist-400">
                {wf.workflow_key} · v{wf.version || "?"} · {wf.status}
              </div>
              <p className="mt-2 line-clamp-2 text-sm text-mist-400">
                {wf.description || n.map((x) => x.id).join(" → ")}
              </p>
              <button
                type="button"
                disabled={!!running || !goal.trim()}
                onClick={() => onRun(wf)}
                className="mt-4 rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase tracking-[0.14em] text-ink-950 disabled:opacity-40"
              >
                {running === wf.workflow_id ? "Starting…" : "一键运行"}
              </button>
            </div>
          );
        })}
      </div>

      {editing ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4">
          <div className="flex h-[90vh] w-full max-w-5xl flex-col rounded-2xl border border-white/10 bg-ink-950">
            <div className="flex flex-wrap items-center gap-2 border-b border-white/10 p-4">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="rounded-lg border border-white/10 bg-ink-900 px-3 py-1.5 text-sm text-mist-100"
                placeholder="名称"
              />
              <input
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
                className="min-w-[180px] flex-1 rounded-lg border border-white/10 bg-ink-900 px-3 py-1.5 text-sm text-mist-100"
                placeholder="描述"
              />
              <input
                value={nodeId}
                onChange={(e) => setNodeId(e.target.value)}
                className="w-28 rounded-lg border border-white/10 bg-ink-900 px-2 py-1.5 font-mono text-xs text-mist-100"
                placeholder="node id"
              />
              <input
                value={skillInput}
                onChange={(e) => setSkillInput(e.target.value)}
                className="w-36 rounded-lg border border-white/10 bg-ink-900 px-2 py-1.5 font-mono text-xs text-mist-100"
                placeholder="skill"
              />
              <button
                type="button"
                onClick={addNode}
                className="rounded-lg border border-white/15 px-3 py-1.5 font-mono text-[10px] uppercase text-mist-200"
              >
                加节点
              </button>
              <button
                type="button"
                onClick={onExport}
                className="rounded-lg border border-white/15 px-3 py-1.5 font-mono text-[10px] uppercase text-mist-200"
              >
                导出
              </button>
              <div className="ml-auto flex gap-2">
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  className="rounded-lg px-3 py-1.5 font-mono text-xs text-mist-400"
                >
                  关闭
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={onSave}
                  className="rounded-lg bg-signal px-4 py-1.5 font-mono text-xs font-semibold uppercase text-ink-950 disabled:opacity-40"
                >
                  保存
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                fitView
                proOptions={{ hideAttribution: true }}
              >
                <Background color="#3dffa822" gap={22} />
                <Controls />
              </ReactFlow>
            </div>
            <div className="border-t border-white/10 px-4 py-2 font-mono text-[10px] text-mist-400">
              拖拽连线配置 depends_on；节点标签第二行为 skill。
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
