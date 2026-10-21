"""The per-turn LangGraph graph (spec §7.3, M3-02).

    load_context → understand → step_executor → respond → supervise ─pass/block→ emit
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

from homehelper.agent.deps import AgentDeps
from homehelper.agent.nodes.act import step_and_act
from homehelper.agent.nodes.emit import emit
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
        if state.agent is not None:
            return {}
        return {
            "agent": AgentState(
                conversation_id=message.conversation_id,
                release_id=deps.release_id,
                user_id=message.user_id,
            )
        }

    async def understand_node(state: GraphState) -> Update:
        return await understand(state, deps)

    async def step_executor(state: GraphState) -> Update:
        return await step_and_act(state, deps, get_stream_writer())

    async def respond_node(state: GraphState) -> Update:
        if state.turn.reply is None:
            get_stream_writer()(StatusEvent(stage="responding", label="Writing a reply…"))
        return await respond(state, deps)

    async def supervise_node(state: GraphState) -> Update:
        if state.turn.reply is not None:
            get_stream_writer()(StatusEvent(stage="checking", label="Double-checking…"))
        return await supervise(state, deps)

    async def emit_node(state: GraphState) -> Update:
        return emit(state, deps, get_stream_writer())

    builder = StateGraph(GraphState)
    builder.add_node("load_context", load_context)
    builder.add_node("understand", understand_node)
    builder.add_node("step_executor", step_executor)
    builder.add_node("respond", respond_node)
    builder.add_node("supervise", supervise_node)
    builder.add_node("emit", emit_node)
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "understand")
    builder.add_edge("understand", "step_executor")
    builder.add_edge("step_executor", "respond")
    builder.add_edge("respond", "supervise")
    builder.add_conditional_edges("supervise", after_supervise, ["respond", "emit"])
    builder.add_edge("emit", END)
    return builder.compile(checkpointer=checkpointer)
