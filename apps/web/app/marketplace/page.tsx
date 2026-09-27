import { redirect } from "next/navigation";

/** Marketplace UI removed — harness agents register via Agent page / install scripts. */
export default function MarketplacePage() {
  redirect("/agents");
}
