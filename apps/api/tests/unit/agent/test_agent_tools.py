"""The journey agent with MCP tools: the responder's tool loop and code-run step actions (M5-07)."""

from typing import Any

from homehelper.agent.deps import AgentDeps
from homehelper.agent.nodes.act import PlanDraft, PlanDraftItem
from homehelper.agent.protocol import ToolCall
from homehelper.agent.runtime import JourneyAgent
from homehelper.agent.state import NLUResult, SlotUpdate
from homehelper.agent.tools import McpToolbox
from homehelper.agent.turn import AgentReply
from homehelper.channels.events import (
    BookingSlotsCard,
    HandoffCard,
    InboundMessage,
    StepCard,
    StructuredAction,
    VideoCard,
)
from homehelper.llm import FakeLLMClient, Message, ToolTurn
from homehelper.mcp_servers.stores import InMemoryBookingStore
from tests.unit.agent.test_journey_agent import PASS, PLAN, REPORT, FakeRetriever, _cards
from tests.unit.agent.test_tools import servers

GUIDE_TOOLS = ["tutorials__search_videos", "parts_catalog__search_parts"]


def call(name: str, call_id: str = "1", **arguments: Any) -> ToolTurn:
    return ToolTurn.model_validate(
        {"tool_calls": [{"id": call_id, "name": name, "arguments": arguments}]}
    )


def reply(message: str, *citation_ids: str) -> ToolTurn:
    return call("reply", "r", message=message, citation_ids=list(citation_ids))


def _agent(llm: FakeLLMClient, bookings: InMemoryBookingStore | None = None) -> JourneyAgent:
    tools = McpToolbox(servers(bookings))
    return JourneyAgent(AgentDeps.default(llm, FakeRetriever(), tools=tools))


async def _send(
    agent: JourneyAgent, text: str | None = None, *, result: str | None = None
) -> list[Any]:
    action = StructuredAction(type="step_result", value=result) if result else None
    message = InboundMessage(
        conversation_id="conv-1", text=text, action=action, user_id="demo_alex"
    )
    return [event async for event in agent.handle(message)]


def _tool_messages(messages: list[Message]) -> list[Message]:
    return [m for m in messages if m.role == "tool"]


async def test_guide_step_offers_its_read_tools_and_shows_a_video_card() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [PLAN],
            "responder": [
                call("tutorials__search_videos", query="Bosch dishwasher filter cleaning"),
                reply("Let's start with the filter; there's a short video below.", "c1"),
            ],
            "supervisor": [PASS],
        }
    )
    agent = _agent(llm)
    events = await _send(agent, "My Bosch dishwasher won't drain")

    first, second = llm.calls_for("responder")
    assert first.tools == [*GUIDE_TOOLS, "reply"]
    (result,) = _tool_messages(second.messages)
    assert '"tool": "tutorials.search_videos"' in str(result.content)
    cards = _cards(events)
    assert isinstance(cards[0], StepCard)
    assert cards[1:] and all(isinstance(c, VideoCard) for c in cards[1:])
    snapshot = await agent.snapshot("conv-1")
    assert snapshot.tool_calls == [
        ToolCall(
            name="tutorials.search_videos",
            arguments={"query": "Bosch dishwasher filter cleaning"},
            source="llm",
        )
    ]
    # The supervisor sees the tool result as evidence for the reply.
    (review,) = llm.calls_for("supervisor")
    assert "<tool_results>" in str(review.messages[0].content)


