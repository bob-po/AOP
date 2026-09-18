import { Suspense } from "react";
import { TasksWorkspace } from "@/components/tasks/TasksWorkspace";

export default function TasksPage() {
  return (
    <Suspense fallback={<div className="p-6 font-mono text-sm text-mist-400">Loading tasks…</div>}>
      <TasksWorkspace />
    </Suspense>
  );
}
