from fastapi import APIRouter, Request
from pydantic import BaseModel

from homehelper import __version__

router = APIRouter(prefix="/v1", tags=["meta"])


class MetaResponse(BaseModel):
    version: str
    release_id: str
    environment: str


@router.get("/meta", response_model=MetaResponse)
async def meta(request: Request) -> MetaResponse:
    settings = request.app.state.settings
    return MetaResponse(
        version=__version__, release_id=settings.release_id, environment=settings.app_env
    )
