from typing import Dict, Any, List
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage
from tavily import TavilyClient
from systems.agents.tools.llm_config import config, llm
from systems.agents.memory.state import AgentState
import os
from dotenv import load_dotenv        


load_dotenv(dotenv_path=".env")
tavily_api_key = os.environ.get("TAVILY_API_KEY", "")  
tavily = TavilyClient(api_key=tavily_api_key)

EVALUATION_PROMPT = """
You are **ExpertSystem**, the rigorous QA gatekeeper in a multi-agent workflow.

Candidate answer:
{answer}

User context:
- Description: {text_description}
- Diagnosis (may be empty): {diagnosis}

Check for: technical correctness, completeness, feasibility, safety,
and alignment with the user's needs.

**Output (STRICT):**
• If every criterion is satisfied → reply with exactly: True
• Otherwise → reply with:
    False
    - brief advice 1
    - brief advice 2   (max 3 lines total)
Rules:
* First token must be True or False.
* If you output True, output nothing else.
* If you output False, list 1-3 advice lines prefixed “- ”.
"""

RESEARCH_CRITIQUE_PROMPT = """
You are a researcher helping to improve rejected troubleshooting instructions.

Given the critique below, suggest up to 3 concise web-search queries that would
collect authoritative information (updated safety guidelines, technical specs,
detailed repair procedures, etc.) useful for fixing the deficiencies.
Return ONE query per line, no explanations.
"""
    
GENERATION_PROMPT = """
You are a home-helper assistant. Using the critique and research snippets below,
produce an improved, modular, safety-focused set of troubleshooting
recommendations. Keep it concise - aim for ≤ 3 bullet points.

Critique:
{critique}

Research context:
{content}
"""


def evaluation_node(state: AgentState) -> Dict[str, Any]:
    """Judge the incoming answer and return Boolean + optional critique."""
    response = llm.invoke(
        [
            SystemMessage(
                content=EVALUATION_PROMPT.format(
                    answer=state.get("answer", ""),
                    text_description=state.get("text_description", ""),
                    diagnosis=state.get("diagnosis", ""),
                )
            )
        ]
    )
    raw = response.content.strip()
    accepted = raw.startswith("True")

    if accepted:
        return {
            "accepted": True,
            "final_output": "True",
        }

    # Strip leading "False" and keep advice as critique
    advice_lines = [ln.strip() for ln in raw.splitlines()[1:] if ln.strip()]
    critique = "\n".join(advice_lines) or "No advice provided."

    return {
        "accepted": False,
        "critique": critique,
    }


def research_critique_node(state: AgentState) -> Dict[str, Any]:
    """Turn critique into search queries and pull supporting snippets."""
    resp = llm.invoke(
        [
            SystemMessage(content=RESEARCH_CRITIQUE_PROMPT),
            HumanMessage(content=state["critique"]),
        ]
    )
    queries = [ln.strip() for ln in resp.content.splitlines() if ln.strip()][:3]

    content: List[str] = []
    for q in queries:
        results = tavily.search(query=q, max_results=3)
        for r in results["results"]:
            content.append(r["content"])
    return {"content": content}


def generation_node(state: AgentState) -> Dict[str, Any]:
    """Transform research into final advice string (False + bullet points)."""
    research = "\n".join(state.get("content", []))
    resp = llm.invoke(
        [
            SystemMessage(
                content=GENERATION_PROMPT.format(critique=state["critique"], content=research)
            )
        ]
    )

    # Ensure strict False-prefixed format and limit to 3 lines of advice
    advice_lines = [ln.strip() for ln in resp.content.splitlines() if ln.strip()]
    if not advice_lines or advice_lines[0].lower() != "false":
        advice_lines.insert(0, "False")
    final_output = "\n".join(advice_lines[:4])

    return {"final_output": final_output}
    
def branch_on_acceptance(state: AgentState) -> str:
    """If accepted → END, else → research node."""
    return END if state.get("accepted") else "research_critique_node"



builder = StateGraph(AgentState)

builder.add_node("evaluation_node", evaluation_node)
builder.add_node("research_critique_node", research_critique_node)
builder.add_node("generation_node", generation_node)

builder.set_entry_point("evaluation_node")
builder.add_conditional_edges("evaluation_node", branch_on_acceptance)
builder.add_edge("research_critique_node", "generation_node")
builder.add_edge("generation_node", END)

graph = builder.compile()




def run_agent(initial_state: Dict[str, Any]) -> str:
    
    final_state: AgentState = graph.invoke(initial_state)
    return final_state["final_output"]

