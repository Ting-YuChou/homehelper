import sys

# Redirect stdout to a log file
# sys.stdout = open('/home/kanandan/PROJECTS/HomeHelper/cse247-HomeHelper-Sigma/output.log', 'a')


import sqlite3
import requests
import json
import uuid
from typing import List, Dict, Tuple
import time
import os
from langchain_ollama import ChatOllama
from langchain.schema import HumanMessage, SystemMessage, AIMessage

def ensure_conversation_dir():
    """Ensure the conversations directory exists."""
    os.makedirs("conversations", exist_ok=True)

def get_scenarios_with_intonations() -> List[Tuple[str, str, str]]:
    """Retrieve scenarios, solutions, and human intonations from the database."""
    conn = sqlite3.connect('home_helper.db')
    cursor = conn.cursor()
    
    # Query to get scenarios, solutions, and human intonations
    cursor.execute("""
        SELECT scenario, conversation, human_intonations 
        FROM appliance_scenarios
    """)
    
    scenarios = []
    for row in cursor.fetchall():
        scenario = row[0]
        solution = row[1]
        intonation = row[2].strip() if row[2] else ""
        scenarios.append((scenario, solution, intonation))
    
    conn.close()
    return scenarios

def save_conversation_to_db(scenario: str, intonation: str, chat_history: List[Dict]):
    """Save the conversation to the database using scenario and intonation as composite key."""
    conn = sqlite3.connect('home_helper.db')
    cursor = conn.cursor()
    
    # Create the system_conversation_qwq column if it doesn't exist
    cursor.execute("""
        SELECT name FROM pragma_table_info('appliance_scenarios') 
        WHERE name='system_conversation_qwq'
    """)
    if not cursor.fetchone():
        cursor.execute("""
            ALTER TABLE appliance_scenarios 
            ADD COLUMN system_conversation_qwq TEXT
        """)
    
    # Convert chat history to JSON string
    conversation_json = json.dumps({
        "chat_history": chat_history,
        "intonation_used": intonation
    })
    
    # Update the conversation in the database using composite key
    cursor.execute("""
        UPDATE appliance_scenarios 
        SET system_conversation_qwq = ? 
        WHERE scenario = ? AND human_intonations = ?
    """, (conversation_json, scenario, intonation))
    
    conn.commit()
    conn.close()

def check_if_solution_found(response: str, solution: str) -> bool:
    """Check if the Home Helper's response indicates it has found the solution."""
    # Convert both to lowercase for comparison
    response_lower = response.lower()
    solution_lower = solution.lower()
    
    # Check if key phrases from the solution appear in the response
    key_phrases = solution_lower.split()
    key_phrases = [phrase for phrase in key_phrases if len(phrase) > 3]  # Filter out short words
    
    # If more than 70% of key phrases are found in the response, consider it solved
    matches = sum(1 for phrase in key_phrases if phrase in response_lower)
    return (matches / len(key_phrases)) > 0.7 if key_phrases else False

def generate_user_message(chat_history: List[Dict], scenario: str, intonation: str) -> str:
    """Generate the next message as a user experiencing the scenario using Gemma3."""
    chat = ChatOllama(model="gemma3")
    
    system_prompt = f"""You are a user experiencing a home appliance problem.
    Your communication style is: {intonation}
    Your goal is to describe your problem to a handyman helper without directly stating the solution.
    Be natural and conversational, as if you're actually experiencing this issue.
    Focus on the symptoms and effects of the problem rather than the technical details.
    Maintain your communication style throughout the conversation.
    
    For example, if your style is 'DIY, Curious and Tech Savy', you might:
    - Show interest in understanding the technical aspects
    - Mention any troubleshooting you've already tried
    - Ask about the underlying causes
    - Be willing to try solutions yourself"""
    
    # Convert chat history to messages
    messages = [SystemMessage(content=system_prompt)]
    
    for msg in chat_history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))
    
    # Add the current scenario as context
    messages.append(HumanMessage(content=f"Remember, you are experiencing this scenario: {scenario}"))
    messages.append(HumanMessage(content="What would you say next to describe your problem to the handyman?"))
    
    response = chat.invoke(messages)
    return response.content

