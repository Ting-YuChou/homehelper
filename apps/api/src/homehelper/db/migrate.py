"""`homehelper db upgrade`: Alembic migrations from the installed package.

The runtime image has no `alembic.ini` or source tree, so the Cloud Run `migrate` job runs this
instead (ADR-011). The database URL comes from the settings, as with `alembic.ini`.
"""

from pathlib import Path
from typing import Annotated

import typer
from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).resolve().parent / "migrations"

app = typer.Typer(no_args_is_help=True, help="Database schema (Alembic).")


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    if database_url is not None:
        config.attributes["database_url"] = database_url
    return config


@app.command("upgrade")
def upgrade(
    revision: Annotated[str, typer.Argument(help="Target revision.")] = "head",
) -> None:
    """Apply migrations up to `revision` (default: head)."""
    command.upgrade(alembic_config(), revision)
