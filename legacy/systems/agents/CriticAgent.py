# agents/CriticAgent.py
from systems.agents.tools.critic_utils import evaluate_sufficiency
from typing import Dict, Any # Import Dict and Any for state type hinting

def critic_evaluate(state: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate if the current answer is sufficient"""

    # Get required state values with fallbacks
    query = state.get("query", "")
    text_description = state.get("text_description", "")
    appliance_info = state.get("appliance_info", "")
    docs = state.get("retrieved_docs", [])
    answer = state.get("answer", "")
    rationale = state.get("rationale", "")
    # Get the previous critic explanation from the state
    previous_critic_explanation = state.get("critic_explanation", None)

    # Print for debugging
    print(f"[Critic] Evaluating answer for round {state.get('reasoning_round', 0)}")

    # Call the evaluation function, now passing the previous_critic_explanation
    verdict, explanation = evaluate_sufficiency(
        query=query,
        text_description=text_description,
        appliance_info=appliance_info,
        docs=docs,
        answer=answer,
        rationale=rationale,
        critic_explanation=previous_critic_explanation # Pass the explanation
    )

    print(f"[Critic] Verdict: {verdict}")
    # Ensure we don't print too much of the explanation
    display_explanation = explanation[:200] + '...' if len(explanation) > 200 else explanation
    print(f"[Critic] Explanation: {display_explanation}")


    # Return updated state
    return {
        **state,
        "verdict": verdict,
        "critic_explanation": explanation # Store the new explanation in the state
    }

