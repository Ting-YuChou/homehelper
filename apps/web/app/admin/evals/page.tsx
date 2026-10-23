import type { Metadata } from "next";

import { EvalsView } from "@/components/admin/evals-view";

export const metadata: Metadata = { title: "Evals" };

// Rendered only after the admin shell's client-side session check, so navigating here blocks
// by design; opt out of instant-navigation validation.
export const instant = false;

export default function EvalsPage() {
  return <EvalsView />;
}
