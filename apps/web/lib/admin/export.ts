// The "export as regression case" form on /admin/review (spec §17.2, M7-02). The API suggests
// the checks from the annotation's issue types; the reviewer can change them before exporting.

import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type Outcome = NonNullable<Schemas["RegressionExportRequest"]["expected_outcomes"]>[number];
export type ExportRequest = Schemas["RegressionExportRequest"];

export const OUTCOMES: readonly Outcome[] = ["resolved", "escalated", "abandoned", "out_of_scope"];

export type ExportForm = {
  outcome: Outcome | "any";
  docId: string | null;
  forbidStepCards: boolean;
  oneStepPerReply: boolean;
  expectedBehavior: string;
  forbiddenText: string; // one phrase per line
  // Not editable here; kept as suggested.
  requiredCards: string[];
  forbiddenCards: string[];
};

type CaseChecks = {
  expected_outcomes?: Outcome[];
  expected_doc_id?: string | null;
  assertions?: {
    forbid_step_cards?: boolean;
    max_step_cards_per_reply?: number | null;
    expected_behavior?: string | null;
    forbidden_text?: string[];
    required_cards?: string[];
    forbidden_cards?: string[];
  };
};

export function formFromCase(exported: CaseChecks): ExportForm {
  const a = exported.assertions ?? {};
  return {
    outcome: exported.expected_outcomes?.[0] ?? "any",
    docId: exported.expected_doc_id ?? null,
    forbidStepCards: a.forbid_step_cards ?? false,
    oneStepPerReply: a.max_step_cards_per_reply === 1,
    expectedBehavior: a.expected_behavior ?? "",
    forbiddenText: (a.forbidden_text ?? []).join("\n"),
    requiredCards: a.required_cards ?? [],
    forbiddenCards: a.forbidden_cards ?? [],
  };
}

const lines = (text: string) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

export function exportBody(form: ExportForm): ExportRequest {
  return {
    expected_outcomes: form.outcome === "any" ? [] : [form.outcome],
    expected_doc_id: form.docId,
    assertions: {
      forbid_step_cards: form.forbidStepCards,
      max_step_cards_per_reply: form.oneStepPerReply ? 1 : null,
      expected_behavior: form.expectedBehavior.trim() || null,
      forbidden_text: lines(form.forbiddenText),
      required_cards: form.requiredCards,
      forbidden_cards: form.forbiddenCards,
    },
  };
}

/** Mirrors the API: a case must check something. */
export function hasChecks(form: ExportForm): boolean {
  return (
    form.outcome !== "any" ||
    form.docId !== null ||
    form.forbidStepCards ||
    form.oneStepPerReply ||
    form.expectedBehavior.trim() !== "" ||
    lines(form.forbiddenText).length > 0 ||
    form.requiredCards.length > 0 ||
    form.forbiddenCards.length > 0
  );
}