async def test_responder_may_call_at_most_three_tools() -> None:
    lookup = {"symptom": "won't drain", "category": "dishwasher"}
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [PLAN],
            "responder": [
                call("parts_catalog__search_parts", "1", **lookup),
                call("parts_catalog__search_parts", "2", **lookup),
                call("parts_catalog__search_parts", "3", **lookup),
                call("parts_catalog__search_parts", "4", **lookup),  # refused: limit reached
                reply("Let's clean the filter first.", "c1"),
            ],
            "supervisor": [PASS],
        }
    )
    agent = _agent(llm)
    await _send(agent, "My Bosch dishwasher won't drain")
    offered = [c.tools for c in llm.calls_for("responder")]
    assert offered[:3] == [[*GUIDE_TOOLS, "reply"]] * 3
    assert offered[3:] == [["reply"], ["reply"]]
    last = _tool_messages(llm.calls_for("responder")[-1].messages)
    assert "tool call limit reached" in str(last[-1].content)
    assert len((await agent.snapshot("conv-1")).tool_calls) == 3


async def test_llm_cannot_book_even_when_it_asks_to() -> None:
    bookings = InMemoryBookingStore()
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [PLAN],
            "responder": [
                call(
                    "service_booking__book",
                    slot_id="any",
                    appliance_id="apl_alex_washer",
                    issue="x",
                ),
                reply("Let's start with the filter.", "c1"),
            ],
            "supervisor": [PASS],
        }
    )
    agent = _agent(llm, bookings)
    await _send(agent, "My Bosch dishwasher won't drain")
    (refused,) = _tool_messages(llm.calls_for("responder")[1].messages)
    assert "this tool is not available" in str(refused.content)
    (recorded,) = (await agent.snapshot("conv-1")).tool_calls
    assert (recorded.name, recorded.ok, recorded.source) == ("service_booking.book", False, "llm")
    assert bookings._bookings == {}


async def test_an_invalid_reply_falls_back_to_a_structured_reply_with_the_results() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [PLAN],
            "responder": [
                call("tutorials__search_videos", query="dishwasher filter"),
                call("reply", "r", text="wrong field"),
                AgentReply(message="Let's start with the filter.", citation_ids=["c1"]),
            ],
            "supervisor": [PASS],
        }
    )
    agent = _agent(llm)
    events = await _send(agent, "My Bosch dishwasher won't drain")
    fallback = llm.calls_for("responder")[-1]
    assert fallback.schema_name == "AgentReply"
    assert "tutorials.search_videos" in str(fallback.messages[0].content)
    assert any(isinstance(c, VideoCard) for c in _cards(events))


async def test_revision_reuses_tool_results_without_calling_tools() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [PLAN],
            "responder": [
                call("tutorials__search_videos", query="dishwasher filter"),
                reply("Clean the filter and also the pump and the spray arms.", "c1"),
                AgentReply(message="Let's start with the filter.", citation_ids=["c1"]),
            ],
            "supervisor": [
                PASS.model_copy(update={"on_task": False, "reasons": ["one step only"]}),
                PASS,
            ],
        }
    )
    agent = _agent(llm)
    await _send(agent, "My Bosch dishwasher won't drain")
    revision = llm.calls_for("responder")[-1]
    assert revision.tools is None  # a structured call, no tools
    assert "tutorials.search_videos" in str(revision.messages[0].content)
    assert len((await agent.snapshot("conv-1")).tool_calls) == 1


async def test_without_tools_the_responder_makes_one_structured_call() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [PLAN],
            "responder": [AgentReply(message="Let's start with the filter.", citation_ids=["c1"])],
            "supervisor": [PASS],
        }
    )
    agent = JourneyAgent(AgentDeps.default(llm, FakeRetriever()))
    await _send(agent, "My Bosch dishwasher won't drain")
    assert [c.schema_name for c in llm.calls_for("responder")] == ["AgentReply"]


async def test_resolved_without_a_profile_appliance_skips_the_repair_record() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [REPORT],
            "planner": [PLAN],
            "responder": [
                reply("Let's start with the filter.", "c1"),
                AgentReply(message="Great, glad it works!"),
            ],
            "supervisor": [PASS],
        }
    )
    agent = _agent(llm)
    await _send(agent, "My Bosch dishwasher won't drain")
    await _send(agent, result="fixed")
    snapshot = await agent.snapshot("conv-1")
    assert snapshot.outcome == "resolved"
    assert snapshot.tool_calls == []
    assert any(
        d["kind"] == "tool" and "skipped mcp:user_profile.add_repair_record" in d["reason"]
        for d in snapshot.decision_log
    )


