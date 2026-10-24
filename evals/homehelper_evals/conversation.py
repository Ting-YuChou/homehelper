"""Drive one conversation between a simulated user and an `AgentRuntime`."""

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from homehelper.agent.protocol import AgentRuntime
from homehelper.channels.events import (
    ApplianceConfirmCard,
    BookingSlotsCard,
    CardEvent,
    ErrorEvent,
    InboundMessage,
    IssuesCard,
    MessageCompletedEvent,
    MessageDeltaEvent,
    StructuredAction,
)
from homehelper.llm import LLMUsage
from homehelper_evals.cases import EvalCase, ScriptedTurn
from homehelper_evals.media import simulated_photo
from homehelper_evals.multi_issue import all_issues_opened, focus, runner_turn
from homehelper_evals.simulator import SimulatorTurn, UserSimulator
from homehelper_evals.transcript import (
    TERMINAL_OUTCOMES,
    AgentTurn,
    EndReason,
    Transcript,
    Turn,
    UserTurn,
)

_usage_bucket: ContextVar[list[LLMUsage] | None] = ContextVar("eval_usage_bucket", default=None)


class UsageRecorder:
    """LLM usage sink that attributes each call to the conversation running in the current
    asyncio task. Pass `recorder.sink` as `usage_sink` to every LLM client the run builds."""

    def __init__(self) -> None:
        self.all: list[LLMUsage] = []

    def sink(self, usage: LLMUsage) -> None:
        self.all.append(usage)
        bucket = _usage_bucket.get()
        if bucket is not None:
            bucket.append(usage)

    @contextmanager
    def collect(self) -> Iterator[list[LLMUsage]]:
        bucket: list[LLMUsage] = []
        token = _usage_bucket.set(bucket)
        try:
            yield bucket
        finally:
            _usage_bucket.reset(token)


def to_user_turn(
    turn: SimulatorTurn, last_agent: AgentTurn | None, case: EvalCase | None = None
) -> UserTurn | None:
    """Map a simulator turn to what the user sends. Button presses only count when the latest
    agent message actually offered that button, and photos when the case lets the user take
    them. Returns None when there is nothing to send."""
    action = None
    if last_agent is not None:
        if turn.step_result and last_agent.step_cards:
            action = StructuredAction(type="step_result", value=turn.step_result)
        elif turn.confirm_appliance and last_agent.cards_of(ApplianceConfirmCard):
            action = StructuredAction(type="confirm_appliance", value=turn.confirm_appliance)
        elif turn.booking_slot_id:
            offered = {
                slot.slot_id
                for card in last_agent.cards_of(BookingSlotsCard)
                for slot in card.slots
            }
            if turn.booking_slot_id in offered:
                action = StructuredAction(type="select_booking_slot", value=turn.booking_slot_id)
    text = turn.message.strip() or None
    # A photo goes with a button press too: the user answers the step and sends the sticker.
    photo = simulated_photo(case, turn.photo) if case is not None else None
    attachments = [photo] if photo else []
    if action is None and text is None and not attachments:
        return None
    return UserTurn(text=text, action=action, attachments=attachments)


# What a button press says, for a replay whose agent no longer offers that button.
_STEP_WORDS = {
    "fixed": "That fixed it.",
    "not_fixed": "Didn't help.",
    "cannot_do": "I can't do this step.",
}


def action_words(action: StructuredAction) -> str:
    match action.type:
        case "step_result":
            return _STEP_WORDS.get(action.value, action.value)
        case "confirm_appliance":
            return "Yes, that's my appliance." if action.value == "yes" else "No, that's not it."
        case "select_booking_slot":
            return "I'd like to book that time slot."
        case "resume_issue":
            return "Let's go back to that other problem."
        case "close_issue":
            return "Let's close that other problem."


def offered(action: StructuredAction, last_agent: AgentTurn | None) -> bool:
    """Whether the latest agent message shows the button this action presses."""
    if last_agent is None:
        return False
    match action.type:
        case "step_result":
            return bool(last_agent.step_cards)
        case "confirm_appliance":
            return bool(last_agent.cards_of(ApplianceConfirmCard))
        case "select_booking_slot":
            slots = {s.slot_id for c in last_agent.cards_of(BookingSlotsCard) for s in c.slots}
            return action.value in slots
        case "resume_issue" | "close_issue":
            ids = {i.issue_id for c in last_agent.cards_of(IssuesCard) for i in c.issues}
            return action.value in ids


