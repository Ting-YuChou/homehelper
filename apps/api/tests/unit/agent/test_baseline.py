from homehelper.agent.baseline import BaselineAgent, BaselineReply
from homehelper.channels.events import (
    AgentEvent,
    CardEvent,
    HandoffCard,
    InboundMessage,
    MessageCompletedEvent,
    MessageDeltaEvent,
    StepCard,
    StructuredAction,
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

CHUNK = RetrievedChunk(
    chunk_id="c1",
    text="If the dishwasher does not drain, clean the filter.",
    score=0.9,
    metadata=ChunkMetadata(
        doc_id="bosch-shx68t55",
        category=CategoryId("dishwasher"),
        brand="Bosch",
        section_path=["Troubleshooting"],
        page_start=18,
        page_end=18,
    ),
)


class FakeRetriever:
    def __init__(self, web: list[WebFinding] | None = None) -> None:
        self.queries: list[RetrievalQuery] = []
        self._web = web or []

    async def search(self, query: RetrievalQuery) -> RetrievalResult:
        self.queries.append(query)
        return RetrievalResult(
            query=query, source="manual", chunks=[CHUNK], web_findings=self._web, sufficient=True
        )


async def _turn(agent: BaselineAgent, text: str | None = None, result: str | None = None):
    action = StructuredAction(type="step_result", value=result) if result else None
    message = InboundMessage(conversation_id="c", text=text, action=action)
    return [event async for event in agent.handle(message)]


def _cards(events: list[AgentEvent]) -> list:
    return [event.card for event in events if isinstance(event, CardEvent)]


async def test_step_card_cites_only_retrieved_chunks() -> None:
    llm = FakeLLMClient(
        {
            "responder": [
                BaselineReply(
                    message="Let's check the filter.",
                    step="Clean the filter at the bottom of the tub.",
                    citation_ids=["c1", "invented", "c1"],
                )
            ]
        }
    )
    retriever = FakeRetriever()
    events = await _turn(BaselineAgent(llm, retriever), "My dishwasher won't drain")

    assert retriever.queries[0].query_en == "My dishwasher won't drain"
    assert retriever.queries[0].category is None  # the baseline never filters
    (card,) = _cards(events)
    assert isinstance(card, StepCard)
    assert [(c.chunk_id, c.doc_id, c.page) for c in card.citations] == [
        ("c1", "bosch-shx68t55", 18)
    ]
    completed = events[-1]
    assert isinstance(completed, MessageCompletedEvent)
    assert completed.citations == card.citations
    assert [e.text for e in events if isinstance(e, MessageDeltaEvent)] == [
        "Let's check the filter."
    ]


async def test_prompt_carries_excerpts_and_untrusted_web_but_history_stays_plain() -> None:
    llm = FakeLLMClient(
        {
            "responder": [
                BaselineReply(message="Try the filter.", step="Clean the filter."),
                BaselineReply(message="Great!", outcome="resolved"),
            ]
        }
    )
    web = [WebFinding(claim="Clean the filter monthly.", url="https://www.bosch-home.com/x")]
    agent = BaselineAgent(llm, FakeRetriever(web))
    await _turn(agent, "It won't drain")
    await _turn(agent, result="fixed")

    first, second = llm.calls_for("responder")
    assert first.messages[0].role == "system"
    turn = str(first.messages[-1].content)
    assert '<excerpt id="c1" manual="bosch-shx68t55" page="18">' in turn
    assert 'trust="untrusted"' in turn
    # The button became a sentence, and earlier excerpts are not resent in the history.
    assert "it fixed the problem" in str(second.messages[-1].content)
    history = [str(m.content) for m in second.messages[1:-1]]
    assert history[0] == "It won't drain"
    assert not any("<excerpt" in h for h in history)
    assert (await agent.snapshot("c")).outcome == "resolved"


async def test_query_keeps_the_first_message_and_the_latest_ones() -> None:
    llm = FakeLLMClient({"responder": [BaselineReply(message="ok")] * 4})
    retriever = FakeRetriever()
    agent = BaselineAgent(llm, retriever)
    for text in ["My coffee maker leaks", "two", "three", "four"]:
        await _turn(agent, text)
    assert retriever.queries[-1].query_en == "My coffee maker leaks three four"


async def test_escalation_hands_off_without_a_step() -> None:
    llm = FakeLLMClient(
        {
            "responder": [
                BaselineReply(
                    message="Please stop and call a technician.",
                    step="Open the back panel.",
                    outcome="escalated",
                )
            ]
        }
    )
    agent = BaselineAgent(llm, FakeRetriever())
    events = await _turn(agent, "I smell burning plastic")
    assert [type(card) for card in _cards(events)] == [HandoffCard]
    snapshot = await agent.snapshot("c")
    assert (snapshot.outcome, snapshot.journey) == ("escalated", None)
