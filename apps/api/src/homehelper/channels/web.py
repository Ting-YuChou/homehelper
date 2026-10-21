"""Web channel: JSON in, Server-Sent Events out (spec §13.3).

Each `AgentEvent` becomes one SSE event whose `event:` field is the event `type` and whose `data:`
is the event as JSON. A comment line is sent after 15 s without events so Cloud Run and proxies keep
the connection open; buffering is disabled with `X-Accel-Buffering: no`.
"""

import asyncio
from collections.abc import AsyncIterator, Mapping

from fastapi.sse import KEEPALIVE_COMMENT, format_sse_event
from pydantic import BaseModel, Field, model_validator
from starlette.responses import StreamingResponse

from homehelper.channels.events import AgentEvent, Channel, InboundMessage, StructuredAction

HEARTBEAT_S = 15.0
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
MAX_TEXT_CHARS = 4000
MAX_ATTACHMENTS = 4


class SSEResponse(StreamingResponse):
    """`text/event-stream` for a stream we encode ourselves. (FastAPI's `EventSourceResponse` as a
    route's `response_class` expects the endpoint itself to be a generator.)"""

    media_type = "text/event-stream"


class SendMessageRequest(BaseModel):
    """Body of `POST /v1/conversations/{id}/messages`: text, attachment ids, or a card action."""

    text: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    attachments: list[str] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)
    action: StructuredAction | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "SendMessageRequest":
        if not (self.text and self.text.strip()) and not self.attachments and self.action is None:
            raise ValueError("a message needs text, an attachment or an action")
        return self


def encode_event(event: AgentEvent) -> bytes:
    return format_sse_event(event=event.type, data_str=event.model_dump_json())


async def _next[T](iterator: AsyncIterator[T]) -> T:
    return await anext(iterator)


async def with_heartbeat(
    events: AsyncIterator[AgentEvent], *, interval_s: float = HEARTBEAT_S
) -> AsyncIterator[bytes]:
    """Encode events, inserting a heartbeat comment whenever the stream is idle for `interval_s`.

    The pending read is never cancelled by a heartbeat, only when the client goes away.
    """
    pending: asyncio.Task[AgentEvent] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(_next(events))
            done, _ = await asyncio.wait({pending}, timeout=interval_s)
            if not done:
                yield KEEPALIVE_COMMENT
                continue
            task, pending = pending, None
            try:
                event = task.result()
            except StopAsyncIteration:
                return
            yield encode_event(event)
    finally:
        if pending is not None:
            pending.cancel()


class WebChannelAdapter:
    channel: Channel = "web"

    def __init__(self, *, heartbeat_s: float = HEARTBEAT_S) -> None:
        self.heartbeat_s = heartbeat_s

    def parse_inbound(
        self, payload: SendMessageRequest, *, conversation_id: str, user_id: str | None
    ) -> InboundMessage:
        return InboundMessage(
            conversation_id=conversation_id,
            channel=self.channel,
            text=payload.text.strip() if payload.text else None,
            attachments=payload.attachments,
            action=payload.action,
            user_id=user_id,
        )

    def render(
        self,
        events: AsyncIterator[AgentEvent],
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> SSEResponse:
        return SSEResponse(
            with_heartbeat(events, interval_s=self.heartbeat_s),
            status_code=status_code,
            headers={**SSE_HEADERS, **(headers or {})},
        )
