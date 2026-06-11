"""Workflow REST endpoints.

Mapping (method, path) -> permission -> service call:

POST    /workflows           workflows:write   create
GET     /workflows           workflows:read    list_page
GET     /workflows/{id}      workflows:read    get
PATCH   /workflows/{id}      workflows:write   update
DELETE  /workflows/{id}      workflows:delete  delete_one

Handlers stay thin:
1. FastAPI parses + validates input (via the body / query schema).
2. The require_permission dependency enforces authz.
3. The handler calls a service function.
4. Errors -> HTTPException with the appropriate status code.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.authz import Permission, require_permission
from flowforge.db import get_session
from flowforge.models import User
from flowforge.schemas.workflow import (
    WorkflowCreate,
    WorkflowPage,
    WorkflowRead,
    WorkflowUpdate,
)
from flowforge.services import workflow_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post(
    "",
    response_model=WorkflowRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow(
    body: WorkflowCreate,
    current_user: User = Depends(
        require_permission(Permission.WORKFLOWS_WRITE)
    ),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRead:
    """Create a new workflow owned by the current user.

    201 Created + the new resource is the REST convention for
    POST-to-collection.
    """

    wf = await workflow_service.create(
        session,
        owner_id=current_user.id,
        name=body.name,
        description=body.description,
        definition=body.definition,
    )

    return wf  # type: ignore[return-value]


@router.get("", response_model=WorkflowPage)
async def list_workflows(
    cursor: str | None = Query(
        default=None,
        description="Opaque pagination token from a previous response.",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Max items per page.",
    ),
    _r: User = Depends(
        require_permission(Permission.WORKFLOWS_READ)
    ),
    session: AsyncSession = Depends(get_session),
) -> WorkflowPage:
    """List workflows, newest first, cursor-paginated."""

    items, next_cursor = await workflow_service.list_page(
        session,
        cursor=cursor,
        limit=limit,
    )

    return WorkflowPage(
        items=items,
        next_cursor=next_cursor,
    )  # type: ignore[arg-type]


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: uuid.UUID,
    _r: User = Depends(
        require_permission(Permission.WORKFLOWS_READ)
    ),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRead:
    wf = await workflow_service.get(session, workflow_id)

    if wf is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Workflow not found",
        )

    return wf  # type: ignore[return-value]


@router.patch("/{workflow_id}", response_model=WorkflowRead)
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowUpdate,
    _w: User = Depends(
        require_permission(Permission.WORKFLOWS_WRITE)
    ),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRead:
    """Partial update.

    exclude_unset=True is the WHOLE reason PATCH semantics work —
    it gives us only fields the client EXPLICITLY sent.
    Omitted fields stay as-is in the DB.

    Without it, every optional field would arrive as None and we'd
    nuke values to NULL on every request.
    """

    patch = body.model_dump(exclude_unset=True)

    wf = await workflow_service.update(
        session,
        workflow_id,
        patch,
    )

    if wf is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Workflow not found",
        )

    return wf  # type: ignore[return-value]


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workflow(
    workflow_id: uuid.UUID,
    _d: User = Depends(
        require_permission(Permission.WORKFLOWS_DELETE)
    ),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """204 No Content is the REST convention for a successful DELETE."""

    deleted = await workflow_service.delete_one(
        session,
        workflow_id,
    )

    if not deleted:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Workflow not found",
        )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )