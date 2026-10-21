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

# Called once the turn has finished and been persisted, with its total LLM cost.
TurnHook = Callable[[float], Awaitable[None]]


@dataclass
class _Draft:
    text: list[str] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)


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
        started = time.perf_counter()
        cost_usd = 0.0
        try:
            with track_usage() as tally:
                await self._persist(_user_message(inbound, trace_id))
                attributed, last_id = await self._stream(inbound, trace_id, queue, started, tally)
                cost_usd = tally.cost_usd
            await self._finish(inbound, last_id, cost_usd - attributed)
        except Exception:
            log.exception("turn_failed", conversation_id=inbound.conversation_id)
            await queue.put(AGENT_ERROR)
        finally:
            await queue.put(None)
            if on_finish is not None:
                try:
                    await on_finish(cost_usd)
                except Exception:
                    log.exception("turn_hook_failed", conversation_id=inbound.conversation_id)

    async def _stream(
        self,
        inbound: InboundMessage,
        trace_id: str | None,
        queue: asyncio.Queue[AgentEvent | None],
        started: float,
        tally: UsageTally,
    ) -> tuple[float, str | None]:
        """Forward agent events, persisting each completed message. Returns the cost already
        attributed to messages and the last message id."""
        assembler = MessageAssembler()
        attributed = 0.0
        last_id: str | None = None
        async for event in self._agent.handle(inbound):
            assembler.add(event)
            if isinstance(event, MessageCompletedEvent):
                message = assembler.complete(event, inbound.conversation_id)
                message.trace_id = trace_id
                message.latency_ms = round((time.perf_counter() - started) * 1000)
                message.cost_usd = tally.cost_usd - attributed
                attributed = tally.cost_usd
                await self._persist(message)
                last_id = message.id
            elif isinstance(event, ErrorEvent):
                log.warning("agent_error_event", code=event.code)
            await queue.put(event)
        return attributed, last_id

    async def _finish(
        self, inbound: InboundMessage, last_id: str | None, unattributed_cost: float
    ) -> None:
        snapshot = await self._agent.snapshot(inbound.conversation_id)
        async with self._sessionmaker.begin() as session:
            if last_id is not None and unattributed_cost > 0:
                # LLM calls after the last `message.completed` (e.g. a late supervisor check).
                await repository.add_cost(session, last_id, unattributed_cost)
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
