"""
Web tools module for Home Helper.

This module provides web search and retrieval utilities for the Home Helper system.
"""

from langchain_community.document_loaders import BraveSearchLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from .tools.llm_config import embeddings
from typing import List, Tuple, Dict, Any
from langchain_core.tools import tool
import os
import requests

# Optional: Override Brave API key if needed
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")

# Define exports
__all__ = ['search_web', 'perform_brave_search', 'search_google_response']


@tool
def perform_brave_search(query: str, count: int = 10) -> List[Document]:
    """ Perform a Brave search and return the results as a list of Documents.
    Args:
        query (str): The search query.
        count (int): The number of results to return.
        Returns:
        List[Document]: A list of Documents containing the search results.
        """
    print("[Retrieval] Performing Brave search...")
    loader = BraveSearchLoader(
        api_key=BRAVE_API_KEY,
        query=query
    )
    return loader.load()[:count]

@tool
def search_google_response(query: str) -> str:
    """Search Google for the given query and return the top result."""
    url = f"https://www.google.com/search?q={query}"
    print("search_google_response")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }
    results = requests.get(url, headers=headers)
    if results.status_code == 200:
        return results.text
    else:
        return "Error fetching search results."

@tool
def search_web(query: str, num_results: int = 5) -> str:
    """
    Search the web for information related to the query.

    Args:
        query (str): The search query
        num_results (int): Number of results to return (default: 5)

    Returns:
        str: A formatted string containing search results
    """
    try:
        # Use Brave search as the primary method
        documents = perform_brave_search(query, count=num_results)

        # Format the results
        results = []
        for i, doc in enumerate(documents, 1):
            title = doc.metadata.get('title', 'No title')
            url = doc.metadata.get('link', 'No URL')
            snippet = doc.page_content[:200] + '...' if len(doc.page_content) > 200 else doc.page_content

            results.append(f"{i}. **{title}**\n   URL: {url}\n   {snippet}\n")

        if results:
            return f"Search results for '{query}':\n\n" + "\n".join(results)
        else:
            # Fallback to Google if no results from Brave
            return f"No results found for '{query}' using Brave Search. Try refining your query."

    except Exception as e:
        return f"Error performing web search: {str(e)}"
