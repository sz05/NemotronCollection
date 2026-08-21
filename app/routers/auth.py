"""Auth routes: Google login (ID-token verification), dev-login fallback,
logout, current-user info, and per-user Nemotron API key storage.

The session JWT is set as an httpOnly cookie so frontend JS never sees it;
the browser attaches it automatically (fetch uses credentials: 'include').
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import get_current_user, user_is_admin
from app.models import User
from app.repository import (
    get_or_create_dev_user,
    get_or_create_google_user,
    set_user_nemotron_key,
)
from app.schemas import (
    AuthConfigOut,
    DevLoginRequest,
    GoogleLoginRequest,
    NemotronKeyRequest,
    UserOut,
)
from app.services.auth import (
    AUTH_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    AuthError,
    create_session_token,
    encrypt_api_key,
    generate_csrf_token,
    verify_google_token,
)

router = APIRouter(prefix="/auth")


def _user_out(user: User, csrf_token: str = "") -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        picture=user.picture,
        has_nemotron_key=bool(user.nemotron_key_encrypted),
        is_admin=user_is_admin(user),
        csrf_token=csrf_token,
    )


def _cookie_secure() -> bool:
    # Browsers reject SameSite=None cookies without Secure; plain secure=False
    # stays for localhost dev where samesite is "lax".
    return settings.cookie_samesite.lower() == "none"


def _set_csrf_cookie(response: Response) -> str:
    """Set a fresh CSRF cookie and return the token to echo in the body. The
    cookie is httpOnly (the browser sends it back automatically; the client
    learns the value from the response body, not by reading the cookie), so an
    XSS can't lift it either."""
    token = generate_csrf_token()
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=settings.jwt_expiry_days * 24 * 3600,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=_cookie_secure(),
    )
    return token


def _set_auth_cookie(response: Response, user: User) -> str:
    response.set_cookie(
        AUTH_COOKIE_NAME,
        create_session_token(user.id),
        max_age=settings.jwt_expiry_days * 24 * 3600,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=_cookie_secure(),
    )
    return _set_csrf_cookie(response)


@router.get("/config", response_model=AuthConfigOut)
async def auth_config() -> AuthConfigOut:
    """Tells the frontend which login methods are available."""
    return AuthConfigOut(google_client_id=settings.google_client_id, dev_auth=settings.dev_auth)


@router.post("/google", response_model=UserOut)
async def google_login(
    body: GoogleLoginRequest, response: Response, db: AsyncSession = Depends(get_session)
) -> UserOut:
    try:
        # verify_google_token does a BLOCKING network fetch (Google's signing
        # certs). Run it off the event loop so a slow/hanging verification
        # can't freeze every other request (health checks included).
        claims = await asyncio.to_thread(verify_google_token, body.credential)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = await get_or_create_google_user(
        db,
        google_sub=claims["sub"],
        email=claims.get("email", ""),
        name=claims.get("name", ""),
        picture=claims.get("picture", ""),
    )
    csrf = _set_auth_cookie(response, user)
    return _user_out(user, csrf)


@router.post("/dev-login", response_model=UserOut)
async def dev_login(
    body: DevLoginRequest, response: Response, db: AsyncSession = Depends(get_session)
) -> UserOut:
    if not settings.dev_auth:
        raise HTTPException(status_code=403, detail="Dev login is disabled")
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email")
    user = await get_or_create_dev_user(db, email)
    csrf = _set_auth_cookie(response, user)
    return _user_out(user, csrf)


@router.post("/logout")
async def logout(response: Response) -> dict:
    # Attributes must match the ones the cookie was set with, or some
    # browsers ignore the deletion.
    for name in (AUTH_COOKIE_NAME, CSRF_COOKIE_NAME):
        response.delete_cookie(
            name,
            samesite=settings.cookie_samesite,
            secure=_cookie_secure(),
        )
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
) -> UserOut:
    # Reuse the existing CSRF cookie, or mint one now (covers sessions created
    # before CSRF was added). The frontend reads the token from this response.
    csrf = request.cookies.get(CSRF_COOKIE_NAME) or _set_csrf_cookie(response)
    return _user_out(user, csrf)


@router.put("/nemotron-key", response_model=UserOut)
async def save_nemotron_key(
    body: NemotronKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> UserOut:
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=422, detail="API key is empty")
    user = await set_user_nemotron_key(db, user, encrypt_api_key(api_key))
    return _user_out(user)


@router.delete("/nemotron-key", response_model=UserOut)
async def clear_nemotron_key(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> UserOut:
    user = await set_user_nemotron_key(db, user, None)
    return _user_out(user)
