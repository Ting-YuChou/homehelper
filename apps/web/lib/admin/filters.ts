// Filters of /admin/review, kept in the URL so a filtered list can be shared and reloaded.

export const OUTCOME_FILTERS = [
  "resolved",
  "escalated",
  "abandoned",
  "out_of_scope",
  "open",
] as const;
export type OutcomeFilter = (typeof OUTCOME_FILTERS)[number];
export type FeedbackFilter = "up" | "down";
export type AnnotatedFilter = "yes" | "no";

export type ReviewFilters = {
  outcome?: OutcomeFilter;
  feedback?: FeedbackFilter;
  release?: string;
  annotated?: AnnotatedFilter;
  /** A random sample instead of the newest conversations (spec §17.2). */
  sample: boolean;
};

export const PAGE_SIZE = 50;
export const SAMPLE_SIZE = 20;

function oneOf<T extends string>(value: string | null, allowed: readonly T[]): T | undefined {
  return allowed.find((option) => option === value);
}

export function filtersFromSearch(search: URLSearchParams): ReviewFilters {
  const filters: ReviewFilters = { sample: search.get("sample") === "1" };
  const outcome = oneOf(search.get("outcome"), OUTCOME_FILTERS);
  const feedback = oneOf(search.get("feedback"), ["up", "down"] as const);
  const annotated = oneOf(search.get("annotated"), ["yes", "no"] as const);
  const release = search.get("release")?.trim();
  if (outcome) filters.outcome = outcome;
  if (feedback) filters.feedback = feedback;
  if (release) filters.release = release;
  if (annotated) filters.annotated = annotated;
  return filters;
}

export function filtersToSearch(filters: ReviewFilters): string {
  const search = new URLSearchParams();
  if (filters.outcome) search.set("outcome", filters.outcome);
  if (filters.feedback) search.set("feedback", filters.feedback);
  const release = filters.release?.trim();
  if (release) search.set("release", release);
  if (filters.annotated) search.set("annotated", filters.annotated);
  if (filters.sample) search.set("sample", "1");
  return search.toString();
}

export type ReviewQuery = {
  outcome?: OutcomeFilter;
  feedback?: FeedbackFilter;
  release_id?: string;
  annotated?: boolean;
  limit?: number;
  sample?: number;
};

/** Query parameters of `GET /v1/admin/conversations` (without the page cursor). */
export function reviewQuery(filters: ReviewFilters): ReviewQuery {
  const query: ReviewQuery = {};
  if (filters.outcome) query.outcome = filters.outcome;
  if (filters.feedback) query.feedback = filters.feedback;
  const release = filters.release?.trim();
  if (release) query.release_id = release;
  if (filters.annotated) query.annotated = filters.annotated === "yes";
  if (filters.sample) query.sample = SAMPLE_SIZE;
  else query.limit = PAGE_SIZE;
  return query;
}
