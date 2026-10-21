import type { Metadata } from "next";
import { Suspense } from "react";

import { ChatShell, ChatShellSkeleton } from "@/components/chat/chat-shell";

export const metadata: Metadata = { title: "Chat" };

// The shell lives in the layout so an in-flight turn keeps streaming when a new conversation's
// URL replaces /chat. The pages only select the conversation (via the route params).
export default function ChatLayout({ children }: LayoutProps<"/chat">) {
  return (
    <Suspense fallback={<ChatShellSkeleton />}>
      <ChatShell />
      {children}
    </Suspense>
  );
}
