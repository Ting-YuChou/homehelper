# run_self_practice.py
from systems.agents.tools.self_practice import generate_training_data, load_ifixit_data, convert_ifixit_to_qa_pairs
import os
import json
import time
import argparse
from pathlib import Path

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Generate critic training data with parallel processing')
    parser.add_argument('--max-workers', type=int, default=4, help='Number of parallel workers (default: 4)')
    parser.add_argument('--max-turns', type=int, default=3, help='Maximum reasoning turns per QA pair (default: 3)')
    parser.add_argument('--sample-size', type=int, default=0, help='Sample size for testing (0 means use all data)')
    args = parser.parse_args()

    start_time = time.time()
    print(f"Starting self-practice with {args.max_workers} workers and max {args.max_turns} turns")
    
    # Ensure directories exist
    Path("data/training").mkdir(parents=True, exist_ok=True)
    
    # Step 1: Collect QA pairs from all available sources
    all_qa_pairs = []
    
    # Load original QA pairs (your existing 3 pairs)
    original_qa_file = "data/training/qa_pairs.json"
    if os.path.exists(original_qa_file):
        with open(original_qa_file, 'r') as f:
            original_pairs = json.load(f)
            print(f"Loaded {len(original_pairs)} original QA pairs")
            all_qa_pairs.extend(original_pairs)
    
    # Load synthetic QA pairs (if generate_qa_pairs.py was run)
    synthetic_qa_file = "data/training/synthetic_qa_pairs.json"
    if os.path.exists(synthetic_qa_file):
        with open(synthetic_qa_file, 'r') as f:
            synthetic_pairs = json.load(f)
            print(f"Loaded {len(synthetic_pairs)} synthetic QA pairs")
            all_qa_pairs.extend(synthetic_pairs)
    
    # Load and convert iFixit data (if process_ifixit.py was run)
    ifixit_data_path = "data/ifixit/processed_ifixit_manuals.json"
    if os.path.exists(ifixit_data_path):
        ifixit_data = load_ifixit_data(ifixit_data_path)
        if ifixit_data:
            ifixit_qa_pairs = convert_ifixit_to_qa_pairs(ifixit_data)
            print(f"Converted {len(ifixit_qa_pairs)} iFixit manuals to QA pairs")
            all_qa_pairs.extend(ifixit_qa_pairs)
    
    print(f"Total QA pairs collected: {len(all_qa_pairs)}")
    
    # Take a sample if requested (for testing)
    if args.sample_size > 0 and args.sample_size < len(all_qa_pairs):
        import random
        random.seed(42)  # for reproducibility
        all_qa_pairs = random.sample(all_qa_pairs, args.sample_size)
        print(f"Sampled {args.sample_size} QA pairs for testing")
    
    # Save combined QA pairs
    combined_qa_file = "data/training/combined_qa_pairs.json"
    with open(combined_qa_file, 'w') as f:
        json.dump(all_qa_pairs, f, indent=2)
    
    print(f"Created combined QA dataset with {len(all_qa_pairs)} pairs")
    
    # Step 2: Generate critic training data
    print("\nGenerating critic training data...")
    generate_training_data(
        qa_pairs_file=combined_qa_file,  # Use the combined file
        output_dir="data/training",
        max_turns=args.max_turns,
        ifixit_data_path=ifixit_data_path,  # Also pass the original iFixit data
        max_workers=args.max_workers
    )
    
    end_time = time.time()
    total_time = end_time - start_time
    hours, remainder = divmod(total_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    print(f"\nProcess complete! Your critic training data is ready.")
    print(f"Total execution time: {int(hours)}h {int(minutes)}m {int(seconds)}s")

if __name__ == "__main__":
    main()