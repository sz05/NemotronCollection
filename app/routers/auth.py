"""Auth routes: Google login (ID-token verification), dev-login fallback,
logout, current-user info, and per-user Nemotron API key storage.

The session JWT is set as an httpOnly cookie so frontend JS never sees it;
the browser attaches it automatically (fetch uses credentials: 'include').
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import get_current_user
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
    AuthError,
    create_session_token,
    encrypt_api_key,
    verify_google_token,
)

router = APIRouter(prefix="/auth")


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        picture=user.picture,
        has_nemotron_key=bool(user.nemotron_key_encrypted),
    )


def _set_auth_cookie(response: Response, user: User) -> None:
    response.set_cookie(
        AUTH_COOKIE_NAME,
        create_session_token(user.id),
        max_age=settings.jwt_expiry_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        # secure=False is acceptable for localhost dev; set True behind HTTPS.
        secure=False,
    )


@router.get("/config", response_model=AuthConfigOut)
async def auth_config() -> AuthConfigOut:
    """Tells the frontend which login methods are available."""
    return AuthConfigOut(google_client_id=settings.google_client_id, dev_auth=settings.dev_auth)


@router.post("/google", response_model=UserOut)
async def google_login(
    body: GoogleLoginRequest, response: Response, db: AsyncSession = Depends(get_session)
) -> UserOut:
    try:
        claims = verify_google_token(body.credential)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = await get_or_create_google_user(
        db,
        google_sub=claims["sub"],
        email=claims.get("email", ""),
        name=claims.get("name", ""),
        picture=claims.get("picture", ""),
    )
    _set_auth_cookie(response, user)
    return _user_out(user)


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
    _set_auth_cookie(response, user)
    return _user_out(user)


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(AUTH_COOKIE_NAME)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)


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
