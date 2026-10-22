"use client";

import { Film, LoaderCircle, TriangleAlert, X } from "lucide-react";

import type { MediaKind } from "@/lib/media/validate";

export type PendingAttachment = {
  key: string;
  file: File;
  kind: MediaKind;
  preview: string | null; // object URL for images the browser can show
  status: "uploading" | "ready" | "error";
  id?: string;
  error?: string;
};

/** Files picked in the composer: previews while they upload, with a remove button. */
export function AttachmentChips({
  items,
  onRemove,
}: {
  items: PendingAttachment[];
  onRemove: (key: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <ul className="mx-auto mb-2 flex w-full max-w-3xl flex-wrap gap-2" aria-label="Attachments">
      {items.map((item) => (
        <li key={item.key} className="relative">
          <div className="flex size-16 items-center justify-center overflow-hidden rounded-md border bg-muted">
            {item.kind === "image" && item.preview ? (
              // eslint-disable-next-line @next/next/no-img-element -- local object URL preview
              <img src={item.preview} alt={item.file.name} className="size-full object-cover" />
            ) : (
              <Film className="size-6 text-muted-foreground" aria-label={item.file.name} />
            )}
            {item.status === "uploading" && (
              <span className="absolute inset-0 flex items-center justify-center bg-background/60">
                <LoaderCircle className="size-5 animate-spin" aria-label="Uploading" />
              </span>
            )}
            {item.status === "error" && (
              <span
                className="absolute inset-0 flex items-center justify-center bg-destructive/20"
                title={item.error}
              >
                <TriangleAlert className="size-5 text-destructive" aria-label={item.error} />
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => onRemove(item.key)}
            className="absolute -top-2 -right-2 rounded-full border bg-background p-0.5 shadow-sm"
            aria-label={`Remove ${item.file.name}`}
          >
            <X className="size-3" />
          </button>
        </li>
      ))}
    </ul>
  );
}
