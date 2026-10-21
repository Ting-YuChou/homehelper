"""Baseline agent (M2-06): one LLM call per turn plus RAG, nothing else (spec §16.4).

No journey engine, no NLU, no code guardrails, no supervisor: the retriever gets the user's own
words without metadata filters, and the responder decides everything, including when the
conversation is over. The journey agent's scores are reported against this one.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from homehelper.agent import prompts
from homehelper.agent.deps import Retriever
from homehelper.agent.protocol import AgentSnapshot, Outcome
from homehelper.channels.events import (
    AgentEvent,
    Card,
    CardEvent,
    HandoffCard,
    InboundMessage,
    MessageCompletedEvent,
    MessageDeltaEvent,
    StatusEvent,
    StepCard,
)
from homehelper.knowledge.schemas import Citation, RetrievalQuery, RetrievalResult
from homehelper.knowledge.web import format_for_responder
from homehelper.llm import LLMClient, Message

# A card button is turned into the sentence a user would have typed.
ACTION_TEXT = {
    "fixed": "I tried that and it fixed the problem.",
    "not_fixed": "I tried that step but it did not fix the problem.",
    "cannot_do": "I can't do that step.",
}
# The retrieval query is the user's first message (it usually names the appliance and problem)
# plus their latest ones.
QUERY_TURNS = 3
MAX_QUERY_CHARS = 1000


class BaselineReply(BaseModel):
    """What the user sees this turn."""

    message: str = Field(description="The reply to the user.")
    step: str | None = Field(
        default=None, description="The one troubleshooting step to try now, if any."
    )
    citation_ids: list[str] = Field(
        default_factory=list, description="Ids of the manual excerpts that support the step."
    )
    outcome: Literal["resolved", "escalated", "out_of_scope"] | None = Field(
        default=None, description="Set only when the conversation should end."
    )


@dataclass
class _Conversation:
    history: list[Message] = field(default_factory=list)
    user_texts: list[str] = field(default_factory=list)
    steps_given: int = 0
    outcome: Outcome | None = None


class BaselineAgent:
    def __init__(self, llm: LLMClient, retriever: Retriever) -> None:
        self._llm = llm
        self._retriever = retriever
        self._conversations: dict[str, _Conversation] = {}

    async def handle(self, message: InboundMessage) -> AsyncIterator[AgentEvent]:
        conv = self._conversations.setdefault(message.conversation_id, _Conversation())
        user_text = _user_text(message)
        conv.user_texts.append(user_text)

        yield StatusEvent(stage="retrieving", label="Checking the manuals")
        query = " ".join(_query_texts(conv.user_texts))[:MAX_QUERY_CHARS]
        retrieval = await self._retriever.search(RetrievalQuery(query_en=query))

        yield StatusEvent(stage="responding", label="Writing a reply")
        turn = prompts.render(
            "baseline_turn",
            user_text=user_text,
            excerpts=[
                {
                    "id": chunk.chunk_id,
                    "title": chunk.metadata.doc_id,
                    "page": chunk.metadata.page_start,
                    "text": chunk.text,
                }
                for chunk in retrieval.chunks
            ],
            web_block=format_for_responder(retrieval.web_findings)
            if retrieval.web_findings
            else "",
        )
        reply = await self._llm.structured(
            "responder",
            [
                Message(role="system", content=prompts.render("baseline_system")),
                *conv.history,
                Message(role="user", content=turn),
            ],
            BaselineReply,
        )

        # History keeps the plain user text: old excerpts would only crowd the context.
        conv.history.append(Message(role="user", content=user_text))
        conv.history.append(Message(role="assistant", content=reply.model_dump_json()))
        if reply.outcome is not None:
            conv.outcome = reply.outcome

        citations = _citations(reply.citation_ids, retrieval)
        cards: list[Card] = []
        if reply.step and reply.outcome is None:
            conv.steps_given += 1
            cards.append(
                StepCard(
                    plan_item_id=f"b{conv.steps_given}",
                    index=conv.steps_given,
                    total=conv.steps_given,  # the baseline has no plan, so no known total
                    instruction=reply.step,
                    citations=citations,
                )
            )
        if reply.outcome == "escalated":
            cards.append(HandoffCard(reason="Recommended a technician", booking_available=False))

        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        yield MessageDeltaEvent(message_id=message_id, text=reply.message)
        for card in cards:
            yield CardEvent(message_id=message_id, card=card)
        yield MessageCompletedEvent(message_id=message_id, citations=citations)

    async def snapshot(self, conversation_id: str) -> AgentSnapshot:
        conv = self._conversations.get(conversation_id, _Conversation())
        return AgentSnapshot(conversation_id=conversation_id, outcome=conv.outcome)


def _query_texts(texts: list[str]) -> list[str]:
    if len(texts) <= QUERY_TURNS:
        return texts
    return [texts[0], *texts[-(QUERY_TURNS - 1) :]]


def _user_text(message: InboundMessage) -> str:
    if message.action is not None:
        return ACTION_TEXT.get(message.action.value, message.action.value)
    return message.text or ""


def _citations(ids: list[str], retrieval: RetrievalResult) -> list[Citation]:
    """Keeps only ids that were actually retrieved this turn (an invented id is dropped)."""
    by_id = {chunk.chunk_id: chunk for chunk in retrieval.chunks}
    return [Citation.from_chunk(by_id[i]) for i in dict.fromkeys(ids) if i in by_id]
