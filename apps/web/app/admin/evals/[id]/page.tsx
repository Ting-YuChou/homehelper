import type { Metadata } from "next";
import { Suspense } from "react";

import { EvalReportDetail } from "@/components/admin/eval-report-detail";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Eval report" };

// Rendered only after the admin shell's client-side session check, so navigating here blocks
// by design; opt out of instant-navigation validation.
export const instant = false;

export default function EvalReportPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <EvalReportDetail />
    </Suspense>
  );
}
