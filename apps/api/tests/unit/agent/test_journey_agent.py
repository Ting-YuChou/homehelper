from homehelper.agent.deps import AgentDeps
from homehelper.agent.nodes.act import PlanDraft, PlanDraftItem
from homehelper.agent.runtime import JourneyAgent
from homehelper.agent.state import NLUResult, SlotUpdate
from homehelper.agent.supervisor import BLOCKED_REPLY, SupervisorReview
from homehelper.agent.turn import AgentReply
from homehelper.channels.events import (
    AgentEvent,
    CardEvent,
    ErrorEvent,
    HandoffCard,
    InboundMessage,
    MessageCompletedEvent,
    MessageDeltaEvent,
    SafetyCard,
    StatusEvent,
    StepCard,
    StructuredAction,
)
from homehelper.knowledge.schemas import (
    CategoryId,
    ChunkMetadata,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
)
from homehelper.llm import FakeLLMClient


def _chunk(chunk_id: str, page: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        text=f"Troubleshooting text on page {page}.",
        score=0.9,
        metadata=ChunkMetadata(
            doc_id="bosch-shx68t55",
            category=CategoryId("dishwasher"),
            brand="Bosch",
            page_start=page,
            page_end=page,
        ),
    )


class FakeRetriever:
    def __init__(self) -> None:
        self.queries: list[RetrievalQuery] = []

    async def search(self, query: RetrievalQuery) -> RetrievalResult:
        self.queries.append(query)
        return RetrievalResult(
            query=query,
            source="manual",
            chunks=[_chunk("c1", 18), _chunk("c2", 19)],
            sufficient=True,
            filter_level="brand_category",
        )


REPORT = NLUResult(
    intent="report_problem",
    slot_updates=[
        SlotUpdate(name="appliance_category", value="dishwasher"),
        SlotUpdate(name="symptom", value="does not drain"),
        SlotUpdate(name="brand", value="Bosch"),
    ],
    search_query_en="dishwasher does not drain",
)
PLAN = PlanDraft(
    items=[
        PlanDraftItem(instruction="Clean the filter.", citation_ids=["c1", "made-up"]),
        PlanDraftItem(instruction="Check the drain hose for kinks.", citation_ids=["c2"]),
    ]
)
PASS = SupervisorReview(grounded=True, safe=True, on_task=True)


def _agent(llm: FakeLLMClient, retriever: FakeRetriever | None = None) -> JourneyAgent:
    return JourneyAgent(AgentDeps.default(llm, retriever or FakeRetriever()))


async def _send(agent: JourneyAgent, text: str | None = None, result: str | None = None):
    action = StructuredAction(type="step_result", value=result) if result else None
    message = InboundMessage(conversation_id="conv-1", text=text, action=action)
    return [event async for event in agent.handle(message)]


def _cards(events: list[AgentEvent]) -> list:
    return [event.card for event in events if isinstance(event, CardEvent)]


def _text(events: list[AgentEvent]) -> str:
    return "".join(event.text for event in events if isinstance(event, MessageDeltaEvent))


async def test_troubleshoot_walks_the_plan_to_resolved_across_turns() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [PLAN],
            "responder": [
                AgentReply(message="Let's start with the filter.", citation_ids=["c1"]),
                AgentReply(message="Thanks. Next, the drain hose."),
                AgentReply(message="Great, glad it works!"),
            ],
            "supervisor": [PASS, PASS],
        }
    )
    retriever = FakeRetriever()
    agent = _agent(llm, retriever)

    first = await _send(agent, "My Bosch dishwasher won't drain")
    assert isinstance(first[0], StatusEvent)
    assert {e.stage for e in first if isinstance(e, StatusEvent)} >= {
        "understanding",
        "retrieving",
        "planning",
        "responding",
        "checking",
    }
    (query,) = retriever.queries
    assert (query.query_en, query.category, query.brand) == (
        "dishwasher does not drain",
        CategoryId("dishwasher"),
        "Bosch",
    )
    (card,) = _cards(first)
    assert isinstance(card, StepCard)
    assert (card.index, card.total, card.instruction) == (1, 2, "Clean the filter.")
    assert [c.chunk_id for c in card.citations] == ["c1"]  # the invented id was dropped
    completed = first[-1]
    assert isinstance(completed, MessageCompletedEvent)
    assert (completed.journey, completed.step) == ("troubleshoot", "guide")

    second = await _send(agent, result="not_fixed")
    assert [c.instruction for c in _cards(second) if isinstance(c, StepCard)] == [
        "Check the drain hose for kinks."
    ]
    assert len(llm.calls_for("nlu")) == 1  # buttons skip NLU

    third = await _send(agent, result="fixed")
    assert _text(third) == "Great, glad it works!"
    snapshot = await agent.snapshot("conv-1")
    assert (snapshot.outcome, snapshot.journey, snapshot.step) == (
        "resolved",
        "troubleshoot",
        "resolved",
    )
    reasons = [d["reason"] for d in snapshot.decision_log]
    assert any("skipped mcp:user_profile.add_repair_record" in r for r in reasons)
    # The responder saw the conversation so far, including the step it showed.
    last_prompt = str(llm.calls_for("responder")[-1].messages[-1].content)
    assert "[Step 2/2: Check the drain hose for kinks.]" in last_prompt


async def test_hazard_uses_the_fixed_template_and_hands_off() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [
                NLUResult(
                    intent="report_problem",
                    slot_updates=[SlotUpdate(name="appliance_category", value="dryer")],
                    hazard_signals=["smoke_or_burning"],
                )
            ]
        }
    )
    agent = _agent(llm)
    events = await _send(agent, "There's smoke coming out of my dryer")
    cards = _cards(events)
    assert [type(c) for c in cards] == [SafetyCard, HandoffCard]
    assert "Smoke or a burning smell" in _text(events)
    assert llm.calls_for("responder") == []  # hazard replies are never generated
    snapshot = await agent.snapshot("conv-1")
    assert (snapshot.outcome, snapshot.hazard_flags) == ("escalated", ["smoke_or_burning"])


async def test_supervisor_revises_once_then_blocks() -> None:
    reject = SupervisorReview(grounded=False, safe=True, on_task=True, reasons=["Unsupported."])
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [PLAN],
            "responder": [AgentReply(message="Draft one."), AgentReply(message="Draft two.")],
            "supervisor": [reject, reject],
        }
    )
    agent = _agent(llm)
    events = await _send(agent, "My Bosch dishwasher won't drain")
    assert _text(events) == BLOCKED_REPLY
    assert not any(isinstance(c, StepCard) for c in _cards(events))
    revise_prompt = str(llm.calls_for("responder")[1].messages[-1].content)
    assert "- Unsupported." in revise_prompt


async def test_out_of_scope_gets_the_fixed_reply() -> None:
    llm = FakeLLMClient({"nlu": [NLUResult(intent="out_of_scope")]})
    agent = _agent(llm)
    events = await _send(agent, "Write me a poem about cats")
    assert _cards(events) == []
    assert (await agent.snapshot("conv-1")).outcome == "out_of_scope"
    assert llm.calls_for("responder") == []


async def test_llm_failure_becomes_an_error_event_and_the_turn_can_be_retried() -> None:
    llm = FakeLLMClient({"nlu": [RuntimeError("down"), NLUResult(intent="small_talk")]})
    llm.add("responder", AgentReply(message="Hi! What can I help with?"))
    agent = _agent(llm)
    failed = await _send(agent, "hello")
    assert isinstance(failed[-1], ErrorEvent)
    retried = await _send(agent, "hello")
    assert _text(retried) == "Hi! What can I help with?"
