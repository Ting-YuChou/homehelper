"use client";

import { CircleCheck, CircleDashed, CircleX } from "lucide-react";

import type { ConversationDetail, StepCard, StructuredAction } from "@/lib/api/types";
import type { PendingTurn } from "@/lib/chat/turn";
import { cn } from "@/lib/utils";

import { OutcomeBadge } from "./outcome-badge";

type StepProgress = { card: StepCard; result: string | null };

/** The steps shown so far, each with the result the user reported for it. */
export function stepProgress(
  conversation: ConversationDetail | undefined,
  turn: PendingTurn | undefined,
): StepProgress[] {
  const steps = new Map<string, StepProgress>();
  let last: StepProgress | null = null;
  const record = (cards: { type: string }[], action: StructuredAction | null | undefined) => {
    if (action?.type === "step_result" && last) last.result = action.value;
    for (const card of cards) {
      if (card.type === "step") {
        last = { card: card as StepCard, result: null };
        steps.set(last.card.plan_item_id, last);
      }
    }
  };
  for (const message of conversation?.messages ?? []) record(message.cards, message.action);
  if (turn) {
    record([], turn.request.action);
    for (const draft of turn.drafts) record(draft.cards, null);
  }
  return [...steps.values()];
}

const JOURNEYS: Record<string, string> = {
  troubleshoot: "Troubleshooting",
  how_to_use: "How to use",
};

export function ProgressPanel({
  conversation,
  turn,
}: {
  conversation: ConversationDetail | undefined;
  turn: PendingTurn | undefined;
}) {
  const steps = stepProgress(conversation, turn);
  const journey = conversation?.active_journey;
  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium">
          {journey ? (JOURNEYS[journey] ?? journey) : "Progress"}
        </h2>
        <OutcomeBadge outcome={conversation?.outcome} />
      </div>
      {steps.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Steps from the manual show up here as we go.
        </p>
      ) : (
        <ol className="flex flex-col gap-3">
          {steps.map(({ card, result }) => {
            const Icon =
              result === "fixed" ? CircleCheck : result ? CircleX : CircleDashed;
            return (
              <li key={card.plan_item_id} className="flex gap-2 text-sm">
                <Icon
                  className={cn(
                    "mt-0.5 size-4 shrink-0",
                    result === "fixed" ? "text-emerald-600" : "text-muted-foreground",
                  )}
                  aria-hidden
                />
                <span className="flex flex-col gap-0.5">
                  <span className="text-xs text-muted-foreground">
                    Step {card.index} of {card.total}
                  </span>
                  <span className={cn(result && result !== "fixed" && "text-muted-foreground")}>
                    {card.instruction}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
