"""
Storage tools module for Home Helper.

This module provides document storage and retrieval utilities for the Home Helper system.
"""

from langchain_community.document_loaders import BraveSearchLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from .llm_config import embeddings
from .tools.web_tools import perform_brave_search
from typing import List, Tuple
import os

# Define exports
__all__ = ['chunk_documents', 'build_vector_index', 'get_retriever_for_query']


def chunk_documents(docs: List[Document], chunk_size: int = 500, chunk_overlap: int = 100) -> List[Document]:
    print(f"[Retrieval] Chunking {len(docs)} documents...")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return splitter.split_documents(docs)


def build_vector_index(chunks: List[Document]) -> FAISS:
    print(f"[Retrieval] Building FAISS vector index with {len(chunks)} chunks...")
    return FAISS.from_documents(chunks, embeddings)


def get_retriever_for_query(query: str) -> Tuple[FAISS, List[Document], List[Document]]:
    """
    High-level retrieval pipeline:
    - Brave search
    - Chunking
    - Embedding
    - FAISS index
    Returns FAISS retriever, original docs, and chunked docs
    """
    original_docs = perform_brave_search(query)
    chunked_docs = chunk_documents(original_docs)
    index = build_vector_index(chunked_docs)
    return index, original_docs, chunked_docs