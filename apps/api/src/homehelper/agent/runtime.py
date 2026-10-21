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
        self._graph = build_graph(deps, checkpointer or InMemorySaver(serde=checkpoint_serde()))

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
        try:
            with self._turn_span(message):
                async for event in self._graph.astream(
                    turn,  # type: ignore[arg-type]  # a partial update, not a whole GraphState
                    _config(message.conversation_id),
                    stream_mode="custom",
                ):
                    await queue.put(cast(AgentEvent, event))
        except Exception as exc:
            # The failed turn is not checkpointed, so the conversation can simply be retried.
            log.exception("agent_turn_failed", conversation_id=message.conversation_id)
            await queue.put(
                ErrorEvent(
                    code="agent_error", message=f"The assistant failed: {type(exc).__name__}"
                )
            )
        finally:
            await queue.put(None)

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

    async def state(self, conversation_id: str) -> GraphState | None:
        snapshot = await self._graph.aget_state(_config(conversation_id))
        values: dict[str, Any] = snapshot.values or {}
        return GraphState.model_validate(values) if values else None

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
