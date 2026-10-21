import time
import requests
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.tools import tool
from langchain_ollama.chat_models import ChatOllama
from langchain_ollama.embeddings import OllamaEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_core.messages import ToolMessage
from langchain.schema import Document,  BaseMessage
from langgraph.graph import StateGraph, END
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, TypedDict, Tuple
import json
from langchain_community.document_loaders import BraveSearchLoader
import os
import re
from urllib.parse import urlparse, parse_qs

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")

#write all the print statements in all the modules and submodules to a file called debug.log by default
import sys
# sys.stdout = open('debug_product_recc.log', 'w')
# 
import random
# Initialize the embedding function
embedding_function = OllamaEmbeddings(model="nomic-embed-text")

# Initialize the in-memory vector store
vector_store = InMemoryVectorStore(embedding_function)

@tool
def store_data_vectorstore(data: str) -> None:
    """Store the given data in the vector store."""
    print(f"Storing data in vector store: {data}")
    # Embed the data and store it in the vector store
    document = Document(page_content=data)
    vector_store.add_documents([document])

@tool
def search_vectorstore(query: str) -> List[str]:
    """Search the vector store for the given query."""
    print(f"Searching vector store for: {query}")
    results = vector_store.similarity_search(query, k=5)  # Adjust 'k' for top N results
    return [result.page_content for result in results]

def fetch_page_content(url: str) -> Optional[str]:
    """Fetch the content of a webpage."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching page content: {e}")
        return None

def extract_amazon_info(url: str) -> Tuple[str, str]:
    """Extract product title and description from Amazon page."""
    try:
        # Clean and validate the URL
        parsed_url = urlparse(url)
        if not parsed_url.netloc.endswith('amazon.com'):
            return url, "Invalid Amazon URL"
            
        # Extract ASIN from URL
        asin = None
        path_parts = parsed_url.path.split('/')
        for part in path_parts:
            if re.match(r'^[A-Z0-9]{10}$', part):
                asin = part
                break
                
        if not asin:
            # Try to extract from query parameters
            query_params = parse_qs(parsed_url.query)
            if 'dp' in query_params:
                asin = query_params['dp'][0]
            elif 'product' in query_params:
                asin = query_params['product'][0]
        
        if not asin:
            return url, "Could not extract product ID"
            
        # Construct a clean Amazon URL with the ASIN
        clean_url = f"https://www.amazon.com/dp/{asin}"
        
        # Try to fetch the page content
        content = fetch_page_content(clean_url)
        if not content:
            return clean_url, "Product information unavailable"
        
        soup = BeautifulSoup(content, 'html.parser')
        
        # Extract title
        title = None
        title_elem = soup.find('span', {'id': 'productTitle'})
        if title_elem:
            title = title_elem.get_text().strip()
        
        # Extract description
        description = None
        desc_elem = soup.find('div', {'id': 'productDescription'})
        if desc_elem:
            description = desc_elem.get_text().strip()
        else:
            # Try alternative description locations
            desc_elem = soup.find('div', {'id': 'feature-bullets'})
            if desc_elem:
                description = desc_elem.get_text().strip()
        
        if not title:
            # Use a generic title with the ASIN
            title = f"Amazon Product ({asin})"
        
        if not description:
            description = "Product information unavailable"
        
        return title, description
    except Exception as e:
        print(f"Error extracting Amazon info: {e}")
        return url, "Error retrieving product information"

def extract_youtube_info(url: str) -> Tuple[str, str]:
    """Extract video title and description from YouTube page."""
    try:
        content = fetch_page_content(url)
        if not content:
            return url, "No description available"
        
        soup = BeautifulSoup(content, 'html.parser')
        
        # Extract title
        title = None
        title_elem = soup.find('meta', {'property': 'og:title'})
        if title_elem:
            title = title_elem.get('content')
        
        # Extract description
        description = None
        desc_elem = soup.find('meta', {'property': 'og:description'})
        if desc_elem:
            description = desc_elem.get('content')
        
        if not title:
            # Extract from URL if title not found
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            if 'v' in query_params:
                video_id = query_params['v'][0]
                title = f"YouTube Video {video_id}"
        
        if not description:
            description = "No description available"
        
        return title or url, description
    except Exception as e:
        print(f"Error extracting YouTube info: {e}")
        return url, "No description available"

@tool
def perform_brave_search(query: str, count: int = 10) -> List[Dict[str, str]]:
    """Perform search using Brave Search API and return structured results with titles and descriptions."""
    print(f"[Retrieval] Performing Brave search for: {query}")

    # Modify query to specifically look for Amazon and YouTube links
    search_query = f"{query} site:amazon.com OR site:youtube.com"
    
    loader = BraveSearchLoader(
        api_key=BRAVE_API_KEY,
        query=search_query,
        search_kwargs={"count": count}
    )
    try:
        docs = loader.load()
        results = []
        for doc in docs:
            url = doc.metadata.get("link")
            if not url:
                continue
                
            if "amazon.com" in url:
                title, description = extract_amazon_info(url)
                # Only add if we got a valid title
                if title and title != url:
                    results.append({
                        "type": "amazon",
                        "url": url,
                        "title": title,
                        "description": description
                    })
            elif "youtube.com" in url:
                title, description = extract_youtube_info(url)
                results.append({
                    "type": "youtube",
                    "url": url,
                    "title": title,
                    "description": description
                })
        return results
    except Exception as e:
        print(f"[Retrieval Error] Brave search failed: {e}")
        return []

tool_map = {
    # "store_data_vectorstore": store_data_vectorstore,
    # "search_vectorstore": search_vectorstore,
    "perform_brave_search": perform_brave_search,
}

class AgentState(TypedDict):
    messages: List[BaseMessage]
    tool_calls: Optional[List[Dict]]
    tool_result: Optional[str]
    agent_count: int
    critic_count: int

def summarize(messages):
    if isinstance(messages, list):
        return messages[-1]
    return messages

global_iter = 0

def agent(state: AgentState) -> AgentState:
    llm = ChatOllama(model="llama3.2:3b", tool_choice="auto")
    start = time.time()
    print("\n=== AGENT CALL START ===")
    print(f"Current agent count: {state.get('agent_count', 0)}")
    print(f"Current critic count: {state.get('critic_count', 0)}")
    
    if state.get("agent_count", 0) >= 2:
        print("Agent limit reached, generating final summary")
        summary_llm = ChatOllama(model="gemma3")
        last_message = state["messages"][-1]
        last_content = last_message.content if hasattr(last_message, 'content') else last_message.get('content', '')
        
        try:
            # Process the search results and format them
            search_results = json.loads(last_content)
            formatted_results = []
            
            # Group results by type
            amazon_results = [r for r in search_results if r["type"] == "amazon"]
            youtube_results = [r for r in search_results if r["type"] == "youtube"]
            
            if amazon_results:
                formatted_results.append("TOOLS NEEDED:")
                for result in amazon_results:
                    formatted_results.append(f"- [{result['title']}]({result['url']}): {result['description']}")
            
            if youtube_results:
                formatted_results.append("\nYOUTUBE TUTORIALS:")
                for result in youtube_results:
                    formatted_results.append(f"- [{result['title']}]({result['url']}): {result['description']}")
            
            final_content = "\n".join(formatted_results)
            return {
                "messages": state["messages"] + [AIMessage(content=final_content)],
                "agent_count": state["agent_count"],
                "critic_count": state.get("critic_count", 0)
            }
        except json.JSONDecodeError:
            # If the content is not valid JSON, return it as is
            return {
                "messages": state["messages"] + [AIMessage(content=last_content)],
                "agent_count": state["agent_count"],
                "critic_count": state.get("critic_count", 0)
            }
    
    llm = llm.bind_tools(tools=tool_map.values())
    temp_messages = []
    temp_messages.append(SystemMessage(content="""You are a helpful assistant that provides specific product links and YouTube tutorials for home repairs. Your task is to:
