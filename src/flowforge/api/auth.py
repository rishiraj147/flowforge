"""Auth endpoints: register, login, refresh.

Routers stay THIN. Each handler:
1. Parses input (FastAPI does this via the body model).
2. Calls a service function.
3. Maps the outcome to a response or HTTPException.
"""

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.config import Settings, settings_from_request
from flowforge.db import get_session
from flowforge.schemas.auth import (
    AccessTokenOnly,
    LoginRequest,
    RefreshRequest,
    TokenPair,
)
from flowforge.schemas.user import UserCreate, UserRead
from flowforge.security import (
    REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from flowforge.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: UserCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_from_request),
) -> UserRead:
    """Create a new user. Returns the public view (no password hash)."""

    existing = await user_service.get_user_by_email(
        session,
        body.email,
    )

    if existing is not None:
        # 409 Conflict = the request was well-formed but conflicts with state.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Email already registered",
        )

    register_role = "developer" if settings.load_test_auto_developer_role else None

    user = await user_service.create_user(
        session,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        role=register_role,
    )

    # response_model=UserRead + from_attributes=True turns the ORM User into the
    # safe public shape — password_hash is dropped automatically.
    return user  # type: ignore[return-value]


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_from_request),
) -> TokenPair:
    """Verify credentials and issue both tokens."""

    user = await user_service.authenticate(
        session=session,
        email=body.email,
        password=body.password,
    )

    if user is None:
        # Same message for both "wrong email" and "wrong password"
        # — prevents account enumeration attacks.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid credentials",
        )

    return TokenPair(
        access_token=create_access_token(str(user.id), settings),
        refresh_token=create_refresh_token(str(user.id), settings),
    )


@router.post("/refresh", response_model=AccessTokenOnly)
async def refresh(
    body: RefreshRequest,
    settings: Settings = Depends(settings_from_request),
) -> AccessTokenOnly:
    """Exchange a valid refresh token for a fresh access token."""

    try:
        payload = decode_token(body.refresh_token, settings)
    except jwt.PyJWTError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid refresh token",
        )

    # Reject access tokens passed here — they're for protected routes, not refresh.
    if payload.get("type") != REFRESH:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not a refresh token",
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Malformed token",
        )

    return AccessTokenOnly(
        access_token=create_access_token(sub, settings),
    )