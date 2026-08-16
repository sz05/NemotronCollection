"""Shared FastAPI dependencies (auth)."""

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.services.auth import AUTH_COOKIE_NAME, AuthError, decode_session_token


async def get_current_user(
    access_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_session),
) -> User:
    if not access_token:
        raise HTTPException(status_code=401, detail="Not logged in")
    try:
        user_id = decode_session_token(access_token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user
