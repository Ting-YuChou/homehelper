from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from langgraph.prebuilt import ToolNode
from langchain_core.messages import ToolMessage, SystemMessage
from langchain.schema.messages import HumanMessage, AIMessage
import json
# run_agent import from KnowledgeRetrievalSystem
from .KnowledgeRetrievalSystem import run_agent
from .InputSystem import run_vision_agent
from .ProductReccSystem import get_product_recommendations as get_product_links
from .ExpertSystem import run_agent as expert_system_run

from langgraph.graph import StateGraph, MessagesState
from langgraph.prebuilt import ToolNode
from .agents.LLMconfig import Config as LLMconfig
from typing import Literal
from .agents.video_agent import summarize_video
import os

import sys
# sys.stdout = open('debug_orchestrator.log', 'w')

# Constants
MAX_ATTEMPTS = 2

@tool
def video_summarizer(video_path: str):
    """ Summarizes the Video in the given video_path. That is converts video content to text content"""
    print("In Video Summarizer Tool", video_path)
    return summarize_video(video_path)

@tool
def get_Instructions(query: str):
    """ Get Instructions or steps to follow to resolve the given query"""
    print("In Get Instructions")
    return run_agent(query)

@tool
def get_vision_data(text: str, image_path: str):
    """ Get Instructions or steps to follow to resolve the given query Multimodal version"""
    print("In Get Instructions(multi-modal)", text, image_path)
    return run_vision_agent(text, image_path)

# @tool
# def multimodal_get_instructions(query: str, image_path: str):
#     """ Get Instructions or steps to follow to resolve the given query Multimodal version"""
#     print("In Get Instructions(multi-modal)")
#     return run_agent(query, image_path)




def fetch_product_links(query: str):
    """ The Query input should be a solution step to solve or help the user with repairing or fixing another product.
    It should have all the tools needed to complete the task.
    The ouput will have links to the tools, and youtube links that are related to this task.
    """
    print("In Get Product Recommendations")
    return get_product_links(query)



@tool
def expert_qa_evaluation(answer: str, text_description: str, diagnosis: str = ""):
    """Evaluates the answer using ExpertSystem for technical correctness, completeness, feasibility, and safety"""
    print("In Expert QA Evaluation")
    state = {
        "answer": answer,
        "text_description": text_description,
        "diagnosis": diagnosis
    }
    return expert_system_run(state)

@tool
def format_response(response: str):
    """Format the response to be concise and clear"""
    # Handle list input
    if isinstance(response, list):
        # Join list elements with newlines if they're strings
        response = "\n".join(str(x) for x in response if isinstance(x, str))
    
    # Handle dictionary input
    if isinstance(response, dict):
        # Try to get the text field first
        text = response.get('text')
        if text:
            return str(text).strip()
        # If no text field, try other common fields
        text = response.get('answer') or response.get('summary') or response.get('content')
        if text:
            return str(text).strip()
        # If no text field found, convert dict to string
        return str(response).strip()
    
    # Handle string input
    return str(response).strip()

tools = [video_summarizer, get_Instructions, get_vision_data, expert_qa_evaluation, format_response]
tool_node = ToolNode(tools)



llm_with_tools = LLMconfig.get_llm("tool_use").bind_tools(tools=tools)

import os
from typing import List, Optional
import cv2
from PIL import Image

def validate_media_file(file_path: str, media_type: str) -> bool:
    """Validate if a media file exists and is valid"""
    if not os.path.exists(file_path):
        print(f"Error: {media_type} file not found at {file_path}")
        return False
    
    try:
        if media_type == "video":
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                print(f"Error: Invalid video file at {file_path}")
                return False
            cap.release()
        elif media_type == "image":
            with Image.open(file_path) as img:
                img.verify()
    except Exception as e:
        print(f"Error validating {media_type} file {file_path}: {e}")
        return False
    
    return True

