"""HMAC-SHA256 signatures for webhook request verification.

Callers sign the raw HTTP body with a shared secret. We recompute the digest
and compare with constant-time equality to detect tampering or wrong secrets.
"""

import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="


def compute_signature(secret: str, body: bytes) -> str:
    """Return header value: sha256=<hex digest of HMAC-SHA256(secret, body)."""

    digest = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify X-FlowForge-Signature matches the body (constant-time compare)."""

    if not signature_header:
        return False

    header = signature_header.strip()

    if not header.startswith(SIGNATURE_PREFIX):
        return False

    provided = header[len(SIGNATURE_PREFIX):]

    if not provided:
        return False

    expected_digest = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(provided, expected_digest)
