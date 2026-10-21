"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries";
import type { ConversationDetail, Rating } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const REASONS = ["Wrong or unhelpful step", "Hard to follow", "Not safe", "Didn't fit my appliance"];

/** 👍/👎 on an assistant message (spec §13.2, M4-08). 👎 asks for a reason. */
export function FeedbackButtons({
  conversationId,
  messageId,
  rating,
}: {
  conversationId: string;
  messageId: string;
  rating: Rating | null | undefined;
}) {
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");

  const give = useMutation({
    mutationFn: (body: { rating: Rating; reason?: string }) =>
      unwrap(
        api.POST("/v1/messages/{message_id}/feedback", {
          params: { path: { message_id: messageId } },
          body,
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData<ConversationDetail>(
        queryKeys.conversation(conversationId),
        (conversation) =>
          conversation && {
            ...conversation,
            messages: conversation.messages.map((message) =>
              message.id === messageId ? { ...message, feedback: saved.rating } : message,
            ),
          },
      );
      setAsking(false);
      setReason("");
      toast.success("Thanks for the feedback!");
    },
    onError: () => toast.error("Couldn't save your feedback."),
  });

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Helpful"
          aria-pressed={rating === "up"}
          disabled={give.isPending}
          className={cn(rating === "up" && "text-emerald-600")}
          onClick={() => give.mutate({ rating: "up" })}
        >
          <ThumbsUp className={cn(rating === "up" && "fill-current")} />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Not helpful"
          aria-pressed={rating === "down"}
          aria-expanded={asking}
          disabled={give.isPending}
          className={cn(rating === "down" && "text-red-600")}
          onClick={() => setAsking((open) => !open)}
        >
          <ThumbsDown className={cn(rating === "down" && "fill-current")} />
        </Button>
      </div>
      {asking && (
        <form
          className="flex max-w-md flex-col gap-2 rounded-xl border p-3"
          onSubmit={(event) => {
            event.preventDefault();
            give.mutate({ rating: "down", reason: reason.trim() || undefined });
          }}
        >
          <span className="text-sm font-medium">What went wrong?</span>
          <div className="flex flex-wrap gap-1.5">
            {REASONS.map((preset) => (
              <Button
                key={preset}
                type="button"
                size="xs"
                variant={reason === preset ? "secondary" : "outline"}
                onClick={() => setReason(preset)}
              >
                {preset}
              </Button>
            ))}
          </div>
          <Textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Anything else? (optional)"
            aria-label="Feedback reason"
            maxLength={1000}
            rows={2}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" size="sm" variant="ghost" onClick={() => setAsking(false)}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={give.isPending}>
              Send feedback
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