def run_orchestrator(user_message, video_paths=[], image_paths=[], chat_history=None):
    # Initialize a fresh message list for each call
    messages = []
    
    # Add system message with clear instructions
    messages.append(SystemMessage(content="""
    You are a helpful HandyMan assistant.
    Always make the output concise and clear and less than 200 words.
                                  
    Make sure to provide the user with the best possible solution to the problem along with the name of the product the user is trying to troubleshoot..
    If ther user request is very very vague, you should ask the user to provide more information.
    If the user request is not clear, you should say you are just a handy man assistant and you can't help with that.
    REQUIRED WORKFLOW (FOLLOW THESE STEPS IN ORDER):
    1. For repair/maintenance queries with images:
       a. Call 'get_vision_data' with the user's query and image path to analyze the image if an image is provided.
       b. Call 'video_summarizer' with the user's query and video path to summarize the video if a video is provided.
       b. Use the vision analysis to inform the next steps
       c. Call 'get_Instructions' with the user's query and vision analysis
       d. Call 'expert_qa_evaluation' with the instructions, user's query, and vision diagnosis
       e. If expert returns "False":
          - Extract the critique points from the expert's response
          - Call 'get_Instructions' again with: original query + vision analysis + "Please improve these steps: " + critique points
          - Call 'expert_qa_evaluation' again
          - Repeat until "True" or 2 attempts
       f. Call 'format_response' with the final instructions to ensure proper formatting
    2. For repair/maintenance queries without images:
       a. Call 'get_Instructions' with the user's query
       b. Call 'expert_qa_evaluation' with the instructions and user's query
       c. If expert returns "False":
          - Extract the critique points from the expert's response
          - Call 'get_Instructions' again with: original query + "Please improve these steps: " + critique points
          - Call 'expert_qa_evaluation' again
          - Repeat until "True" or 2 attempts
       d. Call 'format_response' with the final instructions to ensure proper formatting
    IMPORTANT:
    The output should always be less than 200 words, and should either be either steps on how the user can fix the problem or steps on how the user can try troubleshooting, or if its too dangerous, should suggest the user to call a professional.
    The output should not include Agent, User conversations, only the steps to fix the problem.
    """))
    
    # Add chat history if provided
    if chat_history:
        for msg in chat_history:
            if msg.get('user_message'):
                messages.append(HumanMessage(content=msg['user_message']))
            if msg.get('agent_response'):
                messages.append(AIMessage(content=msg['agent_response']))
    
    # Process the user message and any media files
    content = user_message 
    valid_media = []
    vision_analysis = None
    
    # Validate and process video files
    if video_paths:
        for video_path in video_paths:
            if validate_media_file(video_path, "video"):
                valid_media.append(("video", video_path))
                content += f"\nVideo file path: {video_path}"
    
    # Validate and process image files
    if image_paths:
        for image_path in image_paths:
            if validate_media_file(image_path, "image"):
                valid_media.append(("image", image_path))
                content += f"\nImage file path: {image_path}"
                # Get vision analysis for the first valid image
                if not vision_analysis:
                    vision_analysis = run_vision_agent(user_message, image_path)
    
    # Add the processed user message
    messages.append(HumanMessage(content=content))
    tools_by_name = {tool.name: tool for tool in tools}

    current_attempt = 0
    last_instructions = None
    last_evaluation = None
    original_user_message = user_message

    while current_attempt < MAX_ATTEMPTS:
        print("TOOL MESSAGE", messages[-1])
        response = llm_with_tools.invoke(messages)
        messages.append(response)
        print("RESPONSE:", response)
        print("TOOL CALLS:", response.tool_calls)
        
        for tool_call in response.tool_calls:
            print(f"Processing tool call: {tool_call['name']}")
            # Ensure image_path is a string for get_vision_data
            if tool_call["name"].lower() == "get_vision_data".lower() and isinstance(tool_call["args"].get("image_path"), list):
                tool_call["args"]["image_path"] = tool_call["args"]["image_path"][0]
            
            # Handle format_response tool call
            if tool_call["name"].lower() == "format_response".lower():
                args = tool_call["args"]
                if isinstance(args, dict):
                    if "text" in args:
                        tool_call["args"] = {"response": args["text"]}
                    elif "response" in args and isinstance(args["response"], list):
                        tool_call["args"] = {"response": "\n".join(str(x) for x in args["response"] if isinstance(x, str))}
            
            # Handle expert_qa_evaluation tool call
            if tool_call["name"].lower() == "expert_qa_evaluation".lower():
                if not isinstance(tool_call["args"], dict):
                    tool_call["args"] = {}
                if "answer" not in tool_call["args"] and last_instructions:
                    tool_call["args"]["answer"] = last_instructions
                if "text_description" not in tool_call["args"]:
                    tool_call["args"]["text_description"] = original_user_message
                if "diagnosis" not in tool_call["args"] and vision_analysis:
                    tool_call["args"]["diagnosis"] = vision_analysis.get("diagnosis", "")
            
            tool_result = tools_by_name[tool_call["name"]].invoke(tool_call["args"])
            print(f"Tool result for {tool_call['name']}: {tool_result}")
            
            if tool_call["name"].lower() == "get_Instructions".lower():
                last_instructions = tool_result
            elif tool_call["name"] == "expert_qa_evaluation":
                last_evaluation = tool_result
                if isinstance(tool_result, dict) and tool_result.get("result") == "True":
                    current_attempt = MAX_ATTEMPTS  # Exit the loop if evaluation is successful
                    break
            
            messages.append(ToolMessage(
                content="\n" + json.dumps(tool_result),
                name=tool_call["name"],
                tool_call_id=tool_call["id"],
            ))
            print("TOOL RESULT", tool_result)
        
        if not response.tool_calls:
            break
            
        current_attempt += 1
        
        # If we need to improve the instructions
        if current_attempt < MAX_ATTEMPTS and last_evaluation and isinstance(last_evaluation, dict) and last_evaluation.get("result") == "False":
            critique_points = last_evaluation.get("critique", "")
            improvement_query = f"{user_message}\nPlease improve these steps: {critique_points}"
            if vision_analysis:
                improvement_query = f"{improvement_query}\nVision Analysis: {vision_analysis.get('diagnosis', '')}"
            messages.append(HumanMessage(content=improvement_query))

    print("*************************************************************\n")
    print(messages)
    print("*************************************************************\n")
    
    # Use the last successful instructions or the best attempt
    output = last_instructions if last_instructions else messages[-1].content
    # If output is a dict, extract only the 'answer' field or a short summary
    if isinstance(output, dict):
        concise = output.get('answer') or output.get('text') or output.get('summary')
        if not concise:
            # Try to find a string value in the dict
            for v in output.values():
                if isinstance(v, str) and v.strip():
                    concise = v
                    break
        output = concise or "Sorry, I couldn't generate a concise answer."
    elif isinstance(output, list):
        output = "\n".join(str(x) for x in output if isinstance(x, str))
    # Truncate to 200 words max
    output = str(output).strip()
    if len(output.split()) > 200:
        output = " ".join(output.split()[:200]) + "..."

    # Format the final response
    try:
        formatted_output = tools_by_name["format_response"].invoke({"response": output})
    except Exception as e:
        print(f"Error formatting response: {e}")
        formatted_output = output

    # --- PRODUCT LINKS UPDATE ---
    # Combine the user's original message and the final troubleshooting step for a more specific query
    product_links_query = f"{original_user_message}\n{formatted_output}"
    if vision_analysis:
        product_links_query = f"{product_links_query}\nVision Analysis: {vision_analysis.get('diagnosis', '')}"
    return formatted_output, fetch_product_links(product_links_query)

# print(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'uploads', 'images', 'test.jpg'))
# print(run_orchestrator("the microwave is not working",[], [os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'uploads', 'images', 'test.jpg')]))

# result = tool_node.invoke({"messages": [llm_with_tools.invoke("what's the weather in sf?")]})
# print(result)