"""The signed-in user's data (spec §13.2, §15.2): appliances, warranty and repair history, read
through the `user_profile` MCP server so the page and the agent see the same data platform."""

from fastapi import APIRouter, HTTPException, status

from homehelper.api.deps import McpDep, UserDep
from homehelper.api.schemas import ApplianceOut, RepairOut, WarrantyOut
from homehelper.core.logging import get_logger
from homehelper.mcp_servers.client import McpToolError
from homehelper.mcp_servers.factory import McpServers
from homehelper.mcp_servers.schemas import Appliance, RepairRecord, WarrantyStatus

router = APIRouter(prefix="/me", tags=["me"])
log = get_logger(__name__)

RECENT_REPAIRS = 3
UNKNOWN_USER = "Unknown user"  # the `user_profile` tools' error for a user it has no profile for


@router.get("/appliances", response_model=list[ApplianceOut])
async def my_appliances(user: UserDep, mcp: McpDep) -> list[ApplianceOut]:
    """Guests have no profile, so they get an empty list, as does a demo user the data platform
    does not know (e.g. one removed from `data/mock/` after they signed in). Any other tool
    failure (e.g. the database is down) is a 503, not an empty list."""
    if not user.is_demo:
        return []
    try:
        return await _appliances(mcp, user.id)
    except McpToolError as e:
        if UNKNOWN_USER in e.message:
            log.info("my_appliances.no_profile", user_id=user.id)
            return []
        log.warning("my_appliances.unavailable", user_id=user.id, error=e.message)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Appliance data is unavailable"
        ) from e


async def _appliances(mcp: McpServers, user_id: str) -> list[ApplianceOut]:
    async with mcp.client("user_profile") as profile:
        appliances = await profile.call_as(list[Appliance], "list_appliances", {"user_id": user_id})
        out: list[ApplianceOut] = []
        for appliance in appliances:
            ids = {"user_id": user_id, "appliance_id": appliance.appliance_id}
            warranty = await profile.call_as(WarrantyStatus, "get_warranty_status", ids)
            repairs = await profile.call_as(
                list[RepairRecord], "list_repair_history", {**ids, "limit": RECENT_REPAIRS}
            )
            out.append(
                ApplianceOut(
                    appliance_id=appliance.appliance_id,
                    category=appliance.category,
                    brand=appliance.brand,
                    model_number=appliance.model_number,
                    nickname=appliance.nickname,
                    purchase_date=appliance.purchase_date,
                    warranty=WarrantyOut.model_validate(
                        warranty.model_dump(exclude={"appliance_id"})
                    ),
                    recent_repairs=[
                        RepairOut.model_validate(r.model_dump(exclude={"user_id", "appliance_id"}))
                        for r in repairs
                    ],
                )
            )
    return out
