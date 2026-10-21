"""`homehelper mcp ...`: run one server standalone for debugging, or reset the mock tables."""

import asyncio
from typing import Annotated, Literal

import typer
from mcp.server.transport_security import TransportSecuritySettings

from homehelper.core.config import get_settings
from homehelper.core.logging import configure_logging
from homehelper.db.engine import create_engine
from homehelper.mcp_servers.factory import build_mcp_servers
from homehelper.mcp_servers.mock_data import load_mock_data
from homehelper.mcp_servers.registry import SERVER_NAMES
from homehelper.mcp_servers.stores import seed_mock_tables

app = typer.Typer(no_args_is_help=True, help="MCP servers (M5).")


@app.command("serve")
def serve(
    server: Annotated[str, typer.Argument(help=f"One of: {', '.join(SERVER_NAMES)}")],
    mode: Annotated[str | None, typer.Option(help="real | mock (default: MCP_MODE)")] = None,
    port: Annotated[int, typer.Option(help="Port on 127.0.0.1.")] = 8001,
    transport: Annotated[str, typer.Option(help="streamable-http | stdio")] = "streamable-http",
) -> None:
    """Run one server on its own, e.g. for the MCP Inspector (http://127.0.0.1:<port>/)."""
    if server not in SERVER_NAMES:
        raise typer.BadParameter(f"unknown server {server!r}")
    if transport not in ("streamable-http", "stdio"):
        raise typer.BadParameter(f"unknown transport {transport!r}")
    if mode not in (None, "real", "mock"):
        raise typer.BadParameter(f"unknown mode {mode!r}")
    settings = get_settings()
    if mode:
        settings = settings.model_copy(update={"mcp_mode": mode})
    configure_logging(settings.log_level)
    mcp = build_mcp_servers(settings, engine=create_engine(settings.database_url))[server]
    mcp.settings.port = port
    # Standalone on localhost: restore the DNS-rebinding protection the mounted servers skip.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    )
    selected: Literal["streamable-http", "stdio"] = (
        "stdio" if transport == "stdio" else "streamable-http"
    )
    mcp.run(selected)


@app.command("seed")
def seed() -> None:
    """Reset the Postgres mock tables to `data/mock/` (needs `make migrate`)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    data = load_mock_data(settings.mock_dir)

    async def run() -> None:
        engine = create_engine(settings.database_url)
        try:
            await seed_mock_tables(engine, data)
        finally:
            await engine.dispose()

    asyncio.run(run())
    typer.echo(f"seeded {len(data.appliances)} appliances, {len(data.repair_history)} repairs")