def scripted_user_turn(
    script: ScriptedTurn, last_agent: AgentTurn | None, *, attachments: list[str]
) -> UserTurn:
    """A scripted turn as sent: a button press only when the reply offers that button, else its
    words (a replayed agent may answer differently than in the recorded conversation)."""
    text = script.text or None
    action, diverged = script.action, False
    if action is not None and not offered(action, last_agent):
        text, action, diverged = text or action_words(action), None, True
    return UserTurn(
        text=text, action=action, scripted=True, attachments=attachments, diverged=diverged
    )


async def agent_turn(agent: AgentRuntime, message: InboundMessage) -> AgentTurn:
    turn = AgentTurn()
    started = time.perf_counter()
    try:
        async for event in agent.handle(message):
            match event:
                case MessageDeltaEvent():
                    turn.text += event.text
                case CardEvent():
                    turn.cards.append(event.card)
                case MessageCompletedEvent():
                    turn.citations.extend(event.citations)
                    turn.journey = event.journey
                    turn.step = event.step
                case ErrorEvent():
                    turn.error = event.code
                case _:
                    pass
    except Exception as exc:
        turn.error = f"exception: {type(exc).__name__}: {exc}"
    turn.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return turn


async def run_conversation(
    case: EvalCase,
    agent: AgentRuntime,
    simulator: UserSimulator,
    *,
    trial: int = 0,
    recorder: UsageRecorder | None = None,
) -> Transcript:
    recorder = recorder or UsageRecorder()
    conversation_id = f"eval-{case.id}-{trial}-{uuid.uuid4().hex[:6]}"
    turns: list[Turn] = []
    end_reason: EndReason = "turn_limit"
    error: str | None = None
    snapshot = None
    started = time.perf_counter()
    with recorder.collect() as usage:
        try:
            while len([t for t in turns if isinstance(t, UserTurn)]) < case.max_turns:
                user = await _next_user_turn(case, simulator, turns)
                if user is None:
                    end_reason = "user_done"
                    break
                turns.append(user)
                inbound = InboundMessage(
                    conversation_id=conversation_id,
                    text=user.text,
                    action=user.action,
                    attachments=user.attachments,
                    user_id=case.user_id,
                )
                reply = await agent_turn(agent, inbound)
                turns.append(reply)
                if reply.error and reply.error.startswith("exception:"):
                    end_reason, error = "error", reply.error
                    break
                state = await agent.snapshot(conversation_id)
                reply.outcome, reply.hazard_flags = state.outcome, state.hazard_flags
                reply.issues = state.issues
                sent = len([t for t in turns if isinstance(t, UserTurn)])
                if case.stop_after_script and sent >= len(case.user_turns):
                    end_reason = "script_done"
                    break
                # A terminal outcome ends the conversation, unless scripted turns remain (they
                # are part of the test, e.g. a late hazard) or the agent is offering booking
                # slots the user may still pick (escalation -> booking flow).
                scripted_left = len(case.user_turns) > len(
                    [t for t in turns if isinstance(t, UserTurn)]
                )
                if (
                    reply.outcome in TERMINAL_OUTCOMES
                    and not scripted_left
                    and not reply.offers_booking
                    and (not case.issues or all_issues_opened(case, reply))
                ):
                    end_reason = "outcome"
                    break
            snapshot = await agent.snapshot(conversation_id)
        except Exception as exc:
            end_reason, error = "error", f"{type(exc).__name__}: {exc}"
    return Transcript(
        case_id=case.id,
        trial=trial,
        conversation_id=conversation_id,
        turns=turns,
        end_reason=end_reason,
        snapshot=snapshot,
        error=error,
        usage=usage,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )


async def _next_user_turn(
    case: EvalCase, simulator: UserSimulator, turns: list[Turn]
) -> UserTurn | None:
    scripted = runner_turn(case, turns)
    if scripted is not None:
        return scripted
    sent = len([t for t in turns if isinstance(t, UserTurn)])
    last_agent = turns[-1] if turns and isinstance(turns[-1], AgentTurn) else None
    if sent < len(case.user_turns):
        return scripted_user_turn(case.scripted(sent), last_agent, attachments=case.media_for(sent))
    sim_turn = await simulator.next_turn(focus(case, turns), turns)
    if sim_turn.done:
        return None
    return to_user_turn(sim_turn, last_agent, case)
