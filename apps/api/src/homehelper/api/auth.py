"""Demo login (spec §18.1): pick a mock user (or continue as a guest) and get a signed cookie."""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import TypeAdapter

from homehelper.api.deps import SESSION_COOKIE, SessionDep, SessionSigner, SettingsDep, UserDep
from homehelper.api.schemas import DemoLoginRequest, DemoUserOut, UserOut
from homehelper.conversations import repository

router = APIRouter(prefix="/auth", tags=["auth"])

GUEST_NAME = "Guest"
_DEMO_USERS = TypeAdapter(list[DemoUserOut])


@lru_cache(maxsize=4)
def _load_demo_users(path: Path, mtime: float) -> tuple[DemoUserOut, ...]:
    raw = json.loads(path.read_text())
    # users.json is owned by the mock data platform (M5); only id/display_name are relied on.
    for user in raw:
        user.setdefault("description", user.get("persona"))
    return tuple(_DEMO_USERS.validate_python(raw))


def demo_users(data_dir: Path) -> tuple[DemoUserOut, ...]:
    path = data_dir / "mock" / "users.json"
    if not path.exists():
        return ()
    return _load_demo_users(path, path.stat().st_mtime)


@router.get("/demo-users", response_model=list[DemoUserOut])
async def list_demo_users(settings: SettingsDep) -> list[DemoUserOut]:
    return list(demo_users(settings.data_dir))


@router.post("/demo-login", response_model=UserOut)
async def demo_login(
    body: DemoLoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> UserOut:
    if body.user_id is None:
        user = await repository.upsert_user(
            session, repository.new_id("guest"), GUEST_NAME, is_demo=False
        )
    else:
        demo = next((u for u in demo_users(settings.data_dir) if u.id == body.user_id), None)
        if demo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown demo user")
        user = await repository.upsert_user(session, demo.id, demo.display_name, is_demo=True)
    signer: SessionSigner = request.app.state.session_signer
    response.set_cookie(
        SESSION_COOKIE,
        signer.dumps(user.id),
        max_age=signer.max_age_s,
        httponly=True,
        secure=signer.secure,
        samesite="lax",
    )
    return UserOut.model_validate(user)


@router.get("/me", response_model=UserOut)
async def me(user: UserDep) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> Response:
    signer: SessionSigner = request.app.state.session_signer
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=signer.secure, samesite="lax")
    return response
