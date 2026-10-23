"""Regression cases exported from annotations (spec §17.2, M7-02).

This is the contract between the API, which builds a case from a reviewed conversation, and the
eval runner, which replays it: `evals/datasets/regression/<id>.yaml` holds `RegressionCase`
dumps and loads them as `homehelper_evals.cases.EvalCase` (a superset; a test keeps them in
step). The API image ships without the evals package, so the contract lives here.
"""

from datetime import datetime
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from homehelper.agent.protocol import Outcome
from homehelper.channels.events import StructuredAction
from homehelper.quality.schemas import IssueType

MAX_REPLAY_TURNS = 12  # = the eval runner's MAX_TURNS


class ScriptedTurn(BaseModel):
    """One user message of a replayed conversation: typed text, a card button press, or both.
    A turn with neither must send media (a photo-only message)."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    action: StructuredAction | None = None


def empty_turns(turns: list[ScriptedTurn | str], media_turns: set[int]) -> list[int]:
    """Indexes of scripted turns that would send nothing at all."""
    return [
        index
        for index, turn in enumerate(turns)
        if index not in media_turns
        and (
            not turn.strip() if isinstance(turn, str) else not turn.text.strip() and not turn.action
        )
    ]


class ReplayMedia(BaseModel):
    """A photo or video sent with one of the scripted turns, under `data/media/` (git-ignored)."""

    model_config = ConfigDict(extra="forbid")

    turn: int  # 0-based index into user_turns
    path: str


class RegressionAssertions(BaseModel):
    """What the replayed reply must (not) do; a subset of the eval runner's `Assertions`."""

    model_config = ConfigDict(extra="forbid")

    forbidden_text: list[str] = Field(default_factory=list)
    forbid_step_cards: bool = False
    required_cards: list[str] = Field(default_factory=list)
    forbidden_cards: list[str] = Field(default_factory=list)
    max_step_cards_per_reply: int | None = Field(default=None, ge=1)
    # Graded by the LLM judge on the last reply; usually the reviewer's expected response.
    expected_behavior: str | None = Field(default=None, max_length=4000)


class RegressionSource(BaseModel):
    """Where a case came from, so a failure can be traced back to the reviewed conversation."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    message_id: str  # the annotated assistant reply
    annotation_id: str
    release_id: str
    issue_types: list[IssueType] = Field(default_factory=list)
    exported_at: datetime


class RegressionCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^reg-[a-z0-9-]{1,60}$")
    kind: Literal["regression"] = "regression"
    user_id: str | None = None  # the demo user, so profile tools see the same data; None = guest
    scenario: str  # context for the judge; no simulator runs on a replay
    user_turns: list[ScriptedTurn] = Field(min_length=1, max_length=MAX_REPLAY_TURNS)
    media: list[ReplayMedia] = Field(default_factory=list)
    expected_outcomes: list[Outcome] = Field(default_factory=list)  # empty: not checked
    expected_doc_id: str | None = None
    assertions: RegressionAssertions = Field(default_factory=RegressionAssertions)
    stop_after_script: Literal[True] = True
    max_turns: int = Field(default=MAX_REPLAY_TURNS, ge=1, le=MAX_REPLAY_TURNS)
    source: RegressionSource
    notes: str | None = None

    @model_validator(mode="after")
    def _turns_send_something(self) -> Self:
        empty = empty_turns(list(self.user_turns), {m.turn for m in self.media})
        if empty:
            raise ValueError(f"user turns {empty} need text, an action or media")
        if any(not 0 <= m.turn < len(self.user_turns) for m in self.media):
            raise ValueError("media must be sent with one of the user_turns")
        return self


def case_yaml(case: RegressionCase) -> str:
    """The file `evals regression pull` writes to `evals/datasets/regression/<id>.yaml`."""
    data = case.model_dump(mode="json", exclude_defaults=True)
    header = (
        f"# Regression case exported from annotation {case.source.annotation_id} "
        f"(conversation {case.source.conversation_id}, release {case.source.release_id}).\n"
        "# Replayed by `uv run evals run --suite regression`; spec §17.2.\n"
    )
    return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
