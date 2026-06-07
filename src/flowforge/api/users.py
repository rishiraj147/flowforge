"""User endpoints. /users/me is the canonical "what does this token map to?" route."""

from fastapi import APIRouter, Depends

from flowforge.deps import get_current_user
from flowforge.models import User
from flowforge.schemas.user import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def me(
    current_user: User = Depends(get_current_user),
) -> UserRead:
    """Returns the currently authenticated user.

    Auth is enforced by the dependency alone — no code in this function checks
    anything. If the token is missing/invalid/expired, get_current_user raises
    401 and this handler never runs.
    """
    return current_user  # type: ignore[return-value]