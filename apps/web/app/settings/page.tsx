import { Suspense } from "react";
import { SettingsPageView } from "@/components/settings/SettingsPageView";

export default function SettingsPage() {
  return (
    <Suspense
      fallback={
        <div className="px-4 py-6 font-mono text-sm text-mist-400 md:px-8">加载设置…</div>
      }
    >
      <SettingsPageView />
    </Suspense>
  );
}
