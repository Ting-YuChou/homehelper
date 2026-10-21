from homehelper.agent.protocol import AgentRuntime
from homehelper.agent.stub import PLAN, StubAgent
from homehelper.channels.events import (
    AgentEvent,
    CardEvent,
    HandoffCard,
    InboundMessage,
    MessageCompletedEvent,
    SafetyCard,
    StepCard,
    StructuredAction,
)
from homehelper.main import create_app
from tests.conftest import make_settings


async def _turn(agent: StubAgent, text: str | None = None, result: str | None = None) -> list:
    action = StructuredAction(type="step_result", value=result) if result else None
    message = InboundMessage(conversation_id="c1", text=text, action=action)
    return [event async for event in agent.handle(message)]


def _cards(events: list[AgentEvent]) -> list:
    return [event.card for event in events if isinstance(event, CardEvent)]


async def test_walks_the_plan_until_fixed() -> None:
    agent = StubAgent()
    first = await _turn(agent, "My dishwasher won't start")
    assert isinstance(first[-1], MessageCompletedEvent)
    assert [(c.index, c.total) for c in _cards(first)] == [(1, len(PLAN))]
    assert first[-1].citations == _cards(first)[0].citations

    second = await _turn(agent, result="not_fixed")
    assert [c.index for c in _cards(second)] == [2]
    await _turn(agent, result="fixed")
    snapshot = await agent.snapshot("c1")
    assert (snapshot.outcome, snapshot.journey, snapshot.step) == (
        "resolved",
        "troubleshoot",
        "resolved",
    )


async def test_hands_off_when_plan_runs_out() -> None:
    agent = StubAgent()
    await _turn(agent, "It won't drain")
    for _ in PLAN[1:]:
        await _turn(agent, result="cannot_do")
    last = await _turn(agent, "still not fixed")
    assert isinstance(_cards(last)[-1], HandoffCard)
    assert (await agent.snapshot("c1")).outcome == "escalated"
    ended = await _turn(agent, "hello?")
    assert _cards(ended) == []


async def test_hazard_gets_safety_card_and_handoff() -> None:
    agent = StubAgent()
    events = await _turn(agent, "There is smoke coming out of the back")
    assert [type(card) for card in _cards(events)] == [SafetyCard, HandoffCard]
    assert (await agent.snapshot("c1")).outcome == "escalated"
    assert not any(isinstance(card, StepCard) for card in _cards(events))


async def test_app_uses_stub_unless_an_agent_is_injected() -> None:
    settings = make_settings()
    injected: AgentRuntime = StubAgent()
    default, custom = create_app(settings), create_app(settings, agent=injected)
    assert isinstance(default.state.agent, StubAgent)
    assert custom.state.agent is injected
    for app in (default, custom):
        await app.state.redis.aclose()
        await app.state.db_engine.dispose()
