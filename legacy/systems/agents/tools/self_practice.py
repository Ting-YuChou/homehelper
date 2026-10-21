# agents/tools/self_practice.py
import json
import os
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional
import random
import concurrent.futures
import threading
import time

# Initialize LLM
from .tools.llm_config import config
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    openai_api_base=config.nrp_api_base,
    openai_api_key=config.nrp_api_key,
    model=config.model_options["tool_use"],
    temperature=0.3
)

# Global lock for safe writing to shared files
checkpoint_lock = threading.Lock()

def load_ifixit_data(ifixit_path: str) -> List[Dict]:
    """Load the processed iFixit repair manuals"""
    if not os.path.exists(ifixit_path):
        print(f"Cannot find iFixit data at {ifixit_path}")
        return []
    
    try:
        with open(ifixit_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading iFixit data: {e}")
        return []


def convert_ifixit_to_qa_pairs(ifixit_data: List[Dict]) -> List[Dict]:
    """Convert iFixit manuals to QA pairs format for compatibility"""
    qa_pairs = []
    
    for manual in ifixit_data:
        question = manual.get('problem', f"How do I {manual.get('title', 'repair this device')}?")
        answer = manual.get('full_procedure', '')
        
        if question and answer:
            qa_pairs.append({
                "question": question,
                "answer": answer
            })
    
    return qa_pairs

def process_qa_pair(pair: Dict, max_turns: int, pair_idx: int, total_pairs: int) -> List[Dict]:
    """Process a single QA pair in parallel and return generated examples"""
    try:
        question = pair["question"]
        correct_answer = pair["answer"]
        
        print(f"Processing QA pair {pair_idx+1}/{total_pairs}: {question[:50]}...")
        start_time = time.time()
        
        # Generate examples using the enhanced logic
        examples = generate_examples_from_qa(pair, max_turns)
        
        # Add pair_idx to each example for tracking
        for example in examples:
            example["qa_pair_idx"] = pair_idx
        
        end_time = time.time()
        elapsed = end_time - start_time
        print(f"QA pair {pair_idx+1}/{total_pairs} processed in {elapsed:.2f} seconds")
        
        return examples
    except Exception as e:
        print(f"Error processing QA pair {pair_idx+1}/{total_pairs}: {e}")
        # Return a single error example to maintain processing flow
        return [{
            "question": pair.get("question", "Unknown"),
            "context": [],
            "answer": f"ERROR: {str(e)}",
            "rationale": "An error occurred during processing",
            "label": "Reject",
            "turn": 0,
            "qa_pair_idx": pair_idx,
            "error": str(e)
        }]

def process_ifixit_manual(manual: Dict, max_turns: int, idx: int, total: int) -> List[Dict]:
    """Process a single iFixit manual in parallel and return generated examples"""
    try:
        # Extract title and steps
        title = manual.get("Title", "Unknown device repair")
        steps = manual.get("Steps", [])
        
        print(f"Processing iFixit manual {idx+1}/{total}: {title[:50]}...")
        start_time = time.time()
        
        if not steps or len(steps) < 3:
            return []  # Skip manuals with too few steps
        
        # Generate examples using the existing logic from generate_examples_from_ifixit
        examples = []
        
        # Create problem question from title
        question = f"How do I {title.lower()}?"
        
        # Use the full procedure as the correct answer
        full_procedure = " ".join([
            step.get("Text_raw", "") for step in steps
        ])
        
        # Create examples at different points in the procedure
        context = []
        
        for turn in range(min(max_turns, len(steps) - 1)):
            # Select steps to include in the current answer
            current_steps = steps[:turn+1]
            
            # Create partial answer from available steps
            partial_answer = " ".join([
                step.get("Text_raw", "") for step in current_steps
            ])
            
            # Generate rationale for this partial answer
            rationale = generate_ifixit_rationale(current_steps, title, turn)
            
            # Determine if this partial procedure is sufficient
            is_sufficient = (turn >= len(steps) - 2) or (random.random() > 0.8 and turn > 0)
            
            # Create example
            example = {
                "question": question,
                "context": context.copy(),
                "answer": partial_answer,
                "rationale": rationale,
                "label": "Accept" if is_sufficient else "Reject",
                "turn": turn,
                "manual_idx": idx
            }
            
            examples.append(example)
            
            # Generate query and simulate retrieval for next turn
            if turn < max_turns - 1 and turn < len(steps) - 1:
                query = f"Next steps for {title} after {current_steps[-1].get('Order', 0)}"
                
                # Add next step info to context
                next_step = steps[turn+1]
                retrieved_doc = f"Step {next_step.get('Order', 0)}: {next_step.get('Text_raw', '')}"
                
                # Add to context
                context.extend([query, retrieved_doc])
        
        end_time = time.time()
        elapsed = end_time - start_time
        print(f"iFixit manual {idx+1}/{total} processed in {elapsed:.2f} seconds")
        
        return examples
    except Exception as e:
        print(f"Error processing iFixit manual {idx+1}/{total}: {e}")
        return []

def generate_training_data(
    qa_pairs_file: str, 
    output_dir: str, 
    max_turns: int = 3,
    ifixit_data_path: Optional[str] = None,
    max_workers: int = 4
) -> None:
    """
    Generate synthetic training data for the Critic by self-practicing
    with parallel processing and checkpointing
    """
    # Create output directory if it doesn't exist
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Load QA pairs
    with open(qa_pairs_file, 'r') as f:
        qa_pairs = json.load(f)
    
    # Optionally load iFixit data for enrichment
    ifixit_data = []
    if ifixit_data_path and os.path.exists(ifixit_data_path):
        ifixit_data = load_ifixit_data(ifixit_data_path)
        print(f"Loaded {len(ifixit_data)} iFixit manuals for additional examples")
    
    # Check for existing checkpoint
    checkpoint_file = os.path.join(output_dir, "critic_training_data_checkpoint.json")
    output_file = os.path.join(output_dir, "critic_training_data.json")
    
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, 'r') as f:
            training_data = json.load(f)
            print(f"Loaded checkpoint with {len(training_data)} examples")
            
            # Find the processed QA pair indices
            processed_qa_indices = set()
            processed_ifixit_indices = set()
            
            for example in training_data:
                if "qa_pair_idx" in example:
                    processed_qa_indices.add(example["qa_pair_idx"])
                if "manual_idx" in example:
                    processed_ifixit_indices.add(example["manual_idx"])
            
            # Filter qa_pairs to only include unprocessed ones
            pairs_to_process = [(i, pair) for i, pair in enumerate(qa_pairs) if i not in processed_qa_indices]
            # Filter ifixit_data to only include unprocessed ones
            ifixit_to_process = [(i, manual) for i, manual in enumerate(ifixit_data) if i not in processed_ifixit_indices]
            
            print(f"Resuming with {len(pairs_to_process)} QA pairs and {len(ifixit_to_process)} iFixit manuals remaining")
    else:
        training_data = []
        pairs_to_process = list(enumerate(qa_pairs))
        ifixit_to_process = list(enumerate(ifixit_data))
    
    # Function to save checkpoint
    def save_checkpoint(data, checkpoint_path, final_path=None):
        with checkpoint_lock:
            with open(checkpoint_path, 'w') as f:
                json.dump(data, f, indent=2)
            if final_path:
                with open(final_path, 'w') as f:
                    json.dump(data, f, indent=2)
    
    # Process QA pairs in parallel
    if pairs_to_process:
        print(f"Starting parallel processing of {len(pairs_to_process)} QA pairs with {max_workers} workers")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all QA pairs for processing
            future_to_idx = {
                executor.submit(process_qa_pair, qa_pairs[idx], max_turns, idx, len(qa_pairs)): idx 
                for idx, pair in pairs_to_process
            }
            
            # Process results as they complete
            completed = 0
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    # Get results for this QA pair
                    new_examples = future.result()
                    
                    # Add to training data
                    with checkpoint_lock:
                        training_data.extend(new_examples)
                    
                    # Update counter
                    completed += 1
                    
                    # Save checkpoint periodically
                    if completed % 5 == 0 or completed == len(pairs_to_process):
                        save_checkpoint(training_data, checkpoint_file, output_file)
                        print(f"Saved progress: {completed}/{len(pairs_to_process)} QA pairs processed, {len(training_data)} examples")
                    
                except Exception as e:
                    print(f"ERROR processing QA pair {idx}: {e}")
    
    # Process iFixit data in parallel if available
    if ifixit_to_process:
        print(f"Starting parallel processing of {len(ifixit_to_process)} iFixit manuals with {max_workers} workers")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all iFixit manuals for processing
            future_to_idx = {
                executor.submit(process_ifixit_manual, ifixit_data[idx], max_turns, idx, len(ifixit_data)): idx 
                for idx, manual in ifixit_to_process
            }
            
            # Process results as they complete
            completed = 0
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    # Get results for this iFixit manual
                    new_examples = future.result()
                    
                    # Add to training data
                    with checkpoint_lock:
                        training_data.extend(new_examples)
                    
                    # Update counter
                    completed += 1
                    
                    # Save checkpoint periodically
                    if completed % 5 == 0 or completed == len(ifixit_to_process):
                        save_checkpoint(training_data, checkpoint_file, output_file)
                        print(f"Saved progress: {completed}/{len(ifixit_to_process)} iFixit manuals processed, {len(training_data)} examples")
                    
                except Exception as e:
                    print(f"ERROR processing iFixit manual {idx}: {e}")
    
    # Save final training data
    save_checkpoint(training_data, checkpoint_file, output_file)
    
    print(f"Generated {len(training_data)} training examples in {output_file}")