1. Use the perform_brave_search tool to find:
   - Amazon links for specific tools needed for the repair
   - YouTube tutorial links that show how to do the repair
2. The tool will return structured results with titles and descriptions
3. Format your response to include both Amazon products and YouTube tutorials

IMPORTANT:
- You MUST use the perform_brave_search tool to find actual Amazon and YouTube links
- You MUST use the exact URLs, titles, and descriptions returned by the search tool
- Do not modify or make up any content
- Only include actual Amazon and YouTube links in your response
- Format links in markdown style: [Title](URL)"""))
    
    summarized_messages = summarize(state["messages"])
    temp_messages.append(summarized_messages)
    
    print("\n=== INVOKING LLM ===")
    response = llm.invoke(temp_messages)
    print(f"LLM Response: {response}")
    
    iter = 0
    while response.tool_calls and iter < 2:
        print(f"\n=== TOOL CALL ITERATION {iter + 1} ===")
        tool_calls = [t for t in response.tool_calls]
        for tool_call in tool_calls:
            print(f"Calling tool: {tool_call['name']}")
            result = tool_map[tool_call["name"]].invoke(tool_call["args"])
            print(f"Tool result: {result}")
            temp_messages.append(ToolMessage(
                content=json.dumps(result),
                name=tool_call["name"],
                tool_call_id=tool_call["id"],
            ))
        
        response = llm.invoke([temp_messages[0], summarize(temp_messages[1:])])
        temp_messages.append(response)
        iter += 1
    
    print("\n=== AGENT CALL COMPLETE ===")
    agent_count = state.get("agent_count", 0) + 1
    
    if not response.content:
        response.content = "No valid response generated. Please try again."
    
    return {
        "messages": state["messages"] + [AIMessage(content=response.content)],
        "agent_count": agent_count,
        "critic_count": state.get("critic_count", 0)
    }

def critic(state):
    print("\n=== CRITIC CALL START ===")
    print(f"Current critic count: {state.get('critic_count', 0)}")
    
    if state.get("critic_count", 0) >= 2:
        print("Critic limit reached, returning True")
        return True
        
    llm = ChatOllama(model="mistral:7b")
    llm = llm.bind_tools(tools=tool_map.values())
    messages = []
    messages.append(SystemMessage(content="""You are a helpful assistant that helps improve responses about home appliances and home improvement. Your task is to give TRUE or FALSE if the response contains:
