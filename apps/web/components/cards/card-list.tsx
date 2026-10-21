"use client";

import type { Card, StructuredAction } from "@/lib/api/types";

export function CardList({
  cards,
}: {
  cards: Card[];
  interactive: boolean;
  onAction: (action: StructuredAction) => void;
}) {
  if (cards.length === 0) return null;
  return (
    <div className="flex flex-col gap-3">
      {cards.map((card, index) => (
        <div key={index} className="rounded-xl border p-4 text-sm">
          {card.type === "step" ? card.instruction : card.type}
        </div>
      ))}
    </div>
  );
}
