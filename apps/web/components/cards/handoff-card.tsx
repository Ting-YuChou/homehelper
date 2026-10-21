import { HardHat } from "lucide-react";

import type { HandoffCard as HandoffCardData } from "@/lib/api/types";

export function HandoffCard({ card }: { card: HandoffCardData }) {
  return (
    <section className="flex gap-3 rounded-xl border border-violet-200 bg-violet-50/60 p-4 dark:border-violet-900 dark:bg-violet-950/30">
      <HardHat className="mt-0.5 size-5 shrink-0 text-violet-600" aria-hidden />
      <div className="flex flex-col gap-1">
        <h3 className="font-medium">A technician should take a look</h3>
        <p className="text-sm text-muted-foreground">{card.reason}</p>
        {card.booking_available && (
          <p className="text-sm">Ask me to book a visit and I&apos;ll find you a time slot.</p>
        )}
      </div>
    </section>
  );
}
