"""The per-turn LangGraph graph (spec §7.3, M3-02).

    load_context → perceive → understand → step_executor → respond → supervise ─pass/block→ emit
                                                              ↑__________revise (once)___|

`step_executor` runs the pure journey engine (`transition()`, which also applies the hazard,
scope and routing guardrails of spec §7.3 `guard_input`/`route`) and then `act` for the step's
actions. Nodes stream `AgentEvent`s through LangGraph's custom stream; the graph state is
checkpointed per conversation (`thread_id` = conversation id).
"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from homehelper.agent.deps import AgentDeps, record
from homehelper.agent.nodes.act import step_and_act
from homehelper.agent.nodes.emit import emit
from homehelper.agent.nodes.mcp_actions import load_profile
from homehelper.agent.nodes.perceive import perceive
from homehelper.agent.nodes.respond import respond
from homehelper.agent.nodes.understand import understand
from homehelper.agent.state import AgentState
from homehelper.agent.supervisor import after_supervise, supervise
from homehelper.agent.turn import CHECKPOINT_TYPES, GraphState
from homehelper.channels.events import StatusEvent

Update = dict[str, Any]  # a node's partial state update


def checkpoint_serde() -> JsonPlusSerializer:
    """Revive only our own state types from checkpoints (LangGraph's strict msgpack mode)."""
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)


def build_graph(
    deps: AgentDeps, checkpointer: BaseCheckpointSaver | None
) -> CompiledStateGraph[GraphState]:
    async def load_context(state: GraphState) -> Update:
        get_stream_writer()(StatusEvent(stage="understanding", label="Reading your message…"))
        message = state.turn.message
        assert message is not None, "every turn starts with a message"
        user_id = state.agent.user_id if state.agent is not None else message.user_id
        profile = await load_profile(deps, user_id)
        if state.agent is None:
            return {
                "agent": AgentState(
                    conversation_id=message.conversation_id,
                    release_id=deps.release_id,
                    user_id=message.user_id,
                    profile=profile,
                )
            }
        if profile == state.agent.profile:
            return {}
        return {"agent": state.agent.model_copy(update={"profile": profile})}

    async def perceive_node(state: GraphState) -> Update:
        message = state.turn.message
        if message is None or not message.attachments:
            return {}
        with deps.span("perceive", input={"attachments": message.attachments}) as span:
            update = await perceive(state, deps, get_stream_writer())
            turn = update.get("turn")
            media = turn.media if turn is not None else []
            record(span, output=[o.model_dump(exclude_none=True) for o in media])
            return update

    async def understand_node(state: GraphState) -> Update:
        with deps.span("understand") as span:
            update = await understand(state, deps)
            turn = update.get("turn")
            nlu = turn.nlu if turn is not None else None
            record(span, output=nlu.model_dump() if nlu else "skipped: card action")
            return update

    async def step_executor(state: GraphState) -> Update:
        # Covers spec §7.3 guard_input/route/step_executor/act: the engine does all of them.
        before = len(state.state.decision_log)
        where = {"journey": state.state.active_journey, "step": state.state.step_id}
        with deps.span("step_executor", input=where) as span:
            update = await step_and_act(state, deps, get_stream_writer())
            agent, turn = update["agent"], update["turn"]
            record(
                span,
                output={
                    "journey": agent.active_journey,
                    "step": agent.step_id,
                    "decisions": [
                        d.model_dump(exclude_none=True) for d in agent.decision_log[before:]
                    ],
                    "fixed_replies": [reply.rule_id for reply in turn.fixed_replies],
                },
            )
            return update

    async def respond_node(state: GraphState) -> Update:
        if state.turn.reply is None:
            get_stream_writer()(StatusEvent(stage="responding", label="Writing a reply…"))
        with deps.span("respond") as span:
            update = await respond(state, deps)
            turn = update.get("turn")
            reply = turn.reply if turn is not None else None
            record(span, output=reply.model_dump() if reply else "skipped: fixed template")
            return update

    async def supervise_node(state: GraphState) -> Update:
        if state.turn.reply is not None:
            get_stream_writer()(StatusEvent(stage="checking", label="Double-checking…"))
        with deps.span("supervise") as span:
            update = await supervise(state, deps)
            turn = update.get("turn")
            verdict = turn.verdict if turn is not None else None
            record(span, output=verdict.model_dump() if verdict else "skipped: fixed template")
            return update

    async def emit_node(state: GraphState) -> Update:
        # The journey is known only now; tag the trace with it from here on (spec §17.1).
        journey = state.state.active_journey or "none"
        with deps.span("emit", tags=[f"journey:{journey}"]):
            return emit(state, deps, get_stream_writer())

    builder = StateGraph(GraphState)
    builder.add_node("load_context", load_context)
    builder.add_node("perceive", perceive_node)
    builder.add_node("understand", understand_node)
    builder.add_node("step_executor", step_executor)
    builder.add_node("respond", respond_node)
    builder.add_node("supervise", supervise_node)
    builder.add_node("emit", emit_node)
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "perceive")
    builder.add_edge("perceive", "understand")
    builder.add_edge("understand", "step_executor")
    builder.add_edge("step_executor", "respond")
    builder.add_edge("respond", "supervise")
    builder.add_conditional_edges("supervise", after_supervise, ["respond", "emit"])
    builder.add_edge("emit", END)
    return builder.compile(checkpointer=checkpointer)
