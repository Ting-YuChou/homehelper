import type { Metadata } from "next";
import { Suspense } from "react";

import { EvalReportDetail } from "@/components/admin/eval-report-detail";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Eval report" };

export default function EvalReportPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <EvalReportDetail />
    </Suspense>
  );
}
