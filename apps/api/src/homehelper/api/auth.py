"""Demo login (spec §18.1): pick a mock user (or continue as a guest) and get a signed cookie."""

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, TypeAdapter

from homehelper.api.deps import (
    SESSION_COOKIE,
    SessionDep,
    SessionSigner,
    SettingsDep,
    UserDep,
    client_ip,
)
from homehelper.api.schemas import DemoLoginRequest, DemoUserOut, UserOut
from homehelper.conversations import repository
from homehelper.ratelimit import TurnGuards

router = APIRouter(prefix="/auth", tags=["auth"])

GUEST_NAME = "Guest"


class MockUser(BaseModel):
    """An entry of `data/mock/users.json`, owned by the mock data platform (M5, spec §12.2).
    Only these fields are relied on; the MCP servers key on the same `user_id`."""

    user_id: str
    display_name: str
    notes: str | None = None


_MOCK_USERS = TypeAdapter(list[MockUser])


@lru_cache(maxsize=4)
def _load_demo_users(path: Path, mtime: float) -> tuple[DemoUserOut, ...]:
    users = _MOCK_USERS.validate_json(path.read_bytes())
    return tuple(
        DemoUserOut(id=u.user_id, display_name=u.display_name, description=u.notes) for u in users
    )


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
    signer: SessionSigner = request.app.state.session_signer
    guards: TurnGuards = request.app.state.turn_guards
    ip = client_ip(request, request.app.state.settings)
    decision = await guards.login_limiter.hit(f"rl:login:{ip}")
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many sign-ins. Please try again later.",
            headers={"Retry-After": str(decision.retry_after_s)},
        )
    if not signer.access_code_matches(body.access_code):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Wrong access code")
    if body.user_id is None:
        # A guest who still has a valid cookie keeps their guest user (and its rate limits).
        token = request.cookies.get(SESSION_COOKIE)
        current_id = signer.loads(token) if token else None
        current = await repository.get_user(session, current_id) if current_id else None
        if current is not None and not current.is_demo:
            user = current
        else:
            user = await repository.upsert_user(
                session, repository.new_id("guest"), GUEST_NAME, is_demo=False
            )
    else:
        demo = next((u for u in demo_users(settings.data_dir) if u.id == body.user_id), None)
        if demo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown demo user")
        user = await repository.upsert_user(session, demo.id, demo.display_name, is_demo=True)
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
