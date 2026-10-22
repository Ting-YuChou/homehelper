"""A scripted `AgentRuntime` for API and UI development before the journey agent exists.

It makes no LLM or retrieval calls. A conversation walks a fixed three-step dishwasher plan:
the first message gets step 1, a "not fixed"/"can't do" answer gets the next step, "fixed" ends
it as resolved, and running out of steps hands off. A message mentioning gas, smoke, sparks or
burning gets the safety card and a handoff. State lives in memory only.
"""

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from homehelper.agent.protocol import AgentSnapshot, Outcome
from homehelper.channels.events import (
    AgentEvent,
    Card,
    CardEvent,
    HandoffCard,
    InboundMessage,
    MessageCompletedEvent,
    MessageDeltaEvent,
    SafetyCard,
    StatusEvent,
    StepCard,
)
from homehelper.knowledge.schemas import Citation

JOURNEY = "troubleshoot"
DOC_ID = "bosch-shx68t55"
PLAN = [
    ("Check that the door is fully latched and the child lock is off.", 12),
    ("Clean the filter at the bottom of the tub, then restart a cycle.", 18),
    ("Turn the breaker off for one minute to reset the control board.", 21),
]
HAZARD = re.compile(r"\b(gas|smoke|smoking|sparks?|burning)\b", re.I)


@dataclass
class _Conversation:
    cursor: int = 0  # index of the step being shown
    started: bool = False
    outcome: Outcome | None = None
    step: str | None = None


class StubAgent:
    def __init__(self) -> None:
        self._conversations: dict[str, _Conversation] = {}

    async def handle(self, message: InboundMessage) -> AsyncIterator[AgentEvent]:
        conv = self._conversations.setdefault(message.conversation_id, _Conversation())
        yield StatusEvent(stage="understanding", label="Reading your message")
        text, cards = self._turn(conv, message)
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        yield MessageDeltaEvent(message_id=message_id, text=text)
        for card in cards:
            yield CardEvent(message_id=message_id, card=card)
        citations = [c for card in cards if isinstance(card, StepCard) for c in card.citations]
        yield MessageCompletedEvent(
            message_id=message_id, citations=citations, journey=JOURNEY, step=conv.step
        )

    async def snapshot(self, conversation_id: str) -> AgentSnapshot:
        conv = self._conversations.get(conversation_id, _Conversation())
        return AgentSnapshot(
            conversation_id=conversation_id,
            outcome=conv.outcome,
            journey=JOURNEY if conv.started else None,
            step=conv.step,
        )

    def _turn(self, conv: _Conversation, message: InboundMessage) -> tuple[str, list[Card]]:
        if conv.outcome is not None:
            return "This conversation has ended. Start a new one for another problem.", []
        if message.text and HAZARD.search(message.text):
            return self._end(
                conv,
                "escalated",
                "That could be dangerous, so let's stop troubleshooting here.",
                SafetyCard(
                    hazard="smoke_or_burning",
                    instructions=[
                        "If it is safe to do so, unplug the appliance or switch off its breaker.",
                        "Do not use it until a qualified technician checks it.",
                    ],
                ),
                HandoffCard(reason="Possible electrical hazard", booking_available=True),
            )
        if not conv.started:
            conv.started = True
            opening = "Let's work through this one step at a time."
            if message.attachments:
                opening = "Thanks for the photo; this demo can't look at it yet. " + opening
            return opening, [self._step(conv)]

        if message.action is not None and message.action.type in ("resume_issue", "close_issue"):
            # The scripted demo has one problem, so it never offers an issues card.
            return "Let's keep going with this one.", [self._step(conv)]
        result = message.action.value if message.action else (message.text or "").lower()
        if "fixed" in result and "not" not in result:
            return self._end(conv, "resolved", "Great, glad it's working again!")
        conv.cursor += 1
        if conv.cursor >= len(PLAN):
            return self._end(
                conv,
                "escalated",
                "We've tried everything the manual suggests. A technician should take a look.",
                HandoffCard(reason="All troubleshooting steps tried", booking_available=True),
            )
        return "Thanks for trying that. Here's the next step.", [self._step(conv)]

    def _step(self, conv: _Conversation) -> StepCard:
        conv.step = "guide"
        instruction, page = PLAN[conv.cursor]
        return StepCard(
            plan_item_id=f"p{conv.cursor + 1}",
            index=conv.cursor + 1,
            total=len(PLAN),
            instruction=instruction,
            citations=[Citation(chunk_id=f"stub-{page}", doc_id=DOC_ID, page=page)],
        )

    def _end(
        self, conv: _Conversation, outcome: Outcome, text: str, *cards: Card
    ) -> tuple[str, list[Card]]:
        conv.started = True
        conv.outcome = outcome
        conv.step = "escalate" if outcome == "escalated" else "resolved"
        return text, list(cards)
