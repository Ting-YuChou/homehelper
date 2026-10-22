"""Request dependencies: DB session, the signed session cookie, admin token, Origin check."""

import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from homehelper.conversations import repository
from homehelper.core.config import Settings
from homehelper.db.models import User
from homehelper.mcp_servers.factory import McpServers

SESSION_COOKIE = "hh_session"
_DEV_SECRET = "homehelper-local-session-secret"  # local and test only
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def session_secret(settings: Settings) -> str:
    """The secret behind session cookies and media tokens (each signer uses its own salt)."""
    secret = settings.session_secret.get_secret_value()
    if not secret:
        if settings.app_env not in ("local", "test"):
            raise RuntimeError("SESSION_SECRET must be set outside local and test")
        secret = _DEV_SECRET
    return secret


class SessionSigner:
    """Signs the user id into the `hh_session` cookie (spec §18.1: signed httpOnly cookie)."""

    def __init__(self, settings: Settings) -> None:
        self._serializer = URLSafeTimedSerializer(session_secret(settings), salt="hh-session")
        self.max_age_s = settings.session_max_age_s
        self.secure = settings.app_env not in ("local", "test")

    def dumps(self, user_id: str) -> str:
        return self._serializer.dumps(user_id)

    def loads(self, token: str) -> str | None:
        try:
            value = self._serializer.loads(token, max_age=self.max_age_s)
        except BadSignature:  # also covers SignatureExpired
            return None
        return value if isinstance(value, str) else None


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One transaction per request, committed when the handler returns without raising.

    Used with `scope="function"`, so the commit happens before the response is sent: a client may
    use what it just created in its very next request.
    """
    async with request.app.state.db_sessionmaker.begin() as session:
        yield session


def get_mcp(request: Request) -> McpServers:
    return request.app.state.mcp


SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]
McpDep = Annotated[McpServers, Depends(get_mcp)]


async def current_user(request: Request, session: SessionDep) -> User:
    signer: SessionSigner = request.app.state.session_signer
    token = request.cookies.get(SESSION_COOKIE)
    user_id = signer.loads(token) if token else None
    user = await repository.get_user(session, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in with a demo user first")
    return user


UserDep = Annotated[User, Depends(current_user)]


def check_origin(request: Request, settings: SettingsDep) -> None:
    """CSRF defence for cookie-authenticated writes: a browser Origin must be one we serve."""
    origin = request.headers.get("origin")
    if request.method in UNSAFE_METHODS and origin and origin not in settings.cors_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")


def require_admin(
    settings: SettingsDep, x_admin_token: Annotated[str | None, Header()] = None
) -> None:
    expected = settings.admin_token.get_secret_value()
    if not expected or not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin token required")
