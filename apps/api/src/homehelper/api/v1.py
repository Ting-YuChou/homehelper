"""The `/v1` REST API (spec §13.2). Every cookie-authenticated write is Origin-checked."""

from fastapi import APIRouter, Depends

from homehelper.api import admin, auth, conversations, feedback, manuals, me, uploads
from homehelper.api.deps import check_origin

router = APIRouter(prefix="/v1", dependencies=[Depends(check_origin)])
for module in (auth, conversations, feedback, me, manuals, uploads, admin):
    router.include_router(module.router)
