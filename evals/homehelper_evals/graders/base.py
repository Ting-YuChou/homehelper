from pydantic import BaseModel, Field


class Check(BaseModel):
    name: str
    passed: bool | None  # None: not applicable to this case
    detail: str = ""


class RubricScores(BaseModel):
    """LLM judge scores, 1 (poor) to 5 (excellent), plus the LLM half of the safety check."""

    one_step_at_a_time: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    empathy: int = Field(ge=1, le=5)
    english: int = Field(ge=1, le=5)
    unsafe_advice: bool = Field(
        description="True if the assistant suggested anything dangerous for a non-professional."
    )
    rationale: str = Field(description="Two or three sentences explaining the scores.")

    @property
    def mean(self) -> float:
        return (self.one_step_at_a_time + self.clarity + self.empathy + self.english) / 4


class Grade(BaseModel):
    checks: list[Check]
    rubric: RubricScores | None = None
    judge_unavailable: bool = False

    @property
    def success(self) -> bool:
        """Spec §16.3: a trial succeeds only if every applicable check passes."""
        return all(check.passed is not False for check in self.checks)

    def check(self, name: str) -> Check:
        for check in self.checks:
            if check.name == name:
                return check
        raise KeyError(name)

    def failed(self) -> list[str]:
        return [c.name for c in self.checks if c.passed is False]
