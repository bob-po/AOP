import { Suspense } from "react";
import { TasksWorkspace } from "@/components/tasks/TasksWorkspace";

export default async function TaskDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Suspense fallback={<div className="p-6 font-mono text-sm text-mist-400">Loading task…</div>}>
      <TasksWorkspace initialTaskId={id} />
    </Suspense>
  );
}
