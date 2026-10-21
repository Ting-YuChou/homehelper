"""Supervisor (M3-09, spec §8.2): checks a draft reply before the user sees it.

Code checks run first: S1 citation ids (invented ids are dropped, not argued about), S5 format,
and G-PRIV-01. The LLM check (S2 grounded, S3 safe, S4 on task) runs only for replies that make
technical claims. A failed draft is revised once with the reasons; a second failure is replaced
by `BLOCKED_REPLY`.
"""

from typing import Any

from pydantic import BaseModel, Field

from homehelper.agent import prompts
from homehelper.agent.deps import AgentDeps
from homehelper.agent.guardrails import check_privacy
from homehelper.agent.nodes.respond import ResponsePlan, response_plan, user_text
from homehelper.agent.state import Decision
from homehelper.agent.turn import AgentReply, GraphState, SupervisorVerdict
from homehelper.core.logging import get_logger
from homehelper.llm import LLMError, Message

log = get_logger(__name__)

MAX_REPLY_CHARS = 1200
BLOCKED_REPLY = (
    "Sorry, I couldn't put together a reliable answer just now. Could you tell me a bit more "
    "about what's happening? If you'd rather not continue, a qualified technician can take a "
    "look."
)


class SupervisorReview(BaseModel):
    grounded: bool
    safe: bool
    on_task: bool
    reasons: list[str] = Field(default_factory=list)


def code_checks(reply: AgentReply, *, booking_in_progress: bool) -> list[str]:
    reasons: list[str] = []
    text = reply.message.strip()
    if not text:
        reasons.append("The reply is empty.")
    elif len(text) > MAX_REPLY_CHARS:
        reasons.append("The reply is too long; keep it to a few short sentences.")
    asked = check_privacy(text, booking_in_progress=booking_in_progress)
    if asked:
        reasons.append(f"Do not ask the user for personal data ({', '.join(asked)}).")
    return reasons


async def llm_review(
    graph: GraphState, deps: AgentDeps, plan: ResponsePlan, reply: AgentReply
) -> list[str]:
    prompt = prompts.render(
        "supervisor",
        task=plan.task,
        excerpts=[{"id": c.chunk_id, "text": c.text} for c in plan.excerpts],
        plan_step=plan.plan_item["instruction"] if plan.plan_item else None,
        reply=reply.message,
        user_text=user_text(graph),
    )
    try:
        review = await deps.llm.structured(
            "supervisor", [Message(role="user", content=prompt)], SupervisorReview
        )
    except LLMError as exc:
        # The code checks already passed; an outage of the reviewer must not block the turn.
        log.warning("supervisor_unavailable", error=repr(exc))
        return []
    if review.grounded and review.safe and review.on_task:
        return []
    return review.reasons or ["The reviewer rejected the draft without a reason."]


async def supervise(graph: GraphState, deps: AgentDeps) -> dict[str, Any]:
    turn = graph.turn
    reply = turn.reply
    if reply is None:  # a fixed template replaced the response
        return {}
    plan = response_plan(graph, deps)
    state = graph.state.model_copy(deep=True)

    invented = [cid for cid in reply.citation_ids if cid not in plan.citable_ids]
    if invented:
        reply = reply.model_copy(
            update={"citation_ids": [c for c in reply.citation_ids if c in plan.citable_ids]}
        )
        state.decision_log.append(
            Decision(
                kind="supervisor",
                journey=state.active_journey,
                rule_id="S1",
                reason=f"dropped citation ids that were not retrieved: {invented}",
            )
        )

    step = deps.step(state)
    reasons = code_checks(reply, booking_in_progress=step is not None and step.type == "handoff")
    if not reasons and plan.cite:
        reasons = await llm_review(graph, deps, plan, reply)

    if not reasons:
        verdict = SupervisorVerdict(action="pass")
    elif turn.revisions == 0:
        verdict = SupervisorVerdict(action="revise", reasons=reasons)
    else:
        verdict = SupervisorVerdict(action="block", reasons=reasons)
        reply = AgentReply(message=BLOCKED_REPLY)
    if verdict.action != "pass":
        state.decision_log.append(
            Decision(
                kind="supervisor",
                journey=state.active_journey,
                reason=f"{verdict.action}: {'; '.join(reasons)}",
            )
        )
    return {"agent": state, "turn": turn.model_copy(update={"reply": reply, "verdict": verdict})}


def after_supervise(graph: GraphState) -> str:
    verdict = graph.turn.verdict
    return "respond" if verdict is not None and verdict.action == "revise" else "emit"
