"""Regression cases exported from annotations (spec §17.2, M7-02).

This is the contract between the API, which builds a case from a reviewed conversation, and the
eval runner, which replays it: `evals/datasets/regression/<id>.yaml` holds `RegressionCase`
dumps and loads them as `homehelper_evals.cases.EvalCase` (a superset; a test keeps them in
step). The API image ships without the evals package, so the contract lives here.
"""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from homehelper.agent.protocol import Outcome
from homehelper.channels.events import StructuredAction
from homehelper.quality.schemas import IssueType

MAX_REPLAY_TURNS = 12  # = the eval runner's MAX_TURNS


class ScriptedTurn(BaseModel):
    """One user message of a replayed conversation: typed text, a card button press, or both."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    action: StructuredAction | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not self.text.strip() and self.action is None:
            raise ValueError("a scripted turn needs text or an action")
        return self


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
