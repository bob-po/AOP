import { redirect } from "next/navigation";

/** Scheduling console removed — routing lives under Agent → 智能路由. */
export default function SchedulingPage() {
  redirect("/agents");
}
