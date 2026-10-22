"use client";

import { ArrowUp, Paperclip } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { UploadError, uploadFile } from "@/lib/api/uploads";
import { ACCEPT, checkFiles, kindOf } from "@/lib/uploads/validate";

import { AttachmentChips, type PendingAttachment } from "./attachment-chips";

let nextKey = 0;

export function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  /** Resolves to true when the message was refused and its text should be restored. */
  onSend: (text: string, attachments: string[]) => Promise<boolean>;
}) {
  const [text, setText] = useState("");
  const [items, setItems] = useState<PendingAttachment[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const previews = useRef(new Set<string>());

  useEffect(() => {
    const urls = previews.current;
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  const uploading = items.some((item) => item.status === "uploading");
  const ready = items.filter((item) => item.status === "ready" && item.id);
  const canSend = !disabled && !uploading && (text.trim().length > 0 || ready.length > 0);

  function update(key: string, change: Partial<PendingAttachment>) {
    setItems((current) =>
      current.map((item) => (item.key === key ? { ...item, ...change } : item)),
    );
  }

  function release(item: PendingAttachment) {
    if (item.preview) {
      URL.revokeObjectURL(item.preview);
      previews.current.delete(item.preview);
    }
  }

  function remove(key: string) {
    const gone = items.find((item) => item.key === key);
    if (gone) release(gone);
    setItems((current) => current.filter((item) => item.key !== key));
  }

  function pick(files: File[]) {
    const { accepted, errors } = checkFiles(items, files);
    setProblems(errors);
    const added = accepted.map((file): PendingAttachment => {
      const kind = kindOf(file) ?? "image";
      const preview = kind === "image" ? URL.createObjectURL(file) : null;
      if (preview) previews.current.add(preview);
      return { key: `f${nextKey++}`, file, kind, preview, status: "uploading" };
    });
    setItems((current) => [...current, ...added]);
    for (const item of added) {
      uploadFile(item.file)
        .then((attachment) => update(item.key, { status: "ready", id: attachment.id }))
        .catch((error: unknown) =>
          update(item.key, {
            status: "error",
            error: error instanceof UploadError ? error.message : "Upload failed.",
          }),
        );
    }
  }

  async function submit() {
    if (!canSend) return;
    const sent = text.trim();
    const sentItems = items;
    setText("");
    setItems([]);
    setProblems([]);
    const refused = await onSend(
      sent,
      ready.map((item) => item.id as string),
    );
    if (refused) {
      setText(sent);
      setItems(sentItems);
    } else {
      sentItems.forEach(release);
    }
  }

  return (
    <form
      className="shrink-0 border-t bg-background p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <AttachmentChips items={items} onRemove={remove} />
      {problems.length > 0 && (
        <ul className="mx-auto mb-2 w-full max-w-3xl text-sm text-destructive" role="alert">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2">
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(event) => {
            pick(Array.from(event.target.files ?? []));
            event.target.value = ""; // picking the same file again still fires
          }}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon-lg"
          disabled={disabled}
          onClick={() => input.current?.click()}
          aria-label="Attach a photo or video"
        >
          <Paperclip />
        </Button>
        <Textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit();
            }
          }}
          placeholder="Describe the problem, or attach a photo…"
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
