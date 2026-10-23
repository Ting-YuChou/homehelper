import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from homehelper.agent.checkpoint import APPLICATION_NAME, postgres_checkpointer
from homehelper.agent.deps import AgentDeps
from homehelper.agent.runtime import JourneyAgent
from homehelper.agent.turn import AgentReply
from homehelper.channels.events import InboundMessage, StepCard, StructuredAction
from homehelper.llm import FakeLLMClient
from tests.unit.agent.test_journey_agent import PASS, PLAN, REPORT, FakeRetriever, _cards

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://homehelper:homehelper@localhost:5432/homehelper"
)


async def _turn(agent: JourneyAgent, conversation_id: str, **fields: object) -> list:
    message = InboundMessage(conversation_id=conversation_id, **fields)  # type: ignore[arg-type]
    return [event async for event in agent.handle(message)]


async def test_conversation_state_survives_a_restart() -> None:
    conversation_id = f"it-{uuid.uuid4().hex[:8]}"
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [PLAN],
            "responder": [AgentReply(message="Try the filter."), AgentReply(message="Next one.")],
            "supervisor": [PASS, PASS],
        }
    )
    async with postgres_checkpointer(DATABASE_URL) as saver:
        first = JourneyAgent(AgentDeps.default(llm, FakeRetriever()), saver)
        await _turn(first, conversation_id, text="My Bosch dishwasher won't drain")

    # A new process: a fresh agent and connection pool see the same conversation.
    async with postgres_checkpointer(DATABASE_URL) as saver:
        second = JourneyAgent(AgentDeps.default(llm, FakeRetriever()), saver)
        events = await _turn(
            second,
            conversation_id,
            action=StructuredAction(type="step_result", value="not_fixed"),
        )
        steps = [c for c in _cards(events) if isinstance(c, StepCard)]
        assert [(c.index, c.instruction) for c in steps] == [(2, "Check the drain hose for kinks.")]
        snapshot = await second.snapshot(conversation_id)
        assert (snapshot.journey, snapshot.step) == ("troubleshoot", "guide")
        state = await second.state(conversation_id)
        assert state is not None and len(state.transcript) == 4

    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        found = await conn.execute(text("SELECT to_regclass('langgraph.checkpoints')"))
        assert found.scalar() == "langgraph.checkpoints"
    await engine.dispose()


async def test_a_connection_closed_by_the_server_is_replaced() -> None:
    """Neon closes every connection when an idle compute suspends; the next turn must not fail."""
    config = {"configurable": {"thread_id": f"it-{uuid.uuid4().hex[:8]}"}}
    async with postgres_checkpointer(DATABASE_URL) as saver:
        engine = create_async_engine(DATABASE_URL)
        async with engine.connect() as admin:
            killed = await admin.execute(
                text(
                    "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity"
                    " WHERE application_name = :name"
                ),
                {"name": APPLICATION_NAME},
            )
            assert killed.scalar()
        await engine.dispose()
        assert await saver.aget_tuple(config) is None  # type: ignore[arg-type]
