# generate_qa_pairs.py
import json
import os
from pathlib import Path
from typing import List, Dict
import random

def generate_qa_pairs(output_file: str, num_pairs: int = 50):
    """Generate synthetic QA pairs for appliance repair"""
    
    # Define appliance types
    appliances = [
        "refrigerator", "dishwasher", "washing machine", "dryer", "microwave", 
        "oven", "stove", "range", "freezer", "garbage disposal", "water heater",
        "air conditioner", "furnace", "vacuum cleaner", "blender", "toaster", 
        "coffee maker", "food processor", "mixer", "deep fryer"
    ]
    
    # Define brands
    brands = [
        "Samsung", "LG", "Whirlpool", "GE", "Frigidaire", "Maytag", "KitchenAid", 
        "Bosch", "Kenmore", "Electrolux", "Amana", "Haier", "Hotpoint", "Miele",
        "Thermador", "Sub-Zero", "Viking", "Dyson", "Shark", "Breville"
    ]
    
    # Define common problems by appliance type
    problems = {
        "refrigerator": [
            "not cooling properly", "making loud noises", "leaking water", 
            "freezer not freezing", "ice maker not working", "water dispenser not working",
            "freezing food in refrigerator section", "frost buildup in freezer",
            "interior light not working", "door not sealing properly"
        ],
        "dishwasher": [
            "not cleaning dishes properly", "not draining", "leaking water", 
            "making strange noises", "door not latching", "soap dispenser not opening",
            "leaving white residue on dishes", "displaying error code", 
            "not starting", "stopping mid-cycle"
        ],
        "washing machine": [
            "not spinning", "not draining", "making loud noises", "vibrating excessively",
            "leaking water", "not filling with water", "door or lid won't lock",
            "clothes still wet after cycle", "displaying error code", "not starting"
        ],
        "dryer": [
            "not heating", "taking too long to dry clothes", "making loud noises",
            "turning off prematurely", "not tumbling", "overheating", "door not closing properly",
            "displaying error code", "tripping circuit breaker", "burning smell"
        ],
        "microwave": [
            "not heating food", "turntable not rotating", "making loud noises",
            "sparking inside", "display not working", "door not closing properly",
            "buttons not responding", "burning smell", "shutting off unexpectedly",
            "light inside not working"
        ],
        "oven": [
            "not heating properly", "temperature inaccurate", "door not closing",
            "self-cleaning feature not working", "broiler not working", "making strange noises",
            "display not working", "burning smell", "elements not heating", "timer not working"
        ]
    }
    
    # Default problems for appliances not specifically defined
    default_problems = [
        "not turning on", "making strange noises", "overheating", "smoking",
        "shutting off unexpectedly", "leaking", "display not working", 
        "error message showing", "burning smell", "damaged power cord"
    ]
    
    # Define common answers/solutions
    solutions = {
        "refrigerator not cooling properly": "For a refrigerator not cooling properly: 1) Check if the vents inside the refrigerator are blocked with food, 2) Clean the condenser coils at the back or bottom, 3) Ensure the door seals are intact and making proper contact, 4) Check if the evaporator fan is running, 5) Verify the temperature settings are correct, 6) Make sure the refrigerator has proper clearance for ventilation, 7) If these steps don't resolve the issue, the refrigerator may have a failing compressor or refrigerant leak requiring professional service.",
        
        "dishwasher not draining": "For a dishwasher that's not draining: 1) Remove and clean the filter at the bottom of the dishwasher, 2) Check for food debris in the drain hose, 3) Ensure the drain hose isn't kinked or clogged, 4) Verify the garbage disposal is clear if the dishwasher drains into it, 5) Check that the air gap (if installed) isn't blocked, 6) Run a cycle with dishwasher cleaner to remove buildup, 7) If these steps don't work, the drain pump may need to be replaced.",
        
        "washing machine not spinning": "For a washing machine not spinning: 1) Make sure the load is balanced and not overloaded, 2) Check if the lid switch or door lock is functioning properly, 3) Look for objects caught between the inner and outer drums, 4) Test the drive belt for wear or damage, 5) Verify the motor coupling is intact, 6) Ensure the machine is on a level surface, 7) Check for error codes on the display, 8) If these steps don't help, the motor, control board, or transmission may need professional repair.",
        
        "dryer not heating": "For a dryer not heating: 1) Check if the power supply is adequate (gas dryers need both electricity and gas), 2) Clean the lint trap and exhaust vent thoroughly, 3) Test the thermal fuse for continuity (this is a common failure point), 4) Check the heating element or gas valve solenoids, 5) Verify the cycling thermostat and high-limit thermostat are functioning, 6) Ensure the dryer isn't in air-dry or fluff mode, 7) If these steps don't resolve the issue, the control board may need replacement.",
        
        "microwave not heating food": "For a microwave not heating food: 1) Test if other functions work (light, fan, turntable), 2) Check if the door switches are engaging properly, 3) Listen for the magnetron humming when operating, 4) Ensure the microwave isn't in a demo or showcase mode, 5) Verify the diode and capacitor are functioning (WARNING: do not attempt to service these components as they can hold a lethal electrical charge even when unplugged), 6) For persistent issues, professional service is recommended as microwaves contain dangerous high-voltage components."
    }
    
    # Generate QA pairs
    qa_pairs = []
    
    for _ in range(num_pairs):
        # Select random appliance type
        appliance = random.choice(list(problems.keys()) if random.random() < 0.7 else appliances)
        
        # Select random brand
        brand = random.choice(brands)
        
        # Select random problem
        if appliance in problems:
            problem = random.choice(problems[appliance])
        else:
            problem = random.choice(default_problems)
        
        # Create question
        question = f"My {brand} {appliance} is {problem}."
        
        # Find specific solution or generate a generic one
        solution_key = f"{appliance} {problem}"
        if solution_key in solutions:
            answer = solutions[solution_key]
        else:
            # Generate a more generic answer based on the problem type
            if "not turning on" in problem:
                answer = f"For a {brand} {appliance} that's not turning on: 1) Check if it's properly plugged in and the outlet has power, 2) Inspect the power cord for damage, 3) Check if a circuit breaker has tripped, 4) Look for a reset button on the appliance, 5) Verify any safety switches or interlocks are engaged, 6) If applicable, check if the display shows any error codes, 7) Test any fuses that may be accessible to the user, 8) If these steps don't resolve the issue, the control board or internal power supply may need professional service."
            
            elif "noise" in problem:
                answer = f"For a {brand} {appliance} making strange noises: 1) Ensure the appliance is level and stable, 2) Check for loose parts or foreign objects, 3) Inspect for worn bearings or bushings, 4) Look for damaged or unbalanced moving parts, 5) Tighten any loose screws or fasteners, 6) If the noise is rhythmic, check rotating components like fans or motors, 7) If the noise is accompanied by vibration, check mounting hardware, 8) For persistent unusual noises, professional diagnosis may be necessary as it could indicate a failing motor or other major component."
            
            elif "leaking" in problem:
                answer = f"For a leaking {brand} {appliance}: 1) Turn off and unplug the appliance if possible, 2) Check all water connections for looseness or damage, 3) Inspect hoses for cracks or wear, 4) Look for clogged drain lines that might cause backup, 5) Check door seals or gaskets for tears or buildup, 6) Ensure the appliance is level so water flows properly, 7) Look for cracks in interior components or the housing, 8) If you can't locate the source of the leak or it persists after tightening connections, professional service is recommended."
            
            else:
                answer = f"To troubleshoot your {brand} {appliance} that is {problem}: 1) Consult the user manual for specific guidance, 2) Unplug the appliance for 1-2 minutes and then plug it back in to reset the electronics, 3) Check for any error codes and look them up in the manual or manufacturer's website, 4) Clean any filters or vents that might be causing restricted airflow or operation, 5) Ensure all settings are correct for the intended operation, 6) Look for visible damage to components or wiring, 7) If these basic steps don't help, contact {brand} customer service or a qualified repair technician as the issue may require professional diagnosis and repair."
        
        # Add to QA pairs
        qa_pairs.append({
            "question": question,
            "answer": answer
        })
    
    # Save to file
    Path(os.path.dirname(output_file)).mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(qa_pairs, f, indent=2)
    
    print(f"Generated {len(qa_pairs)} QA pairs and saved to {output_file}")
    return qa_pairs

def main():
    # Generate 50 QA pairs
    generate_qa_pairs("data/training/synthetic_qa_pairs.json", num_pairs=50)
    
    # Optionally combine with existing pairs
    original_qa_file = "data/training/qa_pairs.json"
    if os.path.exists(original_qa_file):
        with open(original_qa_file, 'r') as f:
            original_qa_pairs = json.load(f)
        
        with open("data/training/synthetic_qa_pairs.json", 'r') as f:
            synthetic_qa_pairs = json.load(f)
        
        combined_qa_pairs = original_qa_pairs + synthetic_qa_pairs
        
        with open("data/training/expanded_qa_pairs.json", 'w') as f:
            json.dump(combined_qa_pairs, f, indent=2)
        
        print(f"Combined original ({len(original_qa_pairs)}) and synthetic ({len(synthetic_qa_pairs)}) QA pairs into expanded dataset with {len(combined_qa_pairs)} pairs")

if __name__ == "__main__":
    main()