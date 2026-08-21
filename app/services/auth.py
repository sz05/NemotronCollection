"""Auth primitives: session JWTs, Google ID-token verification, and Fernet
encryption for the user's stored Nemotron API key.

The JWT travels in an httpOnly cookie (set by the /auth routes) so it is
never readable by frontend JS. The Fernet key that encrypts stored API keys is
derived from a SEPARATE secret (api_key_enc_secret) so a leaked signing secret
can't also decrypt stored keys; it falls back to jwt_secret only for local dev.
"""

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet, InvalidToken
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.config import settings

AUTH_COOKIE_NAME = "access_token"
# Double-submit CSRF token cookie. Sent automatically by the browser; the
# frontend echoes the same value (obtained from the login / /auth/me response
# body) in an X-CSRF-Token header, and the server checks they match.
CSRF_COOKIE_NAME = "csrf_token"

_JWT_ALGORITHM = "HS256"


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


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
        claims = google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), settings.google_client_id
        )
    except ValueError as exc:
        raise AuthError("Google token verification failed") from exc
    # Reject unverified emails: otherwise someone could sign in with a Google
    # account whose (unverified) email matches a victim's and claim it.
    if not claims.get("email_verified"):
        raise AuthError("Google account email is not verified")
    return claims


def _fernet() -> Fernet:
    # Key separation: encrypt with the dedicated api_key_enc_secret so a leaked
    # JWT signing secret can't also decrypt stored API keys. Fall back to
    # jwt_secret only when the dedicated one isn't configured (local dev).
    secret = settings.api_key_enc_secret or settings.jwt_secret
    digest = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode()).decode()


def decrypt_api_key(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        # jwt_secret changed since the key was stored; user must re-enter it.
        raise AuthError("Stored API key can no longer be decrypted") from exc
