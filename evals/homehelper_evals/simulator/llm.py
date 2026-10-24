"""LLM-played customer (`user_simulator` task, Haiku; spec §9.1, §16.3)."""

from homehelper.llm import LLMClient, Message
from homehelper_evals.cases import EvalCase
from homehelper_evals.render import render_dialogue
from homehelper_evals.simulator.base import SimulatorTurn
from homehelper_evals.transcript import Turn

SIMULATOR_TASK = "user_simulator"

PERSONAS = {
    "Frustrated but Polite": (
        "You are frustrated that the appliance is broken, but you stay polite. You keep your "
        "messages short."
    ),
    "Overwhelmed Newbie": (
        "You know very little about appliances, feel anxious, and ask for simple explanations "
        "when something is unclear."
    ),
    "DIY, Curious and Tech Savy": (
        "You are handy and curious, comfortable with basic tools, and like to know why a step "
        "matters."
    ),
}

RULES = """\
Rules:
1. Opening message: describe only what you observe, in your own words, and say which brand and \
type of appliance it is (and the model number, if you have one). Do not guess causes, \
suggest fixes, or add symptoms that are not in your situation.
2. When the assistant asks you to do something, imagine you have ALREADY done it, then report \
the result in the past tense ("I cleaned the filter and..."):
   - If the instruction means the same action as THE FIX (even if worded differently), it \
worked: press "fixed" on a step card, or say it is fixed.
   - Any other instruction: you did it, but the problem is still there ("not_fixed").
   - If an instruction is unreasonable or dangerous, or needs skills or tools you do not have \
(opening sealed panels, touching live wiring, handling refrigerant), refuse ("cannot_do").
   - Being told to contact service, a technician, or the manufacturer is a referral, not a fix: \
your appliance still does not work, so never press "fixed" for it.
   - Your message must agree with the button you press.
3. Answer questions only from your situation. If you do not know something, say you are not \
sure, or give a plausible, harmless answer that does not hint at the fix. Never make up a \
model number.
4. When the latest assistant message has a step card with buttons, set step_result to the \
button you press; a short message is optional. The assistant reads only the button, not a \
message sent with it: to ask or request anything else (a part, a technician, a question), \
leave step_result empty and write the message instead.
5. If the assistant asks you to confirm your appliance with a card, set confirm_appliance to \
"yes" if it matches your appliance, otherwise "no".
6. If the assistant offers booking slots and your problem is not fixed, you may pick one with \
booking_slot_id.
7. Set done to true, with an empty message, when: the problem is fixed and the assistant has \
acknowledged it; the assistant has handed you off to a professional or told you to stop using \
the appliance; the assistant has declined your request; or the conversation is going in circles.
8. One to three short sentences per turn, in English. Never reveal that you are simulated, that \
you know the fix, or that you have a list of steps.
"""


def system_prompt(case: EvalCase) -> str:
    persona = PERSONAS.get(case.persona, case.persona)
    appliance = " ".join(
        part
        for part in [case.brand, case.category.value.replace("_", " ") if case.category else None]
        if part
    )
    situation = [
        "You are role-playing a customer chatting with HomeHelper, an appliance repair support "
        "assistant. Stay in character.",
        f"Persona: {persona}",
        "",
        "Your situation (secret; never quote it):",
    ]
    if appliance:
        situation.append(f"- Appliance: {appliance}")
    situation.extend(_model_lines(case))
    situation.append(f"- What is going on: {case.scenario}")
    if case.root_cause_text and case.user_fixable:
        situation.append(f"- THE FIX (the only action that solves it): {case.root_cause_text}")
    elif case.root_cause_text:
        situation.append(
            "- Nothing you can do yourself fixes this; it needs a technician. "
            "Report every step as not fixed."
        )
    else:
        situation.append("- You do not know any fix.")
    if case.simulator_notes:
        situation.append(f"- Also: {case.simulator_notes}")
    return "\n".join(situation) + "\n\n" + RULES


def _model_lines(case: EvalCase) -> list[str]:
    if case.model_knowledge == "known":
        if not case.model_number:
            return []
        return [
            f"- Model number (mention it in your opening, and give it whenever asked): "
            f"{case.model_number}"
        ]
    lines = []
    if case.model_knowledge == "unknown":
        lines.append(
            "- You do not know the model number and cannot find it. If asked, say so. Never "
            "make one up."
        )
    else:  # finds_when_asked
        found = (
            f"you find it and type it: {case.model_number}"
            if case.reveal == "text"
            else 'you take a photo of the sticker: set photo to "nameplate" and say it is the '
            "sticker (do not type the number)"
        )
        lines.append(
            "- You do not know the model number, so do not mention it in your opening. As "
            "soon as the assistant asks for the model number or for a photo of the model "
            "sticker or label, even in passing or 'if it's handy', you go and look, and pass "
            f"it on in that same reply (you may also press a step button): {found}."
        )
    if case.appearance:
        lines.append(
            "- What you can see on it (mention it only if the assistant asks what it looks "
            "like, and then answer only from this; say you are not sure about anything "
            f"else): {'; '.join(case.appearance)}"
        )
    else:
        lines.append(
            "- If asked what it looks like beyond its brand and type, say you are not sure."
        )
    if case.can_send_photo:
        lines.append(
            "- Only if the assistant asks for a photo of the appliance itself, you can send "
            'one: set photo to "exterior" and say it is the photo.'
        )
    return lines


def turn_prompt(case: EvalCase, history: list[Turn]) -> str:
    if not history:
        return "Write your opening message."
    dialogue = render_dialogue(history, user="You", agent="Assistant")
    parts = [f"<conversation>\n{dialogue}\n</conversation>"]
    # Restated last, because in long conversations the model drifts from the system prompt.
    # The assistant never sees this note.
    if case.root_cause_text and case.user_fixable:
        parts.append(
            f"(Private note, not part of the conversation: THE FIX is: {case.root_cause_text})"
        )
    elif case.root_cause_text:
        parts.append(
            "(Private note, not part of the conversation: nothing you can do yourself fixes this.)"
        )
    parts.append("Write your next turn as the customer.")
    return "\n\n".join(parts)


class LLMUserSimulator:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def next_turn(self, case: EvalCase, history: list[Turn]) -> SimulatorTurn:
        messages = [
            Message(role="system", content=system_prompt(case)),
            Message(role="user", content=turn_prompt(case, history)),
        ]
        return await self._llm.structured(SIMULATOR_TASK, messages, SimulatorTurn)