WASHER_REPORT = NLUResult(
    intent="report_problem",
    slot_updates=[
        SlotUpdate(name="appliance_category", value="washing_machine"),
        SlotUpdate(name="symptom", value="won't drain"),
        SlotUpdate(name="error_code", value="OE"),
    ],
    search_query_en="washer won't drain OE error",
)


async def test_profile_prefills_checks_warranty_and_recalls_a_similar_repair() -> None:
    retriever = FakeRetriever()
    llm = FakeLLMClient(
        {
            "nlu": [WASHER_REPORT],
            "planner": [PLAN],
            "responder": [
                reply("Last time the drain filter fixed this; let's start there.", "c1"),
                AgentReply(message="Great, glad it works!"),
            ],
            "supervisor": [PASS],
        }
    )
    agent = JourneyAgent(AgentDeps.default(llm, retriever, tools=McpToolbox(servers())))
    await _send(agent, "My washer won't drain and shows OE")

    (query,) = retriever.queries
    assert (query.brand, query.model_number) == ("LG", "WM4000HWA")  # from the profile
    snapshot = await agent.snapshot("conv-1")
    assert [(c.name, c.source, c.ok) for c in snapshot.tool_calls] == [
        ("user_profile.get_warranty_status", "action", True),
        ("user_profile.list_repair_history", "action", True),
    ]
    assert any("linked apl_alex_washer" in d["reason"] for d in snapshot.decision_log)
    prompt = str(llm.calls_for("responder")[0].messages[0].content)
    assert "repair history (in the tool results) has an earlier problem" in prompt

    await _send(agent, result="fixed")
    record = (await agent.snapshot("conv-1")).tool_calls[-1]
    assert (record.name, record.ok) == ("user_profile.add_repair_record", True)
    assert record.arguments["appliance_id"] == "apl_alex_washer"
    assert record.arguments["resolution"] == "Clean the filter."


async def test_an_active_warranty_flags_disassembly_steps() -> None:
    dryer = NLUResult(
        intent="report_problem",
        slot_updates=[
            SlotUpdate(name="appliance_category", value="dryer"),
            SlotUpdate(name="symptom", value="not heating"),
        ],
        search_query_en="dryer not heating",
    )
    plan = PlanDraft(
        items=[
            PlanDraftItem(instruction="Clean the lint filter.", citation_ids=["c1"]),
            PlanDraftItem(
                instruction="Remove the back panel and test the thermal fuse.",
                citation_ids=["c2"],
                requires_disassembly=True,
                risk_level="medium",
            ),
        ]
    )
    llm = FakeLLMClient(
        {
            "nlu": [dryer],
            "planner": [plan],
            "responder": [reply("Let's start with the lint filter.", "c1")],
            "supervisor": [PASS],
        }
    )
    agent = _agent(llm)
    await _send(agent, "My Samsung dryer isn't heating")
    graph = await agent.state("conv-1")
    assert graph is not None and graph.agent is not None
    flagged = [i.instruction for i in graph.agent.plan if i.warranty_warning]
    assert flagged == ["Remove the back panel and test the thermal fuse."]


async def test_guests_get_no_profile_and_no_user_tools() -> None:
    llm = FakeLLMClient(
        {
            "nlu": [WASHER_REPORT],
            "planner": [PLAN],
            "responder": [reply("Let's start with the drain filter.", "c1")],
            "supervisor": [PASS],
        }
    )
    agent = _agent(llm)
    message = InboundMessage(
        conversation_id="conv-1", text="My washer won't drain", user_id="guest_abc"
    )
    [event async for event in agent.handle(message)]
    graph = await agent.state("conv-1")
    assert graph is not None and graph.agent is not None
    assert graph.agent.profile is None and graph.agent.appliance_id is None
    snapshot = await agent.snapshot("conv-1")
    assert snapshot.tool_calls == []
    assert any(
        "skipped mcp:user_profile.get_warranty_status: no signed-in user" in d["reason"]
        for d in snapshot.decision_log
    )


