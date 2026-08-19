"""Content-addressable hashing for artifact deduplication."""

import hashlib


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact_storage_key(content_hash: str) -> str:
    """S3 object key — same bytes always map to the same key."""

    return f"artifacts/{content_hash}"
