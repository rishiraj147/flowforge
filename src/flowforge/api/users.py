"""User endpoints — public + admin.

Public:
    GET /users/me                    - read your own profile

Admin (require users:manage permission):
    GET /users                       - list all users
    PATCH /users/{user_id}/role      - change a user's role

The auth wall and the permission wall are different DEPENDENCIES — composing
them in the function signature is how FastAPI does access control:
    - get_current_user      -> authn (who?)
    - require_permission(P) -> authz (allowed?)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.authz import Permission, require_permission
from flowforge.db import get_session
from flowforge.deps import get_current_user
from flowforge.models import User
from flowforge.schemas.user import RoleUpdate, UserRead
from flowforge.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


# Order matters: literal paths ("/me") must be declared BEFORE parameterized
# paths ("/{user_id}/...") otherwise FastAPI tries to match "me" as a uuid.

@router.get("/me", response_model=UserRead)
async def me(
    current_user: User = Depends(get_current_user),
) -> UserRead:
    """Public — any authenticated user can read their own profile."""
    return current_user  # type: ignore[return-value]


@router.get("", response_model=list[UserRead])
async def list_users(
    # We bind to `_admin` (underscore prefix) to signal "we don't read this,
    # we just need the gate to run." The handler doesn't care WHO the admin is.
    _admin: User = Depends(
        require_permission(Permission.USERS_MANAGE)
    ),
    session: AsyncSession = Depends(get_session),
) -> list[UserRead]:
    """Admin — list every user. Real apps would paginate."""
    users = await user_service.list_all_users(session)
    return users  # type: ignore[return-value]


@router.patch(
    "/{user_id}/role",
    response_model=UserRead,
)
async def update_user_role(
    user_id: uuid.UUID,
    body: RoleUpdate,
    _admin: User = Depends(
        require_permission(Permission.USERS_MANAGE)
    ),
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    """Admin — change another user's role.

    Note: NO endpoint-level safety against demoting the last admin. That's a
    real bug for a real app. For now, the human admin is responsible. We'll
    add a guard if/when we adopt this pattern in production.
    """

    updated = await user_service.set_role(
        session,
        user_id,
        body.role,
    )

    if updated is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "User not found",
        )

    return updated  # type: ignore[return-value]