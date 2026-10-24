"use client";

import { useQuery } from "@tanstack/react-query";
import { BookOpen, Globe } from "lucide-react";

import { manualQuery } from "@/lib/api/queries";
import type { Citation, WebSource } from "@/lib/api/types";

/** Manual name + page; opens the PDF at that page in a new tab when the PDF is served
 * (spec §15.3). The public demo serves none (spec Q10), so there the chip is plain text. */
export function CitationChip({ citation }: { citation: Citation }) {
  const manual = useQuery(manualQuery(citation.doc_id));
  const title = manual.data?.title ?? citation.doc_id;
  const label = `${title}, p. ${citation.page}`;
  const className =
    "inline-flex max-w-full items-center gap-1.5 rounded-full border bg-background px-2.5 py-1 text-xs text-muted-foreground";
  const content = (
    <>
      <BookOpen className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">{title}</span>
      <span className="shrink-0 font-medium text-foreground">p. {citation.page}</span>
    </>
  );
  if (!manual.data?.url) {
    return (
      <span className={className} title={citation.section ? `${label} · ${citation.section}` : label}>
        {content}
      </span>
    );
  }
  return (
    <a
      href={`${manual.data.url}#page=${citation.page}`}
      target="_blank"
      rel="noopener noreferrer"
      title={citation.section ? `${label} · ${citation.section}` : label}
      aria-label={`Open ${label}`}
      className={`${className} transition-colors hover:bg-muted hover:text-foreground`}
    >
      {content}
    </a>
  );
}

export function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {citations.map((citation) => (
        <CitationChip key={citation.chunk_id} citation={citation} />
      ))}
    </div>
  );
}

/** An unofficial web page a step comes from (spec §10.6): its site, labelled as such, opening in
 * a new tab. */
export function WebSourceChip({ source }: { source: WebSource }) {
  const label = source.title ? `${source.title} (${source.domain})` : source.domain;
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer nofollow"
      title={label}
      aria-label={`Open unofficial source ${label}`}
      className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-dashed bg-background px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      <Globe className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">{source.domain}</span>
      <span className="shrink-0 font-medium text-amber-700 dark:text-amber-400">
        Unofficial source
      </span>
    </a>
  );
}

export function WebSourceList({ sources }: { sources: WebSource[] }) {
  if (sources.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {sources.map((source) => (
        <WebSourceChip key={source.url} source={source} />
      ))}
    </div>
  );
}
