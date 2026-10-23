import type { Metadata } from "next";
import { Suspense } from "react";

import { ReviewList } from "@/components/admin/review-list";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Review" };

// Rendered only after the admin shell's client-side session check, so navigating here blocks
// by design; opt out of instant-navigation validation.
export const instant = false;

export default function ReviewPage() {
  // The filters live in the URL (useSearchParams), so the list renders below Suspense.
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <ReviewList />
    </Suspense>
  );
}
