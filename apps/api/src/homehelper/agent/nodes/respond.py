"""`respond` (M3-08): the responder writes the message for the current step.

Code decides what the message must do (`ResponsePlan`): ask for one missing detail, present one
plan item, answer from excerpts, or explain a handoff. The LLM only words it and cites excerpt
ids. A fixed template that replaces the response (hazards, scope) skips the LLM entirely.

At a step with `tools_allowed` (spec §7.3) the responder may first call those read tools, at
most `MAX_TOOL_CALLS` times; its reply is itself a `reply` tool call, so the output stays a
validated `AgentReply`. A revision reuses the results instead of calling the tools again.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from homehelper.agent import prompts
from homehelper.agent.deps import AgentDeps, presented_item, slot_values, step_position
from homehelper.agent.engine.issues import find_record
from homehelper.agent.engine.predicates import unconfirmed_low_confidence
from homehelper.agent.engine.transition import (
    NOTICE_REMIND_PAUSED,
    NOTICE_RESUME_PAUSED,
    NOTICE_RESUMED_ISSUE,
)
from homehelper.agent.guardrails import HAZARD_RULES
from homehelper.agent.nodes.mcp_actions import as_tool_call, booked, booking_fallback, tool_user
from homehelper.agent.state import AgentState
from homehelper.agent.tools import ToolOutcome, from_llm_name, without_user
from homehelper.agent.turn import MAX_TRANSCRIPT_LINES, AgentReply, GraphState
from homehelper.core.logging import get_logger
from homehelper.core.text import neutralize_tags
from homehelper.knowledge.schemas import RetrievedChunk, WebFinding
from homehelper.knowledge.web import format_for_responder
from homehelper.llm import LLMError, Message, ToolSpec

log = get_logger(__name__)

MAX_TOOL_CALLS = 3  # spec §7.3
BOOK_ACTION = "mcp:service_booking.book"
# Read tools for a side question asked during another journey (spec §7.4).
SIDE_TOOLS = {
    "my_appliances": [
        "mcp:user_profile.list_appliances",
        "mcp:user_profile.get_appliance",
        "mcp:user_profile.get_warranty_status",
        "mcp:user_profile.list_repair_history",
    ],
    "ask_parts": [
        "mcp:parts_catalog.search_parts",
        "mcp:parts_catalog.get_part",
        "mcp:tutorials.search_videos",
    ],
}
SIDE_TASKS = {
    "my_appliances": (
        "Answer the user's question about their appliances, warranty or repairs using the "
        "tools (if you cannot look it up, say they need to be signed in), then remind them of "
        "the step they were trying and ask how it went."
    ),
    "ask_parts": (
        "Suggest the parts, tools or videos that fit using the tools, then remind them of the "
        "step they were trying and ask how it went."
    ),
}
MAX_TOOL_RESULT_CHARS = 3000
REPLY_TOOL = ToolSpec(
    name="reply",
    description=(
        "Send your message to the user. Call this exactly once, when you are ready to answer."
    ),
    parameters=AgentReply.model_json_schema(),
)

SLOT_QUESTIONS = {
    "appliance_category": "which appliance it is (for example a washer, dryer or refrigerator)",
    "symptom": "what problem they are seeing",
    "question": "what they would like to know",
}
HANDOFF_REASONS = {
    "only_powered_steps_left": (
        "the remaining steps need the appliance switched on, which is not safe until it has "
        "been checked"
    ),
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
    "Booking a technician is not available for this appliance in this chat, so suggest "
    "contacting the manufacturer's service or a qualified local technician."
)
SLOTS_NOTE = (
    "The app shows a few technician visit times below your message; say the user can pick one "
    "to book it. Do not list the times yourself."
)


@dataclass
class ResponsePlan:
    task: str
    excerpts: list[RetrievedChunk] = field(default_factory=list)
    plan_item: dict[str, object] | None = None
    cite: bool = False  # whether the LLM check for grounding applies
    web: list[WebFinding] | None = None  # the step's web sources; None: all of the retrieval's

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
    side_intent = turn.nlu.intent if turn.nlu else None
    if turn.side_question and side_intent in SIDE_TASKS:
        return ResponsePlan(task=SIDE_TASKS[side_intent])
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
            pending = unconfirmed_low_confidence(state)
            details = ", ".join(f"{n}={state.slots[n].value}" for n in pending)
            return ResponsePlan(task=f"Ask the user to confirm these details: {details}.")
        case "guide":
            item = presented_item(state)
            if item is None:
                return ResponsePlan(task="Ask the user how it is going.")
            cited = set(item.citation_ids)
            findings = turn.retrieval.web_findings if turn.retrieval else []
            web = [f for f in findings if f.id in cited]
            index, total = step_position(state, item)
            return ResponsePlan(
                task="Present the next troubleshooting step.",
                excerpts=[chunk for chunk in retrieved if chunk.chunk_id in cited],
                plan_item={
                    "index": index,
                    "total": total,
                    "instruction": item.instruction,
                    "warranty_warning": item.warranty_warning,
                    "safety_rule": item.safety_rule,
                    "general": item.general,
                    "from_web": bool(web) and len(web) == len(cited),
                },
                cite=True,
                web=web,
            )
        case "inform" if turn.retrieval is None:
            # Answered from tools (profile, parts, videos), not from the manuals.
            return ResponsePlan(
                task=(
                    f"{step.goal} Use the tool results and tools. Mention only what they "
                    "return; if there is nothing, say so. End by asking whether that helps."
                )
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
            note = SLOTS_NOTE if state.offered_slots else BOOKING_NOTE
            return ResponsePlan(
                task=(
                    "Explain briefly that a professional technician is the best next step "
                    f"because {_handoff_reason(state)}. {note}"
                )
            )
        case _:  # end; `state.outcome` summarizes all issues, so read this step's own outcome
            booking = booked(turn.tool_results)
            if booking is not None and booking.ok:
                return ResponsePlan(
                    task=(
                        "The technician visit is booked; the app states the date, time and "
                        "technician right above your message. Close warmly."
                    )
                )
            message = turn.message
            picked = (
                message is not None
                and message.action is not None
                and (message.action.type == "select_booking_slot")
            )
            if booking is not None or (picked and BOOK_ACTION in step.actions):
                # The visit was not booked: the tool failed, or it could not run at all.
                return ResponsePlan(
                    task=(
                        "That visit time could not be booked (it may have just been taken). "
                        "Apologize briefly and suggest contacting the manufacturer's service "
                        "or a qualified local technician."
                    )
                )
            if step.outcome == "resolved":
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
    action = message.action
    if action is not None:
        record = find_record(graph.state, action.value)
        if action.type in ("resume_issue", "close_issue") and record is not None:
            verb = "go back to" if action.type == "resume_issue" else "close"
            return f"[pressed {verb}: {record.summary}]"
        return f"[pressed {action.type}: {action.value}]"
    marker = media_marker(graph)
    return "\n".join(part for part in (message.text or "", marker) if part)


def media_marker(graph: GraphState) -> str | None:
    """What the user's photos and videos were, in one code-built line for the transcript."""
    media = graph.turn.media
    if not media:
        return None
    photos = sum(o.kind == "image" for o in media)
    videos = len(media) - photos
    sent = ", ".join(
        f"{n} {noun}{'s' if n > 1 else ''}"
        for n, noun in ((photos, "photo"), (videos, "video"))
        if n
    )
    seen = next((o.vision for o in media if o.vision is not None), None)
    video = next((o.video for o in media if o.video is not None), None)
    if seen is None and video is None:
        return f"[sent {sent}; it couldn't be analyzed]"
    details: list[str] = []
    if seen is not None:
        identity = " ".join(v for v in (seen.brand, seen.category, seen.model_number) if v)
        if identity:
            details.append(f"photo shows {identity} (confidence {seen.confidence:.1f})")
        details.extend(seen.visible_issues)
        if seen.displayed_error_code:
            details.append(f"display shows {seen.displayed_error_code}")
    if video is not None:
        identity = " ".join(v for v in (video.brand, video.category) if v)
        if identity:
            details.append(f"video shows {identity} (confidence {video.confidence:.1f})")
        if video.symptom_description:
            details.append(video.symptom_description)
        details.extend(f"sound: {cue}" for cue in video.audio_cues)
        details.extend(f"display shows {code}" for code in video.visible_error_codes)
    if any(o.error for o in media):
        details.append("some of it couldn't be analyzed")
    return f"[sent {sent}: {'; '.join(details) or 'nothing recognizable'}]"


