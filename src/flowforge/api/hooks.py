"""Public webhook receiver — no JWT; secured by URL token + HMAC."""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.db import get_session
from flowforge.schemas.webhook import WebhookDeliveryResult
from flowforge.services import webhook_service

router = APIRouter(prefix="/hooks", tags=["hooks"])


@router.post(
    "/{token}",
    response_model=WebhookDeliveryResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_webhook(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    signature: str | None = Header(default=None, alias="X-FlowForge-Signature"),
) -> WebhookDeliveryResult:
    """External systems POST events here to trigger a workflow.

    Security:
    - Unguessable token in URL (capability URL)
    - HMAC-SHA256 of raw body in X-FlowForge-Signature: sha256=<hex>
    - Idempotency-Key header prevents duplicate executions
    """

    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )

    body = await request.body()

    result = await webhook_service.process_webhook_delivery(
        session,
        token=token,
        body=body,
        signature_header=signature,
        idempotency_key=idempotency_key.strip(),
    )

    if result.reason == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")

    if result.reason == "disabled":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Webhook is disabled")

    if result.reason == "invalid_signature":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")

    if result.reason == "workflow_unavailable":
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Workflow cannot be executed",
        )

    return WebhookDeliveryResult(
        triggered=result.triggered,
        duplicate=result.duplicate,
        execution_id=result.execution_id,
        reason=result.reason,
    )
