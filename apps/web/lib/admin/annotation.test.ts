import { describe, expect, it } from "vitest";

import {
  ISSUE_TYPES,
  annotationBody,
  annotationError,
  draftFrom,
  emptyDraft,
  issueLabel,
} from "./annotation";

describe("annotation drafts", () => {
  it("lists the spec's eight issue types with labels", () => {
    expect(ISSUE_TYPES).toEqual([
      "wrong_diagnosis",
      "unsafe",
      "hallucination",
      "wrong_manual",
      "too_many_steps_at_once",
      "tone",
      "missed_escalation",
      "other",
    ]);
    expect(issueLabel("too_many_steps_at_once")).toBe("Too many steps at once");
  });

  it("follows the server's rules", () => {
    expect(annotationError(emptyDraft())).toBe("Pick a verdict.");
    expect(annotationError({ ...emptyDraft(), verdict: "incorrect" })).toBe(
      "Pick at least one issue type.",
    );
    expect(annotationError({ ...emptyDraft(), verdict: "correct", issueTypes: ["tone"] })).toBe(
      "A correct reply has no issue types.",
    );
    expect(annotationError({ ...emptyDraft(), verdict: "correct" })).toBeNull();
    expect(
      annotationError({
        ...emptyDraft(),
        verdict: "incorrect",
        issueTypes: ["tone"],
        notes: "x".repeat(4001),
      }),
    ).toBe("Notes are too long (4000 characters at most).");
  });

  it("builds the request body: trimmed text, blank as null, issues in spec order", () => {
    expect(
      annotationBody({
        verdict: "incorrect",
        issueTypes: ["tone", "unsafe"],
        expectedResponse: "  Refer to a technician. ",
        notes: "   ",
      }),
    ).toEqual({
      verdict: "incorrect",
      issue_types: ["unsafe", "tone"],
      expected_response: "Refer to a technician.",
      notes: null,
    });
  });

  it("starts an edit from a saved annotation", () => {
    expect(
      draftFrom({
        verdict: "incorrect",
        issue_types: ["tone"],
        expected_response: null,
        notes: "Curt",
      }),
    ).toEqual({ verdict: "incorrect", issueTypes: ["tone"], expectedResponse: "", notes: "Curt" });
  });
});
