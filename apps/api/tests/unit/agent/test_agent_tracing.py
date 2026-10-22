import json
import uuid

from langfuse import LangfuseOtelSpanAttributes
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from homehelper.agent.deps import AgentDeps
from homehelper.agent.runtime import JourneyAgent
from homehelper.agent.turn import AgentReply
from homehelper.channels.events import InboundMessage
from homehelper.core.tracing import Tracer
from homehelper.llm import FakeLLMClient
from tests.conftest import make_settings
from tests.unit.agent.test_journey_agent import PASS, PLAN, REPORT, FakeRetriever


async def test_a_turn_traces_every_node_and_why_it_moved() -> None:
    settings = make_settings(
        langfuse_public_key=f"pk-lf-test-{uuid.uuid4().hex}", langfuse_secret_key="sk-lf-test"
    )
    exporter = InMemorySpanExporter()
    tracer = Tracer(settings, span_exporter=exporter)
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [PLAN],
            "responder": [AgentReply(message="Try the filter.")],
            "supervisor": [PASS],
        }
    )
    agent = JourneyAgent(AgentDeps.default(llm, FakeRetriever(), tracer=tracer))
    message = InboundMessage(conversation_id="conv-t", text="My Bosch dishwasher won't drain")
    _ = [event async for event in agent.handle(message)]
    tracer.flush()

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert {
        "agent.turn",
        "understand",
        "step_executor",
        "knowledge.search",
        "plan.build",
        "respond",
        "supervise",
        "emit",
    } <= set(spans)
    turn = spans["agent.turn"]
    trace_ids = {span.context.trace_id for span in spans.values() if span.context is not None}
    assert turn.context is not None and trace_ids == {turn.context.trace_id}
    attrs = dict(spans["understand"].attributes or {})
    assert attrs[LangfuseOtelSpanAttributes.TRACE_SESSION_ID] == "conv-t"

    output = json.loads(
        str(dict(spans["step_executor"].attributes or {})["langfuse.observation.output"])
    )
    moves = [
        (d.get("from_step"), d.get("to_step"), d.get("predicate")) for d in output["decisions"]
    ]
    assert ("diagnose", "guide", "plan_available") in moves
    tags = dict(spans["emit"].attributes or {})[LangfuseOtelSpanAttributes.TRACE_TAGS]
    assert isinstance(tags, tuple) and "journey:troubleshoot" in tags
    tracer.shutdown()
