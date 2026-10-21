from typing import TypedDict, Optional, Annotated
import operator

class AgentState(TypedDict):
    # Existing fields
    messages: Annotated[list, operator.add]
    image_path: str
    video_path: str
    tries: int
    summary_for_retrieval: Optional[str]
    text_description: str
    appliance_info: Optional[str]
    extracted_features: Optional[str]
    diagnosis: Optional[str]
    fallback_triggered: bool
    
    # New SIM-RAG fields
    reasoning_round: int              # Track iteration count
    answer: Optional[str]             # Current answer
    rationale: Optional[str]          # Reasoning rationale
    retrieved_docs: Optional[list[str]]  # Context documents
    verdict: Optional[str]            # Critic verdict (Accept/Reject)
    critic_explanation: Optional[str]  # Critic reasoning
    
    
    # NEW fields required by ExpertSystem.py 
    accepted: bool                         
    critique: Optional[str]                
    content: Optional[list[str]]          
    final_output: Optional[str] 