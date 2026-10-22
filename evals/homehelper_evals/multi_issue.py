"""Multi-issue conversations (ADR-007): the runner, not the simulated user, brings up the second
problem and goes back to the first, so every trial exercises the same pause / offer / resume
path. The simulated user only answers the agent about the problem being discussed."""

from homehelper.agent.protocol import IssueSnapshot
from homehelper.channels.events import IssuesCard, StructuredAction
from homehelper_evals.cases import EvalCase
from homehelper_evals.transcript import AgentTurn, Turn, UserTurn

SWITCH = "switch"
RETURN = "return"


def _sent(turns: list[Turn]) -> set[str]:
    return {t.script for t in turns if isinstance(t, UserTurn) and t.script}


def focus_index(case: EvalCase, turns: list[Turn]) -> int:
    """Which issue the user is talking about: the first, the second after the switch, and the
    first again after the return."""
    sent = _sent(turns)
    return 1 if SWITCH in sent and RETURN not in sent else 0


def focus(case: EvalCase, turns: list[Turn]) -> EvalCase:
    """The case as the simulated user should see it right now."""
    return case.focused(focus_index(case, turns)) if case.issues else case


def settled(issue: IssueSnapshot) -> bool:
    """Ended, or waiting at a step that already has an outcome (e.g. a handoff)."""
    return issue.status == "ended" or issue.outcome is not None


def runner_turn(case: EvalCase, turns: list[Turn]) -> UserTurn | None:
    """The scripted switch or return turn, when it is due; otherwise None."""
    if not case.issues or not turns or not isinstance(turns[-1], AgentTurn):
        return None
    last = turns[-1]
    sent = _sent(turns)
    issues = last.issues
    if SWITCH not in sent:
        shown = sum(len(t.step_cards) for t in turns if isinstance(t, AgentTurn))
        if shown >= case.switch_after_steps or (issues and settled(issues[0])):
            second = case.issues[1]
            model = f" (model {second.model_number})" if second.model_number else ""
            text = f"Also, my {second.appliance}{model} has a problem. {second.scenario}"
            return UserTurn(text=text, scripted=True, script=SWITCH)
        return None
    if RETURN in sent or len(issues) < 2:
        return None
    first, second = issues[0], issues[1]
    if first.status != "paused" or not settled(second):
        return None
    return _return_turn(case, last, first.issue_id)


def _return_turn(case: EvalCase, last: AgentTurn, issue_id: str) -> UserTurn:
    appliance = case.issues[0].appliance
    offered = any(o.issue_id == issue_id for card in last.cards_of(IssuesCard) for o in card.issues)
    text: str | None = None
    action: StructuredAction | None = None
    match case.return_via:
        case "card" if offered:
            action = StructuredAction(type="resume_issue", value=issue_id)
        case "close" if offered:
            action = StructuredAction(type="close_issue", value=issue_id)
        case "close":
            text = f"Never mind my {appliance}, I'll deal with it later."
        case "confirm":
            text = "Yes, let's go back to the other problem."
        case _:  # "appliance", or "card" when no card was offered
            # Not "Thanks! ...": a goodbye-like message never resumes a paused issue.
            text = f"Now, back to my {appliance} from before."
    return UserTurn(text=text, action=action, scripted=True, script=RETURN)


def all_issues_opened(case: EvalCase, last: AgentTurn) -> bool:
    return len(last.issues) >= len(case.issues)
