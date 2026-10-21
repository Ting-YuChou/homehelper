from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homehelper.agent.protocol import AgentSnapshot
from homehelper.agent.stub import StubAgent
from homehelper.channels.events import (
    AgentEvent,
    CardEvent,
    ErrorEvent,
    InboundMessage,
    MessageCompletedEvent,
    StructuredAction,
)
from homehelper.conversations import repository
from homehelper.conversations.service import ConversationService, TurnHook
from homehelper.db.models import Conversation
from homehelper.llm import LLMUsage, record_usage

pytestmark = pytest.mark.integration

TRACE_ID = "ab" * 16


async def _conversation(sessionmaker: async_sessionmaker[AsyncSession]) -> Conversation:
    async with sessionmaker.begin() as session:
        user_id = repository.new_id("test")
        await repository.upsert_user(session, user_id, "Test user", is_demo=False)
        return await repository.create_conversation(session, user_id=user_id, release_id="dev")


async def _turn(
    service: ConversationService,
    inbound: InboundMessage,
    *,
    trace_id: str | None = None,
    on_finish: TurnHook | None = None,
) -> list[AgentEvent]:
    stream = service.start_turn(inbound, trace_id=trace_id, on_finish=on_finish)
    events = [event async for event in stream]
    await service.wait_idle()
    return events


class CostlyAgent(StubAgent):
    """The stub, plus a fake LLM call before it answers."""

    async def handle(self, message: InboundMessage) -> AsyncIterator[AgentEvent]:
        record_usage(
            LLMUsage(
                task="respond",
                model="fake",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.0123,
                latency_ms=1.0,
            )
        )
        async for event in super().handle(message):
            yield event


class BrokenAgent(StubAgent):
    async def handle(self, message: InboundMessage) -> AsyncIterator[AgentEvent]:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    async def snapshot(self, conversation_id: str) -> AgentSnapshot:
        return AgentSnapshot(conversation_id=conversation_id)


async def test_turn_persists_user_and_assistant_messages(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    conversation = await _conversation(sessionmaker)
    service = ConversationService(sessionmaker, StubAgent())
    inbound = InboundMessage(conversation_id=conversation.id, text="My dishwasher won't start")

    events = await _turn(service, inbound, trace_id=TRACE_ID)

    completed = [e for e in events if isinstance(e, MessageCompletedEvent)]
    cards = [e for e in events if isinstance(e, CardEvent)]
    assert len(completed) == 1 and len(cards) == 1
    async with sessionmaker() as session:
        user, assistant = await repository.list_messages(session, conversation.id)
        stored = await session.get(Conversation, conversation.id)
    assert (user.role, user.content, user.action) == ("user", inbound.text, None)
    assert assistant.id == completed[0].message_id
    assert assistant.role == "assistant"
    assert assistant.content == "Let's work through this one step at a time."
    assert assistant.cards == [cards[0].card.model_dump(mode="json")]
    assert assistant.citations[0]["doc_id"] == "bosch-shx68t55"
    assert assistant.trace_id == user.trace_id == TRACE_ID
    assert assistant.latency_ms is not None and assistant.latency_ms >= 0
    assert assistant.cost_usd == 0
    assert stored is not None
    assert stored.title == inbound.text
    assert stored.active_journey == "troubleshoot"
    assert stored.outcome is None


async def test_step_card_action_resolves_the_conversation(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    conversation = await _conversation(sessionmaker)
    service = ConversationService(sessionmaker, StubAgent())
    await _turn(service, InboundMessage(conversation_id=conversation.id, text="Not starting"))
    action = StructuredAction(type="step_result", value="fixed")
    await _turn(service, InboundMessage(conversation_id=conversation.id, action=action))

    async with sessionmaker() as session:
        messages = await repository.list_messages(session, conversation.id)
        stored = await session.get(Conversation, conversation.id)
    assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[2].action == {"type": "step_result", "value": "fixed"}
    assert messages[2].content == ""
    assert stored is not None and stored.outcome == "resolved"
    assert stored.title == "Not starting"


async def test_llm_cost_is_stored_on_the_message_and_reported(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    conversation = await _conversation(sessionmaker)
    service = ConversationService(sessionmaker, CostlyAgent())
    reported: list[float] = []

    async def on_finish(cost_usd: float) -> None:
        reported.append(cost_usd)

    await _turn(
        service, InboundMessage(conversation_id=conversation.id, text="Hi"), on_finish=on_finish
    )

    async with sessionmaker() as session:
        _, assistant = await repository.list_messages(session, conversation.id)
    assert assistant.cost_usd == pytest.approx(0.0123)
    assert reported == [pytest.approx(0.0123)]


async def test_turn_finishes_when_the_client_disconnects(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    conversation = await _conversation(sessionmaker)
    service = ConversationService(sessionmaker, StubAgent())
    stream = service.start_turn(InboundMessage(conversation_id=conversation.id, text="Hi"))
    await anext(stream)  # the first status event, then the client goes away
    await stream.aclose()
    await service.wait_idle()

    async with sessionmaker() as session:
        messages = await repository.list_messages(session, conversation.id)
    assert [m.role for m in messages] == ["user", "assistant"]


async def test_agent_failure_becomes_an_error_event(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    conversation = await _conversation(sessionmaker)
    service = ConversationService(sessionmaker, BrokenAgent())
    finished: list[float] = []

    async def on_finish(cost_usd: float) -> None:
        finished.append(cost_usd)

    events = await _turn(
        service, InboundMessage(conversation_id=conversation.id, text="Hi"), on_finish=on_finish
    )

    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent) and events[0].code == "agent_error"
    assert finished == [0.0]
    async with sessionmaker() as session:
        messages = await repository.list_messages(session, conversation.id)
    assert [m.role for m in messages] == ["user"]
