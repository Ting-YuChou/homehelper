import copy
from pathlib import Path
from typing import Any

import pytest

from homehelper.agent.engine import (
    PREDICATES,
    JourneyCatalog,
    JourneyValidationError,
    PredicateRegistry,
    default_catalog,
    is_write_tool,
    load_catalog,
    load_journey,
    parse_journey,
)
from homehelper.agent.engine.loader import DEFAULT_JOURNEYS_DIR

VALID: dict[str, Any] = {
    "id": "demo",
    "version": 1,
    "goal": "Demo.",
    "entry_intents": ["report_problem"],
    "slots": {"appliance_category": {"type": "enum", "values": "categories", "required": True}},
    "guardrails": [{"when": "hazard_detected", "to": "help"}],
    "steps": [
        {
            "id": "ask",
            "type": "collect",
            "transitions": [{"when": "required_slots_filled", "to": "go"}],
        },
        {
            "id": "go",
            "type": "system",
            "actions": ["knowledge.search"],
            "transitions": [{"when": "always", "to": "done"}],
        },
        {"id": "done", "type": "end", "outcome": "resolved"},
        {
            "id": "help",
            "type": "handoff",
            "outcome": "escalated",
            "tools_allowed": ["mcp:service_booking.list_slots"],
            "transitions": [{"when": "booking_confirmed", "to": "booked"}],
        },
        {
            "id": "booked",
            "type": "end",
            "outcome": "escalated",
            "actions": ["mcp:service_booking.book"],
        },
    ],
}


def variant(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(VALID)
    data.update(changes)
    return data


def with_step(index: int, **changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(VALID)
    data["steps"][index].update(changes)
    return data


def errors_of(data: dict[str, Any]) -> str:
    with pytest.raises(JourneyValidationError) as exc:
        parse_journey(data, "demo.yaml")
    assert exc.value.source == "demo.yaml"
    return str(exc.value)


def test_packaged_journeys_load_and_validate() -> None:
    catalog = default_catalog()
    assert set(catalog.journeys) == {"troubleshoot", "how_to_use", "out_of_scope"}
    assert catalog.for_intent("report_problem") is catalog["troubleshoot"]
    assert catalog.for_intent("ask_how_to") is catalog["how_to_use"]
    assert catalog.for_intent("small_talk") is None
    assert catalog.for_intent(None) is None


def test_troubleshoot_matches_spec_and_exposes_only_read_tools() -> None:
    troubleshoot = default_catalog()["troubleshoot"]
    assert [s.id for s in troubleshoot.steps] == [
        "gather",
        "confirm_appliance",
        "diagnose",
        "guide",
        "resolved",
        "escalate",
        "escalated_end",
    ]
    assert troubleshoot.entry_step == "gather"
    assert troubleshoot.required_slots() == ["appliance_category", "symptom"]
    # Visit times are looked up by code (the profile's ZIP), never by the LLM.
    assert troubleshoot.step("escalate").actions == ["mcp:service_booking.list_slots"]
    assert troubleshoot.step("escalate").tools_allowed == []
    for journey in default_catalog().journeys.values():
        for step in journey.steps:
            assert not any(is_write_tool(tool) for tool in step.tools_allowed)
    assert troubleshoot.step("escalated_end").actions == ["mcp:service_booking.book"]
    with pytest.raises(KeyError):
        troubleshoot.step("nope")


def test_valid_fixture_parses() -> None:
    assert parse_journey(VALID).id == "demo"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            with_step(0, transitions=[{"when": "required_slots_filled", "to": "nowhere"}]),
            "target 'nowhere' does not exist",
        ),
        (
            with_step(0, transitions=[{"when": "moon_is_full", "to": "go"}]),
            "predicate 'moon_is_full' is not registered",
        ),
        (
            with_step(0, skip_when="moon_is_full", skip_to="go"),
            "skip_when: predicate 'moon_is_full'",
        ),
        (with_step(0, skip_when="always", skip_to="limbo"), "skip_to 'limbo' does not exist"),
        (with_step(3, tools_allowed=["mcp:service_booking.cancel"]), "write tool"),
        (with_step(3, tools_allowed=["mcp:user_profile.update_address"]), "write tool"),
        (with_step(3, tools_allowed=["mcp:user_profile.export_all"]), "not a known read-only tool"),
        (with_step(3, tools_allowed=["mcp:web_search.search"]), "not a known read-only tool"),
        (with_step(1, actions=["mcp:mystery.tool"]), "unknown action 'mcp:mystery.tool'"),
        (variant(guardrails=[{"when": "moon_is_full", "to": "help"}]), "guardrails[0]: predicate"),
        (variant(guardrails=[{"when": "hazard_detected", "to": "gone"}]), "guardrails[0]: target"),
        (with_step(3, tools_allowed=["mcp:service_booking.book"]), "write tool"),
        (with_step(3, tools_allowed=["mcp:user_profile.add_appliance"]), "write tool"),
        (with_step(3, tools_allowed=["web.search"]), "is not mcp:<server>.<tool>"),
        (with_step(1, actions=["rm -rf"]), "unknown action 'rm -rf'"),
        (with_step(2, template="limerick"), "unknown template 'limerick'"),
        (variant(entry="ghost"), "entry step 'ghost' does not exist"),
        (
            variant(slots={"x": {"type": "enum", "values": "planets"}}),
            "unknown value set 'planets'",
        ),
        (variant(steps=[*VALID["steps"], VALID["steps"][2]]), "duplicate step id 'done'"),
        (
            variant(
                steps=[*VALID["steps"], {"id": "orphan", "type": "end", "outcome": "resolved"}]
            ),
            "step 'orphan' is unreachable",
        ),
    ],
)
def test_graph_errors(data: dict[str, Any], message: str) -> None:
    assert message in errors_of(data)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (with_step(0, transitions=[]), "dead end"),
        (with_step(2, outcome=None), "needs an `outcome`"),
        (with_step(2, transitions=[{"when": "always", "to": "ask"}]), "cannot have transitions"),
        (with_step(2, skip_when="always", skip_to="ask"), "cannot have `skip_when`"),
        (with_step(0, skip_when="always"), "`skip_when` and `skip_to` go together"),
        (with_step(0, skip_to="go"), "`skip_when` and `skip_to` go together"),
        (with_step(0, outcome="resolved"), "`outcome` is only allowed"),
        (with_step(1, tools_allowed=["mcp:a.b"]), "no `tools_allowed`"),
        (variant(slots={"x": {"type": "enum"}}), "enum slots need `values`"),
        (variant(slots={"x": {"type": "text", "values": ["a"]}}), "text slots cannot have"),
        (with_step(0, when="typo"), "Extra inputs are not permitted"),
        (variant(entry_intents=["dance"]), "entry_intents.0"),
        (variant(steps=[]), "steps"),
    ],
)
def test_schema_errors(data: dict[str, Any], message: str) -> None:
    assert message in errors_of(data)


