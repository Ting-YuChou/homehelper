"""
Critic utilities module for Home Helper.

This module provides evaluation and criticism functions for the Home Helper system,
including answer sufficiency evaluation and document summarization.
"""

from langchain_openai import ChatOpenAI
import os
from typing import Tuple, List, Optional
from transformers import T5ForConditionalGeneration, T5Tokenizer
import torch

# Define exports
__all__ = ['evaluate_sufficiency', 'summarize_docs']

# Initialize Critic LLM - will be replaced with fine-tuned model
from .llm_config import config
critic_llm = ChatOpenAI(
    openai_api_base=config.nrp_api_base,
    openai_api_key=config.nrp_api_key,
    model=config.model_options["tool_use"],  # Using the tool_use model for summarization
    temperature=0.1
)

# Load the trained Critic model (T5)
MODEL_PATH = "google/flan-t5-base" # Ensure this path is correct
try:
    critic_tokenizer = T5Tokenizer.from_pretrained(MODEL_PATH)
    critic_model = T5ForConditionalGeneration.from_pretrained(MODEL_PATH)
    print(f"Successfully loaded Critic model from {MODEL_PATH}")
except Exception as e:
    print(f"Error loading Critic model from {MODEL_PATH}: {e}")
    print("Using a fallback LLM for criticism (this will be less effective).")
    # Fallback Critic if T5 model fails to load
    critic_model = None # Indicate that T5 model is not loaded

def summarize_docs(docs: List[str], query: str, text_description: str) -> str:
    """Summarize a list of documents to reduce context length for the Critic."""
    if not docs:
        return "No relevant documents were retrieved."

    # Limit the number of documents to summarize to avoid exceeding context window
    # Even for summarization, the input to the summarization LLM has limits.
    # Selecting top documents based on previous scoring is a good strategy.
    # Assuming docs are already sorted by relevance in retrieval_utils.py
    docs_to_summarize = docs[:5] # Summarize the top 5 documents

    docs_text = "\n\n".join([f"Document {i+1}: {doc}" for i, doc in enumerate(docs_to_summarize)])

    prompt = f"""
    Summarize the following documents to highlight the key information relevant to the user's appliance repair issue.
    Focus on troubleshooting steps, potential causes, and solutions mentioned.

    User Issue: {text_description}
    Search Query: {query}

    Documents:
    {docs_text}

    Provide a concise summary of the key repair information:
    """
    try:
        # Use the critic_llm (which is ChatOpenAI) for summarization
        response = critic_llm.invoke(prompt)
        return response.content.strip()
    except Exception as e:
        print(f"[Summarization Error] Failed to summarize documents: {e}")
        # Fallback to using the raw documents if summarization fails
        return docs_text # Return raw docs (will likely still cause token error for T5)


def evaluate_sufficiency(query: str, text_description: str, appliance_info: str,
                       docs: List[str], answer: str, rationale: str, critic_explanation: Optional[str]) -> Tuple[str, str]:
    """Evaluate if the current answer is sufficient using the trained Critic model or a fallback."""

    # Summarize documents to reduce input length for the Critic model
    summarized_context = summarize_docs(docs, query, text_description)

    input_text = f"""
    Question: {text_description}

    Appliance Info: {appliance_info}

    Context (Summarized from Retrieved Documents):
    {summarized_context}

    Answer: {answer}

    Rationale: {rationale}

    Is this answer sufficient?
    """
    # Add previous critic explanation to the prompt for context in later rounds
    if critic_explanation and critic_explanation != "No explicit rationale provided.":
         input_text += f"\n\nPrevious Critic Feedback: {critic_explanation}"


    # Use trained T5 Critic model if loaded, otherwise use a fallback LLM
    if critic_model:
        try:
            # Use trained Critic model (T5)
            inputs = critic_tokenizer(input_text, return_tensors="pt", truncation=True, max_length=512) # Add truncation
            outputs = critic_model.generate(**inputs)
            verdict = critic_tokenizer.decode(outputs[0], skip_special_tokens=True)

            # Simple check for explanation based on verdict
            if "accept" in verdict.lower():
                explanation = "The answer appears sufficient based on the provided information."
            else:
                 # If T5 rejects, use the critic_llm to generate a more detailed explanation
                 explanation_prompt = f"""
                 The previous answer was deemed insufficient. Based on the following information,
                 explain why the answer is not sufficient and what kind of information is still needed.

                 Question: {text_description}
                 Appliance Info: {appliance_info}
                 Context (Summarized): {summarized_context}
                 Answer: {answer}
                 Rationale: {rationale}

                 Explanation for why the answer is insufficient:
                 """
                 explanation_response = critic_llm.invoke(explanation_prompt)
                 explanation = explanation_response.content.strip()


            # Check verdict from T5 model
            if "accept" in verdict.lower():
                return "Accept", explanation
            else:
                return "Reject", explanation # Return the detailed explanation from critic_llm

        except Exception as e:
            print(f"[Critic T5 Error] Failed to run T5 model: {e}")
            print("Falling back to LLM for criticism.")
            # Fallback to LLM if T5 model encounters an error during inference
            verdict, explanation = evaluate_sufficiency_with_llm(input_text)
            return verdict, explanation

    else:
        # Use fallback LLM for criticism if T5 model was not loaded
        print("[Critic Fallback] Using LLM for criticism.")
        verdict, explanation = evaluate_sufficiency_with_llm(input_text)
        return verdict, explanation

def evaluate_sufficiency_with_llm(input_text: str) -> Tuple[str, str]:
    """Fallback function to evaluate sufficiency using a general LLM."""
    prompt = f"""
    Evaluate the sufficiency of the following answer for an appliance repair question.
    Consider the provided context.

    {input_text}

    Is the answer sufficient? Respond with "Verdict: Accept" or "Verdict: Reject" followed by a brief explanation.
    """
    try:
        response = critic_llm.invoke(prompt)
        content = response.content.strip()
        if "verdict: accept" in content.lower():
            verdict = "Accept"
            explanation = content.replace("Verdict: Accept", "").strip()
        else:
            verdict = "Reject"
            explanation = content.replace("Verdict: Reject", "").strip()
        return verdict, explanation
    except Exception as e:
        print(f"[Critic LLM Fallback Error] Failed to evaluate with fallback LLM: {e}")
        return "Reject", "Critic evaluation failed."

