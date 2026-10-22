"""`step_executor` + `act` (spec §7.3): run the journey engine, then the step's actions, and keep
going while the engine is at a `system` step (e.g. diagnose → knowledge.search, plan.build).

`plan.build` is M3-07: the planner drafts items from the retrieved excerpts, and code applies
the §7.6 rules (`postprocess_plan`). `mcp:` actions call MCP tools with arguments built by code
(`mcp_actions`); their results are this turn's `tool_results`.
"""

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from homehelper.agent import prompts
from homehelper.agent.deps import AgentDeps, record
from homehelper.agent.engine import TurnInput, transition
from homehelper.agent.engine.perception import media_input
from homehelper.agent.engine.schema import is_write_tool
from homehelper.agent.guardrails import postprocess_plan
from homehelper.agent.guardrails.plan import MAX_PLAN_ITEMS
from homehelper.agent.nodes.mcp_actions import (
    as_tool_call,
    booking_confirmation,
    run_mcp_action,
    similar_repairs,
    warranty_active,
)
from homehelper.agent.nodes.understand import QUERY_INTENTS
from homehelper.agent.state import AgentState, Decision, PlanItem
from homehelper.agent.tools import ToolOutcome
from homehelper.agent.turn import GraphState
from homehelper.channels.events import StatusEvent
from homehelper.knowledge.schemas import CategoryId, Citation, RetrievalQuery, RetrievalResult
from homehelper.llm import Message

MAX_ACTION_ROUNDS = 4  # system steps chained in one turn; the catalog needs at most two
NOTICE_REPAIR_HISTORY = "repair_history"  # an earlier repair looks like this problem
Emit = Callable[[object], None]


class PlanDraftItem(BaseModel):
    instruction: str
    citation_ids: list[str] = Field(default_factory=list)
    requires_disassembly: bool = False
    requires_tools: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    targets_symptom: bool = False  # the excerpts tie this step to this exact symptom


class PlanDraft(BaseModel):
    items: list[PlanDraftItem] = Field(default_factory=list)


def _slot(state: AgentState, name: str) -> str | None:
    slot = state.slots.get(name)
    return slot.value if slot else None


def _category(state: AgentState) -> CategoryId | None:
    value = _slot(state, "appliance_category")
    return CategoryId(value) if value in {c.value for c in CategoryId} else None


def retrieval_query(state: AgentState, text: str) -> RetrievalQuery:
    return RetrievalQuery(
        query_en=text,
        category=_category(state),
        brand=_slot(state, "brand"),
        model_number=_slot(state, "model_number"),
        error_code=_slot(state, "error_code"),
    )


def retrieval_label(state: AgentState) -> str:
    category = _slot(state, "appliance_category")
    what = " ".join(p for p in (_slot(state, "brand"), category) if p).replace("_", " ")
    return f"Checking the {what} manual…" if what else "Checking the manuals…"


def retrieval_summary(retrieval: RetrievalResult) -> dict[str, Any]:
    return {
        "source": retrieval.source,
        "filter_level": retrieval.filter_level,
        "top_score": retrieval.top_score,
        "sufficient": retrieval.sufficient,
        "chunks": [
            {"id": c.chunk_id, "doc_id": c.metadata.doc_id, "page": c.metadata.page_start}
            for c in retrieval.chunks
        ],
        "web_findings": len(retrieval.web_findings),
    }


def rank_draft(items: list[PlanDraftItem]) -> list[PlanDraftItem]:
    """Steps aimed at this symptom go first, disassembly last; otherwise the planner's order.

    G-LOOP-01 stops after `MAX_FAILED_STEPS`, so generic checks ahead of the likely fix cost
    the user the fix itself.
    """
    return sorted(items, key=lambda item: (item.requires_disassembly, not item.targets_symptom))