def open_issue_summaries(graph: GraphState) -> list[str]:
    """Paused issues the reply should mention (most recent first), or none."""
    notices = graph.turn.notices
    if NOTICE_RESUME_PAUSED not in notices and NOTICE_REMIND_PAUSED not in notices:
        return []
    return [paused.summary for paused in reversed(graph.state.paused_issues)]


def resumed_summary(graph: GraphState) -> str | None:
    state = graph.state
    if NOTICE_RESUMED_ISSUE not in graph.turn.notices or state.active_issue_id is None:
        return None
    record = find_record(state, state.active_issue_id)
    return record.summary if record else None


def tool_result_text(outcome: ToolOutcome) -> str:
    body: dict[str, Any] = {"tool": outcome.tool, "ok": outcome.ok}
    if outcome.ok:
        body["data"] = outcome.data
    else:
        body["error"] = outcome.error
    # Tool data can hold text from outside (video titles, notes the user typed): it never
    # passes through the prompt templates' `finalize` in a `tool` message, so neutralize it here.
    text = neutralize_tags(json.dumps(body, default=str))
    return text if len(text) <= MAX_TOOL_RESULT_CHARS else text[:MAX_TOOL_RESULT_CHARS] + "…"


def identified_manual(graph: GraphState, deps: AgentDeps) -> str | None:
    """The title of the one manual a rebuilt plan comes from, if it is one (ADR-013)."""
    basis = graph.state.plan_basis
    if deps.manuals is None or basis is None or basis.scope == "generic":
        return None
    entry = deps.manuals.entry(basis.doc_ids[0]) if basis.doc_ids else None
    return entry.title if entry else None


