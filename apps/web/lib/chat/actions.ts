import type { StructuredAction } from "@/lib/api/types";

const STEP_RESULTS: Record<string, string> = {
  fixed: "That fixed it",
  not_fixed: "Didn't help",
  cannot_do: "I can't do this step",
};

/** How a card button press reads in the transcript (the user message has no text). */
export function actionLabel(action: StructuredAction): string {
  switch (action.type) {
    case "step_result":
      return STEP_RESULTS[action.value] ?? action.value;
    case "confirm_appliance":
      return action.value === "yes" ? "Yes, that's my appliance" : "No, that's not it";
    case "select_booking_slot":
      return "Book this time slot";
    case "resume_issue":
      return "Let's go back to that problem";
    case "close_issue":
      return "Close that problem";
  }
}

export const STEP_BUTTONS = [
  { value: "fixed", label: "Fixed it" },
  { value: "not_fixed", label: "Didn't help" },
  { value: "cannot_do", label: "Can't do this" },
] as const;
