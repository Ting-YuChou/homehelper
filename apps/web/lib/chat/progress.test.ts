import { describe, expect, it } from "vitest";

import type { ConversationDetail, Message, StepCard } from "@/lib/api/types";

import { stepProgress } from "./progress";

function step(
  issue_id: string,
  plan_item_id: string,
  instruction: string,
): StepCard {
  return {
    type: "step",
    issue_id,
    plan_item_id,
    index: 1,
    total: 2,
    instruction,
    warranty_warning: false,
  };
}

function message(cards: StepCard[], action: Message["action"] = null): Message {
  return { cards, action } as unknown as Message;
}

describe("stepProgress", () => {
  it("keeps steps of different problems apart and resumes in place", () => {
    const conversation = {
      messages: [
        message([step("iss_1", "p1", "Clean the filter.")]),
        message([], { type: "step_result", value: "not_fixed" }),
        message([step("iss_2", "p1", "Clean the lint screen.")]),
        message([], { type: "step_result", value: "fixed" }),
        message([], { type: "resume_issue", value: "iss_1" }),
        message([step("iss_1", "p1", "Clean the filter.")]),
      ],
    } as unknown as ConversationDetail;
    const steps = stepProgress(conversation, undefined);
    expect(
      steps.map((s) => [s.card.issue_id, s.card.instruction, s.result]),
    ).toEqual([
      ["iss_1", "Clean the filter.", "not_fixed"],
      ["iss_2", "Clean the lint screen.", "fixed"],
    ]);
  });
});
