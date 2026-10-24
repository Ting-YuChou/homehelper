"""The journey agent without a model number (ADR-013), end to end with fake models."""

from homehelper.agent.deps import AgentDeps
from homehelper.agent.nodes.act import PlanDraft, PlanDraftItem
from homehelper.agent.runtime import JourneyAgent
from homehelper.agent.state import NLUResult, SlotUpdate
from homehelper.agent.supervisor import BLOCKED_REPLY, SupervisorReview
from homehelper.agent.turn import AgentReply
from homehelper.channels.events import (
    AgentEvent,
    CardEvent,
    InboundMessage,
    MessageDeltaEvent,
    StepCard,
)
from homehelper.knowledge.schemas import (
    CategoryId,
    ChunkMetadata,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
    WebFinding,
)
from homehelper.llm import FakeLLMClient

from .no_model_helpers import manual_index

WEB = WebFinding(
    claim="Check that the vents inside are not blocked.",
    url="https://www.samsung.com/us/support/cooling",
    id="web-0123456789",
    title="Fridge not cooling",
)


class Library:
    """Two chunks from every manual asked for; web findings when `web` is set."""

    def __init__(self, *, chunks: bool = True, web: bool = False) -> None:
        self.queries: list[RetrievalQuery] = []
        self.chunks, self.web = chunks, web

    async def search(self, query: RetrievalQuery) -> RetrievalResult:
        self.queries.append(query)
        docs = query.doc_ids or ["samsung-fd1"]
        chunks = [
            RetrievedChunk(
                chunk_id=f"{doc}:{n}",
                text=f"{doc} cooling advice {n}",
                score=0.9,
                metadata=ChunkMetadata(
                    doc_id=doc,
                    category=CategoryId.REFRIGERATOR,
                    brand="Samsung",
                    page_start=n,
                    page_end=n,
                ),
            )
            for doc in docs
            for n in (1, 2)
        ]
        return RetrievalResult(
            query=query,
            source="manual" if self.chunks else "web",
            chunks=chunks if self.chunks else [],
            web_findings=[WEB] if self.web else [],
            filter_level="candidates" if self.chunks else None,
            sufficient=True,
        )


REPORT = NLUResult(
    intent="report_problem",
    slot_updates=[
        SlotUpdate(name="appliance_category", value="refrigerator"),
        SlotUpdate(name="brand", value="Samsung"),
        SlotUpdate(name="symptom", value="not cooling"),
    ],
    search_query_en="refrigerator not cooling",
)
PASS = SupervisorReview(grounded=True, safe=True, on_task=True)
FAIL = SupervisorReview(grounded=False, safe=True, on_task=True, reasons=["Not grounded."])


def _agent(llm: FakeLLMClient, library: Library) -> JourneyAgent:
    return JourneyAgent(AgentDeps.default(llm, library, manuals=manual_index()))


async def _send(agent: JourneyAgent, text: str) -> list[AgentEvent]:
    message = InboundMessage(conversation_id="conv-1", text=text)
    return [event async for event in agent.handle(message)]


def _text(events: list[AgentEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, MessageDeltaEvent))


def _steps(events: list[AgentEvent]) -> list[StepCard]:
    return [e.card for e in events if isinstance(e, CardEvent) and isinstance(e.card, StepCard)]


