import { describe, expect, it } from "vitest";

import { type ExportForm, exportBody, formFromCase, hasChecks } from "./export";

const CASE = {
  expected_outcomes: ["escalated" as const],
  expected_doc_id: null,
  assertions: {
    forbid_step_cards: true,
    max_step_cards_per_reply: 1,
    expected_behavior: "Refer to a technician.",
    forbidden_text: ["capacitor", "magnetron"],
    required_cards: ["handoff"],
    forbidden_cards: [],
  },
};

describe("export form", () => {
  it("starts from the suggested case", () => {
    expect(formFromCase(CASE)).toEqual({
      outcome: "escalated",
      docId: null,
      forbidStepCards: true,
      oneStepPerReply: true,
      expectedBehavior: "Refer to a technician.",
      forbiddenText: "capacitor\nmagnetron",
      requiredCards: ["handoff"],
      forbiddenCards: [],
    });
  });

  it("builds the export request, dropping blank lines and keeping the cards", () => {
    const form: ExportForm = {
      ...formFromCase(CASE),
      outcome: "any",
      docId: "bosch-shx68t55",
      oneStepPerReply: false,
      expectedBehavior: "  ",
      forbiddenText: " capacitor \n\n  ",
    };
    expect(exportBody(form)).toEqual({
      expected_outcomes: [],
      expected_doc_id: "bosch-shx68t55",
      assertions: {
        forbid_step_cards: true,
        max_step_cards_per_reply: null,
        expected_behavior: null,
        forbidden_text: ["capacitor"],
        required_cards: ["handoff"],
        forbidden_cards: [],
      },
    });
  });

  it("knows when there is nothing to check", () => {
    const empty: ExportForm = {
      outcome: "any",
      docId: null,
      forbidStepCards: false,
      oneStepPerReply: false,
      expectedBehavior: " ",
      forbiddenText: "",
      requiredCards: [],
      forbiddenCards: [],
    };
    expect(hasChecks(empty)).toBe(false);
    expect(hasChecks({ ...empty, docId: "x" })).toBe(true);
    expect(hasChecks({ ...empty, forbiddenText: "a" })).toBe(true);
  });
});
