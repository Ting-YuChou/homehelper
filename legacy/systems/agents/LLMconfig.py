from langchain_openai import ChatOpenAI
from langchain_huggingface import HuggingFaceEmbeddings
import os
from dotenv import load_dotenv
load_dotenv(override=True)

class Config:
    model_options = {
        "agentic": "gemma3",
        "tool_use": "DeepSeek-R1-Distill-Qwen-32B",
        "vision": "gemma3",
        "function_calling": "gorilla",
        "embeddings": "embed-mistral"
    }
    model_type = "agentic"
    llm_model = model_options[model_type]
    nrp_api_base = "https://llm.nrp-nautilus.io"
    nrp_api_key = os.environ.get("NRP_API_KEY")
    embedding_model_id = "sentence-transformers/all-mpnet-base-v2"  

    @staticmethod
    def get_llm(model_type):
        if(model_type=="tool_use"):
            from langchain_ollama import ChatOllama
            return ChatOllama(model="llama3.2:3b",tool_choice="auto")
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


embeddings = HuggingFaceEmbeddings(
    model_name=config.embedding_model_id,
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True}
)
