"""Journey DSL schema (spec §7.4). Structural checks live here; graph checks live in `loader`."""

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from homehelper.agent.protocol import Outcome
from homehelper.agent.state import Intent

StepType = Literal["collect", "confirm", "system", "guide", "inform", "handoff", "end"]

# Steps that wait for the user; the others act and move on.
INTERACTIVE_STEPS: frozenset[StepType] = frozenset(
    {"collect", "confirm", "guide", "inform", "handoff"}
)
# Step types that may set `outcome` on entry. `handoff` and `inform` set a provisional outcome so
# a conversation the user leaves there is still graded (escalated / resolved).
OUTCOME_STEPS: frozenset[StepType] = frozenset({"end", "handoff", "inform"})

KNOWN_ACTIONS = frozenset({"knowledge.search", "plan.build"})
MCP_TOOL = re.compile(r"^mcp:(?P<server>[a-z][a-z0-9_]*)\.(?P<tool>[a-z][a-z0-9_]*)$")


# MCP tools (spec §12.1). `tools_allowed` is an allowlist of the read tools; write tools run only
# from step actions, never via the LLM. `web_search` is left out on purpose: web content reaches
# the LLM only through the knowledge layer's injection guard (spec §10.6).
MCP_READ_TOOLS = frozenset(
    {
        "mcp:user_profile.get_profile",
        "mcp:user_profile.list_appliances",
        "mcp:user_profile.get_appliance",
        "mcp:user_profile.get_warranty_status",
        "mcp:user_profile.list_repair_history",
        "mcp:parts_catalog.search_parts",
        "mcp:parts_catalog.get_part",
        "mcp:tutorials.search_videos",
        "mcp:service_booking.list_slots",
    }
)
MCP_WRITE_TOOLS = frozenset(
    {
        "mcp:user_profile.add_appliance",
        "mcp:user_profile.add_repair_record",
        "mcp:service_booking.book",
        "mcp:service_booking.cancel",
    }
)
_WRITE_VERB = re.compile(r"^(book|cancel|add|update|delete|remove|set|create)(_|$)")


def is_write_tool(tool: str) -> bool:
    """A known write tool, or any tool whose name starts with a write verb."""
    match = MCP_TOOL.match(tool)
    if not match:
        return False
    return tool in MCP_WRITE_TOOLS or bool(_WRITE_VERB.match(match["tool"]))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SlotSpec(_Strict):
    type: Literal["enum", "text"]
    values: str | list[str] | None = None  # a named value set (e.g. "categories") or a list
    required: bool = False
    ask_policy: Literal["until_filled", "once"] = "until_filled"

    @model_validator(mode="after")
    def _values_match_type(self) -> Self:
        if self.type == "enum" and not self.values:
            raise ValueError("enum slots need `values`")
        if self.type == "text" and self.values is not None:
            raise ValueError("text slots cannot have `values`")
        return self


class Transition(_Strict):
    when: str  # registered predicate name
    to: str  # step id


class Step(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: StepType
    goal: str | None = None
    skip_when: str | None = None
    skip_to: str | None = None  # where to go when `skip_when` holds on entry
    actions: list[str] = Field(default_factory=list)
    tools_allowed: list[str] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    outcome: Outcome | None = None
    template: str | None = None  # fixed reply template id; the LLM responder is skipped

    @model_validator(mode="after")
    def _type_rules(self) -> Self:
        if self.type == "end":
            if self.outcome is None:
                raise ValueError(f"end step {self.id!r} needs an `outcome`")
            if self.transitions:
                raise ValueError(f"end step {self.id!r} cannot have transitions")
            if self.skip_when:
                raise ValueError(f"end step {self.id!r} cannot have `skip_when`")
        elif not self.transitions:
            raise ValueError(f"step {self.id!r} is a dead end: it has no transitions")
        if (self.skip_when is None) != (self.skip_to is None):
            raise ValueError(f"step {self.id!r}: `skip_when` and `skip_to` go together")
        if self.outcome is not None and self.type not in OUTCOME_STEPS:
            raise ValueError(
                f"step {self.id!r}: `outcome` is only allowed on {sorted(OUTCOME_STEPS)}"
            )
        if self.type == "system" and self.tools_allowed:
            raise ValueError(f"system step {self.id!r} produces no reply, so no `tools_allowed`")
        return self


class Journey(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    goal: str
    entry_intents: list[Intent] = Field(default_factory=list)
    entry: str | None = None  # defaults to the first step
    slots: dict[str, SlotSpec] = Field(default_factory=dict)
    guardrails: list[Transition] = Field(default_factory=list)
    steps: list[Step] = Field(min_length=1)

    @property
    def entry_step(self) -> str:
        return self.entry or self.steps[0].id

    def step(self, step_id: str) -> Step:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(f"journey {self.id!r} has no step {step_id!r}")

    def required_slots(self) -> list[str]:
        return [name for name, spec in self.slots.items() if spec.required]
