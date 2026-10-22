"""MCP tools run by journey step actions (spec §7.4, §12.1): code builds the arguments from the
state, so write tools never depend on what the LLM says.

Each builder returns the arguments, or a `Skip` saying why the action cannot run now (no
signed-in user, no matching appliance, ...). A skipped or failed action is logged as a Decision
and the journey carries on: a tool outage must not stop troubleshooting.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homehelper.agent.deps import AgentDeps
from homehelper.agent.protocol import ToolCall
from homehelper.agent.state import AgentState, Decision
from homehelper.agent.tools import ToolOutcome
from homehelper.agent.turn import GraphState

GUEST_PREFIX = "guest_"


@dataclass(frozen=True)
class Skip:
    reason: str


ArgBuilder = Callable[[GraphState, AgentState], dict[str, Any] | Skip]


def tool_user(state: AgentState) -> str | None:
    """The user MCP tools act for; guests have no profile, so their tools are unavailable."""
    user_id = state.user_id
    if user_id is None or user_id.startswith(GUEST_PREFIX):
        return None
    return user_id


def _slot(state: AgentState, name: str) -> str | None:
    slot = state.slots.get(name)
    return slot.value if slot else None


def _video_args(graph: GraphState, state: AgentState) -> dict[str, Any] | Skip:
    query = graph.search_query or _slot(state, "question") or _slot(state, "symptom")
    if not query:
        return Skip("nothing to search videos for")
    return {
        "query": query[:200],
        "brand": _slot(state, "brand"),
        "category": _slot(state, "appliance_category"),
        "max_results": 3,
    }


def _repair_record_args(graph: GraphState, state: AgentState) -> dict[str, Any] | Skip:
    if tool_user(state) is None:
        return Skip("no signed-in user")
    return Skip("the issue is not linked to an appliance in the user's profile")


ACTION_ARGS: dict[str, ArgBuilder] = {
    "mcp:tutorials.search_videos": _video_args,
    "mcp:user_profile.add_repair_record": _repair_record_args,
}


def as_tool_call(outcome: ToolOutcome, source: str) -> ToolCall:
    return ToolCall(
        name=outcome.tool,
        arguments=outcome.arguments,
        source="llm" if source == "llm" else "action",
        ok=outcome.ok,
    )


async def run_mcp_action(
    action: str, graph: GraphState, state: AgentState, deps: AgentDeps
) -> ToolOutcome | None:
    """Run one `mcp:` step action; None when it was skipped. Decisions go to `state`."""
    builder = ACTION_ARGS.get(action)
    if deps.tools is None or builder is None:
        reason = "MCP tools are not connected" if deps.tools is None else "no argument builder"
        state.decision_log.append(
            Decision(
                kind="tool", journey=state.active_journey, reason=f"skipped {action}: {reason}"
            )
        )
        return None
    arguments = builder(graph, state)
    if isinstance(arguments, Skip):
        state.decision_log.append(
            Decision(
                kind="tool",
                journey=state.active_journey,
                reason=f"skipped {action}: {arguments.reason}",
            )
        )
        return None
    with deps.span(action, input=arguments) as span:
        outcome = await deps.tools.call_action(action, arguments, user_id=tool_user(state))
        if span is not None:
            span.update(output=outcome.model_dump(exclude={"arguments"}))
    state.decision_log.append(
        Decision(
            kind="tool",
            journey=state.active_journey,
            reason=(
                f"{outcome.tool}: ok" if outcome.ok else f"{outcome.tool} failed: {outcome.error}"
            ),
        )
    )
    return outcome
