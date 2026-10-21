"""
Retrieval utilities module for Home Helper.

This module provides document retrieval and processing functions for the Home Helper system,
including search, chunking, scoring, and answer generation.
"""

from langchain_community.document_loaders import BraveSearchLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI
from langchain_huggingface import HuggingFaceEmbeddings
from typing import List, Tuple, Dict, Any
import os
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

# Define exports
__all__ = [
    'retrieve_documents',
    'generate_final_answer',
    'perform_brave_search',
    'chunk_documents',
    'score_documents_by_embedding_similarity',
    'generate_search_query'
]

# Initialize LLM
from .llm_config import config

llm = ChatOpenAI(
    openai_api_base=config.nrp_api_base,
    openai_api_key=config.nrp_api_key,
    model=config.model_options["tool_use"],
    temperature=0.3 # Keep temperature here for answer generation
)

# Initialize embeddings (Used for document scoring)
# Ensure this is the same embeddings model used elsewhere if consistency is needed
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-mpnet-base-v2", # Using the model from llm_config
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True}
)

# Brave Search API key
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")

# Note: generate_search_query function is now primarily handled by RAGAgent.py's prompt
# This function remains here for potential standalone use or if needed elsewhere.
# It will use the LLM configured in this file if called directly.
def generate_search_query(appliance_info: str, problem_description: str,
                         text_description: str, reasoning_round: int,
                         previous_context: str, critic_feedback: str) -> str:
    """Generate a search query based on the appliance info and problem diagnosis."""
    # This prompt is similar to the one in RAGAgent.py for consistency
    prompt = f"""
    You are an expert at generating concise and effective search queries for appliance repair issues.
    Your goal is to find specific troubleshooting steps, repair guides, or solutions.

    Based on the following information, generate the single best search query.
    Focus on the appliance model, the specific symptom, and relevant keywords like "troubleshooting", "repair", or "fix".
    If this is a subsequent round, refine the query based on the previous search attempt and the critic's feedback.
    Do NOT include conversational text or unnecessary technical details unless they are error codes or specific, searchable terms.
    Return ONLY the search query text with no additional explanations or formatting.

    APPLIANCE INFO:
    {appliance_info}

    DIAGNOSED PROBLEM:
    {problem_description}

    USER DESCRIPTION:
    {text_description}

    PREVIOUS INTERACTION HISTORY:
    {previous_context}

    Critic Feedback on Previous Attempt:
    {critic_feedback}

    Generate a targeted search query:
    """

    try:
        response = llm.invoke(prompt) # Use the LLM initialized in this file
        query = response.content.strip()
        query = query.replace('`', '').replace('"', '').replace("Search Query:", "").strip()
        if not query:
             raise ValueError("Generated query is empty after cleaning.")
        return query
    except Exception as e:
        print(f"[Query Generation Error in retrieval_utils] Failed to generate query: {e}")
        fallback_query_base = f"{appliance_info} {problem_description} troubleshooting"
        return fallback_query_base.strip() if fallback_query_base.strip() else text_description


def perform_brave_search(query: str, count: int = 10) -> List[Document]:
    """Perform search using Brave Search API"""
    print(f"[Retrieval] Performing Brave search for: {query}")

    loader = BraveSearchLoader(
        api_key=BRAVE_API_KEY,
        query=query,
        search_kwargs={"count": count}
    )
    try:
        return loader.load()
    except Exception as e:
        print(f"[Retrieval Error] Brave search failed: {e}")
        return []


def chunk_documents(docs: List[Document], chunk_size: int = 500, chunk_overlap: int = 100) -> List[Document]:
    """Chunk documents into smaller pieces"""
    print(f"[Retrieval] Chunking {len(docs)} documents...")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return splitter.split_documents(docs)

# Removed the LLM-based score_document_relevance function

def score_documents_by_embedding_similarity(query: str, docs: List[Document]) -> List[Tuple[Document, float]]:
    """Score documents based on embedding similarity to the query."""
    if not docs:
        return []

    try:
        # Embed the query
        query_embedding = embeddings.embed_query(query)

        # Embed the documents
        # Extract document content for embedding
        doc_contents = [doc.page_content for doc in docs]
        doc_embeddings = embeddings.embed_documents(doc_contents)

        # Calculate cosine similarity between query and document embeddings
        # Reshape query_embedding for cosine_similarity function
        query_embedding_reshaped = np.array(query_embedding).reshape(1, -1)
        doc_embeddings_np = np.array(doc_embeddings)

        # Calculate similarity scores
        similarity_scores = cosine_similarity(query_embedding_reshaped, doc_embeddings_np)[0]

        # Pair documents with their scores
        scored_docs = [(docs[i], score) for i, score in enumerate(similarity_scores)]

        # Sort by score in descending order
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        return scored_docs

    except Exception as e:
        print(f"[Embedding Scoring Error] Failed to score documents using embeddings: {e}")
        # Fallback: return documents with a default score, maintaining original order
        return [(doc, 0.5) for doc in docs]


