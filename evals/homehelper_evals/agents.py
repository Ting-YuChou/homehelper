"""Stand-in `AgentRuntime`s so the eval pipeline runs end to end before the real agents exist.

- `EchoAgent`: repeats the user; never reaches an outcome. Exercises turn limits and errors.
- `OracleStubAgent`: walks the case's own `solution_steps` as step cards and reacts to hazards
  with fixed keyword rules. It reads the hidden answer key, so its scores mean nothing about
  agent quality; it exists to exercise the simulator, graders and runner (M2-03, M2-05).

The runner builds agents through an `AgentFactory`, which receives the case so per-case fixtures
(e.g. mock web results) can be wired in. A real runtime ignores the case and returns one shared
instance.
"""

import importlib
import re
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from homehelper.agent.protocol import AgentRuntime, AgentSnapshot, Outcome
from homehelper.channels.events import (
    AgentEvent,
    CardEvent,
    HandoffCard,
    InboundMessage,
    MessageCompletedEvent,
    MessageDeltaEvent,
    SafetyCard,
    StatusEvent,
    StepCard,
)
from homehelper.core.config import Settings
from homehelper.llm.litellm_client import UsageSink
from homehelper_evals.cases import EvalCase

AgentFactory = Callable[[EvalCase], AgentRuntime]


@dataclass
class AgentContext:
    """What the runner hands an agent builder: settings, and the sink its LLM client must report
    usage to so that cost is attributed to the right conversation."""

    settings: Settings
    usage_sink: UsageSink


def _reply(text: str, *cards, journey: str | None = None) -> list[AgentEvent]:
    message_id = f"msg_{uuid.uuid4().hex[:8]}"
    events: list[AgentEvent] = [
        StatusEvent(stage="responding", label="Writing a reply"),
        MessageDeltaEvent(message_id=message_id, text=text),
    ]
    events.extend(CardEvent(message_id=message_id, card=card) for card in cards)
    events.append(MessageCompletedEvent(message_id=message_id, journey=journey))
    return events


class EchoAgent:
    def __init__(self) -> None:
        self._turns: dict[str, int] = {}

    async def handle(self, message: InboundMessage) -> AsyncIterator[AgentEvent]:
        self._turns[message.conversation_id] = self._turns.get(message.conversation_id, 0) + 1
        said = message.text or (message.action.value if message.action else "")
        for event in _reply(f"You said: {said}"):
            yield event

    async def snapshot(self, conversation_id: str) -> AgentSnapshot:
        return AgentSnapshot(conversation_id=conversation_id)


# Keyword hazard rules, a rough copy of spec §8.1 for the stub only (the real guardrails live in
# homehelper.agent.guardrails).
_HAZARDS: list[tuple[str, re.Pattern[str]]] = [
    ("gas_smell", re.compile(r"\b(gas|rotten egg|propane)\b", re.I)),
    ("smoke_or_burning", re.compile(r"\b(smok\w*|burn\w*|spark\w*|flame\w*|fire|melt\w*)\b", re.I)),
    (
        "high_voltage_internal",
        re.compile(r"\b(capacitor|magnetron|high.voltage|transformer)\b", re.I),
    ),
    ("refrigerant", re.compile(r"\b(refrigerant|freon|coolant|sealed system)\b", re.I)),
    ("injury", re.compile(r"\b(shock\w*|bleed\w*|cut my|burned my|injur\w*)\b", re.I)),
]
_POWER_OFF_AND_WAIT = [
    "If it is safe to do so, unplug the appliance or switch off its circuit breaker.",
    "Do not use the appliance until a qualified technician checks it.",
]
_SAFETY_INSTRUCTIONS = {
    # A gas leak is the one hazard where touching plugs or switches is itself dangerous.
    "gas_smell": [
        "Do not touch electrical switches, plugs, or anything that could make a spark.",
        "Open windows and doors, leave the building, and call your gas company from outside.",
    ],
    "smoke_or_burning": _POWER_OFF_AND_WAIT,
    "high_voltage_internal": [
        "Do not open the appliance; high-voltage parts can kill even unplugged."
    ],
    "refrigerant": ["Refrigerant and sealed-system work needs a certified technician."],
    "injury": [
        "Take care of the injury first and seek medical help if needed.",
        *_POWER_OFF_AND_WAIT,
    ],
}
_WATER_ELECTRIC = re.compile(
    r"(water|wet|flood\w*|puddle|leak\w*).*(outlet|cord|plug|power strip|socket|wiring)"
    r"|(outlet|cord|plug|power strip|socket|wiring).*(water|wet|flood\w*|puddle|leak\w*)",
    re.I,
)
_APPLIANCE = re.compile(
    r"\b(dish\s?washer|wash\w*|dryer|fridge|refrigerator|freezer|microwave|coffee|espresso|"
    r"blender|food processor|nutribullet|vacuum|roomba|tv|television|water (filter|purifier)|"
    r"purifier|filter|keurig|ice maker|front loader|appliance)\b",
    re.I,
)
_FIXED = re.compile(r"\b(fixed|works?|working|worked|solved)\b", re.I)


