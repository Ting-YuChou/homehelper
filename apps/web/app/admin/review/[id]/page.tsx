import type { Metadata } from "next";
import { Suspense } from "react";

import { ReviewDetail } from "@/components/admin/review-detail";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Review conversation" };

export default function ReviewConversationPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <ReviewDetail />
    </Suspense>
  );
}
