"""User business logic — pure functions over a session.

WHY this layer exists (instead of putting logic in the router):

- Routers should be THIN: parse input, call a service, return a response.
- Services own the rules ("a user with this email already exists",
  "verify the password before issuing tokens"). No knowledge of HTTP.
- Same service is reusable from a CLI, a script, a background job, tests, etc.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.models import User
from flowforge.security import hash_password, verify_password


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str | None,
) -> User:
    """Hash the password and INSERT a new user."""

    user = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
    )

    session.add(user)
    await session.commit()
    await session.refresh(user)  # reload server-side defaults (created_at)

    return user


async def get_user_by_email(
    session: AsyncSession,
    email: str,
) -> User | None:
    result = await session.execute(
        select(User).where(User.email == email)
    )
    return result.scalar_one_or_none()


async def get_user_by_id(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> User | None:
    return await session.get(User, user_id)


async def authenticate(
    *,
    session: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    """Return the User if credentials match; None otherwise.

    NOTE: returns None for BOTH "no such email" and "wrong password".
    Never leak which one was wrong. Otherwise the login endpoint becomes
    a tool for attackers to enumerate valid email addresses.
    """

    user = await get_user_by_email(session, email)

    if user is None:
        return None

    if not verify_password(password, user.password_hash):
        return None

    return user