@dataclass
class _Conversation:
    next_step: int = 0
    outcome: Outcome | None = None
    hazard_flags: list[str] = field(default_factory=list)
    safety_noted: bool = False


class OracleStubAgent:
    def __init__(self, case: EvalCase) -> None:
        self._case = case
        self._conversations: dict[str, _Conversation] = {}

    async def handle(self, message: InboundMessage) -> AsyncIterator[AgentEvent]:
        state = self._conversations.setdefault(message.conversation_id, _Conversation())
        for event in self._respond(state, message):
            yield event

    async def snapshot(self, conversation_id: str) -> AgentSnapshot:
        state = self._conversations.get(conversation_id, _Conversation())
        return AgentSnapshot(
            conversation_id=conversation_id,
            outcome=state.outcome,
            hazard_flags=state.hazard_flags,
        )

    def _respond(self, state: _Conversation, message: InboundMessage) -> list[AgentEvent]:
        text = message.text or ""
        for hazard, pattern in _HAZARDS:
            if pattern.search(text):
                state.hazard_flags.append(hazard)
                state.outcome = "escalated"
                return _reply(
                    "For your safety, please stop here and do not try to repair this yourself.",
                    SafetyCard(hazard=hazard, instructions=_SAFETY_INSTRUCTIONS[hazard]),
                    HandoffCard(reason=hazard, booking_available=False),
                    journey="escalate",
                )
        safety_card = None
        if _WATER_ELECTRIC.search(text) and not state.safety_noted:
            state.safety_noted = True
            state.hazard_flags.append("water_near_electric")
            safety_card = SafetyCard(
                hazard="water_near_electric",
                instructions=["Switch off the circuit breaker before touching anything wet."],
            )
        if message.action is None and state.next_step == 0 and not _APPLIANCE.search(text):
            state.outcome = "out_of_scope"
            return _reply(
                "I can only help with home appliance problems. Is there an appliance I can "
                "help you with?",
                journey="out_of_scope",
            )

        if message.action is not None:
            fixed = message.action.value == "fixed"
        else:
            fixed = (
                state.next_step > 0
                and bool(_FIXED.search(text))
                and not re.search(r"\b(not|n't|still)\b", text, re.I)
            )
        if fixed:
            state.outcome = "resolved"
            return _reply("Great, glad that fixed it!", journey="troubleshoot")

        steps = self._case.solution_steps
        if state.next_step >= len(steps):
            state.outcome = "escalated"
            return _reply(
                "We have tried every step I have. I recommend a technician visit.",
                HandoffCard(reason="steps_exhausted", booking_available=False),
                journey="troubleshoot",
            )
        state.next_step += 1
        card = StepCard(
            plan_item_id=f"p{state.next_step}",
            index=state.next_step,
            total=len(steps),
            instruction=steps[state.next_step - 1],
        )
        cards = [c for c in (safety_card, card) if c is not None]
        return _reply("Let's try this next.", *cards, journey="troubleshoot")


def load_agent_factory(name: str, context: AgentContext) -> AgentFactory:
    """`echo`, `stub`, or `package.module:callable`, where the callable takes an AgentContext and
    returns an AgentFactory (how the journey and baseline agents plug in)."""
    if name == "echo":
        shared = EchoAgent()
        return lambda case: shared
    if name == "stub":
        return OracleStubAgent
    module_name, _, attr = name.partition(":")
    if not attr:
        raise ValueError(f"unknown agent {name!r}; use echo, stub, or module:callable")
    builder = getattr(importlib.import_module(module_name), attr)
    return builder(context)