1. At least one valid Amazon product link (must be a full URL starting with https://www.amazon.com)
2. At least one valid YouTube tutorial link (must be a full URL starting with https://www.youtube.com)
3. Accurate titles and descriptions for each link
4. A clear organization of tools and tutorials

Make sure that:
- The links exist and are valid
- The titles and descriptions match the actual content
- The content is relevant to the repair procedure"""))
    
    last_message = state["messages"][-1]
    last_content = last_message.content if hasattr(last_message, 'content') else last_message.get('content', '')
    messages.append(HumanMessage(content=last_content))
    
    response = llm.invoke(messages)
    state["critic_count"] = state.get("critic_count", 0) + 1
    
    result = response.content.strip().lower() == "true"
    print(f"Critic result: {result}")
    print("=== CRITIC CALL COMPLETE ===\n")
    return result

def main():
    input_text = """
    You want to repair your refrigerator leak.
    Step-by-Step Repair Instructions
    Identify the Issue: Common refrigerator problems include:
    Leaking water
    Unusual noises
    Insufficient cooling
    Over-freezing
    Ice maker malfunctions
    Safety First: Unplug the refrigerator before performing any repairs to avoid electrical hazards.
    Inspect and Diagnose:
    Leaks: Check door gaskets for wear, ensure the defrost drain isn't clogged, and inspect the drain pan for cracks or overflow.
    Noises: Level the refrigerator, inspect the evaporator fan for obstructions or wear, and ensure the compressor is functioning properly.
    Cooling Issues: Verify temperature settings, inspect door seals, ensure vents aren't blocked, and clean condenser coils.
    Over-Freezing: Check the damper control and thermostat settings.
    Ice Maker Problems: Inspect the water supply line for clogs, check the inlet valve, and ensure the ice maker assembly is functioning.
    Replace Faulty Components:
    Order the necessary replacement parts based on your diagnosis.
    Use the screwdriver to remove and replace defective components like gaskets, thermostats, or fan motors.
    Use the multimeter to test electrical components for continuity before replacement.
    Reassemble and Test:
    After replacing faulty parts, reassemble the refrigerator components.
    Plug in the refrigerator and monitor its performance to ensure the issue is resolved.
    """
    input_text = """This microwave is giving too much noise"""
    print("OUTPUT: ",get_product_recommendations(input_text))

def get_product_recommendations(input_text):
    messages = []
    messages.append(SystemMessage(content="""You are a helpful assistant that recommends products based on the user's query. 
                                  Make sure to get links to that products that are actually useful, no reviews or guide, but actual products.
                                  And also you should provide utility tools that the user can use to complete the task or repair the appliance.
    You should recommend products that are relevant to the user's query and provide accurate titles and descriptions from the actual product pages.
    Be concise: each description should be no more than 1-2 lines.
                                  """))
    
    if isinstance(input_text, dict):
        input_text = str(input_text)
    elif isinstance(input_text, list):
        input_text = " ".join(str(item) for item in input_text)
    
    messages.append(HumanMessage(content=input_text))
    state = {
        "messages": messages,
        "agent_count": 0,
        "critic_count": 0
    }
    
    lang_graph = StateGraph(AgentState)
    lang_graph.add_node("agent", agent)
    lang_graph.add_conditional_edges("agent", lambda state: "agent" if not critic(state) and state["agent_count"] < 2 else END)
    lang_graph.set_entry_point("agent")
    lang_graph = lang_graph.compile()
    
    response = lang_graph.invoke(state)
    
    if not response["messages"]:
        return "No valid response generated. Please try again."
    
    for message in reversed(response["messages"]):
        if hasattr(message, 'content'):
            content = message.content
        else:
            content = message.get('content', '')
        if content and content != "No valid response generated. Please try again.":
            return content
    
    return "No valid response generated. Please try again."

# if __name__ == "__main__":
#     main()
    # print(perform_brave_search.invoke("how to repair a refrigerator"))