def generate_examples_from_qa(pair: Dict, max_turns: int) -> List[Dict]:
    """Generate training examples from a single QA pair"""
    question = pair["question"]
    correct_answer = pair["answer"]
    
    examples = []
    context = []
    
    for turn in range(max_turns):
        # Generate an answer attempt with current context
        answer, rationale = generate_answer_attempt(question, context, turn)
        
        # Check if answer is correct
        is_correct = is_answer_correct(answer, correct_answer)
        
        # Create training example
        example = {
            "question": question,
            "context": context.copy(),  # Copy to avoid reference issues
            "answer": answer,
            "rationale": rationale,
            "label": "Accept" if is_correct else "Reject",
            "turn": turn
        }
        
        examples.append(example)
        
        # If answer is correct and we're not at turn 0, sometimes also 
        # add an "Accept" example for the previous turn to create variety
        if is_correct and turn > 0 and random.random() < 0.3:
            alt_example = {
                "question": question,
                "context": context[:-2].copy(),  # Use context before latest addition
                "answer": answer,
                "rationale": rationale,
                "label": "Accept",  # Sometimes information was already sufficient
                "turn": turn - 1
            }
            examples.append(alt_example)
        
        # If we're at the last turn and still haven't gotten a correct answer,
        # sometimes force an Accept to balance the dataset
        if turn == max_turns - 1 and not is_correct and random.random() < 0.4:
            improved_answer, improved_rationale = generate_improved_answer(
                question, context, correct_answer
            )
            
            final_example = {
                "question": question,
                "context": context.copy(),
                "answer": improved_answer,
                "rationale": improved_rationale,
                "label": "Accept",  # Force accept for the final round
                "turn": turn
            }
            examples.append(final_example)
            
        # Generate a search query for the next round
        if turn < max_turns - 1:
            query = generate_search_query(question, context, answer, turn)
            
            # Simulate retrieval
            new_docs = simulate_retrieval(query)
            
            # Add to context
            context.extend([query] + new_docs)
    
    return examples