def step_tools(graph: GraphState, deps: AgentDeps) -> list[str]:
    """The read tools the responder may call this turn (the step's `tools_allowed`)."""
    if deps.tools is None:
        return []
    if graph.turn.side_question:
        intent = graph.turn.nlu.intent if graph.turn.nlu else None
        return SIDE_TOOLS.get(intent or "", [])
    step = deps.step(graph.state)
    return list(step.tools_allowed) if step is not None else []


def respond_messages(
    graph: GraphState, deps: AgentDeps, plan: ResponsePlan, *, tools_offered: bool = False
) -> list[Message]:
    turn = graph.turn
    journey = deps.journey(graph.state)
    prefix = " ".join(r.text for r in turn.fixed_replies if not r.replaces_response) or None
    power_off_first = any(
        r.rule_id == HAZARD_RULES["water_near_electric"] for r in turn.fixed_replies
    )
    if plan.web is not None:
        web = plan.web
    else:
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
        web_block=prompts.Trusted(format_for_responder(web)) if web else "",
        notices=turn.notices,
        prefix=prefix,
        power_off_first=power_off_first,
        open_issues=open_issue_summaries(graph),
        resumed_issue=resumed_summary(graph),
        tool_results=[tool_result_text(o) for o in turn.tool_results],
        tools_offered=tools_offered,
        model_hint=turn.model_hint is not None,
        identified_manual=identified_manual(graph, deps),
        feedback=turn.verdict.reasons if turn.verdict and turn.verdict.action == "revise" else [],
        transcript=graph.transcript[-MAX_TRANSCRIPT_LINES:],
        user_text=user_text(graph),
    )
    return [Message(role="user", content=prompt)]


