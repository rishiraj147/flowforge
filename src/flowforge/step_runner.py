"""Pure step execution logic — no DB, no Celery.

Worker loads the step dict from the frozen workflow version and calls run_step().
"""

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from flowforge.circuit_breaker import CircuitBreaker
from flowforge.exceptions import PermanentStepError, TransientStepError


def find_step(definition: dict[str, Any], step_id: str) -> dict[str, Any] | None:
    """Return the step dict whose id matches step_id (string comparison)."""

    for step in definition.get("steps", []):
        raw_id = step.get("id")

        if raw_id is None:
            continue

        if str(raw_id) == step_id:
            return step

    return None


def run_step(
    step: dict[str, Any],
    log: Callable[[str], None] | None = None,
    artifact_upload: Callable[[bytes, str, str | None], Any] | None = None,
    attempt: int = 0,
) -> dict[str, Any]:
    """Execute one step definition. Raises ValueError for unknown kinds."""

    kind = step.get("kind", "noop")
    step_id = str(step.get("id"))

    if log is not None:
        log(f"Starting step {step_id!r} (kind={kind!r})")

    if kind == "noop":
        if log is not None:
            log(f"Step {step_id!r} noop complete")

        return {
            "kind": "noop",
            "step_id": step_id,
            "status": "ok",
        }

    if kind == "sleep":
        seconds = int(step.get("seconds", 1))

        for elapsed in range(1, seconds + 1):
            time.sleep(1)

            if log is not None:
                log(f"Sleeping… {elapsed}/{seconds}s")

        if log is not None:
            log(f"Step {step_id!r} sleep complete ({seconds}s)")

        return {
            "kind": "sleep",
            "step_id": step_id,
            "seconds": seconds,
            "status": "ok",
        }

    if kind == "artifact":
        if artifact_upload is None:
            raise ValueError("artifact step requires worker upload context")

        message = str(step.get("message", "flowforge artifact"))
        filename = str(step.get("filename", "output.txt"))
        data = message.encode("utf-8")

        if log is not None:
            log(f"Uploading artifact {filename!r} ({len(data)} bytes)")

        artifact_id = artifact_upload(data, filename, "text/plain")

        if log is not None:
            log(f"Artifact stored: {artifact_id!s}")

        return {
            "kind": "artifact",
            "step_id": step_id,
            "artifact_id": str(artifact_id),
            "filename": filename,
            "status": "ok",
        }

    if kind == "flaky":
        fail_until = int(step.get("fail_until_attempt", 1))

        if attempt < fail_until:
            if log is not None:
                log(
                    f"Transient failure simulated (attempt {attempt}, "
                    f"need {fail_until})",
                    # level passed via log callback signature - emitter uses info
                )

            raise TransientStepError(
                f"simulated transient failure on attempt {attempt}"
            )

        if log is not None:
            log(f"Flaky step succeeded on attempt {attempt}")

        return {
            "kind": "flaky",
            "step_id": step_id,
            "attempt": attempt,
            "status": "ok",
        }

    if kind == "http":
        url = str(step.get("url", "")).strip()

        if not url:
            raise PermanentStepError("http step requires a url")

        breaker = CircuitBreaker(f"http:{url}")

        if log is not None:
            log(f"HTTP GET {url!r} behind circuit breaker")

        def _fetch() -> None:
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    if response.status >= 500:
                        raise TransientStepError(f"upstream returned {response.status}")
            except urllib.error.HTTPError as exc:
                if exc.code >= 500:
                    raise TransientStepError(str(exc)) from exc

                raise PermanentStepError(str(exc)) from exc
            except urllib.error.URLError as exc:
                raise TransientStepError(str(exc)) from exc

        breaker.call(_fetch)

        if log is not None:
            log(f"HTTP step {step_id!r} complete")

        return {
            "kind": "http",
            "step_id": step_id,
            "url": url,
            "status": "ok",
        }

    raise ValueError(f"Unknown step kind: {kind!r}")
