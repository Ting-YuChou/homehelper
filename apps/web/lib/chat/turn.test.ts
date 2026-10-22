import { describe, expect, it } from "vitest";

import { readEvents } from "@/lib/api/stream";
import type { AgentEvent } from "@/lib/api/types";

import { actionLabel } from "./actions";
import { applyEvent, finishTurn, startTurn, restoresComposer } from "./turn";

const step = {
  type: "step" as const,
  plan_item_id: "p1",
  index: 1,
  total: 3,
  instruction: "Check the door latch.",
  citations: [],
  actions: ["fixed" as const, "not_fixed" as const, "cannot_do" as const],
  warranty_warning: false,
};

describe("applyEvent", () => {
  it("assembles a streamed assistant message", () => {
    const events: AgentEvent[] = [
      { type: "status", stage: "retrieving", label: "Checking the manual" },
      { type: "message.delta", message_id: "m1", text: "First, " },
      { type: "message.delta", message_id: "m1", text: "check the door." },
      { type: "card", message_id: "m1", card: step },
      {
        type: "message.completed",
        message_id: "m1",
        citations: [{ chunk_id: "c1", doc_id: "bosch-shx68t55", page: 12 }],
      },
    ];
    let turn = startTurn({ text: "Not starting" });
    turn = applyEvent(turn, events[0]);
    expect(turn.status?.label).toBe("Checking the manual");
    for (const event of events.slice(1)) turn = applyEvent(turn, event);

    expect(turn.status).toBeNull();
    expect(turn.drafts).toEqual([
      {
        id: "m1",
        text: "First, check the door.",
        cards: [step],
        citations: [{ chunk_id: "c1", doc_id: "bosch-shx68t55", page: 12 }],
        completed: true,
      },
    ]);
    expect(finishTurn(turn).done).toBe(true);
  });

  it("keeps messages apart and records errors", () => {
    let turn = startTurn({ text: "Hi" });
    turn = applyEvent(turn, { type: "message.delta", message_id: "a", text: "One" });
    turn = applyEvent(turn, { type: "message.delta", message_id: "b", text: "Two" });
    turn = applyEvent(turn, { type: "error", code: "rate_limited", message: "Slow down" });
    expect(turn.drafts.map((d) => d.text)).toEqual(["One", "Two"]);
    expect(turn.error?.code).toBe("rate_limited");
  });
});

describe("readEvents", () => {
  it("parses SSE chunks split anywhere and skips heartbeats", async () => {
    const wire =
      ': ping\n\nevent: status\ndata: {"type":"status","stage":"understanding","label":"Reading"}\n\n' +
      'event: message.delta\ndata: {"type":"message.delta","message_id":"m1","text":"Hi"}\n\n';
    const bytes = new TextEncoder().encode(wire);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let i = 0; i < bytes.length; i += 7) controller.enqueue(bytes.slice(i, i + 7));
        controller.close();
      },
    });
    const events: AgentEvent[] = [];
    await readEvents(body, (event) => events.push(event));
    expect(events.map((e) => e.type)).toEqual(["status", "message.delta"]);
  });
});

describe("actionLabel", () => {
  it("describes card button presses", () => {
    expect(actionLabel({ type: "step_result", value: "fixed" })).toBe("That fixed it");
    expect(actionLabel({ type: "confirm_appliance", value: "no" })).toBe("No, that's not it");
    expect(actionLabel({ type: "resume_issue", value: "iss_1" })).toBe(
      "Let's go back to that problem",
    );
  });
});

describe("restoresComposer", () => {
  it("gives back the message when it was refused before being processed", () => {
    for (const code of ["rate_limited", "conversation_busy", "network_error", "invalid_attachment"]) {
      expect(restoresComposer(code)).toBe(true);
    }
    expect(restoresComposer("agent_error")).toBe(false);
  });
});
