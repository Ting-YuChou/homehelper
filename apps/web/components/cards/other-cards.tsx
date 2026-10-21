import { CalendarClock, ExternalLink, Package, PlayCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import type {
  BookingSlotsCard as BookingSlotsData,
  PartCard as PartCardData,
  StructuredAction,
  VideoCard as VideoCardData,
} from "@/lib/api/types";


// Parts, videos and booking come with the MCP servers (M5); these renderers keep the UI ready.

const slotFormat = new Intl.DateTimeFormat("en", {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

export function PartCard({ card }: { card: PartCardData }) {
  return (
    <section className="flex items-center gap-3 rounded-xl border p-3">
      <Package className="size-5 shrink-0 text-muted-foreground" aria-hidden />
      <span className="flex-1 text-sm">{card.name}</span>
      {card.price_usd != null && (
        <span className="text-sm font-medium">${card.price_usd.toFixed(2)}</span>
      )}
    </section>
  );
}

export function VideoCard({ card }: { card: VideoCardData }) {
  return (
    <a
      href={card.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3 rounded-xl border p-3 transition-colors hover:bg-muted"
    >
      <PlayCircle className="size-5 shrink-0 text-muted-foreground" aria-hidden />
      <span className="flex-1 text-sm">{card.title}</span>
      <ExternalLink className="size-4 text-muted-foreground" aria-hidden />
    </a>
  );
}

export function BookingSlotsCard({
  card,
  interactive,
  onAction,
}: {
  card: BookingSlotsData;
  interactive: boolean;
  onAction: (action: StructuredAction) => void;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border p-4">
      <h3 className="flex items-center gap-2 font-medium">
        <CalendarClock className="size-4" aria-hidden />
        Available technician visits
      </h3>
      <div className="flex flex-wrap gap-2">
        {card.slots.map((slot) => (
          <Button
            key={slot.slot_id}
            size="sm"
            variant="outline"
            disabled={!interactive}
            onClick={() => onAction({ type: "select_booking_slot", value: slot.slot_id })}
          >
            {slotFormat.format(new Date(slot.starts_at))} · {slot.technician}
          </Button>
        ))}
      </div>
    </section>
  );
}
