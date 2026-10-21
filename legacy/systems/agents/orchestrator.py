import os
import cv2
import torch
import operator
from PIL import Image
from typing import TypedDict, Annotated, Optional
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from IPython.display import Image as IPyImage
from graphviz import Source
from systems.agents.video_agent import summarize_video
from systems.agents.memory.state import AgentState
from systems.agents.LLMconfig import config
from systems.agents.summary_agent import summarize_conversation
from systems.KnowledgeRetrievalSystem import run_agent


orchestrator_llm = config.get_llm("tool_use")

def orchestrator(state: AgentState):
    print("inside - orchestrator node")

    if state.get("video_path"):
        print("hi")
        state["messages"] = []
        print("Triggering video summarization...")
        summary_msg = summarize_video(state["video_path"])
        print(summary_msg)
        state["messages"].append(summary_msg)
        return {"messages": [summary_msg], "tries": state["tries"] + 1, "video_path": None}
    
    response = orchestrator_llm.invoke(state['messages'])
    print(response)
    if state["tries"] == 2:
        print("\n I'm going to print the messages:", state["messages"])
    return {"messages": [response], "tries": state["tries"] + 1}


def human_expert(state: AgentState):
    print("inside human expert node")
    user_reply = input("\n[User] Please provide more details in response to the assistant:\n> ")
    expert_response = HumanMessage(content=user_reply)
    return {
        "messages": [expert_response],
        "video_path": state.get("video_path")
    }

# === Build the Graph ===
graph = StateGraph(AgentState)
graph.add_node("orchestrator", orchestrator)
graph.add_node("human_expert", human_expert)
graph.add_node("conversation_summary", summarize_conversation)

def routing_logic(state: AgentState):
    if state["tries"] >= 3:
        return "conversation_summary"
    return "human_expert"

graph.set_entry_point("orchestrator")
graph.add_conditional_edges("orchestrator", routing_logic, {
    "human_expert": "human_expert",
    "conversation_summary": "conversation_summary"
})
graph.add_edge("human_expert", "orchestrator")

compiled_graph = graph.compile()
compiled_graph.get_graph().draw_png("orchestrator.png")
IPyImage("orchestrator.png")

# === Run the Graph ===
initial_input = {
    # "messages": [HumanMessage(content="The water pressure in my house dropped suddenly. Can you help me figure out why?")],
    "messages": [],
    "tries": 0,
    "video_path": os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'dataset', 'home_issue.mp4')
}

result = compiled_graph.invoke(initial_input)
print("\nFinal Output:")
for msg in result['messages']:
    print(msg.content)