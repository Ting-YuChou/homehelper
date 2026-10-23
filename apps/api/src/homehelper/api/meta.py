from fastapi import APIRouter, Request
from pydantic import BaseModel

from homehelper import __version__

router = APIRouter(prefix="/v1", tags=["meta"])


class MetaResponse(BaseModel):
    version: str
    release_id: str
    git_sha: str  # empty when running from source
    environment: str
    access_code_required: bool  # signing in needs the demo access code


@router.get("/meta", response_model=MetaResponse)
async def meta(request: Request) -> MetaResponse:
    settings = request.app.state.settings
    return MetaResponse(
        version=__version__,
        release_id=settings.release_id,
        git_sha=settings.git_sha,
        environment=settings.app_env,
        access_code_required=request.app.state.session_signer.access_code_required,
    )
