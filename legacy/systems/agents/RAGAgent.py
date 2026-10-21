# agents/RAGAgent.py
from typing import Dict, Any # Import Dict and Any for state type hinting
# Import the updated retrieve_documents
from .tools.retrieval_utils import retrieve_documents
    # Call LLM directly
from .tools.llm_config import config
from langchain_openai import ChatOpenAI
from .tools.retrieval_utils import generate_final_answer

def rag_generate_query(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a search query based on the current state and previous rounds."""

    # Get current reasoning round
    reasoning_round = state.get("reasoning_round", 0)

    # Get previous context and critic feedback
    previous_docs = state.get("retrieved_docs", [])
    previous_query = state.get("query", "")
    critic_feedback = state.get("critic_explanation", "No specific feedback from critic.")

    # Prepare previous interaction history
    prev_context_items = []
    if previous_query:
        prev_context_items.append(f"Previous Search Query: {previous_query}")
    # While the full list of retrieved_docs is kept in the state,
    # we primarily rely on the critic feedback and problem description for query refinement
    # to keep the prompt focused.

    prev_context_text = "\n".join(prev_context_items) if prev_context_items else "No previous search queries."

    # Build prompt for query generation
    # Make the instructions clearer and emphasize generating a concise, effective search query
    prompt = f"""
    You are an expert at generating concise and effective search queries for appliance repair issues.
    Your goal is to find specific troubleshooting steps, repair guides, or solutions.

    Based on the following information, generate the single best search query.
    Focus on the appliance model, the specific symptom, and relevant keywords like "troubleshooting", "repair", or "fix".
    If this is a subsequent round, refine the query based on the previous search attempt and the critic's feedback.
    Do NOT include conversational text or unnecessary technical details unless they are error codes or specific, searchable terms.
    Return ONLY the search query text with no additional explanations or formatting.

    APPLIANCE INFO:
    {state.get("appliance_info", "Unknown appliance")}

    DIAGNOSED PROBLEM:
    {state.get("diagnosis", "Unknown problem")}

    USER DESCRIPTION:
    {state["text_description"]}

    PREVIOUS INTERACTION HISTORY:
    {prev_context_text}

    Critic Feedback on Previous Attempt:
    {critic_feedback}

    Generate a targeted search query:
    """


    # Using the configured LLM for query generation
    llm = ChatOpenAI(
        openai_api_base=config.nrp_api_base,
        openai_api_key=config.nrp_api_key,
        model=config.llm_model, # Using the configured llm_model
        temperature=0.5 # Slightly increased temperature for potentially better query variations
    )

    query = "" # Initialize query
    try:
        response = llm.invoke(prompt)
        query = response.content.strip()

        # Clean the query - remove common unwanted characters/phrases
        query = query.replace('`', '').replace('"', '').replace("Search Query:", "").strip()
        # Ensure the query is not empty after cleaning
        if not query:
             raise ValueError("Generated query is empty after cleaning.")

        print(f"[Round {reasoning_round + 1}] Generated query: {query}")
    except Exception as e:
        # Fallback query if LLM call fails or generates empty query
        fallback_query_base = f"{state.get('appliance_info', '')} {state.get('diagnosis', '')} troubleshooting"
        query = fallback_query_base.strip() if fallback_query_base.strip() else state["text_description"]
        print(f"[ERROR] Failed to generate query: {e}")
        print(f"[Round {reasoning_round + 1}] Using fallback query: {query}")
    
    # Generate documents directly here
  
    # Retrieve documents using the generated query
    # Use the updated parameter names: top_k_docs and top_k_chunks
    # Using default values (5 for both) as defined in retrieval_utils_updated_v2
    docs = retrieve_documents(
        query=query,
        appliance_info=state.get("appliance_info", ""), # Still pass appliance info for retrieval context
        top_k_docs=5, # Number of top original documents to select
        top_k_chunks=5 # Number of top chunks to return
    )

    # Add to existing docs if any
    # Note: The Critic will only receive a summary of these docs due to changes in critic_utils
    current_docs = state.get("retrieved_docs", [])
    # Append new docs to the list
    all_docs = current_docs + docs

    # Increment reasoning round and return updated state
    return {
        **state,
        "query": query, # Store the generated query in the state
        "retrieved_docs": all_docs,
        "reasoning_round": reasoning_round + 1
    }

# The rag_generate_answer function remains the same
def rag_generate_answer(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate an answer based on the retrieved documents"""

    # Generate answer and rationale

    
    answer, rationale = generate_final_answer(
        query=state.get("query", state["text_description"]),
        docs=state.get("retrieved_docs", []), # Use all accumulated docs for answer generation
        appliance_info=state.get("appliance_info", ""),
        problem_description=state.get("diagnosis", ""),
        text_description=state["text_description"]
    )

    return {**state, "answer": answer, "rationale": rationale}