def save_conversation_to_file(scenario: str, solution: str, chat_history: List[Dict], turns: int, solved: bool, intonation: str):
    """Save the conversation to a file in the conversations directory."""
    conversation_data = {
        "scenario": scenario,
        "expected_solution": solution,
        "turns_completed": turns,
        "solved": solved,
        "intonation_used": intonation,
        "chat_history": chat_history
    }
    
    # Create a safe filename from the scenario
    safe_filename = "".join(c if c.isalnum() else "_" for c in scenario)
    filename = f"conversations/{safe_filename}_{uuid.uuid4()}.json"
    
    with open(filename, 'w') as f:
        json.dump(conversation_data, f, indent=2)

def test_scenario(scenario: str, solution: str, intonation: str) -> Dict:
    """Test a single scenario with the chat endpoint through multiple turns."""
    session_id = str(uuid.uuid4())
    chat_history = []
    max_turns = 10
    solved = False
    
    # Initial message to start the conversation
    initial_prompt = f"""Hi, I'm having an issue at home and I need some help. Can you assist me?"""
    
    for turn in range(max_turns):
        # Generate the next message as a user experiencing the problem
        current_message = initial_prompt if turn == 0 else generate_user_message(chat_history, scenario, intonation)
        
        # Make POST request to chat endpoint
        response = requests.post(
            "http://localhost:8006/chat",
            data={
                "message": current_message,
                "session_id": session_id
            }
        )
        
        if response.status_code != 200:
            return {
                "scenario": scenario,
                "solution": solution,
                "error": f"Request failed with status {response.status_code}",
                "status": "error",
                "turns_completed": turn,
                "solved": False,
                "intonation": intonation
            }
        
        response_data = response.json()
        print(f"\nTurn {turn + 1}:")
        print(f"User: {current_message}")
        print(f"Assistant: {response_data['agent_response']}")
        
        # Add messages to chat history
        chat_history.append({"role": "user", "content": current_message})
        chat_history.append({"role": "assistant", "content": response_data["agent_response"]})
        
        # Check if the problem has been solved
        if check_if_solution_found(response_data["agent_response"], solution):
            solved = True
            break
        
        # Add a small delay between requests
        time.sleep(1)
    
    # Save the conversation to both file and database
    save_conversation_to_file(scenario, solution, chat_history, turn + 1, solved, intonation)
    save_conversation_to_db(scenario, intonation, chat_history)
    
    return {
        "scenario": scenario,
        "solution": solution,
        "chat_history": chat_history,
        "turns_completed": turn + 1,
        "solved": solved,
        "status": "success",
        "intonation": intonation
    }

def main():
    # Ensure conversations directory exists
    ensure_conversation_dir()
    
    # Get all scenarios with their solutions and intonations (one per row)
    scenarios = get_scenarios_with_intonations()
    print(f"Found {len(scenarios)} scenario-intonation pairs to test")
    
    results = []
    
    # Test each scenario-intonation pair
    for idx, (scenario, solution, intonation) in enumerate(scenarios):
        print(f"ID: {idx}")
        print(f"\nTesting scenario: {scenario}")
        print(f"Using intonation: {intonation}")
        result = test_scenario(scenario, solution, intonation)
        results.append(result)
        
        # Save intermediate results after each scenario
        with open('evaluation_results.json', 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"Completed scenario in {result['turns_completed']} turns")
        print(f"Problem solved: {result['solved']}")
        print(f"Done with scenario using intonation: {intonation}")
    
    print("\nEvaluation complete. Results saved to evaluation_results.json")

if __name__ == "__main__":
    main()