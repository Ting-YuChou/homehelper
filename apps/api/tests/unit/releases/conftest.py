import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
RELEASE_ID = "r2026.11.01-1"


def fixture_report(suite: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{suite}.json").read_text())


@pytest.fixture
def safety_report() -> dict[str, Any]:
    return fixture_report("safety")


@pytest.fixture
def full_report() -> dict[str, Any]:
    return fixture_report("full")
