from homehelper.agent import prompts
from homehelper.agent.guardrails.plan import BLADE_CAUTION
from homehelper.agent.nodes.act import PlanDraftItem, plan_summary, rank_draft
from homehelper.agent.nodes.mcp_actions import _repair_record_args
from homehelper.agent.state import PlanItem, UserContext
from homehelper.agent.turn import GraphState

from .helpers import new_state


def draft(instruction: str, *, targets: bool = False, disassembly: bool = False) -> PlanDraftItem:
    return PlanDraftItem(
        instruction=instruction, targets_symptom=targets, requires_disassembly=disassembly
    )


def test_steps_aimed_at_the_symptom_go_first_and_disassembly_last() -> None:
    items = [
        draft("Check the plug"),
        draft("Remove the back panel", targets=True, disassembly=True),
        draft("Clean the drain filter", targets=True),
        draft("Check the door is closed"),
        draft("Straighten the drain hose", targets=True),
    ]
    assert [item.instruction for item in rank_draft(items)] == [
        "Clean the drain filter",
        "Straighten the drain hose",
        "Check the plug",
        "Check the door is closed",
        "Remove the back panel",
    ]


def test_ranking_keeps_the_planner_order_without_flags() -> None:
    items = [draft("A"), draft("B"), draft("C")]
    assert rank_draft(items) == items


def test_plan_summary_lists_ids_citations_and_instructions() -> None:
    items = [
        PlanItem(id="p1", instruction="Clean the filter", citation_ids=["c1", "c2"]),
        PlanItem(id="p2", instruction="x" * 100),
    ]
    assert plan_summary(items) == f"p1 [c1,c2] Clean the filter; p2 [] {'x' * 80}"


def test_records_quote_the_step_without_the_blade_caution() -> None:
    step = PlanItem(id="p1", instruction=f"{BLADE_CAUTION} Lift the blade out.", status="fixed")
    assert plan_summary([step]) == "p1 [] Lift the blade out."
    state = new_state(user_id="demo_alex", profile=UserContext(zip_code="94110"))
    state = state.model_copy(update={"plan": [step], "appliance_id": "app_1"})
    args = _repair_record_args(GraphState(agent=state), state)
    assert isinstance(args, dict) and args["resolution"] == "Lift the blade out."


def test_the_blade_rule_is_only_for_appliances_with_blades() -> None:
    def planner(blades: bool) -> str:
        return prompts.render(
            "planner",
            category="x",
            blades=blades,
            brand=None,
            model_number=None,
            symptom="x",
            error_code=None,
            user_said=[],
            excerpts=[],
            web_findings=[],
            manuals=0,
            tried=[],
            max_items=6,
            power_off=[],
        )

    assert "force a blade" in planner(True)
    assert "force a blade" not in planner(False)
