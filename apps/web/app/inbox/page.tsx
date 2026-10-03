import { redirect } from "next/navigation";

/** Inbox UI removed — HITL lives on Tasks 待审批 + Network. */
export default function InboxRedirect() {
  redirect("/tasks?status=waiting_for_user,waiting_for_agent");
}
