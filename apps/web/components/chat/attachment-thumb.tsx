"use client";

import { useQuery } from "@tanstack/react-query";
import { ImageOff } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { attachmentUrlQuery } from "@/lib/api/queries";

/** A sent photo or video, read through its short-lived signed URL (spec §11.1). */
export function AttachmentThumb({ id }: { id: string }) {
  const { data, isError } = useQuery(attachmentUrlQuery(id));
  if (isError) {
    return (
      <div
        className="flex size-24 items-center justify-center rounded-lg bg-muted text-muted-foreground"
        title="This attachment is no longer available"
      >
        <ImageOff className="size-5" aria-label="Attachment unavailable" />
      </div>
    );
  }
  if (!data) return <Skeleton className="size-24 rounded-lg" />;
  if (data.kind === "video") {
    return (
      <video
        src={data.url}
        controls
        preload="metadata"
        className="h-24 max-w-48 rounded-lg bg-black"
        aria-label="Attached video"
      />
    );
  }
  return (
    <a href={data.url} target="_blank" rel="noreferrer">
      {/* eslint-disable-next-line @next/next/no-img-element -- signed URL that expires; nothing to optimize */}
      <img src={data.url} alt="Attached photo" className="size-24 rounded-lg object-cover" />
    </a>
  );
}
