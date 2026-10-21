import asyncio
from collections.abc import AsyncIterator

import pytest
from pydantic import ValidationError

from homehelper.channels.events import (
    AgentEvent,
    CardEvent,
    MessageCompletedEvent,
    MessageDeltaEvent,
    StatusEvent,
    StepCard,
    StructuredAction,
)
from homehelper.channels.web import (
    SendMessageRequest,
    WebChannelAdapter,
    encode_event,
    with_heartbeat,
)
from homehelper.conversations.service import MessageAssembler
from homehelper.knowledge.schemas import Citation


async def _events(*events: AgentEvent, pause_s: float = 0.0) -> AsyncIterator[AgentEvent]:
    for event in events:
        await asyncio.sleep(pause_s)
        yield event


def test_event_type_is_the_sse_event_name() -> None:
    wire = encode_event(MessageDeltaEvent(message_id="msg_1", text="Hi"))
    assert wire == (
        b'event: message.delta\ndata: {"type":"message.delta","message_id":"msg_1","text":"Hi"}\n\n'
    )


async def test_heartbeat_is_sent_while_the_agent_is_idle() -> None:
    status = StatusEvent(stage="retrieving", label="Checking the manual")
    chunks = [
        chunk async for chunk in with_heartbeat(_events(status, pause_s=0.05), interval_s=0.01)
    ]
    assert chunks[0] == b": ping\n\n"
    assert chunks[-1] == encode_event(status)


async def test_no_heartbeat_when_events_keep_coming() -> None:
    status = StatusEvent(stage="understanding", label="Reading your message")
    chunks = [chunk async for chunk in with_heartbeat(_events(status, status), interval_s=1)]
    assert chunks == [encode_event(status)] * 2


async def test_render_sets_streaming_headers() -> None:
    response = WebChannelAdapter().render(_events())
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


def test_parse_inbound_strips_text_and_keeps_the_action() -> None:
    payload = SendMessageRequest(
        text="  it's fixed ", action=StructuredAction(type="step_result", value="fixed")
    )
    inbound = WebChannelAdapter().parse_inbound(payload, conversation_id="conv_1", user_id="u1")
    assert inbound.text == "it's fixed"
    assert inbound.channel == "web"
    assert inbound.action == payload.action
    assert inbound.user_id == "u1"


@pytest.mark.parametrize("body", [{}, {"text": "   "}, {"text": "x" * 4001}])
def test_send_message_request_rejects_empty_or_huge_messages(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SendMessageRequest.model_validate(body)


def test_assembler_joins_deltas_and_cards_per_message() -> None:
    citation = Citation(chunk_id="c1", doc_id="bosch-shx68t55", page=12)
    card = StepCard(plan_item_id="p1", index=1, total=3, instruction="Check the latch.")
    assembler = MessageAssembler()
    for event in (
        MessageDeltaEvent(message_id="m1", text="First, "),
        CardEvent(message_id="m1", card=card),
        MessageDeltaEvent(message_id="m1", text="check the door."),
    ):
        assembler.add(event)
    message = assembler.complete(
        MessageCompletedEvent(message_id="m1", citations=[citation]), "conv_1"
    )
    assert message.content == "First, check the door."
    assert message.role == "assistant"
    assert message.cards == [card.model_dump(mode="json")]
    assert message.citations == [citation.model_dump(mode="json")]
    assert assembler.drafts == {}
