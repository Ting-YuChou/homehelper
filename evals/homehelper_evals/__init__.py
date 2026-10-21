from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_PATH = REPO_ROOT / "data" / "scenarios" / "home_helper_dataset.jsonl"
SPLITS_PATH = REPO_ROOT / "data" / "scenarios" / "splits.json"
REPORTS_DIR = REPO_ROOT / "evals" / "reports"
