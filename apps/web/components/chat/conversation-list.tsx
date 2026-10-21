"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut, MessageSquarePlus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api, unwrap } from "@/lib/api/client";
import { conversationsQuery, queryKeys } from "@/lib/api/queries";
import type { User } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { OutcomeBadge } from "./outcome-badge";

const timeFormat = new Intl.DateTimeFormat("en", { month: "short", day: "numeric" });

export function ConversationList({
  user,
  activeId,
  onNavigate,
}: {
  user: User;
  activeId: string | null;
  onNavigate: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const conversations = useQuery(conversationsQuery);

  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/v1/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
      if (id === activeId) router.push("/chat");
    },
    onError: () => toast.error("Couldn't delete the conversation."),
  });
  const logout = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/auth/logout")),
    onSuccess: () => {
      queryClient.clear();
      router.replace("/login");
    },
  });

  return (
    <div className="flex h-full w-full flex-col">
      <div className="p-3">
        <Button asChild variant="outline" className="w-full justify-start">
          <Link href="/chat" onClick={onNavigate}>
            <MessageSquarePlus data-icon="inline-start" aria-hidden />
            New conversation
          </Link>
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1 px-2">
        <nav aria-label="Conversations" className="flex flex-col gap-0.5 pb-2">
          {conversations.data?.length === 0 && (
            <p className="px-2 py-4 text-sm text-muted-foreground">No conversations yet.</p>
          )}
          {conversations.data?.map((conversation) => (
            <div
              key={conversation.id}
              className={cn(
                "group flex items-center gap-1 rounded-lg pr-1 hover:bg-muted",
                conversation.id === activeId && "bg-muted",
              )}
            >
              <Link
                href={`/chat/${conversation.id}`}
                onClick={onNavigate}
                aria-current={conversation.id === activeId ? "page" : undefined}
                className="flex min-w-0 flex-1 flex-col gap-1 px-2 py-2"
              >
                <span className="truncate text-sm">
                  {conversation.title ?? "New conversation"}
                </span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  {timeFormat.format(new Date(conversation.updated_at))}
                  <OutcomeBadge outcome={conversation.outcome} />
                </span>
              </Link>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Delete conversation"
                className="opacity-60 group-hover:opacity-100 focus-visible:opacity-100"
                disabled={remove.isPending}
                onClick={() => {
                  if (window.confirm("Delete this conversation?")) remove.mutate(conversation.id);
                }}
              >
                <Trash2 />
              </Button>
            </div>
          ))}
        </nav>
      </ScrollArea>
      <div className="flex items-center gap-2 border-t p-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-medium">
          {user.display_name.slice(0, 1)}
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium">{user.display_name}</span>
          {!user.is_demo && <Badge variant="secondary">Guest</Badge>}
        </span>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Switch user"
          onClick={() => logout.mutate()}
        >
          <LogOut />
        </Button>
      </div>
    </div>
  );
}
