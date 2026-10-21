"use client";

import type { Card, StructuredAction } from "@/lib/api/types";

import { ApplianceConfirmCard } from "./appliance-confirm-card";
import { CitationChip } from "./citation-chip";
import { HandoffCard } from "./handoff-card";
import { BookingSlotsCard, PartCard, VideoCard } from "./other-cards";
import { SafetyBanner } from "./safety-banner";
import { StepCard } from "./step-card";

type CardProps = { interactive: boolean; onAction: (action: StructuredAction) => void };

function CardView({ card, ...props }: CardProps & { card: Card }) {
  switch (card.type) {
    case "step":
      return <StepCard card={card} {...props} />;
    case "citation":
      return <CitationChip citation={card.citation} />;
    case "safety":
      return <SafetyBanner card={card} />;
    case "appliance_confirm":
      return <ApplianceConfirmCard card={card} {...props} />;
    case "handoff":
      return <HandoffCard card={card} />;
    case "part":
      return <PartCard card={card} />;
    case "video":
      return <VideoCard card={card} />;
    case "booking_slots":
      return <BookingSlotsCard card={card} {...props} />;
  }
}

/** Safety banners come first, whatever order the agent sent them in. */
export function CardList({ cards, ...props }: CardProps & { cards: Card[] }) {
  if (cards.length === 0) return null;
  const ordered = [
    ...cards.filter((card) => card.type === "safety"),
    ...cards.filter((card) => card.type !== "safety"),
  ];
  return (
    <div className="flex flex-col gap-3">
      {ordered.map((card, index) => (
        <CardView key={index} card={card} {...props} />
      ))}
    </div>
  );
}
