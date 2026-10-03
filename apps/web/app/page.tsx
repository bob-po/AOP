import { Suspense } from "react";
import {
  CommandCenter,
  NetworkIdleHero,
} from "@/components/visual-runtime/CommandCenter";

export default function HomePage() {
  return (
    <Suspense fallback={<NetworkIdleHero />}>
      <CommandCenter />
    </Suspense>
  );
}
