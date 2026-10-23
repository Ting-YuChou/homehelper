"""Admin sign-in (M7-01): the admin token is exchanged for the signed httpOnly `hh_admin` cookie,
so the web app never keeps the token. Scripts can keep sending `X-Admin-Token` instead."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from homehelper.api.deps import ADMIN_COOKIE, AdminSigner, require_admin
from homehelper.api.schemas import AdminLogin
from homehelper.core.logging import get_logger
from homehelper.ratelimit import TurnGuards

router = APIRouter(prefix="/session")
log = get_logger(__name__)


@router.post("", status_code=status.HTTP_204_NO_CONTENT, responses={401: {}, 429: {}})
async def sign_in(body: AdminLogin, request: Request) -> Response:
    signer: AdminSigner = request.app.state.admin_signer
    guards: TurnGuards = request.app.state.turn_guards
    client_ip = request.client.host if request.client else "unknown"
    decision = await guards.admin_login_limiter.hit(f"rl:admin-login:{client_ip}")
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many sign-in attempts. Please try again later.",
            headers={"Retry-After": str(decision.retry_after_s)},
        )
    if not signer.token_matches(body.token):
        log.warning("admin_sign_in_refused", client_ip=client_ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong admin token")
    log.info("admin_signed_in", client_ip=client_ip)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        ADMIN_COOKIE,
        signer.dumps(),
        max_age=signer.max_age_s,
        httponly=True,
        secure=signer.secure,
        samesite="lax",
    )
    return response


@router.get("", status_code=status.HTTP_204_NO_CONTENT, responses={401: {}})
async def check(_: Annotated[None, Depends(require_admin)]) -> Response:
    """204 while signed in (or with the header), else 401."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(request: Request) -> Response:
    signer: AdminSigner = request.app.state.admin_signer
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(ADMIN_COOKIE, httponly=True, secure=signer.secure, samesite="lax")
    return response