def plan_summary(items: list[PlanItem]) -> str:
    """One line per item for the decision log, so eval reports show the whole plan."""
    return "; ".join(
        f"{item.id} [{','.join(item.citation_ids)}] {item.instruction[:80]}" for item in items
    )


def _excerpts(retrieval: RetrievalResult) -> list[dict[str, object]]:
    return [
        {
            "id": chunk.chunk_id,
            "manual": chunk.metadata.doc_id,
            "page": chunk.metadata.page_start,
            "text": chunk.text,
        }
        for chunk in retrieval.chunks
    ]


async def build_plan(
    deps: AgentDeps,
    state: AgentState,
    user_said: list[str] | None = None,
    *,
    in_warranty: bool = False,
) -> tuple[list[PlanItem], list[Decision]]:
    retrieval = state.last_retrieval
    if retrieval is None or not retrieval.chunks:
        return [], [
            Decision(kind="plan", journey=state.active_journey, reason="no manual excerpts")
        ]
    category = _slot(state, "appliance_category") or "appliance"
    prompt = prompts.render(
        "planner",
        category=category.replace("_", " "),
        brand=_slot(state, "brand"),
        model_number=_slot(state, "model_number"),
        symptom=_slot(state, "symptom") or retrieval.query.query_en,
        error_code=_slot(state, "error_code"),
        user_said=user_said or [],
        excerpts=_excerpts(retrieval),
        max_items=MAX_PLAN_ITEMS,
    )
    draft = await deps.llm.structured("planner", [Message(role="user", content=prompt)], PlanDraft)
    retrieved = retrieval.chunk_ids()
    items = [
        PlanItem(
            id=f"p{index}",
            instruction=item.instruction,
            # An id the planner invented is not a citation (spec P3).
            citation_ids=[cid for cid in dict.fromkeys(item.citation_ids) if cid in retrieved],
            requires_disassembly=item.requires_disassembly,
            requires_tools=item.requires_tools,
            risk_level=item.risk_level,
        )
        for index, item in enumerate(rank_draft(draft.items), start=1)
    ]
    # `in_warranty` comes from the profile's warranty check (G-WARR-01).
    edit = postprocess_plan(
        items, category=_slot(state, "appliance_category"), in_warranty=in_warranty
    )
    decisions = [
        Decision(
            kind="plan",
            journey=state.active_journey,
            reason=f"planner drafted {len(items)} items; {len(edit.items)} kept",
        ),
        *edit.decisions,
        Decision(
            kind="plan", journey=state.active_journey, reason=f"plan: {plan_summary(edit.items)}"
        ),
    ]
    return edit.items, decisions


async def run_action(
    action: str,
    graph: GraphState,
    state: AgentState,
    deps: AgentDeps,
    emit: Emit,
    outcomes: list[ToolOutcome] | None = None,
) -> AgentState:
    """Run one step action against `state` (mutated and returned); MCP results go to `outcomes`."""
    if action == "knowledge.search":
        text = graph.search_query or _slot(state, "symptom") or _slot(state, "question") or ""
        emit(StatusEvent(stage="retrieving", label=retrieval_label(state)))
        query = retrieval_query(state, text)
        with deps.span("knowledge.search", input=query.model_dump(exclude_none=True)) as span:
            state.last_retrieval = await deps.retriever.search(query)
            record(span, output=retrieval_summary(state.last_retrieval))
        state.decision_log.append(
            Decision(
                kind="plan",
                journey=state.active_journey,
                reason=(
                    f"retrieved {len(state.last_retrieval.chunks)} chunks "
                    f"(source={state.last_retrieval.source}, "
                    f"level={state.last_retrieval.filter_level}, "
                    f"sufficient={state.last_retrieval.sufficient}): "
                    f"{', '.join(c.chunk_id for c in state.last_retrieval.chunks)}"
                ),
            )
        )
    elif action == "plan.build":
        emit(StatusEvent(stage="planning", label="Putting together the steps…"))
        with deps.span("plan.build") as span:
            user_said = [line.text for line in graph.transcript if line.role == "user"]
            if graph.turn.message is not None and graph.turn.message.text:
                user_said.append(graph.turn.message.text)
            state.plan, decisions = await build_plan(
                deps, state, user_said, in_warranty=warranty_active(outcomes or [])
            )
            record(
                span,
                output={
                    "items": [item.instruction for item in state.plan],
                    "edits": [d.reason for d in decisions],
                },
            )
        state.plan_cursor = 0
        state.decision_log.extend(decisions)
    else:
        outcome = await run_mcp_action(action, graph, state, deps)
        if outcome is not None and outcomes is not None:
            outcomes.append(outcome)
    return state


