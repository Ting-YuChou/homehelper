# systems/agents/VisionGraph.py

from langgraph.graph import StateGraph
from systems.agents.memory.state import AgentState
from .tools.vision_utils import (
    analyze_image,
    detect_problem_from_image_and_text,
    is_low_confidence_response,
    retry_problem_detection,
    scan_image_features
)

def vision_extract_info(state: AgentState) -> AgentState:
    if state.get("text_only_mode"):
        return {**state, "appliance_info": "No image provided - running in text-only mode"}

    if not state.get("image_path"):
        return {**state, "appliance_info": "No image path provided"}

    appliance_info = analyze_image(state["image_path"])
    return {**state, "appliance_info": appliance_info}

def vision_scan_features(state: AgentState) -> AgentState:
    if state.get("text_only_mode"):
        return {**state, "extracted_features": "No image features available - running in text-only mode"}

    if not state.get("image_path"):
        return {**state, "extracted_features": "No image path provided"}

    features = scan_image_features(state["image_path"])
    return {**state, "extracted_features": features}

def vision_detect_problem(state: AgentState) -> AgentState:
    if state.get("text_only_mode"):
        return {
            **state,
            "diagnosis": "No image analysis available - proceeding with text-based diagnosis",
            "fallback_triggered": True
        }

    if not state.get("image_path"):
        return {
            **state,
            "diagnosis": "No image path provided - proceeding with text-based diagnosis",
            "fallback_triggered": True
        }

    diagnosis = detect_problem_from_image_and_text(
        state["image_path"],
        state["text_description"],
        state.get("appliance_info", ""),
        state.get("extracted_features", "")
    )
    fallback = is_low_confidence_response(diagnosis)
    return {
        **state,
        "diagnosis": diagnosis,
        "fallback_triggered": fallback
    }

def vision_fallback(state: AgentState) -> AgentState:
    if state.get("text_only_mode"):
        return {**state, "diagnosis": "No image available for retry - proceeding with text-based analysis"}

    if not state.get("image_path"):
        return {**state, "diagnosis": "No image path provided - proceeding with text-based analysis"}

    retry_result = retry_problem_detection(state["image_path"], state["text_description"])
    return {**state, "diagnosis": retry_result}


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

