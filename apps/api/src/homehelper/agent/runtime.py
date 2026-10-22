"""`JourneyAgent`: the LangGraph journey agent behind the `AgentRuntime` protocol (M3-02)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractContextManager, nullcontext, suppress
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from homehelper.agent.deps import AgentDeps
from homehelper.agent.graph import build_graph, checkpoint_serde
from homehelper.agent.protocol import AgentSnapshot
from homehelper.agent.turn import GraphState, TurnScratch
from homehelper.channels.events import AgentEvent, ErrorEvent, InboundMessage
from homehelper.core.logging import get_logger

log = get_logger(__name__)


def _config(conversation_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": conversation_id}}


class JourneyAgent:
    def __init__(self, deps: AgentDeps, checkpointer: BaseCheckpointSaver | None = None) -> None:
        self._deps = deps
        self._checkpointer = checkpointer or InMemorySaver(serde=checkpoint_serde())
        self._graph = build_graph(deps, self._checkpointer)

    async def handle(self, message: InboundMessage) -> AsyncIterator[AgentEvent]:
        # The graph runs in its own task: the turn's tracing context then lives in that task
        # and never leaks into (or depends on) whoever iterates this generator.
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        task = asyncio.create_task(self._run(message, queue))
        try:
            while (event := await queue.get()) is not None:
                yield event
        finally:
            if not task.done():  # the consumer went away, e.g. the client disconnected
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _run(self, message: InboundMessage, queue: asyncio.Queue[AgentEvent | None]) -> None:
        # A new TurnScratch resets everything per-turn; the rest of the state comes from the
        # checkpoint of this conversation.
        turn = {"turn": TurnScratch(message=message)}
        config = _config(message.conversation_id)
        before: GraphState | None = None
        try:
            before = await self._state(config)
            with self._turn_span(message):
                async for event in self._graph.astream(
                    turn,  # type: ignore[arg-type]  # a partial update, not a whole GraphState
                    config,
                    stream_mode="custom",
                ):
                    await queue.put(cast(AgentEvent, event))
        except Exception as exc:
            log.exception("agent_turn_failed", conversation_id=message.conversation_id)
            if before is not None:  # the turn ran: undo what it saved
                await self._roll_back(message.conversation_id, before)
            await queue.put(
                ErrorEvent(
                    code="agent_error", message=f"The assistant failed: {type(exc).__name__}"
                )
            )
        finally:
            await queue.put(None)

    async def _roll_back(self, conversation_id: str, before: GraphState) -> None:
        """Undo a failed turn so it can simply be retried. LangGraph checkpoints after every node,
        so the nodes that ran before the failure (step results, plan position, tool calls) are
        already saved; writing every field's previous value back as `emit` puts the thread where
        the turn started, with nothing pending. Fields never written before the turn are reset to
        their defaults too."""
        try:
            if before.agent is not None:
                values = {name: getattr(before, name) for name in GraphState.model_fields}
                await self._graph.aupdate_state(_config(conversation_id), values, as_node="emit")
            else:  # the conversation's first turn
                await self._checkpointer.adelete_thread(conversation_id)
        except Exception:
            log.exception("agent_turn_rollback_failed", conversation_id=conversation_id)

    def _turn_span(self, message: InboundMessage) -> AbstractContextManager[Any]:
        tracer = self._deps.tracer
        if tracer is None:
            return nullcontext()
        said = message.text if message.action is None else message.action.model_dump()
        return tracer.turn(
            "agent.turn",
            session_id=message.conversation_id,
            user_id=message.user_id,
            tags=[f"channel:{message.channel}"],
            input=said,
        )

    async def _state(self, config: RunnableConfig) -> GraphState:
        snapshot = await self._graph.aget_state(config)
        return GraphState.model_validate(snapshot.values or {})

    async def state(self, conversation_id: str) -> GraphState | None:
        graph = await self._state(_config(conversation_id))
        return graph if graph.agent is not None else None

    async def snapshot(self, conversation_id: str) -> AgentSnapshot:
        graph = await self.state(conversation_id)
        if graph is None or graph.agent is None:
            return AgentSnapshot(conversation_id=conversation_id)
        state = graph.agent
        return AgentSnapshot(
            conversation_id=conversation_id,
            outcome=state.outcome,
            journey=state.active_journey,
            step=state.step_id,
            hazard_flags=list(state.hazard_flags),
            tool_calls=list(graph.tool_calls),
            decision_log=[d.model_dump(exclude_none=True) for d in state.decision_log],
        )
