"use client";

import { useQuery } from "@tanstack/react-query";
import { Menu } from "lucide-react";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { conversationQuery, meQuery } from "@/lib/api/queries";

import { ConversationList } from "./conversation-list";
import { ConversationView } from "./conversation-view";
import { ProgressPanel } from "./progress-panel";
import { useChatTurns } from "./use-chat-turns";

export function ChatShellSkeleton() {
  return (
    <div className="flex h-dvh">
      <div className="hidden w-72 border-r p-3 md:block">
        <Skeleton className="h-9 w-full" />
      </div>
      <div className="flex-1 p-6">
        <Skeleton className="h-24 w-full max-w-xl" />
      </div>
    </div>
  );
}

export function ChatShell() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useParams<{ id?: string }>();
  const conversationId = params.id ?? null;
  const me = useQuery(meQuery);
  const { turns, errors, adopted, send } = useChatTurns();
  const [menuOpen, setMenuOpen] = useState(false);
  const conversation = useQuery({
    ...conversationQuery(conversationId ?? ""),
    enabled: conversationId !== null && me.isSuccess,
  });

  const unauthorized = me.error instanceof ApiError && me.error.status === 401;
  useEffect(() => {
    if (unauthorized) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthorized, pathname, router]);

  if (!me.data) {
    return me.isError && !unauthorized ? (
      <div className="flex h-dvh items-center justify-center p-6 text-center text-muted-foreground">
        Can&apos;t reach the HomeHelper API right now. Please try again in a moment.
      </div>
    ) : (
      <ChatShellSkeleton />
    );
  }

  const turn = conversationId ? turns[conversationId] : undefined;
  const list = (
    <ConversationList
      user={me.data}
      activeId={conversationId}
      onNavigate={() => setMenuOpen(false)}
    />
  );

  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className="hidden w-72 shrink-0 border-r bg-muted/30 md:flex">{list}</aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b px-2 md:hidden">
          <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Open conversations">
                <Menu />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-72 p-0 pt-10">
              <SheetTitle className="sr-only">Conversations</SheetTitle>
              {list}
            </SheetContent>
          </Sheet>
          <span className="truncate text-sm font-medium">
            {conversation.data?.title ?? "New conversation"}
          </span>
        </header>
        <ConversationView
          key={conversationId === null || conversationId === adopted ? "new" : conversationId}
          conversationId={conversationId}
          conversation={conversation}
          turn={turn}
          error={conversationId ? errors[conversationId] : undefined}
          onSend={(body) => send(conversationId, body)}
        />
      </div>
      <aside className="hidden w-80 shrink-0 border-l lg:block">
        <ProgressPanel conversation={conversation.data} turn={turn} />
      </aside>
    </div>
  );
}
