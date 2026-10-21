"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { ApiError, api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries";
import { streamMessage } from "@/lib/api/stream";
import type {
  Conversation,
  ConversationDetail,
  ErrorEvent,
  SendMessageBody,
} from "@/lib/api/types";
import { applyEvent, finishTurn, type PendingTurn, startTurn } from "@/lib/chat/turn";

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  const copy = { ...record };
  delete copy[key];
  return copy;
}

function creationError(error: unknown): ErrorEvent {
  if (error instanceof ApiError && error.status === 401) {
    return { type: "error", code: "unauthorized", message: "Your session ended. Sign in again." };
  }
  return {
    type: "error",
    code: "network_error",
    message: "Couldn't start a conversation. Please try again.",
  };
}

/** In-flight turns per conversation, kept above the routes so navigation doesn't cut a stream. */
export function useChatTurns() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [turns, setTurns] = useState<Record<string, PendingTurn>>({});
  const [errors, setErrors] = useState<Record<string, ErrorEvent>>({});
  // A conversation created by the first message keeps the "new" view mounted, so the composer
  // (and a refused message's text) survive the /chat → /chat/{id} change.
  const [adopted, setAdopted] = useState<string | null>(null);

  const update = useCallback((id: string, change: (turn: PendingTurn) => PendingTurn) => {
    setTurns((all) => (all[id] ? { ...all, [id]: change(all[id]) } : all));
  }, []);

  /** Send a message (creating the conversation first if needed); resolves with the turn's error. */
  const send = useCallback(
    async (conversationId: string | null, body: SendMessageBody): Promise<ErrorEvent | null> => {
      let id = conversationId;
      if (id === null) {
        let created: Conversation;
        try {
          created = await unwrap(api.POST("/v1/conversations", { body: {} }));
        } catch (error) {
          const event = creationError(error);
          toast.error(event.message);
          return event;
        }
        id = created.id;
        queryClient.setQueryData(queryKeys.conversation(id), { ...created, messages: [] });
        setAdopted(id);
        router.replace(`/chat/${id}`);
      }
      const conversation = id;
      const baseCount =
        queryClient.getQueryData<ConversationDetail>(queryKeys.conversation(conversation))
          ?.messages.length ?? 0;
      const result: { error: ErrorEvent | null } = { error: null };
      setErrors((all) => without(all, conversation));
      setTurns((all) => ({ ...all, [conversation]: startTurn(body, baseCount) }));
      try {
        await streamMessage(conversation, body, (event) => {
          if (event.type === "error") result.error = event;
          update(conversation, (turn) => applyEvent(turn, event));
        });
      } catch {
        // streamMessage already reported the failure as an error event.
      }
      update(conversation, finishTurn);
      // Swap the streamed drafts for the stored messages (real ids, feedback state).
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.conversation(conversation) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
      ]);
      setTurns((all) => without(all, conversation));
      const { error } = result;
      if (error) setErrors((all) => ({ ...all, [conversation]: error }));
      return error;
    },
    [queryClient, router, update],
  );

  return { turns, errors, adopted, send };
}
