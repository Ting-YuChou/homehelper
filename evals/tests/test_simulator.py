from homehelper.channels.events import (
    ApplianceConfirmCard,
    BookingSlot,
    BookingSlotsCard,
    StepCard,
)
from homehelper.llm import FakeLLMClient
from homehelper_evals.conversation import to_user_turn
from homehelper_evals.simulator import LLMUserSimulator, ScriptedUserSimulator, SimulatorTurn
from homehelper_evals.simulator.llm import SIMULATOR_TASK, system_prompt
from homehelper_evals.simulator.scripted import same_step
from homehelper_evals.testing import make_case
from homehelper_evals.transcript import AgentTurn, UserTurn


def step_turn(instruction: str) -> AgentTurn:
    return AgentTurn(cards=[StepCard(plan_item_id="p1", index=1, total=2, instruction=instruction)])


def test_system_prompt_hides_nothing_the_user_needs() -> None:
    prompt = system_prompt(make_case(persona="Overwhelmed Newbie"))
    assert "THE FIX (the only action that solves it): Clean the filter." in prompt
    assert "Bosch dishwasher" in prompt
    assert "feel anxious" in prompt  # persona text, not just the label

    not_fixable = system_prompt(make_case(user_fixable=False, expected_outcomes=["escalated"]))
    assert "Clean the filter" not in not_fixable and "needs a technician" in not_fixable


async def test_llm_simulator_sends_history_and_parses_turn() -> None:
    llm = FakeLLMClient(
        {
            SIMULATOR_TASK: [
                SimulatorTurn(message="My dishwasher won't drain."),
                {"message": "Done, it drains now!", "step_result": "fixed"},
            ]
        }
    )
    simulator = LLMUserSimulator(llm)
    case = make_case()
    opening = await simulator.next_turn(case, [])
    assert opening.message == "My dishwasher won't drain."

    history = [UserTurn(text=opening.message), step_turn("Clean the filter.")]
    turn = await simulator.next_turn(case, history)
    assert turn.step_result == "fixed"
    prompt = llm.calls_for(SIMULATOR_TASK)[1].messages[1].content
    assert "[Step 1/2] Clean the filter." in prompt
    assert "Private note" in prompt and "THE FIX is: Clean the filter." in prompt
    assert llm.calls[1].schema_name == "SimulatorTurn"


def test_buttons_only_count_when_the_card_offered_them() -> None:
    pressed = SimulatorTurn(message="Done.", step_result="fixed")
    assert to_user_turn(pressed, AgentTurn(text="What model is it?")) == UserTurn(text="Done.")
    turn = to_user_turn(pressed, step_turn("Clean the filter."))
    assert turn is not None and turn.action is not None and turn.action.value == "fixed"

    slots = AgentTurn(
        cards=[
            BookingSlotsCard(
                slots=[BookingSlot(slot_id="s1", starts_at="2026-11-01T09:00", technician="A")]
            )
        ]
    )
    booked = to_user_turn(SimulatorTurn(booking_slot_id="s1"), slots)
    assert booked is not None and booked.action is not None
    assert booked.action.type == "select_booking_slot"
    assert to_user_turn(SimulatorTurn(booking_slot_id="nope"), slots) is None


async def test_scripted_simulator_presses_fixed_only_on_the_root_cause() -> None:
    simulator = ScriptedUserSimulator()
    case = make_case()
    assert "Bosch dishwasher" in (await simulator.next_turn(case, [])).message
    history = [UserTurn(text="hi")]
    wrong = await simulator.next_turn(case, [*history, step_turn("Check the drain hose.")])
    assert wrong.step_result == "not_fixed"
    right = await simulator.next_turn(case, [*history, step_turn("Please clean the filter.")])
    assert right.step_result == "fixed"
    assert same_step("Remove and clean the dishwasher filter", "Clean the filter.")
    assert not same_step("Check the hose", "Clean the filter.")


async def test_scripted_simulator_gives_up_without_steps() -> None:
    simulator = ScriptedUserSimulator()
    history = [UserTurn(text="hi"), AgentTurn(text="Hmm?")]
    for _ in range(2):
        turn = await simulator.next_turn(make_case(), history)
        assert not turn.done
        history += [UserTurn(text=turn.message), AgentTurn(text="Hmm?")]
    assert (await simulator.next_turn(make_case(), history)).done


async def test_appliance_confirmation_card() -> None:
    def confirm(brand: str) -> AgentTurn:
        card = ApplianceConfirmCard(category="dishwasher", brand=brand, confidence=0.6)
        return AgentTurn(cards=[card])

    simulator = ScriptedUserSimulator()
    history = [UserTurn(text="hi")]
    yes = await simulator.next_turn(make_case(), [*history, confirm("Bosch")])
    no = await simulator.next_turn(make_case(), [*history, confirm("LG")])
    assert (yes.confirm_appliance, no.confirm_appliance) == ("yes", "no")
    turn = to_user_turn(yes, confirm("Bosch"))
    assert turn is not None and turn.action is not None
    assert (turn.action.type, turn.action.value) == ("confirm_appliance", "yes")
