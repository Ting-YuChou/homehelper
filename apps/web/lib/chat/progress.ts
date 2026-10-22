// Step progress for the side panel, built from stored messages and the in-flight turn. Pure, so
// it is unit tested without a browser.
import type {
  ConversationDetail,
  StepCard,
  StructuredAction,
} from "@/lib/api/types";

import type { PendingTurn } from "./turn";

export type StepProgress = { card: StepCard; result: string | null };

/** Plan item ids restart for every problem (ADR-007), so a step is keyed by its issue too. */
export function stepKey(card: StepCard): string {
  return `${card.issue_id ?? ""}:${card.plan_item_id}`;
}

/** The steps shown so far, each with the result the user reported for it. */
export function stepProgress(
  conversation: ConversationDetail | undefined,
  turn: PendingTurn | undefined,
): StepProgress[] {
  const steps = new Map<string, StepProgress>();
  let last: StepProgress | null = null;
  const record = (
    cards: { type: string }[],
    action: StructuredAction | null | undefined,
  ) => {
    if (action?.type === "step_result" && last) last.result = action.value;
    for (const card of cards) {
      if (card.type === "step") {
        const step = card as StepCard;
        // A step shown again after going back to its problem keeps its place in the list.
        last = steps.get(stepKey(step)) ?? { card: step, result: null };
        steps.set(stepKey(step), last);
      }
    }
  };
  for (const message of conversation?.messages ?? [])
    record(message.cards, message.action);
  if (turn) {
    record([], turn.request.action);
    for (const draft of turn.drafts) record(draft.cards, null);
  }
  return [...steps.values()];
}
