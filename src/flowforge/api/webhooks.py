"""Webhook management REST endpoints (authenticated)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.authz import Permission, require_permission
from flowforge.db import get_session
from flowforge.models import User
from flowforge.schemas.webhook import (
    WebhookCreate,
    WebhookCreated,
    WebhookRead,
    WebhookUpdate,
)
from flowforge.services import webhook_service

router = APIRouter(tags=["webhooks"])


def _webhook_read(webhook) -> WebhookRead:
    return WebhookRead(**webhook_service.webhook_to_read(webhook))


@router.post(
    "/workflows/{workflow_id}/webhooks",
    response_model=WebhookCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow_webhook(
    workflow_id: uuid.UUID,
    body: WebhookCreate,
    current_user: User = Depends(require_permission(Permission.WEBHOOKS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> WebhookCreated:
    try:
        created = await webhook_service.create_webhook(
            session,
            workflow_id=workflow_id,
            owner_id=current_user.id,
            enabled=body.enabled,
        )
    except ValueError as exc:
        if str(exc) == "workflow_already_has_webhook":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Workflow already has a webhook",
            ) from exc

        raise

    if created is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")

    webhook, secret = created

    return WebhookCreated(webhook=_webhook_read(webhook), secret=secret)


@router.get(
    "/workflows/{workflow_id}/webhooks",
    response_model=WebhookRead,
)
async def get_workflow_webhook(
    workflow_id: uuid.UUID,
    _r: User = Depends(require_permission(Permission.WEBHOOKS_READ)),
    session: AsyncSession = Depends(get_session),
) -> WebhookRead:
    webhook = await webhook_service.get_webhook_for_workflow(session, workflow_id)

    if webhook is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found for workflow")

    return _webhook_read(webhook)


@router.patch(
    "/webhooks/{webhook_id}",
    response_model=WebhookRead,
)
async def update_webhook(
    webhook_id: uuid.UUID,
    body: WebhookUpdate,
    _w: User = Depends(require_permission(Permission.WEBHOOKS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> WebhookRead:
    webhook = await webhook_service.update_webhook(
        session,
        webhook_id,
        enabled=body.enabled,
    )

    if webhook is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")

    return _webhook_read(webhook)


@router.post(
    "/webhooks/{webhook_id}/rotate-secret",
    response_model=WebhookCreated,
)
async def rotate_webhook_secret(
    webhook_id: uuid.UUID,
    _w: User = Depends(require_permission(Permission.WEBHOOKS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> WebhookCreated:
    rotated = await webhook_service.rotate_webhook_secret(session, webhook_id)

    if rotated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")

    webhook, secret = rotated

    return WebhookCreated(webhook=_webhook_read(webhook), secret=secret)


@router.delete(
    "/webhooks/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_webhook(
    webhook_id: uuid.UUID,
    _w: User = Depends(require_permission(Permission.WEBHOOKS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    deleted = await webhook_service.delete_webhook(session, webhook_id)

    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")
