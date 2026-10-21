from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_PATH = REPO_ROOT / "data" / "scenarios" / "home_helper_dataset.jsonl"
SPLITS_PATH = REPO_ROOT / "data" / "scenarios" / "splits.json"
ROOT_CAUSES_PATH = REPO_ROOT / "data" / "scenarios" / "root_cause_steps.v1.json"
MANIFEST_PATH = REPO_ROOT / "data" / "manuals" / "manifest.yaml"
DATASETS_DIR = REPO_ROOT / "evals" / "datasets"
REPORTS_DIR = REPO_ROOT / "evals" / "reports"
