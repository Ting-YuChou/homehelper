"use client";

import type { UseQueryResult } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import type {
  ConversationDetail,
  ErrorEvent,
  SendMessageBody,
  StructuredAction,
} from "@/lib/api/types";
import type { PendingTurn } from "@/lib/chat/turn";

import { Composer } from "./composer";
import { AssistantMessage, StatusLine, UserMessage } from "./message";

const SUGGESTIONS = [
  "My dishwasher won't start",
  "The washer shows an OE error",
  "My fridge isn't cooling",
];
// Refusals where the message was never processed, so its text goes back into the composer.
const RETRYABLE = new Set(["rate_limited", "maintenance", "conversation_busy", "network_error"]);

export function ConversationView({
  conversationId,
  conversation,
  turn,
  error,
  onSend,
}: {
  conversationId: string | null;
  conversation: UseQueryResult<ConversationDetail>;
  turn: PendingTurn | undefined;
  error: ErrorEvent | undefined;
  onSend: (body: SendMessageBody) => Promise<ErrorEvent | null>;
}) {
  const bottom = useRef<HTMLDivElement>(null);
  const messages = conversation.data?.messages ?? [];
  const busy = turn !== undefined;
  // Card buttons work on the latest assistant message only, and not while a turn runs.
  const lastAssistantId = busy
    ? null
    : messages.findLast((message) => message.role === "assistant")?.id;

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length, turn]);

  const sendAction = (action: StructuredAction) => void onSend({ action });
  const sendText = async (text: string) => {
    const result = await onSend({ text });
    return result !== null && RETRYABLE.has(result.code);
  };

  if (conversation.error instanceof ApiError && conversation.error.status === 404) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="text-muted-foreground">This conversation doesn&apos;t exist anymore.</p>
        <Button asChild variant="outline">
          <Link href="/chat">Start a new one</Link>
        </Button>
      </div>
    );
  }

  const empty = conversationId === null || (conversation.isSuccess && messages.length === 0);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
          {conversation.isPending && conversationId !== null && (
            <Skeleton className="h-20 w-2/3" />
          )}
          {empty && !busy && (
            <div className="flex flex-col gap-4 py-10">
              <h1 className="text-2xl font-semibold tracking-tight">What&apos;s going on?</h1>
              <p className="text-muted-foreground">
                Tell me which appliance is acting up and what it&apos;s doing. I&apos;ll walk you
                through the fix step by step, straight from the manual.
              </p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((suggestion) => (
                  <Button
                    key={suggestion}
                    variant="outline"
                    size="sm"
                    onClick={() => void sendText(suggestion)}
                  >
                    {suggestion}
                  </Button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message) =>
            message.role === "user" ? (
              <UserMessage key={message.id} text={message.content} action={message.action} />
            ) : (
              <AssistantMessage
                key={message.id}
                message={message}
                interactive={message.id === lastAssistantId}
                onAction={sendAction}
              />
            ),
          )}
          {turn && (
            <>
              <UserMessage text={turn.request.text ?? ""} action={turn.request.action ?? null} />
              {turn.drafts.map((draft) => (
                <AssistantMessage
                  key={draft.id}
                  message={{ ...draft, content: draft.text }}
                  interactive={false}
                  onAction={sendAction}
                  streaming={!draft.completed}
                />
              ))}
              {!turn.done && !turn.error && (
                <StatusLine label={turn.status?.label ?? "Thinking…"} />
              )}
            </>
          )}
          {error && !busy && (
            <Alert variant="destructive">
              <CircleAlert />
              <AlertDescription>{error.message}</AlertDescription>
            </Alert>
          )}
          <div ref={bottom} />
        </div>
      </div>
      <Composer disabled={busy} onSend={sendText} />
    </div>
  );
}
