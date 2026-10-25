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
from homehelper.knowledge.features import ManualIndex
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
    assert "do not ask about any of these yourself" in str(
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


# --- review findings ------------------------------------------------------------------------


class Appears(Library):
    """No chunks on the first search, two per manual afterwards."""

    async def search(self, query: RetrievalQuery) -> RetrievalResult:
        self.chunks = bool(self.queries)
        return await super().search(query)


def _says(**slots: str) -> NLUResult:
    return NLUResult(
        intent="other", slot_updates=[SlotUpdate(name=k, value=v) for k, v in slots.items()]
    )


def _plan(*ids: str) -> PlanDraft:
    return PlanDraft(items=[PlanDraftItem(instruction=f"Step {i}.", citation_ids=[i]) for i in ids])


async def _step_after(agent: JourneyAgent) -> str | None:
    state = await agent.state("conv-1")
    assert state is not None
    return state.state.step_id


async def test_a_hazard_at_a_no_plan_handoff_keeps_it_whatever_comes_next() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [
                REPORT,
                NLUResult(intent="report_problem", hazard_signals=["smoke_or_burning"]),
                _says(trait_layout="side_by_side"),
            ],
            "planner": [_plan("samsung-sbs:1")],
            "responder": [AgentReply(message=x) for x in "abc"],
            "supervisor": [PASS] * 4,
        }
    )
    agent = _agent(llm, Appears(chunks=False))
    await _send(agent, "My Samsung fridge isn't cooling")
    assert await _step_after(agent) == "escalate"
    await _send(agent, "Now there's smoke coming from the back")
    third = await _send(agent, "It's a side by side")
    assert await _step_after(agent) == "escalate" and not _steps(third)


async def test_a_technician_request_at_a_no_plan_handoff_keeps_it() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [REPORT, NLUResult(intent="book_technician"), _says(model_number="RF23ABC")],
            "planner": [_plan("samsung-fd1:1")],
            "responder": [AgentReply(message=x) for x in "abc"],
            "supervisor": [PASS] * 4,
        }
    )
    agent = _agent(llm, Appears(chunks=False))
    await _send(agent, "My Samsung fridge isn't cooling")
    await _send(agent, "Just send a technician")
    await _send(agent, "The model is RF23ABC")
    assert await _step_after(agent) == "escalate"


async def test_a_model_number_at_a_no_plan_handoff_diagnoses_again() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [REPORT, _says(model_number="RF23ABC")],
            "planner": [_plan("samsung-fd1:1")],
            "responder": [AgentReply(message=x) for x in "ab"],
            "supervisor": [PASS] * 4,
        }
    )
    agent = _agent(llm, Appears(chunks=False))
    first = await _send(agent, "My Samsung fridge isn't cooling")
    assert "These steps are general" not in _text(first)  # a handoff has no steps
    second = await _send(agent, "The model is RF23ABC")
    assert await _step_after(agent) == "guide"
    assert [c.instruction for c in _steps(second)] == ["Step samsung-fd1:1."]


async def test_a_model_number_naming_the_manual_already_used_changes_nothing() -> None:
    bosch = NLUResult(
        intent="report_problem",
        slot_updates=[
            SlotUpdate(name="appliance_category", value="dishwasher"),
            SlotUpdate(name="brand", value="Bosch"),
            SlotUpdate(name="symptom", value="not draining"),
        ],
        search_query_en="dishwasher not draining",
    )
    llm = FakeLLMClient(
        {
            "nlu": [bosch, _says(model_number="SHX878")],
            "planner": [_plan("bosch-dw:1", "bosch-dw:2")],
            "responder": [AgentReply(message=x) for x in "ab"],
            "supervisor": [PASS] * 4,
        }
    )
    library = Library()
    agent = _agent(llm, library)
    await _send(agent, "My Bosch dishwasher won't drain")
    second = await _send(agent, "It's an SHX878")
    assert len(library.queries) == 1 and len(llm.calls_for("planner")) == 1
    assert [c.plan_item_id for c in _steps(second)] == ["p1"]
    state = await agent.state("conv-1")
    assert state is not None and state.state.plan_basis is not None
    assert state.state.plan_basis.scope == "model"  # recorded, though nothing re-ran


async def test_a_rebuilt_plan_never_reuses_a_shown_steps_id() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [REPORT, _says(trait_layout="side_by_side")],
            "planner": [_plan("samsung-fd1:1", "samsung-fd2:1"), _plan("samsung-sbs:1")],
            "responder": [AgentReply(message=x) for x in "ab"],
            "supervisor": [PASS] * 4,
        }
    )
    agent = _agent(llm, Library())
    first = await _send(agent, "My Samsung fridge isn't cooling")
    second = await _send(agent, "It's a side by side")
    assert [c.plan_item_id for c in _steps(first)] == ["p1"]
    assert [c.plan_item_id for c in _steps(second)] == ["p3"]


async def test_the_last_step_failing_with_a_new_detail_hands_off_for_the_steps() -> None:
    from homehelper.channels.events import HandoffCard, StructuredAction

    bosch = NLUResult(
        intent="report_problem",
        slot_updates=[
            SlotUpdate(name="appliance_category", value="dishwasher"),
            SlotUpdate(name="brand", value="Bosch"),
            SlotUpdate(name="symptom", value="not draining"),
        ],
        search_query_en="dishwasher not draining",
    )
    llm = FakeLLMClient(
        {
            "nlu": [bosch, _says(model_number="XQ9000")],
            "planner": [_plan("bosch-dw:1")],
            "responder": [AgentReply(message=x) for x in "ab"],
            "supervisor": [PASS] * 4,
        }
    )
    agent = _agent(llm, Library())
    await _send(agent, "My Bosch dishwasher won't drain")
    message = InboundMessage(
        conversation_id="conv-1",
        text="That didn't help, the model is XQ9000",
        action=StructuredAction(type="step_result", value="not_fixed"),
    )
    events = [e async for e in agent.handle(message)]
    cards = [e.card for e in events if isinstance(e, CardEvent) and isinstance(e.card, HandoffCard)]
    assert [c.reason for c in cards] == ["The troubleshooting steps did not fix it"]


async def test_giving_the_brand_the_hint_asked_for_searches_again() -> None:
    no_brand = REPORT.model_copy(
        update={"slot_updates": [u for u in REPORT.slot_updates if u.name != "brand"]}
    )
    llm = FakeLLMClient(
        {
            "nlu": [no_brand, _says(brand="Samsung")],
            "planner": [_plan("samsung-fd1:1"), _plan("samsung-fd2:1")],
            "responder": [AgentReply(message=x) for x in "ab"],
            "supervisor": [PASS] * 4,
        }
    )
    library = Library()
    index = manual_index()
    lg = index.manuals[0].model_copy(update={"doc_id": "lg-fr", "brand": "LG"})
    agent = JourneyAgent(
        AgentDeps.default(llm, library, manuals=ManualIndex((*index.manuals, lg), index.features))
    )
    first = await _send(agent, "My fridge isn't cooling")
    assert "the brand and model number" in _text(first)
    await _send(agent, "It's a Samsung")
    assert len(library.queries) == 2
    assert "lg-fr" not in (library.queries[1].doc_ids or [])
