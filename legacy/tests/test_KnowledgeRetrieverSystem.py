# run_agent.py
from systems.KnowledgeRetrievalSystem import app
import sys
import os

def run_agent(text_description, image_path=None):
    """Run the appliance repair agent"""
    
    # Initial state
    initial_state = {
        "image_path": image_path,
        "text_description": text_description,
        "appliance_info": None,
        "extracted_features": None,
        "diagnosis": None,
        "fallback_triggered": False,
        "query": None,
        "reasoning_round": 0,
        "answer": None,
        "rationale": None,
        "retrieved_docs": [],
        "verdict": None,
        "critic_explanation": None,
        "text_only_mode": image_path is None
    }
    
    # Run the agent
    print(f"Processing request: {text_description}")
    if image_path:
        print(f"Image: {image_path}")
    else:
        print("Running in text-only mode")
    print("-" * 50)
    
    # Execute the agent
    result = app.invoke(initial_state)
    
    # Extract final answer
    final_answer = result.get("answer", "No answer generated.")
    
    print("\nFinal Answer:")
    print("-" * 50)
    print(final_answer)
    
    # Print debug info if requested
    if "--debug" in sys.argv:
        print("\nDebug Information:")
        print("-" * 50)
        print(f"Reasoning Rounds: {result.get('reasoning_round', 0)}")
        print(f"Verdict: {result.get('verdict', 'None')}")
        if not result.get("text_only_mode"):
            print(f"Vision Info: {result.get('appliance_info', 'None')}")
        print(f"Retrieved Docs: {len(result.get('retrieved_docs', []))}")
    
    return result

if __name__ == "__main__":
    # Example usage
    if len(sys.argv) < 2:
        print("Usage: python run_agent.py <problem_description> [image_path] [--debug]")
        print("       python run_agent.py <problem_description> --debug")
        sys.exit(1)
    
    # Parse arguments
    text_description = sys.argv[1]
    image_path = None
    
    # Check if second argument is an image path or debug flag
    if len(sys.argv) > 2 and not sys.argv[2].startswith("--"):
        image_path = sys.argv[2]
    
    run_agent(text_description, image_path)