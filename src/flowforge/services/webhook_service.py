"""Webhook business logic — URL generation, HMAC gate, idempotent delivery."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.models import Webhook, WebhookDelivery, Workflow
from flowforge.services.execution_service import _add_execution, run_execution
from flowforge.webhook_hmac import verify_signature


HOOK_URL_PREFIX = "/hooks/"


@dataclass(frozen=True)
class ProcessWebhookResult:
    triggered: bool
    duplicate: bool = False
    execution_id: uuid.UUID | None = None
    reason: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _generate_secret() -> str:
    return secrets.token_hex(32)


def webhook_url_path(token: str) -> str:
    return f"{HOOK_URL_PREFIX}{token}"


def webhook_to_read(webhook: Webhook) -> dict:
    data = {
        "id": webhook.id,
        "workflow_id": webhook.workflow_id,
        "token": webhook.token,
        "url_path": webhook_url_path(webhook.token),
        "enabled": webhook.enabled,
        "owner_id": webhook.owner_id,
        "last_triggered_at": webhook.last_triggered_at,
        "created_at": webhook.created_at,
        "updated_at": webhook.updated_at,
    }

    return data


async def create_webhook(
    session: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    owner_id: uuid.UUID,
    enabled: bool = True,
) -> tuple[Webhook, str] | None:
    """Create webhook for workflow. Returns (webhook, secret) or None if workflow missing."""

    workflow = await session.get(Workflow, workflow_id)

    if workflow is None:
        return None

    existing = await session.execute(
        select(Webhook).where(Webhook.workflow_id == workflow_id)
    )

    if existing.scalar_one_or_none() is not None:
        raise ValueError("workflow_already_has_webhook")

    secret = _generate_secret()

    webhook = Webhook(
        workflow_id=workflow_id,
        owner_id=owner_id,
        token=_generate_token(),
        secret=secret,
        enabled=enabled,
    )

    session.add(webhook)
    await session.commit()
    await session.refresh(webhook)

    return webhook, secret


async def get_webhook(
    session: AsyncSession,
    webhook_id: uuid.UUID,
) -> Webhook | None:
    return await session.get(Webhook, webhook_id)


async def get_webhook_for_workflow(
    session: AsyncSession,
    workflow_id: uuid.UUID,
) -> Webhook | None:
    workflow = await session.get(Workflow, workflow_id)

    if workflow is None:
        return None

    result = await session.execute(
        select(Webhook).where(Webhook.workflow_id == workflow_id)
    )

    return result.scalar_one_or_none()


async def get_webhook_by_token(
    session: AsyncSession,
    token: str,
) -> Webhook | None:
    result = await session.execute(select(Webhook).where(Webhook.token == token))

    return result.scalar_one_or_none()


async def update_webhook(
    session: AsyncSession,
    webhook_id: uuid.UUID,
    *,
    enabled: bool | None = None,
) -> Webhook | None:
    webhook = await session.get(Webhook, webhook_id)

    if webhook is None:
        return None

    if enabled is not None:
        webhook.enabled = enabled

    await session.commit()
    await session.refresh(webhook)

    return webhook


async def rotate_webhook_secret(
    session: AsyncSession,
    webhook_id: uuid.UUID,
) -> tuple[Webhook, str] | None:
    webhook = await session.get(Webhook, webhook_id)

    if webhook is None:
        return None

    secret = _generate_secret()
    webhook.secret = secret

    await session.commit()
    await session.refresh(webhook)

    return webhook, secret


async def delete_webhook(
    session: AsyncSession,
    webhook_id: uuid.UUID,
) -> bool:
    webhook = await session.get(Webhook, webhook_id)

    if webhook is None:
        return False

    await session.delete(webhook)
    await session.commit()

    return True


async def _find_delivery(
    session: AsyncSession,
    webhook_id: uuid.UUID,
    idempotency_key: str,
) -> WebhookDelivery | None:
    result = await session.execute(
        select(WebhookDelivery).where(
            WebhookDelivery.webhook_id == webhook_id,
            WebhookDelivery.idempotency_key == idempotency_key,
        )
    )

    return result.scalar_one_or_none()


async def process_webhook_delivery(
    session: AsyncSession,
    *,
    token: str,
    body: bytes,
    signature_header: str | None,
    idempotency_key: str,
) -> ProcessWebhookResult:
    """Validate HMAC, enforce idempotency, create execution, run DAG."""

    webhook = await get_webhook_by_token(session, token)

    if webhook is None:
        return ProcessWebhookResult(triggered=False, reason="not_found")

    if not webhook.enabled:
        return ProcessWebhookResult(triggered=False, reason="disabled")

    if not verify_signature(webhook.secret, body, signature_header):
        return ProcessWebhookResult(triggered=False, reason="invalid_signature")

    existing = await _find_delivery(session, webhook.id, idempotency_key)

    if existing is not None:
        return ProcessWebhookResult(
            triggered=False,
            duplicate=True,
            execution_id=existing.execution_id,
            reason="duplicate_event",
        )

    delivery = WebhookDelivery(
        webhook_id=webhook.id,
        idempotency_key=idempotency_key,
    )
    session.add(delivery)

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        replay = await _find_delivery(session, webhook.id, idempotency_key)

        return ProcessWebhookResult(
            triggered=False,
            duplicate=True,
            execution_id=replay.execution_id if replay else None,
            reason="duplicate_event",
        )

    execution = await _add_execution(
        session,
        workflow_id=webhook.workflow_id,
        triggered_by=webhook.owner_id,
        trigger_source="webhook",
        webhook_id=webhook.id,
    )

    if execution is None:
        await session.rollback()
        return ProcessWebhookResult(triggered=False, reason="workflow_unavailable")

    delivery.execution_id = execution.id
    webhook.last_triggered_at = _utc_now()
    execution_id = execution.id

    await session.commit()

    await run_execution(session, execution_id)

    return ProcessWebhookResult(
        triggered=True,
        execution_id=execution_id,
    )
