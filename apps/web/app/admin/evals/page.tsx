import type { Metadata } from "next";

import { EvalsView } from "@/components/admin/evals-view";

export const metadata: Metadata = { title: "Evals" };

export default function EvalsPage() {
  return <EvalsView />;
}
