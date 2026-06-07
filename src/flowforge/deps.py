"""Shared FastAPI dependencies for protected endpoints.

`get_current_user` is the canonical "auth wall": any route that uses it as a
dependency becomes protected. Unprotected routes simply don't list it.
"""

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.config import Settings, settings_from_request
from flowforge.db import get_session
from flowforge.models import User
from flowforge.security import ACCESS, decode_token
from flowforge.services import user_service


# OAuth2PasswordBearer extracts the token from the "Authorization: Bearer <token>"
# header. tokenUrl is METADATA for the OpenAPI docs (Swagger's "Authorize" button
# points there) — it does not affect runtime behavior.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    settings: Settings = Depends(settings_from_request),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Decode the access token, load the user from DB, or raise 401.

    Failure modes (all -> 401):
    - No Authorization header (oauth2_scheme already raises before this runs).
    - Token signature invalid (tampered or signed with a different secret).
    - Token expired.
    - Token is a REFRESH token used here (wrong type).
    - User no longer exists in DB.
    """

    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token, settings)
    except jwt.PyJWTError:
        raise credentials_exc

    # Reject refresh tokens here — they're only valid at /auth/refresh.
    if payload.get("type") != ACCESS:
        raise credentials_exc

    sub = payload.get("sub")
    if sub is None:
        raise credentials_exc

    try:
        user_id = uuid.UUID(sub)
    except (ValueError, TypeError):
        raise credentials_exc

    user = await user_service.get_user_by_id(
        session,
        user_id,
    )

    if user is None:
        raise credentials_exc

    return user