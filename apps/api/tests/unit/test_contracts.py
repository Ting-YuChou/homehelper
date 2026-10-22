from pydantic import TypeAdapter

from homehelper.channels.events import AgentEvent, CardEvent, IssuesCard, StepCard
from homehelper.knowledge.schemas import (
    CategoryId,
    ChunkMetadata,
    Citation,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
)

EVENTS: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)


def test_agent_events_round_trip_through_discriminator() -> None:
    raw = {
        "type": "card",
        "message_id": "msg_1",
        "card": {
            "type": "step",
            "plan_item_id": "p2",
            "index": 2,
            "total": 5,
            "instruction": "Clean the drain pump filter.",
        },
    }
    event = EVENTS.validate_python(raw)
    assert isinstance(event, CardEvent)
    assert isinstance(event.card, StepCard)
    assert event.card.actions == ["fixed", "not_fixed", "cannot_do"]
    assert EVENTS.validate_json(EVENTS.dump_json(event)) == event


def test_issues_card_round_trips() -> None:
    raw = {
        "type": "card",
        "message_id": "msg_1",
        "card": {"type": "issues", "issues": [{"issue_id": "iss_1", "summary": "LG dryer: noisy"}]},
    }
    event = EVENTS.validate_python(raw)
    assert isinstance(event, CardEvent) and isinstance(event.card, IssuesCard)
    assert EVENTS.validate_json(EVENTS.dump_json(event)) == event


def test_citation_from_chunk_uses_last_heading_and_first_page() -> None:
    chunk = RetrievedChunk(
        chunk_id="c1",
        text="...",
        score=0.9,
        metadata=ChunkMetadata(
            doc_id="lg-wm3400",
            category=CategoryId.WASHING_MACHINE,
            brand="LG",
            section_path=["Troubleshooting", "Error codes"],
            page_start=41,
            page_end=42,
            chunk_type="error_code",
        ),
    )
    assert Citation.from_chunk(chunk) == Citation(
        chunk_id="c1", doc_id="lg-wm3400", page=41, section="Error codes"
    )
    result = RetrievalResult(
        query=RetrievalQuery(query_en="OE error"), source="manual", chunks=[chunk]
    )
    assert result.chunk_ids() == {"c1"}
