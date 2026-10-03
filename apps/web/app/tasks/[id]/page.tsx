import { redirect } from "next/navigation";

/** Deep links land on the same Tasks workspace so the list does not remount. */
export default async function TaskDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/tasks?task=${encodeURIComponent(id)}`);
}