async def tool_loop(
    deps: AgentDeps,
    messages: list[Message],
    tools: list[ToolSpec],
    allowed: list[str],
    user_id: str | None,
) -> tuple[AgentReply | None, list[ToolOutcome]]:
    """Let the responder call read tools, then reply. None if it never sent a valid reply."""
    assert deps.tools is not None
    history = list(messages)
    outcomes: list[ToolOutcome] = []
    # Tool calls are capped by count; the extra rounds give the model a chance to reply after it.
    for _ in range(MAX_TOOL_CALLS + 2):
        offered = [*tools, REPLY_TOOL] if len(outcomes) < MAX_TOOL_CALLS else [REPLY_TOOL]
        try:
            turn = await deps.llm.tool_turn("responder", history, offered)
        except LLMError as exc:
            # A provider that fails tool calling must not fail the turn: reply without tools.
            log.warning("responder_tool_turn_failed", error=str(exc))
            return None, outcomes
        final = next((c for c in turn.tool_calls if c.name == REPLY_TOOL.name), None)
        if final is not None:
            try:
                return AgentReply.model_validate(final.arguments), outcomes
            except ValidationError as exc:
                log.warning("responder_reply_invalid", errors=exc.error_count())
                return None, outcomes
        answers = []
        for call in turn.tool_calls:
            if len(outcomes) >= MAX_TOOL_CALLS:
                outcome = ToolOutcome(
                    tool=from_llm_name(call.name),
                    arguments=without_user(call.arguments),
                    ok=False,
                    error="tool call limit reached; reply now",
                )
            else:
                outcome = await deps.tools.call_llm(
                    call.name, call.arguments, allowed=allowed, user_id=user_id
                )
                outcomes.append(outcome)
            answers.append(
                Message(role="tool", content=tool_result_text(outcome), tool_call_id=call.id)
            )
        history.append(Message(role="assistant", content=turn.content, tool_calls=turn.tool_calls))
        history.extend(answers)
    return None, outcomes


async def respond(graph: GraphState, deps: AgentDeps) -> dict[str, Any]:
    try:
        return await _respond(graph, deps)
    except LLMError:
        fallback = booking_fallback(graph.turn)
        if fallback is None:
            raise
        log.warning("responder_failed_after_booking")
        return {"turn": fallback}


async def _respond(graph: GraphState, deps: AgentDeps) -> dict[str, Any]:
    turn = graph.turn
    if any(reply.replaces_response for reply in turn.fixed_replies):
        return {}
    plan = response_plan(graph, deps)
    revisions = turn.revisions + (1 if turn.reply is not None else 0)
    allowed = step_tools(graph, deps) if turn.reply is None else []  # revisions reuse results
    tools = (
        await deps.tools.llm_tools(allowed, user_id=tool_user(graph.state))
        if deps.tools is not None and allowed
        else []
    )
    update: dict[str, Any] = {}
    reply: AgentReply | None = None
    if tools:
        messages = respond_messages(graph, deps, plan, tools_offered=True)
        reply, outcomes = await tool_loop(deps, messages, tools, allowed, tool_user(graph.state))
        if outcomes:
            turn = turn.model_copy(update={"tool_results": [*turn.tool_results, *outcomes]})
            graph = graph.model_copy(update={"turn": turn})
            update["tool_calls"] = [
                *graph.tool_calls,
                *(as_tool_call(o, "llm", graph.state.active_issue_id) for o in outcomes),
            ]
    if reply is None:
        reply = await deps.llm.structured(
            "responder", respond_messages(graph, deps, plan), AgentReply
        )
    update["turn"] = turn.model_copy(update={"reply": reply, "revisions": revisions})
    return update
