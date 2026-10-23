// Keeping /admin/review's list in step with annotations made on a conversation page. Plain
// lists are refetched; a random sample is updated in place instead, since refetching it would
// draw a new sample under the reviewer.

import type { QueryClient, QueryKey } from "@tanstack/react-query";

type Row = { id: string; annotation_count: number };
type Pages<R extends Row> = {
  pages: { items: R[]; next_before: string | null }[];
  pageParams: unknown[];
};

export function isReviewListKey(key: QueryKey): boolean {
  return key[0] === "admin" && key[1] === "conversations";
}

export function isSampleKey(key: QueryKey): boolean {
  const query = key[2] as { sample?: number } | undefined;
  return isReviewListKey(key) && query?.sample !== undefined;
}

export function bumpAnnotations<R extends Row, D extends Pages<R>>(
  data: D | undefined,
  conversationId: string,
  delta: number,
): D | undefined {
  if (!data) return data;
  return {
    ...data,
    pages: data.pages.map((page) => ({
      ...page,
      items: page.items.map((row) =>
        row.id === conversationId
          ? { ...row, annotation_count: Math.max(0, row.annotation_count + delta) }
          : row,
      ),
    })),
  };
}

/** After an annotation changed on `conversationId` (`delta`: +1 added, -1 deleted, 0 edited):
 * refresh that conversation and the plain lists, and update samples in place. */
export function refreshReview(queryClient: QueryClient, conversationId: string, delta: number) {
  void queryClient.invalidateQueries({ queryKey: ["admin", "conversation", conversationId] });
  void queryClient.invalidateQueries({
    predicate: (query) => isReviewListKey(query.queryKey) && !isSampleKey(query.queryKey),
  });
  if (delta !== 0) {
    queryClient.setQueriesData<Pages<Row>>(
      { predicate: (query) => isSampleKey(query.queryKey) },
      (data) => bumpAnnotations(data, conversationId, delta),
    );
  }
}
