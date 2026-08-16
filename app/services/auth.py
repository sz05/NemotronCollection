"""Auth primitives: session JWTs, Google ID-token verification, and Fernet
encryption for the user's stored Nemotron API key.

The JWT travels in an httpOnly cookie (set by the /auth routes) so it is
never readable by frontend JS. The Fernet key is derived from jwt_secret so
one .env secret covers both concerns at this project's scale.
"""

import base64
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet, InvalidToken
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.config import settings

AUTH_COOKIE_NAME = "access_token"

_JWT_ALGORITHM = "HS256"


class AuthError(Exception):
    """Raised when a credential (JWT or Google token) fails verification."""


def create_session_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_expiry_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_session_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise AuthError("Invalid or expired session token") from exc


def verify_google_token(credential: str) -> dict:
    """Verify a Google ID token and return its claims (sub, email, name...)."""
    if not settings.google_client_id:
        raise AuthError("Google login is not configured (GOOGLE_CLIENT_ID missing)")
    try:
        return google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), settings.google_client_id
        )
    except ValueError as exc:
        raise AuthError("Google token verification failed") from exc


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode()).decode()


def decrypt_api_key(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        # jwt_secret changed since the key was stored; user must re-enter it.
        raise AuthError("Stored API key can no longer be decrypted") from exc
