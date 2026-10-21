"""Runs one user turn and persists it (spec §5.2, v0.8 boundary).

The agent only streams `AgentEvent`s; this service writes the user message, assembles each
assistant message from its deltas, cards and `message.completed`, and stores it with the trace id,
latency and the LLM cost collected by `track_usage()`.

The turn runs in its own task and talks to the response through a queue, so a client that
disconnects mid-stream doesn't abort the agent or leave a half-written turn. An assistant message
is written before its `message.completed` is forwarded, so the client can act on it (feedback)
as soon as it sees the event.
"""

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homehelper.agent.protocol import AgentRuntime
from homehelper.channels.events import (
    AgentEvent,
    Card,
    CardEvent,
    ErrorEvent,
    InboundMessage,
    MessageCompletedEvent,
    MessageDeltaEvent,
)
from homehelper.conversations import repository
from homehelper.core.logging import get_logger
from homehelper.db.models import Message
from homehelper.llm import UsageTally, track_usage

log = get_logger(__name__)

AGENT_ERROR = ErrorEvent(
    code="agent_error", message="Something went wrong on our side. Please try again."
)

# Called once the turn has been persisted, before its stream ends, with its total LLM cost.
TurnHook = Callable[[float], Awaitable[None]]


@dataclass
class _Draft:
    text: list[str] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)


@dataclass
class _Progress:
    started: float  # perf_counter at turn start
    attributed: float = 0.0  # cost already stored on messages
    last_id: str | None = None  # last stored assistant message


@dataclass
class MessageAssembler:
    """Collects the events of one turn into assistant messages, keyed by `message_id`."""

    drafts: dict[str, _Draft] = field(default_factory=dict)

    def add(self, event: AgentEvent) -> None:
        if isinstance(event, MessageDeltaEvent):
            self.drafts.setdefault(event.message_id, _Draft()).text.append(event.text)
        elif isinstance(event, CardEvent):
            self.drafts.setdefault(event.message_id, _Draft()).cards.append(event.card)

    def complete(self, event: MessageCompletedEvent, conversation_id: str) -> Message:
        draft = self.drafts.pop(event.message_id, _Draft())
        return Message(
            id=event.message_id,
            conversation_id=conversation_id,
            role="assistant",
            content="".join(draft.text),
            cards=[card.model_dump(mode="json") for card in draft.cards],
            citations=[citation.model_dump(mode="json") for citation in event.citations],
        )


class ConversationService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], agent: AgentRuntime) -> None:
        self._sessionmaker = sessionmaker
        self._agent = agent
        self._tasks: set[asyncio.Task[None]] = set()

    def start_turn(
        self,
        inbound: InboundMessage,
        *,
        trace_id: str | None = None,
        on_finish: TurnHook | None = None,
    ) -> AsyncGenerator[AgentEvent]:
        """Start the turn in the background and return its event stream."""
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        task = asyncio.create_task(self._run(inbound, trace_id, queue, on_finish))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return _drain(queue)

    async def wait_idle(self) -> None:
        """Wait for running turns (shutdown, tests)."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run(
        self,
        inbound: InboundMessage,
        trace_id: str | None,
        queue: asyncio.Queue[AgentEvent | None],
        on_finish: TurnHook | None,
    ) -> None:
        progress = _Progress(started=time.perf_counter())
        with track_usage() as tally:
            try:
                await self._persist(_user_message(inbound, trace_id))
                await self._stream(inbound, trace_id, queue, progress, tally)
            except Exception:
                log.exception("turn_failed", conversation_id=inbound.conversation_id)
                await queue.put(AGENT_ERROR)
            finally:
                # Even a failed turn records its outcome and what it spent (the spend cap must
                # see it), before the stream ends so the client may send its next message.
                try:
                    await self._finish(inbound, progress, tally.cost_usd - progress.attributed)
                except Exception:
                    log.exception("turn_finish_failed", conversation_id=inbound.conversation_id)
                if on_finish is not None:
                    try:
                        await on_finish(tally.cost_usd)
                    except Exception:
                        log.exception("turn_hook_failed", conversation_id=inbound.conversation_id)
                await queue.put(None)

    async def _stream(
        self,
        inbound: InboundMessage,
        trace_id: str | None,
        queue: asyncio.Queue[AgentEvent | None],
        progress: _Progress,
        tally: UsageTally,
    ) -> None:
        """Forward agent events, persisting each completed message with the cost since the last."""
        assembler = MessageAssembler()
        async for event in self._agent.handle(inbound):
            assembler.add(event)
            if isinstance(event, MessageCompletedEvent):
                message = assembler.complete(event, inbound.conversation_id)
                message.trace_id = trace_id
                message.latency_ms = round((time.perf_counter() - progress.started) * 1000)
                message.cost_usd = tally.cost_usd - progress.attributed
                await self._persist(message)
                progress.attributed = tally.cost_usd
                progress.last_id = message.id
            elif isinstance(event, ErrorEvent):
                log.warning("agent_error_event", code=event.code)
            await queue.put(event)

    async def _finish(
        self, inbound: InboundMessage, progress: _Progress, unattributed_cost: float
    ) -> None:
        snapshot = await self._agent.snapshot(inbound.conversation_id)
        async with self._sessionmaker.begin() as session:
            if progress.last_id is not None and unattributed_cost > 0:
                # LLM calls after the last `message.completed` (a late check, or a failed turn).
                await repository.add_cost(session, progress.last_id, unattributed_cost)
            await repository.finish_turn(
                session,
                inbound.conversation_id,
                outcome=snapshot.outcome,
                active_journey=snapshot.journey,
                first_text=inbound.text,
            )

    async def _persist(self, message: Message) -> None:
        async with self._sessionmaker.begin() as session:
            await repository.add_message(session, message)


def _user_message(inbound: InboundMessage, trace_id: str | None) -> Message:
    return Message(
        id=repository.new_id("msg"),
        conversation_id=inbound.conversation_id,
        role="user",
        content=inbound.text or "",
        cards=[],
        citations=[],
        action=inbound.action.model_dump(mode="json") if inbound.action else None,
        trace_id=trace_id,
    )


async def _drain(queue: asyncio.Queue[AgentEvent | None]) -> AsyncGenerator[AgentEvent]:
    while (event := await queue.get()) is not None:
        yield event
