"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";

import { AssistantMessage, UserMessage } from "@/components/chat/message";
import { OutcomeBadge } from "@/components/chat/outcome-badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCost, formatLatency } from "@/lib/admin/format";
import { ApiError } from "@/lib/api/client";
import { adminConversationQuery } from "@/lib/api/queries";
import type { AdminMessage } from "@/lib/api/types";

import { AnnotationPanel } from "./annotation-panel";

const noop = () => {};
const dateTime = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });

function ReplyMeta({ message }: { message: AdminMessage }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span>Latency {formatLatency(message.latency_ms)}</span>
      <span>Cost {formatCost(message.cost_usd)}</span>
      {message.feedback && (
        <span
          className={
            message.feedback === "down"
              ? "flex items-center gap-1 text-destructive"
              : "flex items-center gap-1"
          }
        >
          {message.feedback === "down" ? (
            <ThumbsDown className="size-3.5" aria-hidden />
          ) : (
            <ThumbsUp className="size-3.5" aria-hidden />
          )}
          {message.feedback === "down" ? "Thumbs down" : "Thumbs up"}
          {message.feedback_reason && `: “${message.feedback_reason}”`}
        </span>
      )}
      {message.trace_url ? (
        <a
          href={message.trace_url}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1 underline-offset-4 hover:underline"
        >
          Trace <ExternalLink className="size-3" aria-hidden />
        </a>
      ) : (
        message.trace_id && <span className="font-mono">trace {message.trace_id}</span>
      )}
    </div>
  );
}

/** `/admin/review/[id]`: one conversation, read-only, with annotations on every reply. */
export function ReviewDetail() {
  const { id } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const conversation = useQuery(adminConversationQuery(id));
  const back = searchParams.toString() ? `/admin/review?${searchParams}` : "/admin/review";

  if (conversation.isPending) return <Skeleton className="h-96 w-full" />;
  if (conversation.isError) {
    const missing = conversation.error instanceof ApiError && conversation.error.status === 404;
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        {missing ? "This conversation doesn't exist or was deleted." : "Couldn't load it."}
      </p>
    );
  }
  const detail = conversation.data;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Button asChild variant="ghost" size="sm" className="self-start">
          <Link href={back}>
            <ArrowLeft data-icon="inline-start" aria-hidden />
            All conversations
          </Link>
        </Button>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">
            {detail.title ?? "Untitled conversation"}
          </h1>
          <OutcomeBadge outcome={detail.outcome} />
        </div>
        <p className="text-sm text-muted-foreground">
          {detail.user_is_demo ? detail.user_display_name : "Guest"} · release{" "}
          <span className="font-mono">{detail.release_id}</span>
          {detail.active_journey && (
            <>
              {" "}
              · journey <span className="font-mono">{detail.active_journey}</span>
            </>
          )}{" "}
          · {dateTime.format(new Date(detail.created_at))}
        </p>
      </div>
      <ol className="flex max-w-3xl flex-col gap-6">
        {detail.messages.map((message) =>
          message.role === "user" ? (
            <li key={message.id}>
              <UserMessage
                text={message.content}
                action={message.action}
                attachments={(message.attachments ?? []).map((a) => a.id)}
                adminMedia
              />
            </li>
          ) : (
            <li key={message.id} className="flex flex-col gap-3">
              <AssistantMessage
                message={{ ...message, feedback: undefined }}
                interactive={false}
                onAction={noop}
              />
              <ReplyMeta message={message} />
              {message.role === "assistant" && (
                <AnnotationPanel
                  conversationId={detail.id}
                  messageId={message.id}
                  annotations={message.annotations ?? []}
                />
              )}
            </li>
          ),
        )}
      </ol>
    </div>
  );
}
