"use client";

import { LoaderCircle } from "lucide-react";
import Markdown from "react-markdown";

import { CardList } from "@/components/cards/card-list";
import type { Card, Citation, Message, StructuredAction } from "@/lib/api/types";
import { actionLabel } from "@/lib/chat/actions";

type AssistantContent = Pick<Message, "id" | "content"> & {
  cards: Card[];
  citations: Citation[];
  feedback?: Message["feedback"];
};

export function UserMessage({ text, action }: { text: string; action: StructuredAction | null }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2 text-primary-foreground">
        {text || (action ? <span className="italic">{actionLabel(action)}</span> : null)}
      </div>
    </div>
  );
}

export function AssistantMessage({
  message,
  interactive,
  onAction,
  streaming = false,
}: {
  message: AssistantContent;
  interactive: boolean;
  onAction: (action: StructuredAction) => void;
  streaming?: boolean;
}) {
  return (
    <article className="flex flex-col gap-3" aria-busy={streaming}>
      {message.content && (
        <div className="prose-chat max-w-none text-[15px] leading-relaxed">
          <Markdown>{message.content}</Markdown>
        </div>
      )}
      <CardList cards={message.cards} interactive={interactive} onAction={onAction} />
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
