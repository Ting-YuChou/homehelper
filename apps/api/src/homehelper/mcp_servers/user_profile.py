"""`user_profile` MCP server: a simplified agent data platform (spec §12.1-12.2, M5-02).

`user_id` is a parameter on every tool; the agent's MCP client binds it from the session and
must not let the LLM choose it (M5-07).
"""

from datetime import date
from typing import Annotated, Literal
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from homehelper.knowledge.schemas import CategoryId
from homehelper.mcp_servers.common import Clock, mcp_tool, new_server, utc_now
from homehelper.mcp_servers.mock_data import MockData
from homehelper.mcp_servers.schemas import (
    Appliance,
    RepairOutcome,
    RepairRecord,
    UserProfile,
    WarrantyState,
    WarrantyStatus,
)
from homehelper.mcp_servers.stores import ProfileStore

UserId = Annotated[str, Field(description="The signed-in user's id")]
ApplianceId = Annotated[str, Field(description="An appliance id from list_appliances")]

INSTRUCTIONS = (
    "The signed-in user's profile, registered appliances (brand, model number, warranty) and "
    "past repairs. Use it to prefill the appliance and to mention earlier fixes."
)


def warranty_status(appliance: Appliance, today: date) -> WarrantyStatus:
    until = appliance.warranty_until
    if until is None:
        return WarrantyStatus(appliance_id=appliance.appliance_id, status=WarrantyState.UNKNOWN)
    if until < today:
        return WarrantyStatus(
            appliance_id=appliance.appliance_id, status=WarrantyState.EXPIRED, warranty_until=until
        )
    return WarrantyStatus(
        appliance_id=appliance.appliance_id,
        status=WarrantyState.ACTIVE,
        warranty_until=until,
        days_remaining=(until - today).days,
    )


def build_user_profile_server(
    data: MockData, store: ProfileStore, *, clock: Clock = utc_now
) -> FastMCP:
    server = new_server("user_profile", INSTRUCTIONS)

    def profile(user_id: str) -> UserProfile:
        user = data.user(user_id)
        if user is None:
            raise ToolError(f"Unknown user {user_id!r}")
        return user

    async def owned_appliance(user_id: str, appliance_id: str) -> Appliance:
        profile(user_id)
        appliance = await store.get_appliance(appliance_id)
        # Someone else's appliance looks the same as a missing one.
        if appliance is None or appliance.user_id != user_id:
            raise ToolError(f"Appliance {appliance_id!r} not found for this user")
        return appliance

    @mcp_tool(server, title="Get user profile")
    async def get_profile(user_id: UserId) -> UserProfile:
        """The user's profile: DIY skill level, housing (homeowner or renter) and ZIP code."""
        return profile(user_id)

    @mcp_tool(server, title="List appliances")
    async def list_appliances(user_id: UserId) -> list[Appliance]:
        """All appliances the user has registered, with brand, model number and warranty date."""
        profile(user_id)
        return await store.list_appliances(user_id)

    @mcp_tool(server, title="Get appliance")
    async def get_appliance(user_id: UserId, appliance_id: ApplianceId) -> Appliance:
        """One registered appliance."""
        return await owned_appliance(user_id, appliance_id)

    @mcp_tool(server, title="Add appliance")
    async def add_appliance(
        user_id: UserId,
        category: CategoryId,
        brand: Annotated[str, Field(min_length=1, max_length=64)],
        model_number: Annotated[str, Field(min_length=1, max_length=64)],
        nickname: Annotated[str | None, Field(max_length=120)] = None,
        purchase_date: date | None = None,
        warranty_until: date | None = None,
    ) -> Appliance:
        """Register an appliance for the user (write tool: journey step actions only)."""
        profile(user_id)
        appliance = Appliance(
            appliance_id=f"apl_{uuid4().hex[:12]}",
            user_id=user_id,
            category=category,
            brand=brand.strip(),
            model_number=model_number.strip(),
            nickname=nickname,
            purchase_date=purchase_date,
            warranty_until=warranty_until,
        )
        await store.add_appliance(appliance)
        return appliance

    @mcp_tool(server, title="Get warranty status")
    async def get_warranty_status(user_id: UserId, appliance_id: ApplianceId) -> WarrantyStatus:
        """Whether the appliance is under warranty today (active, expired or unknown)."""
        appliance = await owned_appliance(user_id, appliance_id)
        return warranty_status(appliance, clock().date())

    @mcp_tool(server, title="List repair history")
    async def list_repair_history(
        user_id: UserId,
        appliance_id: Annotated[
            str | None, Field(description="Only this appliance; omit for all")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> list[RepairRecord]:
        """Past repairs, newest first: the issue, what fixed it and whether it worked."""
        if appliance_id is None:
            profile(user_id)
        else:
            await owned_appliance(user_id, appliance_id)
        return (await store.list_repairs(user_id, appliance_id))[:limit]

    @mcp_tool(server, title="Add repair record")
    async def add_repair_record(
        user_id: UserId,
        appliance_id: ApplianceId,
        issue: Annotated[str, Field(min_length=1, max_length=500)],
        resolution: Annotated[str, Field(min_length=1, max_length=1000)],
        outcome: RepairOutcome = "resolved",
        error_code: Annotated[str | None, Field(max_length=16)] = None,
        performed_by: Literal["self", "technician"] = "self",
        repair_date: Annotated[date | None, Field(description="Defaults to today")] = None,
    ) -> RepairRecord:
        """Record how an issue ended (write tool: journey step actions only)."""
        await owned_appliance(user_id, appliance_id)
        record = RepairRecord(
            record_id=f"rep_{uuid4().hex[:12]}",
            user_id=user_id,
            appliance_id=appliance_id,
            date=repair_date or clock().date(),
            issue=issue,
            error_code=error_code,
            resolution=resolution,
            outcome=outcome,
            performed_by=performed_by,
        )
        await store.add_repair(record)
        return record

    return server
