"""Workflow REST endpoints.

Mapping (method, path) -> permission -> service call:

POST    /workflows                           workflows:write   create
GET     /workflows                           workflows:read    list_page
GET     /workflows/{id}                      workflows:read    get
PATCH   /workflows/{id}                      workflows:write   update
DELETE  /workflows/{id}                      workflows:delete  delete_one
GET     /workflows/{id}/versions             workflows:read    list_versions
GET     /workflows/{id}/versions/{n}         workflows:read    get_version

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
from flowforge.dag import DagValidationError
from flowforge.db import get_session
from flowforge.models import User
from flowforge.schemas.workflow import (
    WorkflowCreate,
    WorkflowPage,
    WorkflowRead,
    WorkflowUpdate,
    WorkflowVersionRead,
)
from flowforge.services import workflow_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _dag_error_to_http(exc: DagValidationError) -> HTTPException:
    """Translate a domain validation error into a structured 422 response.

    We use 422 (Unprocessable Entity) - same family as Pydantic validation
    errors. The body carries enough details for the client UI to highlight
    the broken steps.
    """
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "message": exc.message,
            "cycle_nodes": exc.cycle_nodes,
            "bad_step": exc.bad_step,
        },
    )


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
    """Create a new workflow owned by the current user (version 1 snapshot)."""
    try:
        wf = await workflow_service.create(
            session,
            owner_id=current_user.id,
            name=body.name,
            description=body.description,
            definition=body.definition,
        )
    except DagValidationError as exc:
        raise _dag_error_to_http(exc)

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
    current_user: User = Depends(
        require_permission(Permission.WORKFLOWS_WRITE)
    ),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRead:
    """Partial update. Definition changes publish a new immutable version."""

    patch = body.model_dump(exclude_unset=True)

    try:
        wf = await workflow_service.update(
            session,
            workflow_id,
            patch,
            updated_by_id=current_user.id,
        )
    except DagValidationError as exc:
        raise _dag_error_to_http(exc)

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


@router.get(
    "/{workflow_id}/versions",
    response_model=list[WorkflowVersionRead],
)
async def list_workflow_versions(
    workflow_id: uuid.UUID,
    _r: User = Depends(
        require_permission(Permission.WORKFLOWS_READ)
    ),
    session: AsyncSession = Depends(get_session),
) -> list[WorkflowVersionRead]:
    """List all immutable versions for a workflow, newest first."""

    versions = await workflow_service.list_versions(session, workflow_id)

    if versions is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Workflow not found",
        )

    return versions  # type: ignore[return-value]


@router.get(
    "/{workflow_id}/versions/{version_number}",
    response_model=WorkflowVersionRead,
)
async def get_workflow_version(
    workflow_id: uuid.UUID,
    version_number: int,
    _r: User = Depends(
        require_permission(Permission.WORKFLOWS_READ)
    ),
    session: AsyncSession = Depends(get_session),
) -> WorkflowVersionRead:
    """Fetch one immutable version snapshot by version number."""

    version = await workflow_service.get_version(
        session,
        workflow_id,
        version_number,
    )

    if version is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Workflow version not found",
        )

    return version  # type: ignore[return-value]
