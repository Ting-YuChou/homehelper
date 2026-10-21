"""
Agents module for Home Helper.

This module contains the specialized agents used in the Home Helper system,
including vision processing, RAG (Retrieval-Augmented Generation), and critic agents.
"""

# Vision Agent functions
from .VisionAgent import (
    vision_extract_info,
    vision_scan_features,
    vision_detect_problem,
    vision_fallback
)

# RAG Agent functions
from .RAGAgent import (
    rag_generate_query,
    rag_generate_answer
)

# Critic Agent functions
from .CriticAgent import (
    critic_evaluate
)

from .memory import AgentState
import systems.agents as agents
import systems.agents.tools as tools

# Export all agent functions
__all__ = [
    # Vision Agent
    'vision_extract_info',
    'vision_scan_features',
    'vision_detect_problem',
    'vision_fallback',

    # RAG Agent
    'rag_generate_query',
    'rag_generate_answer',

    # Critic Agent
    'critic_evaluate',
]