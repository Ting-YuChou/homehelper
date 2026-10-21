import { TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { StepCard as StepCardData, StructuredAction } from "@/lib/api/types";
import { STEP_BUTTONS } from "@/lib/chat/actions";

import { CitationList } from "./citation-chip";

export function StepCard({
  card,
  interactive,
  onAction,
}: {
  card: StepCardData;
  interactive: boolean;
  onAction: (action: StructuredAction) => void;
}) {
  const buttons = STEP_BUTTONS.filter(({ value }) => card.actions?.includes(value) ?? true);
  return (
    <section
      aria-label={`Step ${card.index} of ${card.total}`}
      className="flex flex-col gap-3 rounded-xl border border-sky-200 bg-sky-50/60 p-4 dark:border-sky-900 dark:bg-sky-950/30"
    >
      <div className="flex items-center gap-3">
        <span className="text-xs font-medium tracking-wide text-sky-800 uppercase dark:text-sky-300">
          Step {card.index} of {card.total}
        </span>
        <div
          className="h-1 flex-1 overflow-hidden rounded-full bg-sky-100 dark:bg-sky-900"
          aria-hidden
        >
          <div
            className="h-full rounded-full bg-sky-500"
            style={{ width: `${(card.index / Math.max(card.total, 1)) * 100}%` }}
          />
        </div>
      </div>
      <p className="text-[15px] leading-relaxed">{card.instruction}</p>
      {card.warranty_warning && (
        <p className="flex items-start gap-2 text-sm text-amber-800 dark:text-amber-300">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          Opening this part yourself may void the warranty. Consider asking the manufacturer first.
        </p>
      )}
      <CitationList citations={card.citations ?? []} />
      {interactive && (
        <div className="flex flex-wrap gap-2">
          {buttons.map(({ value, label }) => (
            <Button
              key={value}
              size="sm"
              variant={value === "fixed" ? "default" : "outline"}
              onClick={() => onAction({ type: "step_result", value })}
            >
              {label}
            </Button>
          ))}
        </div>
      )}
    </section>
  );
}
