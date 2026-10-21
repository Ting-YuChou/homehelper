import { ScanSearch } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ApplianceConfirmCard as ConfirmCardData, StructuredAction } from "@/lib/api/types";

export function categoryLabel(category: string): string {
  const words = category.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function ApplianceConfirmCard({
  card,
  interactive,
  onAction,
}: {
  card: ConfirmCardData;
  interactive: boolean;
  onAction: (action: StructuredAction) => void;
}) {
  const name = [card.brand, card.category && categoryLabel(card.category).toLowerCase()]
    .filter(Boolean)
    .join(" ");
  return (
    <section className="flex flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-start gap-3">
        <ScanSearch className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden />
        <div className="flex flex-col gap-1">
          <p>
            Looks like {name ? `a ${name}` : "this appliance"}
            {card.model_number && (
              <>
                {" "}
                (model <span className="font-mono">{card.model_number}</span>)
              </>
            )}
            . Is that right?
          </p>
          <p className="text-xs text-muted-foreground">
            {Math.round(card.confidence * 100)}% confident
          </p>
        </div>
      </div>
      {interactive && (
        <div className="flex gap-2">
          <Button size="sm" onClick={() => onAction({ type: "confirm_appliance", value: "yes" })}>
            Yes, that&apos;s it
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onAction({ type: "confirm_appliance", value: "no" })}
          >
            No
          </Button>
        </div>
      )}
    </section>
  );
}
