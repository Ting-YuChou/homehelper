"""The admin API (spec §13.2, §17.2): sign-in, conversation review and annotations, regression
export and eval reports. Everything except signing in needs `require_admin`."""

from fastapi import APIRouter

from homehelper.api.admin import evals, export, review, session

router = APIRouter(prefix="/admin", tags=["admin"])
for module in (session, review, export, evals):
    router.include_router(module.router)
