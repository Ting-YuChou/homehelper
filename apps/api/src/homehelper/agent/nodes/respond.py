"""`respond` (M3-08): the responder writes the message for the current step.

Code decides what the message must do (`ResponsePlan`): ask for one missing detail, present one
plan item, answer from excerpts, or explain a handoff. The LLM only words it and cites excerpt
ids. A fixed template that replaces the response (hazards, scope) skips the LLM entirely.
"""

from dataclasses import dataclass, field
from typing import Any

from homehelper.agent import prompts
from homehelper.agent.deps import AgentDeps, presented_item, slot_values
from homehelper.agent.state import AgentState
from homehelper.agent.turn import MAX_TRANSCRIPT_LINES, AgentReply, GraphState
from homehelper.knowledge.schemas import RetrievedChunk
from homehelper.knowledge.web import format_for_responder
from homehelper.llm import Message

SLOT_QUESTIONS = {
    "appliance_category": "which appliance it is (for example a washer, dryer or refrigerator)",
    "symptom": "what problem they are seeing",
    "question": "what they would like to know",
}
HANDOFF_REASONS = {
    "hazard_detected": "there is a safety hazard",
    "max_failed_steps_reached": "the steps from the manual have not fixed it",
    "plan_exhausted": "the steps from the manual have not fixed it",
    "plan_unavailable": "the manual does not cover this problem",
    "user_requested_technician": "the user asked for a technician",
}
RESULT_TEXT = {
    "fixed": "it fixed the problem",
    "not_fixed": "they tried it and it did not help",
    "cannot_do": "they could not do it",
}
BOOKING_NOTE = (
    "Booking a technician is not available in this chat yet, so suggest contacting the "
    "manufacturer's service or a qualified local technician."
)


@dataclass
class ResponsePlan:
    task: str
    excerpts: list[RetrievedChunk] = field(default_factory=list)
    plan_item: dict[str, object] | None = None
    cite: bool = False  # whether the LLM check for grounding applies

    @property
    def citable_ids(self) -> set[str]:
        return {chunk.chunk_id for chunk in self.excerpts}


def _handoff_reason(state: AgentState) -> str:
    for decision in reversed(state.decision_log):
        if decision.to_step == state.step_id and decision.predicate in HANDOFF_REASONS:
            return HANDOFF_REASONS[decision.predicate]
    return "a professional is the safest next step"


def response_plan(graph: GraphState, deps: AgentDeps) -> ResponsePlan:
    state = graph.state
    turn = graph.turn
    retrieved = list(turn.retrieval.chunks) if turn.retrieval else []
    if turn.side_question:
        return ResponsePlan(
            task=(
                "Answer the user's question from the manual excerpts, then remind them of the "
                "step they were trying and ask how it went."
            ),
            excerpts=retrieved,
            cite=True,
        )
    journey = deps.journey(state)
    step = deps.step(state)
    if journey is None or step is None:
        return ResponsePlan(
            task=(
                "Reply to the user briefly, then ask which appliance problem or question you "
                "can help with."
            )
        )
    match step.type:
        case "collect":
            missing = [name for name in journey.required_slots() if name not in state.slots]
            wanted = SLOT_QUESTIONS.get(missing[0], missing[0]) if missing else "any detail"
            return ResponsePlan(task=f"Acknowledge what the user said and ask only {wanted}.")
        case "confirm":
            pending = [n for n, s in state.slots.items() if not s.confirmed and s.confidence < 0.8]
            details = ", ".join(f"{n}={state.slots[n].value}" for n in pending)
            return ResponsePlan(task=f"Ask the user to confirm these details: {details}.")
        case "guide":
            item = presented_item(state)
            if item is None:
                return ResponsePlan(task="Ask the user how it is going.")
            cited = set(item.citation_ids)
            return ResponsePlan(
                task="Present the next troubleshooting step.",
                excerpts=[chunk for chunk in retrieved if chunk.chunk_id in cited],
                plan_item={
                    "index": state.plan.index(item) + 1,
                    "total": len(state.plan),
                    "instruction": item.instruction,
                    "warranty_warning": item.warranty_warning,
                    "safety_rule": item.safety_rule,
                },
                cite=True,
            )
        case "inform":
            return ResponsePlan(
                task=(
                    "Answer the user's question from the manual excerpts. If they do not "
                    "answer it, say the manual does not cover it. End by asking whether that "
                    "helps."
                ),
                excerpts=retrieved,
                cite=True,
            )
        case "handoff":
            return ResponsePlan(
                task=(
                    "Explain briefly that a professional technician is the best next step "
                    f"because {_handoff_reason(state)}. {BOOKING_NOTE}"
                )
            )
        case _:  # end
            if state.outcome == "resolved":
                return ResponsePlan(
                    task="The problem is solved. Close warmly and offer help with anything else."
                )
            return ResponsePlan(task="Close the conversation politely.")


def _previous_result(graph: GraphState) -> str | None:
    message = graph.turn.message
    if message is not None and message.action is not None and message.action.type == "step_result":
        return RESULT_TEXT.get(message.action.value)
    nlu = graph.turn.nlu
    if nlu is not None and nlu.step_feedback in RESULT_TEXT:
        return RESULT_TEXT[nlu.step_feedback]
    return None


def user_text(graph: GraphState) -> str:
    message = graph.turn.message
    assert message is not None
    if message.action is not None:
        return f"[pressed {message.action.type}: {message.action.value}]"
    return message.text or ""


def respond_messages(graph: GraphState, deps: AgentDeps, plan: ResponsePlan) -> list[Message]:
    turn = graph.turn
    journey = deps.journey(graph.state)
    prefix = " ".join(r.text for r in turn.fixed_replies if not r.replaces_response) or None
    web = turn.retrieval.web_findings if turn.retrieval and plan.cite else []
    prompt = prompts.render(
        "respond",
        task=plan.task,
        journey_goal=journey.goal if journey else None,
        slots=slot_values(graph.state),
        plan_item=plan.plan_item,
        previous_result=_previous_result(graph),
        excerpts=[
            {
                "id": chunk.chunk_id,
                "manual": chunk.metadata.doc_id,
                "page": chunk.metadata.page_start,
                "text": chunk.text,
            }
            for chunk in plan.excerpts
        ],
        web_block=format_for_responder(web) if web else "",
        notices=turn.notices,
        prefix=prefix,
        feedback=turn.verdict.reasons if turn.verdict and turn.verdict.action == "revise" else [],
        transcript=graph.transcript[-MAX_TRANSCRIPT_LINES:],
        user_text=user_text(graph),
    )
    return [Message(role="user", content=prompt)]


async def respond(graph: GraphState, deps: AgentDeps) -> dict[str, Any]:
    turn = graph.turn
    if any(reply.replaces_response for reply in turn.fixed_replies):
        return {}
    plan = response_plan(graph, deps)
    reply = await deps.llm.structured("responder", respond_messages(graph, deps, plan), AgentReply)
    revisions = turn.revisions + (1 if turn.reply is not None else 0)
    return {"turn": turn.model_copy(update={"reply": reply, "revisions": revisions})}
