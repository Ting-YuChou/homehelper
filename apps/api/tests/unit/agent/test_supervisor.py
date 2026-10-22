import pytest

from homehelper.agent.supervisor import code_checks, looks_english
from homehelper.agent.turn import AgentReply


@pytest.mark.parametrize(
    "text",
    [
        "Let's start simple: make sure the bowl and lid are locked into place, then try again.",
        "Great, glad that fixed it!",
        "Please clean the drain filter and tell me how it goes.",
    ],
)
def test_english_replies_pass(text: str) -> None:
    assert looks_english(text)


@pytest.mark.parametrize(
    "text",
    [
        "Vérifions d'abord que les portes du réfrigérateur et du congélateur se ferment "
        "correctement, sans rester entrouvertes.",
        "Primero, desenchufe la lavadora y revise que la manguera de desagüe no esté doblada.",
    ],
)
def test_replies_in_other_languages_fail(text: str) -> None:
    assert not looks_english(text)
    reasons = code_checks(AgentReply(message=text), booking_in_progress=False)
    assert any("English" in reason for reason in reasons)
