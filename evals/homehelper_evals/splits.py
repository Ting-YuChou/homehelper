"""Deterministic dev/test split of the scenario dataset (spec §16.1).

Rows are grouped by normalized scenario text, so the three tone variants of a scenario (and any
duplicated scenario text) always land in the same split. Assignment depends only on the text hash,
so it never changes when rows are added or reordered.

Usage: uv run python -m homehelper_evals.splits [--check]
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from homehelper_evals import SCENARIOS_PATH, SPLITS_PATH

Split = Literal["dev", "test"]
DEV_PERCENT = 20


def group_key(scenario: str) -> str:
    return re.sub(r"\s+", " ", scenario.strip().lower())


def assign_split(scenario: str) -> Split:
    digest = hashlib.sha256(group_key(scenario).encode()).hexdigest()
    return "dev" if int(digest[:8], 16) % 100 < DEV_PERCENT else "test"


def load_rows(path: Path = SCENARIOS_PATH) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def build_splits(rows: list[dict]) -> dict:
    assignments = {str(row["id"]): assign_split(row["scenario"]) for row in rows}
    groups = {group_key(row["scenario"]): assignments[str(row["id"])] for row in rows}
    return {
        "version": 1,
        "method": f"sha256(normalized scenario text) % 100 < {DEV_PERCENT} -> dev",
        "counts": {
            "rows": dict(Counter(assignments.values())),
            "scenario_groups": dict(Counter(groups.values())),
        },
        "assignments": assignments,
    }


def load_splits(path: Path = SPLITS_PATH) -> dict[str, Split]:
    return json.loads(path.read_text())["assignments"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if splits.json is stale")
    args = parser.parse_args()
    splits = build_splits(load_rows())
    rendered = json.dumps(splits, indent=1, sort_keys=True) + "\n"
    if args.check:
        if SPLITS_PATH.read_text() != rendered:
            raise SystemExit("splits.json is stale; rerun without --check")
        print("splits.json is up to date")
        return
    SPLITS_PATH.write_text(rendered)
    print(json.dumps(splits["counts"]))


if __name__ == "__main__":
    main()
