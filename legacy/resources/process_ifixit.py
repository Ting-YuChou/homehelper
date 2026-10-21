# process_ifixit.py
import json
import os
import argparse
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("process_ifixit")

def setup_argparse() -> argparse.Namespace:
    """Setup command line argument parsing"""
    parser = argparse.ArgumentParser(description='Process iFixit/MyFixit dataset for SIM-RAG training')
    
    parser.add_argument(
        '--input_dir', 
        type=str, 
        default='MyFixit-Dataset',
        help='Directory containing the MyFixit-Dataset repository'
    )
    
    parser.add_argument(
        '--output_file', 
        type=str, 
        default='data/ifixit/processed_ifixit_manuals.json',
        help='Output file for processed data'
    )
    
    parser.add_argument(
        '--appliance_only', 
        action='store_true',
        help='Process only appliance-related repair manuals'
    )
    
    parser.add_argument(
        '--max_manuals', 
        type=int, 
        default=500,
        help='Maximum number of manuals to process'
    )
    
    parser.add_argument(
        '--min_steps', 
        type=int, 
        default=3,
        help='Minimum number of steps required in a manual'
    )
    
    parser.add_argument(
        '--verbose', 
        action='store_true',
        help='Enable verbose logging'
    )
    
    return parser.parse_args()

def is_appliance_repair(manual: Dict[str, Any]) -> bool:
    """Check if a manual is related to home appliance repair"""
    appliance_keywords = [
        'refrigerator', 'fridge', 'freezer', 'dishwasher', 'washer', 'dryer', 
        'oven', 'stove', 'microwave', 'toaster', 'blender', 'mixer', 'food processor',
        'coffee', 'vacuum', 'air conditioner', 'air filter', 'heater', 'furnace',
        'humidifier', 'dehumidifier', 'water heater', 'garbage disposal',
        'range hood', 'exhaust fan', 'cooktop', 'deep fryer', 'electric kettle',
        'slow cooker', 'pressure cooker', 'rice cooker', 'grill', 'bbq'
    ]
    
    title = manual.get('Title', '').lower()
    category = manual.get('Category', '').lower()
    ancestors = manual.get('Ancestors', [])
    
    # Check if any appliance keyword is in the title, category, or ancestors
    if any(keyword in title for keyword in appliance_keywords):
        return True
    
    if any(keyword in category for keyword in appliance_keywords):
        return True
        
    for ancestor in ancestors:
        if isinstance(ancestor, str) and any(keyword in ancestor.lower() for keyword in appliance_keywords):
            return True
            
    return False

def extract_repair_manuals(
    input_dir: str, 
    appliance_only: bool = False,
    max_manuals: int = 500,
    min_steps: int = 3,
    verbose: bool = False
) -> List[Dict[str, Any]]:
    """Extract repair manuals from the MyFixit dataset"""
    # Look for the JSON directory in the input directory
    json_dir = os.path.join(input_dir, "jsons")
    
    if not os.path.exists(json_dir):
        # Try looking for tmp.json as an alternative
        tmp_file = os.path.join(input_dir, "tmp.json")
        if os.path.exists(tmp_file):
            logger.info(f"Using tmp.json file at {tmp_file}")
            return extract_from_json_file(tmp_file, appliance_only, max_manuals, min_steps, verbose)
        else:
            logger.error(f"Cannot find JSON directory at {json_dir} or tmp.json file")
            return []
    
    all_manuals = []
    
    # Process each JSON file (different device categories)
    for filename in os.listdir(json_dir):
        if not filename.endswith('.json'):
            continue
        
        file_path = os.path.join(json_dir, filename)
        category = filename.replace('.json', '')
        
        logger.info(f"Processing {category} manuals from {file_path}...")
        
        # Extract manuals from this file
        file_manuals = extract_from_json_file(file_path, appliance_only, 
                                             max_manuals - len(all_manuals), 
                                             min_steps, verbose, category)
        
        # Add to our collection
        all_manuals.extend(file_manuals)
        
        if len(all_manuals) >= max_manuals:
            logger.info(f"Reached maximum number of manuals ({max_manuals})")
            break
    
    logger.info(f"Extracted {len(all_manuals)} manuals in total")
    return all_manuals

def extract_from_json_file(
    file_path: str, 
    appliance_only: bool = False,
    max_manuals: int = 500,
    min_steps: int = 3,
    verbose: bool = False,
    default_category: str = "Unknown"
) -> List[Dict[str, Any]]:
    """Extract manuals from a single JSON file"""
    manuals = []
    
    try:
        # MyFixit files are in JSONL format (one JSON object per line)
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
            for line_num, line in enumerate(lines):
                if len(manuals) >= max_manuals:
                    break
                
                try:
                    # Parse the JSON object
                    manual = json.loads(line.strip())
                    
                    # Add category if not present
                    if 'Category' not in manual:
                        manual['Category'] = default_category
                    
                    # Skip if not an appliance and appliance_only is True
                    if appliance_only and not is_appliance_repair(manual):
                        if verbose:
                            logger.debug(f"Skipping non-appliance manual: {manual.get('Title', 'Unknown')}")
                        continue
                    
                    # Skip if not enough steps
                    steps = manual.get('Steps', [])
                    if len(steps) < min_steps:
                        if verbose:
                            logger.debug(f"Skipping manual with insufficient steps: {len(steps)} < {min_steps}")
                        continue
                    
                    # Add to our collection
                    manuals.append(manual)
                    
                    if verbose and len(manuals) % 10 == 0:
                        logger.debug(f"Processed {len(manuals)} manuals so far")
                        
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse JSON at line {line_num+1}")
                    continue
                except Exception as e:
                    logger.warning(f"Error processing manual at line {line_num+1}: {e}")
                    continue
    
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
    
    logger.info(f"Extracted {len(manuals)} manuals from {file_path}")
    return manuals