def generate_ifixit_rationale(steps: List[Dict], title: str, turn: int) -> str:
    """Generate a rationale for the current set of iFixit repair steps"""
    step_texts = [f"Step {step.get('Order', i+1)}: {step.get('Text_raw', '')}" 
                  for i, step in enumerate(steps)]
    
    prompt = f"""
    Generate a rationale for why the current repair instructions for 
    "{title}" are {'sufficient' if turn >= 2 else 'insufficient'}.
    
    Current instructions include:
    {' '.join(step_texts)}
    
    If insufficient, explain what additional information would be needed.
    If sufficient, explain why these steps are enough to complete the repair.
    
    Rationale:
    """
    
    response = llm.invoke(prompt)
    return response.content.strip()

def generate_answer_attempt(question: str, context: List[str], turn: int) -> Tuple[str, str]:
    """Generate an answer attempt based on the current context"""
    context_text = "\n".join(context) if context else "No context available"
    
    # Vary completeness/correctness based on the turn to create diverse training data
    if turn == 0 and random.random() < 0.7:
        completeness_instruction = "Your answer should be incomplete as you lack sufficient information."
    elif turn == 1 and random.random() < 0.5:
        completeness_instruction = "Your answer should be partially complete but missing some key details."
    elif turn == 2 and random.random() < 0.3:
        completeness_instruction = "Your answer should be mostly complete but could benefit from more specifics."
    else:
        completeness_instruction = "Provide your best and most complete answer with the available information."
    
    prompt = f"""
    Question about appliance repair: {question}
    
    Current available information: 
    {context_text}
    
    Provide your best attempt at answering this repair question.
    {completeness_instruction}
    
    Format your response as:
    ANSWER: [your answer]
    RATIONALE: [your detailed reasoning about why this answer is or isn't sufficient]
    """
    
    response = llm.invoke(prompt)
    content = response.content
    
    # Parse answer and rationale
    if "RATIONALE:" in content:
        parts = content.split("RATIONALE:")
        answer = parts[0].replace("ANSWER:", "").strip()
        rationale = parts[1].strip()
    else:
        answer = content.replace("ANSWER:", "").strip()
        rationale = "No explicit rationale provided"
        
    return answer, rationale