def _remember_citations(graph: GraphState, retrieval: RetrievalResult | None) -> None:
    if retrieval is not None:
        for chunk in retrieval.chunks:
            graph.citations[chunk.chunk_id] = Citation.from_chunk(chunk)


async def step_and_act(graph: GraphState, deps: AgentDeps, emit: Emit) -> dict[str, Any]:
    message = graph.turn.message
    assert message is not None
    turn_input = TurnInput.from_message(message, graph.turn.nlu, media_input(graph.turn.media))
    result = transition(deps.catalog, graph.state, turn_input)
    state = result.state
    nlu = graph.turn.nlu
    # The same rule `understand` uses to store the query.
    fresh_query = nlu is not None and bool(nlu.search_query_en) and nlu.intent in QUERY_INTENTS
    if state.active_issue_id != graph.state.active_issue_id and not fresh_query:
        # The query from an earlier turn was about another issue; search by this one's slots.
        graph = graph.model_copy(update={"search_query": None})
    turn = graph.turn.model_copy(
        update={
            "fixed_replies": list(result.fixed_replies),
            "notices": list(result.notices),
            "side_question": result.side_question,
        }
    )
    graph = graph.model_copy(update={"citations": dict(graph.citations)})
    outcomes: list[ToolOutcome] = []
    if not result.skip_respond:
        for _ in range(MAX_ACTION_ROUNDS):
            for action in result.actions:
                state = await run_action(action, graph, state, deps, emit, outcomes)
            _remember_citations(graph, state.last_retrieval)
            if not result.continue_after_actions:
                break
            result = transition(deps.catalog, state, None)
            state = result.state
            turn.fixed_replies.extend(result.fixed_replies)
            turn.notices.extend(result.notices)
        turn.retrieval = state.last_retrieval
    else:
        # A template replaces the reply (e.g. a hazard escalation), but read tools still run:
        # the visit times offered with it come from them.
        for action in result.actions:
            if action.startswith("mcp:") and not is_write_tool(action):
                state = await run_action(action, graph, state, deps, emit, outcomes)
    turn.tool_results = outcomes
    confirmation = booking_confirmation(outcomes, state)
    if confirmation is not None:
        turn.fixed_replies.append(confirmation)
    if similar_repairs(outcomes, state):
        turn.notices.append(NOTICE_REPAIR_HISTORY)

    how_to = turn.nlu is not None and turn.nlu.intent == "ask_how_to"
    if turn.side_question and how_to and turn.nlu and turn.nlu.search_query_en:
        # Answer a how-to question during another journey without touching its step (§7.4).
        emit(StatusEvent(stage="retrieving", label=retrieval_label(state)))
        query = retrieval_query(state, turn.nlu.search_query_en)
        with deps.span("knowledge.search", input=query.model_dump(exclude_none=True)) as span:
            side = await deps.retriever.search(query)
            record(span, output=retrieval_summary(side))
        _remember_citations(graph, side)
        turn.retrieval = side
    return {
        "agent": state,
        "turn": turn,
        "citations": graph.citations,
        "search_query": graph.search_query,
        "tool_calls": [
            *graph.tool_calls,
            *(as_tool_call(o, "action", state.active_issue_id) for o in outcomes if not o.replayed),
        ],
    }
