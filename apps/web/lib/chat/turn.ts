// The in-flight state of one turn, built from the SSE events (spec §13.3). Pure, so it is unit
// tested without a browser.
import type {
  AgentEvent,
  Card,
  Citation,
  ErrorEvent,
  SendMessageBody,
  StatusEvent,
} from "@/lib/api/types";

export type DraftMessage = {
  id: string;
  text: string;
  cards: Card[];
  citations: Citation[];
  completed: boolean;
};

export type PendingTurn = {
  request: SendMessageBody;
  /** Stored messages before this turn; later ones belong to it and are shown as drafts. */
  baseCount: number;
  status: StatusEvent | null;
  drafts: DraftMessage[];
  error: ErrorEvent | null;
  done: boolean;
};

export function startTurn(request: SendMessageBody, baseCount = 0): PendingTurn {
  return { request, baseCount, status: null, drafts: [], error: null, done: false };
}

function updateDraft(
  turn: PendingTurn,
  id: string,
  update: (draft: DraftMessage) => DraftMessage,
): PendingTurn {
  const existing = turn.drafts.find((draft) => draft.id === id);
  const draft = existing ?? { id, text: "", cards: [], citations: [], completed: false };
  const drafts = existing
    ? turn.drafts.map((d) => (d.id === id ? update(draft) : d))
    : [...turn.drafts, update(draft)];
  return { ...turn, drafts };
}

export function applyEvent(turn: PendingTurn, event: AgentEvent): PendingTurn {
  switch (event.type) {
    case "status":
      return { ...turn, status: event };
    case "message.delta":
      return updateDraft(turn, event.message_id, (d) => ({ ...d, text: d.text + event.text }));
    case "card":
      return updateDraft(turn, event.message_id, (d) => ({ ...d, cards: [...d.cards, event.card] }));
    case "message.completed":
      return {
        ...updateDraft(turn, event.message_id, (d) => ({
          ...d,
          citations: event.citations ?? [],
          completed: true,
        })),
        status: null,
      };
    case "error":
      return { ...turn, error: event, status: null };
  }
}

export function finishTurn(turn: PendingTurn): PendingTurn {
  return { ...turn, done: true, status: null };
}