async def test_general_steps_ask_once_then_the_look_picks_the_manual() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [
                REPORT,
                NLUResult(
                    intent="step_feedback",
                    step_feedback="not_fixed",
                    slot_updates=[SlotUpdate(name="trait_layout", value="side_by_side")],
                ),
            ],
            "planner": [
                PlanDraft(
                    items=[
                        PlanDraftItem(
                            instruction="Check the temperature setting.",
                            citation_ids=["samsung-fd1:1", "samsung-sbs:1"],
                        ),
                        PlanDraftItem(
                            instruction="Clean the coils.", citation_ids=["samsung-fd2:1"]
                        ),
                    ]
                ),
                PlanDraft(
                    items=[
                        PlanDraftItem(
                            instruction="Clear the freezer vent.", citation_ids=["samsung-sbs:2"]
                        )
                    ]
                ),
            ],
            "responder": [
                AgentReply(message="Let's check the temperature first."),
                AgentReply(message="Thanks, that's the side-by-side manual. Next, the vent."),
            ],
            "supervisor": [PASS, PASS],
        }
    )
    library = Library()
    agent = _agent(llm, library)

    first = await _send(agent, "My Samsung fridge isn't cooling, no idea of the model")
    query = library.queries[0]
    assert sorted(query.doc_ids or []) == ["samsung-fd1", "samsung-fd2", "samsung-sbs"]
    assert (query.per_doc, query.top_k, query.web) == (2, 8, "always_add")
    (card,) = _steps(first)
    assert card.general and card.instruction == "Check the temperature setting."
    text = _text(first)
    assert text.startswith("Let's check the temperature first.")
    assert text.endswith(
        "You can also send a photo of that sticker or of the front of the refrigerator."
    )
    assert "Is it French door or side by side?" in text
    prompt = str(llm.calls_for("planner")[0].messages[0].content)
    assert "the excerpts come from 3 manuals" in prompt
    assert "do not\nask for the model number" in str(
        llm.calls_for("responder")[0].messages[0].content
    )

    second = await _send(agent, "It's a side by side, and that didn't help")
    assert library.queries[1].doc_ids == ["samsung-sbs"]
    assert library.queries[1].web == "add_when_insufficient"
    (card,) = _steps(second)
    assert (card.index, card.total, card.instruction, card.general) == (
        2,
        2,
        "Clear the freezer vent.",
        False,
    )
    assert "model number" not in _text(second)  # asked once
    replan = str(llm.calls_for("planner")[1].messages[0].content)
    assert "- Check the temperature setting." in replan  # the tried step, not to repeat
    reply = str(llm.calls_for("responder")[1].messages[0].content)
    assert '"Samsung Side by Side Refrigerator"' in reply
    snapshot = await agent.snapshot("conv-1")
    reasons = [d["reason"] for d in snapshot.decision_log]
    assert any(
        r.startswith("identified: identified samsung-sbs from layout=side_by_side") for r in reasons
    )
    assert any(r.startswith("kept 1 tried steps") for r in reasons)


async def test_a_model_number_that_names_no_manual_keeps_the_plan() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [
                REPORT,
                NLUResult(
                    intent="other", slot_updates=[SlotUpdate(name="model_number", value="XQ9000")]
                ),
            ],
            "planner": [
                PlanDraft(
                    items=[
                        PlanDraftItem(
                            instruction="Check the door seal.", citation_ids=["samsung-fd1:1"]
                        )
                    ]
                )
            ],
            "responder": [
                AgentReply(message="Let's check the door seal."),
                AgentReply(message="I don't have that model's manual, so let's keep going."),
            ],
            "supervisor": [PASS, PASS],
        }
    )
    library = Library()
    agent = _agent(llm, library)
    await _send(agent, "My Samsung fridge isn't cooling")
    second = await _send(agent, "The sticker says XQ9000")
    assert len(library.queries) == 1 and len(llm.calls_for("planner")) == 1
    (card,) = _steps(second)
    assert card.instruction == "Check the door seal."  # the same step, still unanswered
    reply = str(llm.calls_for("responder")[1].messages[0].content)
    assert "no manual for the model number" in reply


async def test_a_plan_from_web_findings_shows_its_unofficial_source() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [
                PlanDraft(
                    items=[PlanDraftItem(instruction="Clear the vents.", citation_ids=[WEB.id])]
                )
            ],
            "responder": [AgentReply(message="A support page suggests checking the vents.")],
            "supervisor": [PASS],
        }
    )
    agent = _agent(llm, Library(chunks=False, web=True))
    events = await _send(agent, "My Samsung fridge isn't cooling")
    (card,) = _steps(events)
    assert [(s.domain, s.title) for s in card.web_sources] == [
        ("www.samsung.com", "Fridge not cooling")
    ]
    assert card.citations == []
    prompt = str(llm.calls_for("planner")[0].messages[0].content)
    assert f'<finding id="{WEB.id}"' in prompt and "(none)" in prompt
    responder = str(llm.calls_for("responder")[0].messages[0].content)
    assert "unofficial web page" in responder
    supervisor = str(llm.calls_for("supervisor")[0].messages[0].content)
    assert WEB.claim in supervisor  # grounded in what the page says
    snapshot = await agent.snapshot("conv-1")
    assert any("risk_level=medium" in d["reason"] for d in snapshot.decision_log)


async def test_a_blocked_reply_does_not_count_as_asking() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [
                PlanDraft(
                    items=[
                        PlanDraftItem(
                            instruction="Check the door seal.", citation_ids=["samsung-fd1:1"]
                        )
                    ]
                )
            ],
            "responder": [AgentReply(message="Draft one."), AgentReply(message="Draft two.")],
            "supervisor": [FAIL, FAIL],
        }
    )
    agent = _agent(llm, Library())
    events = await _send(agent, "My Samsung fridge isn't cooling")
    assert _text(events) == BLOCKED_REPLY  # no request for the model number after it
    state = await agent.state("conv-1")
    assert state is not None and state.state.model_asked == []
