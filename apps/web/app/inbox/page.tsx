import { Suspense } from "react";
import { HitlInboxView } from "@/components/inbox/HitlInboxView";

export default function InboxPage() {
  return (
    <Suspense
      fallback={
        <div className="p-6 font-mono text-sm text-mist-400">Loading inbox…</div>
      }
    >
      <HitlInboxView />
    </Suspense>
  );
}
