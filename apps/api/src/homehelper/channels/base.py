"""The channel abstraction (spec §13.1): adapters translate between a transport and the agent's
channel-agnostic `InboundMessage` / `AgentEvent` types. Web is the only channel for now; voice or
LINE would add their own adapter without touching the agent."""

from collections.abc import AsyncIterator
from typing import Protocol

from starlette.responses import Response

from homehelper.channels.events import AgentEvent, Channel, InboundMessage


class ChannelAdapter[PayloadT](Protocol):
    channel: Channel

    def parse_inbound(
        self, payload: PayloadT, *, conversation_id: str, user_id: str | None
    ) -> InboundMessage:
        """Turn a transport payload (already validated by the route) into an `InboundMessage`."""
        ...

    def render(self, events: AsyncIterator[AgentEvent], *, status_code: int = 200) -> Response:
        """Stream the agent's events back over the transport."""
        ...
