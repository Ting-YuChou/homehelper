"use client";

import { LoaderCircle } from "lucide-react";
import Markdown from "react-markdown";

import { CardList } from "@/components/cards/card-list";
import { CitationList } from "@/components/cards/citation-chip";
import type { Card, Citation, Message, StructuredAction } from "@/lib/api/types";
import { actionLabel } from "@/lib/chat/actions";

import { AttachmentThumb } from "./attachment-thumb";
import { FeedbackButtons } from "./feedback-buttons";

type AssistantContent = Pick<Message, "id" | "content"> & {
  cards: Card[];
  citations: Citation[];
  feedback?: Message["feedback"];
};

export function UserMessage({
  text,
  action,
  attachments = [],
  adminMedia = false,
}: {
  text: string;
  action: StructuredAction | null;
  attachments?: string[];
  /** Read the attachments through the admin API (review pages). */
  adminMedia?: boolean;
}) {
  const bubble = text || action;
  return (
    <div className="flex flex-col items-end gap-2">
      {attachments.length > 0 && (
        <div className="flex max-w-[85%] flex-wrap justify-end gap-2">
          {attachments.map((id) => (
            <AttachmentThumb key={id} id={id} admin={adminMedia} />
          ))}
        </div>
      )}
      {bubble && (
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2 text-primary-foreground">
          {text || (action ? <span className="italic">{actionLabel(action)}</span> : null)}
        </div>
      )}
    </div>
  );
}

export function AssistantMessage({
  message,
  interactive,
  onAction,
  streaming = false,
  conversationId,
}: {
  message: AssistantContent;
  interactive: boolean;
  onAction: (action: StructuredAction) => void;
  streaming?: boolean;
  /** Set for stored messages, which can take feedback; drafts can't yet. */
  conversationId?: string;
}) {
  // Sources not already shown on a card (step cards carry their own citations).
  const onCards = new Set(
    message.cards.flatMap((card) =>
      card.type === "step"
        ? (card.citations ?? []).map((c) => c.chunk_id)
        : card.type === "citation"
          ? [card.citation.chunk_id]
          : [],
    ),
  );
  const sources = message.citations.filter((citation) => !onCards.has(citation.chunk_id));
  return (
    <article className="flex flex-col gap-3" aria-busy={streaming}>
      {message.content && (
        <div className="prose-chat max-w-none text-[15px] leading-relaxed">
          <Markdown>{message.content}</Markdown>
        </div>
      )}
      <CardList cards={message.cards} interactive={interactive} onAction={onAction} />
      <CitationList citations={sources} />
      {conversationId && (
        <FeedbackButtons
          conversationId={conversationId}
          messageId={message.id}
          rating={message.feedback}
        />
      )}
    </article>
  );
}

export function StatusLine({ label }: { label: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
      <LoaderCircle className="size-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}