def test_no_end_reachable_and_steps_that_cannot_finish() -> None:
    data = variant(
        guardrails=[],
        steps=[
            {"id": "a", "type": "collect", "transitions": [{"when": "always", "to": "b"}]},
            {"id": "b", "type": "collect", "transitions": [{"when": "always", "to": "a"}]},
            {"id": "z", "type": "end", "outcome": "resolved"},
        ],
        entry="a",
    )
    message = errors_of(data)
    assert "step 'z' is unreachable" in message
    assert "no end step is reachable from entry 'a'" in message
    assert "step 'b' cannot reach any end step" in message


def test_guardrail_is_not_a_way_out_of_a_step_loop() -> None:
    # a <-> b never ends on its own; the hazard guardrail must not make that look valid
    data = variant(
        guardrails=[{"when": "hazard_detected", "to": "z"}],
        steps=[
            {"id": "a", "type": "collect", "transitions": [{"when": "always", "to": "b"}]},
            {"id": "b", "type": "collect", "transitions": [{"when": "always", "to": "a"}]},
            {"id": "z", "type": "end", "outcome": "escalated"},
        ],
        entry="a",
    )
    message = errors_of(data)
    assert "unreachable" not in message  # z is reachable through the guardrail
    assert "no end step is reachable from entry 'a'" in message
    assert "step 'a' cannot reach any end step without a guardrail" in message


def test_load_journey_reports_file_and_yaml_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("id: [unclosed\n")
    with pytest.raises(JourneyValidationError, match="YAML syntax") as exc:
        load_journey(broken)
    assert str(broken) in str(exc.value)

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("id: demo\nversion: 1\ngoal: x\nsteps: []\n")
    with pytest.raises(JourneyValidationError, match=r"invalid\.yaml"):
        load_journey(invalid)


def test_load_catalog_from_directory(tmp_path: Path) -> None:
    with pytest.raises(JourneyValidationError, match="no journey files"):
        load_catalog(tmp_path)
    for path in DEFAULT_JOURNEYS_DIR.glob("*.yaml"):
        (tmp_path / path.name).write_text(path.read_text())
    assert set(load_catalog(tmp_path).journeys) == set(default_catalog().journeys)


def test_catalog_cross_journey_checks() -> None:
    demo = parse_journey(VALID)
    with pytest.raises(JourneyValidationError, match="hazard journey 'troubleshoot' is not loaded"):
        JourneyCatalog.from_journeys([demo])
    with pytest.raises(JourneyValidationError, match="duplicate journey id 'demo'"):
        JourneyCatalog.from_journeys([demo, demo], hazard_journey="demo")
    twin = parse_journey(variant(id="twin"))
    with pytest.raises(JourneyValidationError, match="entry intent of both 'demo' and 'twin'"):
        JourneyCatalog.from_journeys([demo, twin], hazard_journey="demo")
    unguarded = parse_journey(
        variant(guardrails=[{"when": "user_requested_technician", "to": "help"}])
    )
    with pytest.raises(JourneyValidationError, match="has no hazard_detected guardrail"):
        JourneyCatalog.from_journeys([unguarded], hazard_journey="demo")


def test_predicate_registry() -> None:
    registry = PredicateRegistry()

    @registry.register("yes")
    def yes(ctx: object) -> bool:
        return True

    assert "yes" in registry
    assert list(registry) == ["yes"]
    with pytest.raises(ValueError, match="already registered"):
        registry.register("yes")(yes)
    with pytest.raises(JourneyValidationError, match="not registered"):
        parse_journey(VALID, predicates=registry)
    assert "plan_exhausted" in list(PREDICATES)


def test_is_write_tool() -> None:
    assert is_write_tool("mcp:service_booking.book")
    assert is_write_tool("mcp:user_profile.add_repair_record")
    assert is_write_tool("mcp:service_booking.cancel")
    assert is_write_tool("mcp:anything.delete_all")
    assert not is_write_tool("mcp:parts_catalog.search_parts")
    assert not is_write_tool("mcp:service_booking.list_slots")
    assert not is_write_tool("knowledge.search")
