"""Authorization (authz) — Role-Based Access Control.

VOCABULARY:
- authn = authentication = WHO are you? -> handled in deps.py via JWT
- authz = authorization = WHAT can you do? -> handled here

DESIGN:
- Each user has ONE role (admin / developer / viewer).
- Each role maps to a SET of permissions (fine-grained actions).
- Endpoints request a permission via Depends(require_permission(...)).
- The dependency loads the user (reusing get_current_user), checks the
  role->permissions mapping, allows OR raises 403.

KEY DECISIONS:

1. Role is loaded FRESH from the DB on every request (not embedded in JWT).
   Cost: zero extra — we already load the user for authn.
   Benefit: role changes (e.g. demotion) take effect immediately.

2. Endpoints reference PERMISSIONS, not roles. Adding a new role later does
   NOT require touching every endpoint — only this file.

3. Fail closed: unknown role / unknown permission -> deny.
   Security default: when in doubt, say no.
"""

from enum import Enum

from fastapi import Depends, HTTPException, status

from flowforge.deps import get_current_user
from flowforge.models import User


class Role(str, Enum):
    """Coarse-grained user categories. Stored as a String in the DB.

    Inheriting from `str` means Role.ADMIN.value == "admin" and instances are
    JSON-serializable directly (no custom encoder needed).
    """

    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class Permission(str, Enum):
    """Fine-grained actions. Naming convention: '<resource>:<verb>'.

    Endpoints depend on Permission values, NOT Role values. That decoupling
    is what keeps endpoints stable when roles change.
    """

    USERS_READ = "users:read"
    USERS_MANAGE = "users:manage"  # list all users, change roles, delete

    WORKFLOWS_READ = "workflows:read"
    WORKFLOWS_WRITE = "workflows:write"
    WORKFLOWS_DELETE = "workflows:delete"


# THE WHOLE POLICY — single source of truth.
# To change what a role can do, you change THIS dict (and only this dict).
# Version-controlled in git, code-reviewable, diff-able. No DB rows to coordinate.
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: {
        Permission.USERS_READ,
        Permission.USERS_MANAGE,
        Permission.WORKFLOWS_READ,
        Permission.WORKFLOWS_WRITE,
        Permission.WORKFLOWS_DELETE,
    },
    Role.DEVELOPER: {
        Permission.USERS_READ,
        Permission.WORKFLOWS_READ,
        Permission.WORKFLOWS_WRITE,
        Permission.WORKFLOWS_DELETE,
    },
    Role.VIEWER: {
        Permission.USERS_READ,
        Permission.WORKFLOWS_READ,
    },
}


def has_permission(role_value: str, permission: Permission) -> bool:
    """Pure function: testable without HTTP, FastAPI, or a DB.

    Accepts the raw role string (what's stored in users.role) for ergonomics.
    Unknown roles return False — the FAIL-CLOSED default. If a row has a typo
    in the role field, the user gets nothing, not everything.
    """

    try:
        role = Role(role_value)
    except ValueError:
        return False

    return permission in ROLE_PERMISSIONS.get(role, set())


def require_permission(permission: Permission):
    """DEPENDENCY FACTORY — returns a FastAPI dependency that enforces `permission`.

    Why a factory (function-returning-function)?
    FastAPI's Depends() takes a callable with no extra args from your code.
    But we need DIFFERENT callables per permission. Solution: this outer
    function "closes over" the permission and produces a tailored dependency.

    Usage in a route:

        @router.get("/users")
        async def list_users(
            user: User = Depends(
                require_permission(Permission.USERS_MANAGE)
            ),
        ):
            ...

    The handler receives the User object (handy for logging "admin X did Y").
    """

    async def _check(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if not has_permission(current_user.role, permission):
            # 403 Forbidden = "I know who you are, but you can't do this."
            # NOT 401 Unauthorized = that's reserved for "I don't know who you are."
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission.value}",
            )

        return current_user

    return _check