def generate_improved_answer(question: str, context: List[str], correct_answer: str) -> Tuple[str, str]:
    """Generate an improved answer that's closer to the correct answer"""
    context_text = "\n".join(context) if context else "No context available"
    
    prompt = f"""
    Question about appliance repair: {question}
    
    Current available information: 
    {context_text}
    
    The correct answer contains these key points: {correct_answer}
    
    Generate an improved answer that incorporates the key points from the correct answer
    while staying grounded in the available context. The answer should be complete and helpful.
    
    Format your response as:
    ANSWER: [your improved answer]
    RATIONALE: [your detailed reasoning about why this answer is now sufficient]
    """
    
    response = llm.invoke(prompt)
    content = response.content
    
    # Parse answer and rationale
    if "RATIONALE:" in content:
        parts = content.split("RATIONALE:")
        answer = parts[0].replace("ANSWER:", "").strip()
        rationale = parts[1].strip()
    else:
        answer = content.replace("ANSWER:", "").strip()
        rationale = "This answer incorporates all the necessary information to solve the problem."
        
    return answer, rationale

def is_answer_correct(answer: str, correct_answer: str) -> bool:
    """Determine if the generated answer is correct"""
    prompt = f"""
    Compare these two answers about appliance repair and determine if they are effectively equivalent:
    
    Answer 1: {answer}
    
    Answer 2 (Ground Truth): {correct_answer}
    
    Are these answers providing the same core solution to the problem?
    Consider whether Answer 1 includes the key troubleshooting steps and repair instructions from Answer 2.
    
    Answer only YES or NO.
    """
    
    response = llm.invoke(prompt)
    
    # Create more nuanced distribution of accepts/rejects
    # Early rounds should mostly be rejects, later rounds more accepts
    return "YES" in response.content.upper()

def generate_search_query(question: str, context: List[str], prev_answer: str, turn: int) -> str:
    """Generate a search query based on the context and previous answer"""
    context_text = "\n".join(context) if context else "No context available"
    
    # Make queries more targeted based on turn number
    if turn == 0:
        query_instruction = "Generate a broad search query about the general appliance issue."
    elif turn == 1:
        query_instruction = "Generate a more specific query focusing on likely causes of this problem."
    else:
        query_instruction = "Generate a very specific query targeting the exact repair procedure needed."
    
    prompt = f"""
    Based on the user's question and our current understanding, generate a search query to find additional information.
    
    Question: {question}
    
    Current Context: 
    {context_text}
    
    Previous Answer Attempt: 
    {prev_answer}
    
    {query_instruction}
    Generate a focused search query:
    """
    
    response = llm.invoke(prompt)
    return response.content.strip()

def simulate_retrieval(query: str) -> List[str]:
    """Simulate document retrieval - in a real system, this would call an actual retriever"""
    
    prompt = f"""
    Simulate being a retrieval system for appliance repair information.
    Generate 2-3 realistic, detailed, and helpful documents that might be retrieved for this query:
    
    Query: {query}
    
    The documents should include specific repair instructions, troubleshooting steps, or technical details
    that would genuinely help solve an appliance repair problem. Include model-specific information when
    appropriate and safety warnings where relevant.
    
    Return each document starting with "Document: "
    """
    
    response = llm.invoke(prompt)
    content = response.content
    
    # Parse documents
    docs = []
    for line in content.split("Document:"):
        if line.strip():
            docs.append(line.strip())
    
    return docs