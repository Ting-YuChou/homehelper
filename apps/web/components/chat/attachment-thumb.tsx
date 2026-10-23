"use client";

import { useQuery } from "@tanstack/react-query";
import { ImageOff } from "lucide-react";
import { useRef } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { adminAttachmentUrlQuery, attachmentUrlQuery } from "@/lib/api/queries";

/** A sent photo or video, read through its short-lived signed URL (spec §11.1). Reviewers fetch
 * the URL through the admin API (`admin`), since the attachment belongs to someone else. */
export function AttachmentThumb({ id, admin = false }: { id: string; admin?: boolean }) {
  const own = useQuery({ ...attachmentUrlQuery(id), enabled: !admin });
  const reviewed = useQuery({ ...adminAttachmentUrlQuery(id), enabled: admin });
  const { data, isError, refetch } = admin ? reviewed : own;
  // An expired URL (e.g. seeking a video after 15 minutes) gets one fresh URL per successful
  // load, not a loop when the file itself can't be shown.
  const renewed = useRef(false);
  const renew = () => {
    if (renewed.current) return;
    renewed.current = true;
    void refetch();
  };
  const loaded = () => {
    renewed.current = false;
  };
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
        onError={renew}
        onLoadedData={loaded}
        className="h-24 max-w-48 rounded-lg bg-black"
        aria-label="Attached video"
      />
    );
  }
  return (
    <a href={data.url} target="_blank" rel="noreferrer">
      {/* eslint-disable-next-line @next/next/no-img-element -- signed URL that expires; nothing to optimize */}
      <img
        src={data.url}
        alt="Attached photo"
        className="size-24 rounded-lg object-cover"
        onError={renew}
        onLoad={loaded}
      />
    </a>
  );
}