def generate_problem_statement(title: str, category: str) -> str:
    """Generate a question/problem statement from the repair manual title"""
    title_lower = title.lower()
    
    # Remove common prefixes/suffixes for cleaner questions
    title_cleaned = re.sub(r'^(how to|guide to|step by step|tutorial for)\s+', '', title_lower)
    title_cleaned = re.sub(r'\s+(guide|tutorial|walkthrough|howto|instructions)$', '', title_cleaned)
    
    if 'replacement' in title_lower or 'replace' in title_lower:
        # Extract what's being replaced if possible
        match = re.search(r'(replace|replacement of|replacing)\s+(?:the|a|an)?\s*([a-z0-9\s\-]+?)(?:\s+in|\s+on|\s+for|\s+of|$)', title_lower)
        if match:
            component = match.group(2).strip()
            return f"How do I replace the {component} in my {category}?"
        else:
            return f"How do I perform the {title_cleaned} in my {category}?"
    
    elif 'repair' in title_lower or 'fix' in title_lower:
        return f"My {category} needs repair. {title}. How do I fix it?"
    
    elif 'troubleshoot' in title_lower or 'diagnose' in title_lower:
        return f"How do I troubleshoot problems with my {category} as described in {title}?"
    
    else:
        return f"How do I {title_cleaned} for my {category}?"

def process_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Process the steps in a repair manual"""
    processed_steps = []
    
    for step in steps:
        # Get step order (position)
        order = step.get('Order', 0)
        
        # Get text content - try different possible formats
        text = step.get('Text_raw', '')
        if not text and 'Lines' in step:
            # Some manuals have text in a 'Lines' list with 'Text' keys
            text = ' '.join([line.get('Text', '') for line in step.get('Lines', [])])
        
        # Get tools required for this step
        tools = step.get('Tools', [])
        
        # Get parts being manipulated in this step (if annotated)
        parts = []
        if 'Word_level_parts' in step:
            parts = [part.get('name', '') for part in step.get('Word_level_parts', [])]
        
        # Get the actions/verbs for this step (if annotated)
        actions = []
        if 'Verbs' in step:
            actions = [verb.get('name', '') for verb in step.get('Verbs', [])]
        
        # Images for this step (if any)
        images = step.get('Images', [])
        
        # Add the processed step
        processed_steps.append({
            'order': order,
            'text': text,
            'tools': tools,
            'parts': parts,
            'actions': actions,
            'images': images
        })
    
    # Sort steps by order to ensure they're in the correct sequence
    processed_steps.sort(key=lambda x: x['order'])
    
    return processed_steps

def convert_to_training_format(manuals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert repair manuals to a format suitable for SIM-RAG training"""
    processed_manuals = []
    
    for manual in manuals:
        title = manual.get('Title', 'Unknown repair')
        steps = manual.get('Steps', [])
        category = manual.get('Category', 'Unknown')
        
        # Create a problem statement from the title
        problem_statement = generate_problem_statement(title, category)
        
        # Process steps into a structured format
        processed_steps = process_steps(steps)
        
        # Create the full procedure text by joining all step texts
        full_procedure = ' '.join([s['text'] for s in processed_steps if s['text']])
        
        # Create the processed manual
        processed_manual = {
            'title': title,
            'problem': problem_statement,
            'category': category,
            'steps': processed_steps,
            'full_procedure': full_procedure
        }
        
        processed_manuals.append(processed_manual)
    
    return processed_manuals

def main():
    """Main entry point for the script"""
    # Parse command line arguments
    args = setup_argparse()
    
    # Set logging level based on verbose flag
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    logger.info(f"Processing iFixit data from {args.input_dir}")
    
    # Create output directory if it doesn't exist
    Path(os.path.dirname(args.output_file)).mkdir(parents=True, exist_ok=True)
    
    # Extract manuals
    manuals = extract_repair_manuals(
        args.input_dir, 
        args.appliance_only,
        args.max_manuals,
        args.min_steps,
        args.verbose
    )
    
    if not manuals:
        logger.error("No manuals extracted. Exiting.")
        return
    
    # Convert to training format
    logger.info("Converting manuals to training format...")
    processed_manuals = convert_to_training_format(manuals)
    
    # Save processed manuals
    logger.info(f"Saving {len(processed_manuals)} processed manuals to {args.output_file}")
    with open(args.output_file, 'w', encoding='utf-8') as f:
        json.dump(processed_manuals, f, indent=2)
    
    logger.info("Processing complete!")

if __name__ == "__main__":
    main()