"""Password hashing + JWT token utilities.

Two concerns, one file (small project). In a larger codebase you might split
them into security/passwords.py and security/tokens.py.

WHY each piece exists is documented inline.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from flowforge.config import Settings


# ---------- Token "type" claim ----------
# We embed "type": "access" or "type": "refresh" in every JWT so that an attacker
# who steals a refresh token can't pass it where an access token is expected
# (or vice versa). Without this, the two would be indistinguishable.
ACCESS = "access"
REFRESH = "refresh"


# ---------- Password hashing ----------

def hash_password(plain: str) -> str:
    """Hash a plain password with bcrypt.

    rounds=12 -> about 250ms on modern hardware. Imperceptible for one login,
    devastating for an attacker brute-forcing a stolen DB.

    bcrypt automatically generates and embeds a random salt INSIDE the output,
    so two users with the same password get different hashes.
    """
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time compare of a plain password against a stored bcrypt hash.

    "Constant-time" matters: a naive == could leak information about how many
    characters matched via timing. bcrypt.checkpw avoids that.
    """
    return bcrypt.checkpw(
        plain.encode("utf-8"),
        hashed.encode("utf-8"),
    )


# ---------- JWT tokens ----------

def create_access_token(subject: str, settings: Settings) -> str:
    """Short-lived token sent with every protected request."""
    return _encode(
        subject,
        ACCESS,
        timedelta(minutes=settings.access_token_ttl_minutes),
        settings,
    )


def create_refresh_token(subject: str, settings: Settings) -> str:
    """Long-lived token used only against /auth/refresh."""
    return _encode(
        subject,
        REFRESH,
        timedelta(days=settings.refresh_token_ttl_days),
        settings,
    )


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    """Decode + verify signature + verify expiry.

    Raises jwt.PyJWTError (or its subclasses: ExpiredSignatureError,
    InvalidSignatureError, etc.) on any failure. Caller decides what to do
    with the error (usually: return 401).
    """
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def _encode(
    subject: str,
    kind: str,
    ttl: timedelta,
    settings: Settings,
) -> str:
    now = datetime.now(timezone.utc)

    payload = {
        "sub": subject,                    # who the token represents (user id as string)
        "type": kind,                      # access vs refresh
        "iat": int(now.timestamp()),       # issued at
        "exp": int((now + ttl).timestamp())  # expires at — pyjwt enforces this on decode
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )