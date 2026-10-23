"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Shuffle, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { OutcomeBadge } from "@/components/chat/outcome-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  OUTCOME_FILTERS,
  type ReviewFilters,
  SAMPLE_SIZE,
  filtersFromSearch,
  filtersToSearch,
  reviewQuery,
} from "@/lib/admin/filters";
import { formatCost } from "@/lib/admin/format";
import { adminConversationsQuery } from "@/lib/api/queries";
import type { AdminConversationRow } from "@/lib/api/types";

const ALL = "all"; // Radix Select items can't have an empty value
const OUTCOME_LABELS: Record<(typeof OUTCOME_FILTERS)[number], string> = {
  resolved: "Resolved",
  escalated: "Technician",
  abandoned: "Abandoned",
  out_of_scope: "Out of scope",
  open: "No outcome yet",
};

const dateTime = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

function FilterSelect<T extends string>({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: T | undefined;
  options: readonly { value: T; label: string }[];
  onChange: (value: T | undefined) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select
        value={value ?? ALL}
        onValueChange={(next) => onChange(next === ALL ? undefined : (next as T))}
      >
        <SelectTrigger id={id} className="w-40">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>Any</SelectItem>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function Row({ row, search }: { row: AdminConversationRow; search: string }) {
  return (
    <TableRow>
      <TableCell className="max-w-72">
        <Link
          href={`/admin/review/${row.id}${search ? `?${search}` : ""}`}
          className="block truncate font-medium underline-offset-4 hover:underline"
        >
          {row.title ?? "Untitled conversation"}
        </Link>
        <span className="font-mono text-xs text-muted-foreground">{row.id}</span>
      </TableCell>
      <TableCell>
        {row.user_is_demo ? (
          row.user_display_name
        ) : (
          <span className="text-muted-foreground">Guest</span>
        )}
      </TableCell>
      <TableCell className="font-mono text-xs">{row.release_id}</TableCell>
      <TableCell>
        <OutcomeBadge outcome={row.outcome} />
      </TableCell>
      <TableCell className="text-right tabular-nums">{row.message_count}</TableCell>
      <TableCell>
        <span className="flex items-center gap-2 tabular-nums">
          {row.up_count > 0 && (
            <span className="flex items-center gap-0.5" title="Thumbs up">
              <ThumbsUp className="size-3.5" aria-label="Thumbs up" /> {row.up_count}
            </span>
          )}
          {row.down_count > 0 && (
            <span className="flex items-center gap-0.5 text-destructive" title="Thumbs down">
              <ThumbsDown className="size-3.5" aria-label="Thumbs down" /> {row.down_count}
            </span>
          )}
        </span>
      </TableCell>
      <TableCell>
        {row.annotation_count > 0 && (
          <Badge variant="secondary">{row.annotation_count} annotated</Badge>
        )}
      </TableCell>
      <TableCell className="text-right tabular-nums">{formatCost(row.cost_usd)}</TableCell>
      <TableCell className="whitespace-nowrap text-muted-foreground">
        {dateTime.format(new Date(row.updated_at))}
      </TableCell>
    </TableRow>
  );
}

/** `/admin/review`: conversations to review, newest first or as a random sample. */
export function ReviewList() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const filters = filtersFromSearch(new URLSearchParams(searchParams.toString()));
  const search = filtersToSearch(filters);
  const [release, setRelease] = useState(filters.release ?? "");
  const conversations = useInfiniteQuery(adminConversationsQuery(reviewQuery(filters)));

  const apply = (next: ReviewFilters) => {
    const query = filtersToSearch(next);
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };
  const submitRelease = (event: FormEvent) => {
    event.preventDefault();
    apply({ ...filters, release });
  };
  const rows = conversations.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-tight">Review conversations</h1>
        <p className="text-sm text-muted-foreground">
          Annotate replies; incorrect ones can become regression cases.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <FilterSelect
          id="filter-outcome"
          label="Outcome"
          value={filters.outcome}
          options={OUTCOME_FILTERS.map((value) => ({ value, label: OUTCOME_LABELS[value] }))}
          onChange={(outcome) => apply({ ...filters, outcome })}
        />
        <FilterSelect
          id="filter-feedback"
          label="Feedback"
          value={filters.feedback}
          options={[
            { value: "down", label: "Thumbs down" },
            { value: "up", label: "Thumbs up" },
          ]}
          onChange={(feedback) => apply({ ...filters, feedback })}
        />
        <FilterSelect
          id="filter-annotated"
          label="Annotated"
          value={filters.annotated}
          options={[
            { value: "no", label: "Not yet" },
            { value: "yes", label: "Annotated" },
          ]}
          onChange={(annotated) => apply({ ...filters, annotated })}
        />
        <form className="flex flex-col gap-1.5" onSubmit={submitRelease}>
          <Label htmlFor="filter-release">Release</Label>
          <Input
            id="filter-release"
            className="w-40"
            placeholder="Any"
            value={release}
            onChange={(event) => setRelease(event.target.value)}
            onBlur={() =>
              release.trim() !== (filters.release ?? "") && apply({ ...filters, release })
            }
          />
        </form>
        <Button
          variant={filters.sample ? "default" : "outline"}
          onClick={() =>
            filters.sample ? void conversations.refetch() : apply({ ...filters, sample: true })
          }
        >
          <Shuffle data-icon="inline-start" aria-hidden />
          {filters.sample ? "New sample" : `Sample ${SAMPLE_SIZE}`}
        </Button>
        {filters.sample && (
          <Button variant="ghost" onClick={() => apply({ ...filters, sample: false })}>
            Show newest
          </Button>
        )}
      </div>

      {conversations.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : conversations.isError ? (
        <p className="text-sm text-destructive">Couldn&apos;t load conversations.</p>
      ) : rows.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">
          No conversations match these filters.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Conversation</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Release</TableHead>
                <TableHead>Outcome</TableHead>
                <TableHead className="text-right">Messages</TableHead>
                <TableHead>Feedback</TableHead>
                <TableHead>Review</TableHead>
                <TableHead className="text-right">Cost</TableHead>
                <TableHead>Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <Row key={row.id} row={row} search={search} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {conversations.hasNextPage && (
        <Button
          variant="outline"
          className="self-center"
          onClick={() => void conversations.fetchNextPage()}
          disabled={conversations.isFetchingNextPage}
        >
          Load more
        </Button>
      )}
    </div>
  );
}
