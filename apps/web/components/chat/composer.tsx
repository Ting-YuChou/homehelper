"use client";

import { ArrowUp } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  /** Resolves to true when the message was refused and its text should be restored. */
  onSend: (text: string) => Promise<boolean>;
}) {
  const [text, setText] = useState("");
  const canSend = !disabled && text.trim().length > 0;

  async function submit() {
    if (!canSend) return;
    const sent = text.trim();
    setText("");
    if (await onSend(sent)) setText(sent);
  }

  return (
    <form
      className="shrink-0 border-t bg-background p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2">
        <Textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit();
            }
          }}
          placeholder="Describe the problem…"
          aria-label="Message"
          rows={1}
          maxLength={4000}
          className="max-h-40 min-h-10 resize-none"
        />
        <Button type="submit" size="icon-lg" disabled={!canSend} aria-label="Send">
          <ArrowUp />
        </Button>
      </div>
    </form>
  );
}
