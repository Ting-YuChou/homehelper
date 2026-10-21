"""The signed-in user's data. Appliances come from the `user_profile` MCP server (M5); until it
lands this returns an empty list so the web app can be built against the final shape."""

from fastapi import APIRouter

from homehelper.api.deps import UserDep
from homehelper.api.schemas import ApplianceOut

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/appliances", response_model=list[ApplianceOut])
async def my_appliances(user: UserDep) -> list[ApplianceOut]:
    return []
