from .agents.video_agent import summarize_video
from langgraph.graph import END
from langgraph.graph import StateGraph
from systems.agents.memory.state import AgentState
# import END
from systems.agents.VisionAgent import vision_extract_info, vision_detect_problem, vision_fallback, vision_scan_features

def video_summarizer(video_path: str):
    """ Summarizes the Video in the given video_path. That is converts video content to text content"""
    print("In Video Summarizer Tool")
    
    return summarize_video(video_path,fun=run_vision_agent)



def build_vision_subgraph():
    """
    Constructs the vision subgraph for processing appliance images.
    """
    graph = StateGraph(AgentState)

    graph.add_node("vision_extract_info", vision_extract_info)
    graph.add_node("vision_scan_features", vision_scan_features)
    graph.add_node("vision_detect_problem", vision_detect_problem)
    graph.add_node("vision_fallback", vision_fallback)

    graph.set_entry_point("vision_extract_info")

    graph.add_edge("vision_extract_info", "vision_scan_features")
    graph.add_edge("vision_scan_features", "vision_detect_problem")

    def route_after_vision(state: AgentState):
        return "vision_fallback" if state["fallback_triggered"] else 'end'

    graph.add_conditional_edges("vision_detect_problem", route_after_vision, {
        "vision_fallback": "vision_fallback",
        "end": END
    })

    graph.add_edge("vision_fallback", END)

    return graph.compile()

def run_vision_agent(text_description, image_path):
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
    }
    
    # Run the agent
    
    # Execute the agent
    result = build_vision_subgraph().invoke(initial_state)
    
    # Extract final answer
    final_answer = result.get("answer", "No answer generated.")
    
    print("\nFinal Answer:")
    return result