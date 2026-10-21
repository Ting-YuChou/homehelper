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
    MessageCompletedEvent,
    MessageDeltaEvent,
    StructuredAction,
)
from homehelper.llm import LLMUsage
from homehelper_evals.cases import EvalCase
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


def to_user_turn(turn: SimulatorTurn, last_agent: AgentTurn | None) -> UserTurn | None:
    """Map a simulator turn to what the user sends. Button presses only count when the latest
    agent message actually offered that button. Returns None when there is nothing to send."""
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
    if action is None and text is None:
        return None
    return UserTurn(text=text, action=action)


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
                    conversation_id=conversation_id, text=user.text, action=user.action
                )
                reply = await agent_turn(agent, inbound)
                turns.append(reply)
                if reply.error and reply.error.startswith("exception:"):
                    end_reason, error = "error", reply.error
                    break
                state = await agent.snapshot(conversation_id)
                reply.outcome, reply.hazard_flags = state.outcome, state.hazard_flags
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
    sent = len([t for t in turns if isinstance(t, UserTurn)])
    if sent < len(case.user_turns):
        return UserTurn(text=case.user_turns[sent], scripted=True)
    sim_turn = await simulator.next_turn(case, turns)
    if sim_turn.done:
        return None
    last_agent = turns[-1] if turns and isinstance(turns[-1], AgentTurn) else None
    return to_user_turn(sim_turn, last_agent)
