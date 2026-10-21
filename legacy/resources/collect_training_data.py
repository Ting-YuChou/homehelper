# collect_training_data.py
import json
import os
from pathlib import Path

def create_qa_pairs():
    """
    Create basic QA pairs for appliance repair to use as training seeds
    In a real implementation, these would come from your existing data
    """
    qa_pairs = [
        {
            "question": "My Samsung refrigerator is not cooling properly, the temperature is around 50°F.",
            "answer": "For a Samsung refrigerator not cooling properly: 1) Check if the vents inside the refrigerator are blocked with food, 2) Clean the condenser coils at the back or bottom, 3) Ensure the door seals are intact and making proper contact, 4) Check if the evaporator fan is running, 5) If these steps don't resolve the issue, the refrigerator may have a failing compressor or refrigerant leak requiring professional service."
        },
        {
            "question": "My Whirlpool dryer is making a loud squeaking noise during operation.",
            "answer": "For a squeaking Whirlpool dryer: 1) Check and replace worn drum rollers which are a common cause of squeaking, 2) Inspect the idler pulley for wear and replace if necessary, 3) The drum bearing may need lubrication or replacement, 4) Ensure the dryer is level on the floor, 5) The blower wheel might be contacting its housing or have debris caught in it."
        },
        {
            "question": "My LG dishwasher shows an OE error code and stops mid-cycle.",
            "answer": "For an LG dishwasher with OE error code: 1) This indicates a drainage issue, 2) Check and clean the drain hose for any kinks or clogs, 3) Remove and clean the drain pump filter, usually located at the bottom of the dishwasher, 4) Check the air gap if installed, 5) Ensure the garbage disposal is clear if the dishwasher drains into it, 6) If these steps don't resolve the issue, the drain pump may need to be replaced."
        }
        # Add more pairs as needed
    ]
    
    # Create directory if it doesn't exist
    Path("data/training").mkdir(parents=True, exist_ok=True)
    
    # Save to file
    with open("data/training/qa_pairs.json", "w") as f:
        json.dump(qa_pairs, f, indent=2)
    
    print(f"Created {len(qa_pairs)} QA pairs for training")

if __name__ == "__main__":
    create_qa_pairs()