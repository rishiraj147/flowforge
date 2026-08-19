"""HMAC webhook signature tests."""

from flowforge.webhook_hmac import compute_signature, verify_signature


def test_compute_and_verify_signature():
    secret = "test-secret"
    body = b'{"event":"order.created","id":"evt_123"}'

    signature = compute_signature(secret, body)

    assert signature.startswith("sha256=")
    assert verify_signature(secret, body, signature)


def test_verify_rejects_wrong_secret():
    body = b"payload"

    signature = compute_signature("secret-a", body)

    assert not verify_signature("secret-b", body, signature)


def test_verify_rejects_tampered_body():
    secret = "secret"
    body = b"original"
    signature = compute_signature(secret, body)

    assert not verify_signature(secret, b"tampered", signature)
