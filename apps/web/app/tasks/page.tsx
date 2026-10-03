import { Suspense } from "react";
import { TasksWorkspace } from "@/components/tasks/TasksWorkspace";

function TasksFallback() {
  return (
    <div className="flex h-[calc(100vh-3.5rem)] min-h-[560px] flex-col lg:flex-row">
      <aside className="w-full border-b border-white/10 px-3 py-3 lg:w-64 lg:border-b-0 lg:border-r">
        <div className="font-display text-lg text-mist-100">任务</div>
        <p className="mt-3 font-mono text-xs text-mist-400">加载任务…</p>
      </aside>
      <div className="flex flex-1 items-center justify-center font-mono text-sm text-mist-400">
        选择左侧任务查看 Live Agent Network
      </div>
    </div>
  );
}

export default function TasksPage() {
  return (
    <Suspense fallback={<TasksFallback />}>
      <TasksWorkspace />
    </Suspense>
  );
}
