from langgraph.graph import StateGraph, END
from systems.agents.VisionAgent import vision_extract_info, vision_detect_problem, vision_fallback, vision_scan_features
from systems.agents.RAGAgent import rag_generate_query, rag_generate_answer
from systems.agents.CriticAgent import critic_evaluate
from systems.agents.memory.state import AgentState
import sys

builder = StateGraph(AgentState)


# RAG nodes (new)
builder.add_node("rag_generate_query", rag_generate_query)
builder.add_node("rag_generate_answer", rag_generate_answer)

# Critic node (new)
builder.add_node("critic_evaluate", critic_evaluate)

# Set entry point
builder.set_entry_point("rag_generate_query")


# RAG pipeline with SIM-RAG loops
builder.add_edge("rag_generate_query", "rag_generate_answer")
builder.add_edge("rag_generate_answer", "critic_evaluate")

# MainAgent.py - update the critic decision routing
def check_critic_decision(state):
    """Determine next step based on critic verdict"""
    
    # Print for debugging
    print(f"[Critic] Verdict: {state.get('verdict')} | Round: {state.get('reasoning_round')}")
    
    # Check if we should continue or end
    if state.get("verdict") == "Accept":
        print("[Critic] Answer accepted! Ending.")
        return END
    elif state.get("reasoning_round", 0) >= 3:  # Max 3 rounds
        print(f"[Critic] Max rounds ({state.get('reasoning_round')}) reached. Ending with current answer.")
        return END
    else:
        print(f"[Critic] Answer rejected. Continuing to round {state.get('reasoning_round', 0) + 1}.")
        return "rag_generate_query"  # Loop back for more info

builder.add_conditional_edges("critic_evaluate", check_critic_decision, {
    "rag_generate_query": "rag_generate_query",
    END: END
})

app = builder.compile()


def run_agent(text_description, image_path=None):
    """Run the appliance repair agent"""
    
    # Initial state
    initial_state = {
        "image_path": image_path,
        "text_description": text_description,
        "appliance_info": None,
        "extracted_features": None,
        "diagnosis": None,
        "fallback_triggered": False,
        "query": None,
        "reasoning_round": 0,
        "answer": None,
        "rationale": None,
        "retrieved_docs": [],
        "verdict": None,
        "critic_explanation": None,
        "text_only_mode": image_path is None
    }
    
    # Run the agent
    print(f"Processing request: {text_description}")
    if image_path:
        print(f"Image: {image_path}")
    else:
        print("Running in text-only mode")
    print("-" * 50)
    
    # Execute the agent
    result = app.invoke(initial_state)
    
    # Extract final answer
    final_answer = result.get("answer", "No answer generated.")
    
    print("\nFinal Answer:")
    print("-" * 50)
    print(final_answer)
    
    # Print debug info if requested
    if "--debug" in sys.argv:
        print("\nDebug Information:")
        print("-" * 50)
        print(f"Reasoning Rounds: {result.get('reasoning_round', 0)}")
        print(f"Verdict: {result.get('verdict', 'None')}")
        if not result.get("text_only_mode"):
            print(f"Vision Info: {result.get('appliance_info', 'None')}")
        print(f"Retrieved Docs: {len(result.get('retrieved_docs', []))}")
    
    return result

# run_agent("This microwave is hot even when it is not being used, please help me diagnose the issue")


# png_graph = app.get_graph().draw_png(
            
#         )
# image_name = "graph"+"v2"
# with open(image_name+".png", "wb") as f:
#     f.write(png_graph)


# from langchain_core.runnables.graph_mermaid import MermaidDrawMethod

# png_graph = graph.get_graph().draw_mermaid_png(draw_method=MermaidDrawMethod.PYPPETEER)
# image_name = "graph_v1"
# with open(f"{image_name}.png", "wb") as f:
#     f.write(png_graph)

    


# from langchain_core.runnables.graph_png import PngDrawer

# # Assuming 'graph' is your StateGraph instance
# png_drawer = PngDrawer()
# png_graph = png_drawer.draw(graph, output_path="graph_v1.png")

# from graphviz import Source

# # Create a Source object from the DOT source
# dot_source = graph.get_graph().to_dot()

# source = Source(dot_source)
# png_graph = graph.get_graph().draw_png(output_file_path="graph_v1.png")


