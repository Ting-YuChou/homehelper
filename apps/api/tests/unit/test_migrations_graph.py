"""Tracks D and E both add migrations; whoever merges second re-points `down_revision` so the
graph keeps exactly one head (CLAUDE.md, parallel development)."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def test_migration_graph_has_exactly_one_head() -> None:
    heads = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_heads()
    assert len(heads) == 1, f"multiple Alembic heads {heads}; re-point a down_revision"