def classify_source_type(link: str) -> str:
    """Classify the type of source based on URL"""
    if any(domain in link for domain in ["youtube.com", "vimeo.com"]): # Corrected youtube domains
        return "video"
    if any(domain in link for domain in ["manualslib", "support", ".pdf"]):
        return "manual"
    if any(domain in link for domain in ["reddit.com", "quora.com", "justanswer", "stackexchange"]):
        return "forum"
    return "article"


def retrieve_documents(query: str, appliance_info: str, top_k_docs: int = 5, top_k_chunks: int = 5) -> List[str]:
    """
    Retrieve relevant documents from Brave Search, score them by embedding similarity,
    chunk the top documents, and return the content of the top chunks.
    """
    # Augment query with appliance info for better initial search results
    augmented_query = f"{query} {appliance_info}".strip()

    # Perform Brave search
    original_docs = perform_brave_search(augmented_query, count=10) # Get 10 initial documents

    if not original_docs:
        print("[Retrieval] No results from Brave search, using fallback information.")
        return [
            "No specific documents found. General troubleshooting steps: 1) Check power supply, 2) Look for error codes, 3) Consult manufacturer website.",
            f"For appliance issues with {appliance_info}, first ensure all connections are secure and the unit has power."
        ]

    # Score the original documents by embedding similarity
    scored_original_docs = score_documents_by_embedding_similarity(query, original_docs)

    # Select the top_k_docs original documents based on embedding similarity score
    top_n_original_docs = [doc for doc, score in scored_original_docs[:top_k_docs]]

    if not top_n_original_docs:
         print(f"[Retrieval] No original documents scored highly enough to select top {top_k_docs}.")
         # Fallback to chunking and returning content from the initial search results if scoring fails
         chunked_fallback_docs = chunk_documents(original_docs)
         return [doc.page_content for doc in chunked_fallback_docs[:top_k_chunks]]


    # Chunk only the top N original documents
    chunked_docs = chunk_documents(top_n_original_docs)

    # Score the chunks (optional, could just take top chunks from top docs)
    # For simplicity and reduced calls, let's just take the top_k_chunks from the combined list
    # If more sophisticated chunk ranking is needed, embedding similarity could be applied here too.
    # Let's re-score chunks by embedding similarity to select the best ones across documents
    scored_chunks = score_documents_by_embedding_similarity(query, chunked_docs)

    # Return just the content from top_k_chunks
    # Add source type info to the document content before returning
    final_retrieved_content = []
    for doc, score in scored_chunks[:top_k_chunks]:
         link = doc.metadata.get("link", "N/A")
         source_type = classify_source_type(link)
         final_retrieved_content.append(f"[{source_type.upper()}] {doc.page_content}")
         # Print for debugging
         title = doc.metadata.get("title", "Untitled")
         print(f"[Retrieval] Final Chunk ({score:.4f}): {title[:60]}... | {source_type.upper()}")


    return final_retrieved_content

def generate_final_answer(query: str, docs: List[str], appliance_info: str,
                        problem_description: str, text_description: str) -> Tuple[str, str]:
    """Generate a final answer and rationale based on retrieved documents"""

    # Use the provided docs (which are now chunk content)
    context = "\n\n".join([f"Document {i+1}: {doc}" for i, doc in enumerate(docs)])

    prompt = f"""
    You are a helpful appliance repair assistant. Based on the following information, provide:
    1. A clear answer that helps solve the user's problem
    2. Your reasoning process (which will not be shown to the user)

    USER ISSUE:
    {text_description}

    APPLIANCE INFO:
    {appliance_info}

    DIAGNOSED PROBLEM:
    {problem_description}

    SEARCH QUERY USED:
    {query}

    RETRIEVED INFORMATION:
    {context}

    Provide your response in the following format:
    ANSWER: [Your helpful response to the user with clear, step-by-step repair instructions]

    RATIONALE: [Your detailed reasoning process, explaining how the retrieved information supports your answer]
    """

    response = llm.invoke(prompt) # Use the LLM initialized in this file
    content = response.content

    # Split into answer and rationale
    parts = content.split("RATIONALE:")

    if len(parts) < 2:
        answer = content.replace("ANSWER:", "").strip()
        rationale = "No explicit rationale provided."
    else:
        answer = parts[0].replace("ANSWER:", "").strip()
        rationale = parts[1].strip()

    return answer, rationale
