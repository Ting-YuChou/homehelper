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


async def test_issue_actions_do_not_advance_the_plan() -> None:
    agent = StubAgent()
    await _turn(agent, "My dishwasher won't start")
    message = InboundMessage(
        conversation_id="c1", action=StructuredAction(type="resume_issue", value="iss_1")
    )
    events = [event async for event in agent.handle(message)]
    assert [c.index for c in _cards(events)] == [1]


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


async def test_deferred_agent_delegates_once_attached() -> None:
    import pytest

    from homehelper.agent.factory import DeferredAgent

    deferred = DeferredAgent()
    with pytest.raises(RuntimeError, match="not ready"):
        await deferred.snapshot("c1")
    stub = StubAgent()
    deferred.attach(stub)
    events = [e async for e in deferred.handle(InboundMessage(conversation_id="c1", text="hi"))]
    assert isinstance(events[-1], MessageCompletedEvent)
    assert (await deferred.snapshot("c1")).journey == "troubleshoot"


def test_journey_runtime_setting_installs_a_deferred_agent() -> None:
    from homehelper.agent.factory import DeferredAgent

    app = create_app(make_settings(agent_runtime="journey"))
    assert isinstance(app.state.agent, DeferredAgent)
    assert app.state.conversations is not None
