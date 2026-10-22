from homehelper.agent.nodes.act import PlanDraftItem, plan_summary, rank_draft
from homehelper.agent.state import PlanItem


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
