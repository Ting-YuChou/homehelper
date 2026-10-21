"""
LLM Configuration module for Home Helper.

This module provides configuration and instances for language models and embeddings
used throughout the Home Helper system.
"""

from langchain_openai import ChatOpenAI
from langchain_huggingface import HuggingFaceEmbeddings
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Define exports
__all__ = ['config', 'llm', 'embeddings']

class Config:
    model_options = {
        "agentic": "gemma3",
        "tool_use": "llama3-sdsc",
        "vision": "llama3",
        "function_calling": "gorilla",
        "embeddings": "embed-mistral"
    }
    model_type = "tool_use"
    llm_model = model_options[model_type]
    nrp_api_base = "https://llm.nrp-nautilus.io"
    nrp_api_key = os.environ.get("NRP_API_KEY")
    embedding_model_id = "sentence-transformers/all-mpnet-base-v2"

    @staticmethod
    def get_llm(model_type):
        model_name = Config.model_options[model_type]
        return ChatOpenAI(
            openai_api_base=Config.nrp_api_base,
            openai_api_key=Config.nrp_api_key,
            model=model_name,
            temperature=0.2
        )
    @staticmethod
    def get_embeddings():
        return HuggingFaceEmbeddings(
            model_name=Config.embedding_model_id,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True}
        )

config = Config()

llm = ChatOpenAI(
    openai_api_base=config.nrp_api_base,
    openai_api_key=config.nrp_api_key,
    model=config.llm_model,
    temperature=0.2
)

embeddings = HuggingFaceEmbeddings(
    model_name=config.embedding_model_id,
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True}
)
