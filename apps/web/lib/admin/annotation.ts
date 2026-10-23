// Annotation drafts on /admin/review. The rules mirror `AnnotationFields` in the API so the form
// can explain a problem before the request is sent.

export const ISSUE_TYPES = [
  "wrong_diagnosis",
  "unsafe",
  "hallucination",
  "wrong_manual",
  "too_many_steps_at_once",
  "tone",
  "missed_escalation",
  "other",
] as const;
export type IssueType = (typeof ISSUE_TYPES)[number];
export type Verdict = "correct" | "incorrect";

const LABELS: Record<IssueType, string> = {
  wrong_diagnosis: "Wrong diagnosis",
  unsafe: "Unsafe",
  hallucination: "Hallucination",
  wrong_manual: "Wrong manual",
  too_many_steps_at_once: "Too many steps at once",
  tone: "Tone",
  missed_escalation: "Missed escalation",
  other: "Other",
};

const MAX_TEXT = 4000;

export function issueLabel(issue: IssueType): string {
  return LABELS[issue];
}

export type AnnotationDraft = {
  verdict: Verdict | null;
  issueTypes: IssueType[];
  expectedResponse: string;
  notes: string;
};

export function emptyDraft(): AnnotationDraft {
  return { verdict: null, issueTypes: [], expectedResponse: "", notes: "" };
}

export function draftFrom(annotation: {
  verdict: Verdict;
  issue_types: IssueType[];
  expected_response: string | null;
  notes: string | null;
}): AnnotationDraft {
  return {
    verdict: annotation.verdict,
    issueTypes: [...annotation.issue_types],
    expectedResponse: annotation.expected_response ?? "",
    notes: annotation.notes ?? "",
  };
}

export function annotationError(draft: AnnotationDraft): string | null {
  if (draft.verdict === null) return "Pick a verdict.";
  if (draft.verdict === "incorrect" && draft.issueTypes.length === 0) {
    return "Pick at least one issue type.";
  }
  if (draft.verdict === "correct" && draft.issueTypes.length > 0) {
    return "A correct reply has no issue types.";
  }
  if (draft.expectedResponse.length > MAX_TEXT) {
    return `The expected response is too long (${MAX_TEXT} characters at most).`;
  }
  if (draft.notes.length > MAX_TEXT) return `Notes are too long (${MAX_TEXT} characters at most).`;
  return null;
}

const blankToNull = (text: string) => text.trim() || null;

/** The body of `POST /v1/admin/annotations` (plus `message_id`) or `PUT .../{id}`. */
export function annotationBody(draft: AnnotationDraft & { verdict: Verdict }) {
  return {
    verdict: draft.verdict,
    issue_types: ISSUE_TYPES.filter((issue) => draft.issueTypes.includes(issue)),
    expected_response: blankToNull(draft.expectedResponse),
    notes: blankToNull(draft.notes),
  };
}
