"""Pydantic schemas for auth endpoints (login / refresh / token responses)."""

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    """POST /auth/login body."""

    email: EmailStr
    password: str


class TokenPair(BaseModel):
    """Response of /auth/login — both tokens at once."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # OAuth2 convention; clients send "Authorization: Bearer <token>"


class AccessTokenOnly(BaseModel):
    """Response of /auth/refresh — only a fresh access token."""

    access_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """POST /auth/refresh body."""

    refresh_token: str