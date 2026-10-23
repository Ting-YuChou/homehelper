"""Request dependencies: DB session, the signed session cookie, admin token, Origin check,
and the caller's IP."""

import hashlib
import hmac
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
ADMIN_COOKIE = "hh_admin"
_DEV_SECRET = "homehelper-local-session-secret"  # local and test only
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CLIENT_IP_HEADER = "x-hh-client-ip"
PROXY_SECRET_HEADER = "x-hh-proxy-secret"


def session_secret(settings: Settings) -> str:
    """The secret behind session cookies and media tokens (each signer uses its own salt)."""
    secret = settings.session_secret.get_secret_value()
    if not secret:
        if settings.app_env not in ("local", "test"):
            raise RuntimeError("SESSION_SECRET must be set outside local and test")
        secret = _DEV_SECRET
    return secret


def client_ip(request: Request, settings: Settings) -> str:
    """The caller's IP for rate limits (ADR-011).

    The web app's `/v1` proxy forwards the visitor's IP in `X-HH-Client-IP`, believed only
    with the shared proxy secret. Otherwise, on Cloud Run, the last `X-Forwarded-For` entry is
    the address Cloud Run itself appended (earlier entries are whatever the caller sent).
    Locally there is no front end, so the socket peer is used.
    """
    peer = request.client.host if request.client else "unknown"
    if settings.app_env in ("local", "test"):
        return peer
    secret = settings.proxy_secret.get_secret_value()
    vouched = request.headers.get(CLIENT_IP_HEADER)
    sent = request.headers.get(PROXY_SECRET_HEADER, "")
    if secret and vouched and hmac.compare_digest(sent.encode(), secret.encode()):
        return vouched.strip()
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.rsplit(",", 1)[-1].strip() or peer


class SessionSigner:
    """Signs the user id into the `hh_session` cookie (spec §18.1: signed httpOnly cookie).

    With a demo access code, the signing salt carries a keyed fingerprint of the code, so
    changing the code ends every session (ADR-011).
    """

    def __init__(self, settings: Settings) -> None:
        secret = session_secret(settings)
        self._code = settings.demo_access_code.get_secret_value().strip()
        salt = "hh-session"
        if self._code:
            digest = hmac.new(secret.encode(), self._code.encode(), hashlib.sha256).hexdigest()
            salt += ":" + digest[:32]
        self._serializer = URLSafeTimedSerializer(secret, salt=salt)
        self.max_age_s = settings.session_max_age_s
        self.secure = settings.app_env not in ("local", "test")

    @property
    def access_code_required(self) -> bool:
        return bool(self._code)

    def access_code_matches(self, code: str | None) -> bool:
        if not self._code:
            return True
        return bool(code) and secrets.compare_digest(code.strip().encode(), self._code.encode())

    def dumps(self, user_id: str) -> str:
        return self._serializer.dumps(user_id)

    def loads(self, token: str) -> str | None:
        try:
            value = self._serializer.loads(token, max_age=self.max_age_s)
        except BadSignature:  # also covers SignatureExpired
            return None
        return value if isinstance(value, str) else None


class AdminSigner:
    """Signs the `hh_admin` cookie the admin token is exchanged for (M7-01).

    The cookie carries a fingerprint of the token, so rotating `ADMIN_TOKEN` ends every admin
    session; with no token configured nothing validates.
    """

    def __init__(self, settings: Settings) -> None:
        secret = session_secret(settings)
        self._serializer = URLSafeTimedSerializer(secret, salt="hh-admin")
        self._secret = secret.encode()
        self._token = settings.admin_token.get_secret_value()
        self.max_age_s = settings.admin_session_max_age_s
        self.secure = settings.app_env not in ("local", "test")

    def _fingerprint(self) -> str:
        # Keyed, so a cookie (signed, not encrypted) gives nothing to guess the token against.
        return hmac.new(self._secret, self._token.encode(), hashlib.sha256).hexdigest()[:32]

    def token_matches(self, token: str) -> bool:
        if not (self._token and token):
            return False
        return secrets.compare_digest(token.encode(), self._token.encode())

    def dumps(self) -> str:
        if not self._token:
            raise ValueError("ADMIN_TOKEN is not set")
        return self._serializer.dumps(self._fingerprint())

    def valid(self, cookie: str) -> bool:
        if not self._token:
            return False
        try:
            value = self._serializer.loads(cookie, max_age=self.max_age_s)
        except BadSignature:  # also covers SignatureExpired
            return False
        return isinstance(value, str) and secrets.compare_digest(value, self._fingerprint())


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


async def require_admin(
    request: Request, x_admin_token: Annotated[str | None, Header()] = None
) -> None:
    """The `X-Admin-Token` header (CLI, curl) or the `hh_admin` cookie (the web app). A wrong
    header counts against the same per-IP limit as a wrong sign-in."""
    signer: AdminSigner = request.app.state.admin_signer
    if x_admin_token and signer.token_matches(x_admin_token):
        return
    cookie = request.cookies.get(ADMIN_COOKIE)
    if cookie and signer.valid(cookie):
        return
    if x_admin_token:
        await admin_attempt_allowed(request)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin token required")


async def admin_attempt_allowed(request: Request) -> None:
    """Count an admin token attempt from this address; 429 once over the limit."""
    guards = request.app.state.turn_guards
    ip = client_ip(request, request.app.state.settings)
    decision = await guards.admin_login_limiter.hit(f"rl:admin-login:{ip}")
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many admin sign-in attempts. Please try again later.",
            headers={"Retry-After": str(decision.retry_after_s)},
        )
