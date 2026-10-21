"""Builders for fixed cases and transcripts, for unit tests (like FakeLLMClient for the LLM)."""

from typing import Any

from homehelper.agent.protocol import AgentSnapshot, ToolCall
from homehelper_evals.cases import EvalCase
from homehelper_evals.transcript import AgentTurn, EndReason, Transcript, UserTurn


def make_case(**overrides: Any) -> EvalCase:
    values: dict[str, Any] = {
        "id": "case-1",
        "kind": "scenario",
        "category": "dishwasher",
        "brand": "Bosch",
        "scenario": "The dishwasher does not drain.",
        "solution_steps": ["Check the drain hose for kinks.", "Clean the filter."],
        "root_cause_step": 2,
        "expected_outcomes": ["resolved"],
        **overrides,
    }
    return EvalCase.model_validate(values)


def make_transcript(
    *turns: UserTurn | AgentTurn,
    outcome: str | None = "resolved",
    end_reason: EndReason = "outcome",
    tool_calls: list[str] | None = None,
) -> Transcript:
    return Transcript(
        case_id="case-1",
        trial=0,
        conversation_id="conv-1",
        turns=list(turns),
        end_reason=end_reason,
        snapshot=AgentSnapshot(
            conversation_id="conv-1",
            outcome=outcome,  # type: ignore[arg-type]
            tool_calls=[ToolCall(name=name) for name in tool_calls or []],
        ),
    )
