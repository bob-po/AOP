import { Suspense } from "react";
import { CommandCenter } from "@/components/visual-runtime/CommandCenter";

export default function HomePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[50vh] items-center justify-center font-mono text-sm text-mist-400">
          booting visual runtime…
        </div>
      }
    >
      <CommandCenter />
    </Suspense>
  );
}