ONE_STEP = PlanDraft(items=[PlanDraftItem(instruction="Clean the filter.", citation_ids=["c1"])])


async def _escalate(llm_replies: list[Any], bookings: InMemoryBookingStore, user_id: str):
    llm = FakeLLMClient(
        {
            "nlu": [WASHER_REPORT],
            "planner": [ONE_STEP],
            "responder": llm_replies,
            "supervisor": [PASS, PASS, PASS],
        }
    )
    agent = _agent(llm, bookings)

    async def send(text: str | None = None, action: StructuredAction | None = None) -> list[Any]:
        message = InboundMessage(
            conversation_id="conv-1", text=text, action=action, user_id=user_id
        )
        return [event async for event in agent.handle(message)]

    await send("My washer won't drain and shows OE")
    escalated = await send(action=StructuredAction(type="step_result", value="not_fixed"))
    return agent, send, escalated


async def test_escalation_offers_visit_times_and_books_the_one_picked() -> None:
    bookings = InMemoryBookingStore()
    agent, send, escalated = await _escalate(
        [
            reply("Let's clean the filter.", "c1"),
            AgentReply(message="A technician is the best next step; pick a time below."),
            AgentReply(message="You're booked!"),
        ],
        bookings,
        "demo_alex",
    )
    handoff = next(c for c in _cards(escalated) if isinstance(c, HandoffCard))
    assert handoff.booking_available
    slots = next(c for c in _cards(escalated) if isinstance(c, BookingSlotsCard)).slots
    assert 0 < len(slots) <= 4
    snapshot = await agent.snapshot("conv-1")
    assert snapshot.step == "escalate"
    assert snapshot.tool_calls[-1].arguments == {
        "zip_code": "94110",
        "category": "washing_machine",
        "limit": 4,
    }

    await send(action=StructuredAction(type="select_booking_slot", value=slots[0].slot_id))
    snapshot = await agent.snapshot("conv-1")
    assert (snapshot.step, snapshot.outcome) == ("escalated_end", "escalated")
    book = snapshot.tool_calls[-1]
    assert (book.name, book.source, book.ok) == ("service_booking.book", "action", True)
    assert book.arguments["appliance_id"] == "apl_alex_washer"
    assert await bookings.active_slot_ids([slots[0].slot_id]) == {slots[0].slot_id}


async def test_a_slot_that_was_not_offered_is_not_booked() -> None:
    bookings = InMemoryBookingStore()
    agent, send, _ = await _escalate(
        [
            reply("Let's clean the filter.", "c1"),
            AgentReply(message="A technician is the best next step; pick a time below."),
            AgentReply(message="Please pick one of the times shown."),
        ],
        bookings,
        "demo_alex",
    )
    await send(action=StructuredAction(type="select_booking_slot", value="made-up-slot"))
    snapshot = await agent.snapshot("conv-1")
    assert snapshot.step == "escalate"
    assert all(c.name != "service_booking.book" for c in snapshot.tool_calls)
    assert bookings._bookings == {}


async def test_guests_are_not_offered_booking() -> None:
    bookings = InMemoryBookingStore()
    _, _, escalated = await _escalate(
        [
            reply("Let's clean the filter.", "c1"),
            AgentReply(message="A technician is the best next step."),
        ],
        bookings,
        "guest_abc",
    )
    cards = _cards(escalated)
    assert not any(isinstance(c, BookingSlotsCard) for c in cards)
    handoff = next(c for c in cards if isinstance(c, HandoffCard))
    assert not handoff.booking_available
