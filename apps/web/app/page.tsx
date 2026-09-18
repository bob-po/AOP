import { Suspense } from "react";
import { DashboardView } from "@/components/dashboard/DashboardView";

export default function HomePage() {
  return (
    <Suspense fallback={<div className="p-6 font-mono text-sm text-mist-400">Loading…</div>}>
      <DashboardView />
    </Suspense>
  );
}
