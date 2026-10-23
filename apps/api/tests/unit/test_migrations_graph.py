"""Tracks D and E both add migrations; whoever merges second re-points `down_revision` so the
graph keeps exactly one head (CLAUDE.md, parallel development)."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def test_migration_graph_has_exactly_one_head() -> None:
    heads = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_heads()
    assert len(heads) == 1, f"multiple Alembic heads {heads}; re-point a down_revision"


def test_the_packaged_migrations_are_the_ones_alembic_ini_runs() -> None:
    """`homehelper db upgrade` (the Cloud Run migrate job: the image has no alembic.ini)."""
    from homehelper.db.migrate import alembic_config

    packaged = ScriptDirectory.from_config(alembic_config())
    from_ini = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    assert Path(packaged.dir).resolve() == Path(from_ini.dir).resolve()
    assert packaged.get_heads() == from_ini.get_heads()


def test_db_upgrade_command_runs_alembic_to_head(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from homehelper import cli
    from homehelper.db import migrate

    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        migrate.command,
        "upgrade",
        lambda config, revision: calls.append((revision, config.attributes.get("database_url"))),
    )
    result = CliRunner().invoke(cli.app, ["db", "upgrade"])
    assert result.exit_code == 0, result.output
    assert calls == [("head", None)]  # the URL comes from the settings, as with alembic.ini
