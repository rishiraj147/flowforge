"""Pure DAG scheduling helpers — no DB, no Celery.

Used by the orchestrator to decide which steps are ready to run.
"""

from dataclasses import dataclass, field
from typing import Any


def step_id_str(step: dict[str, Any]) -> str:
    raw = step.get("id")

    if raw is None:
        raise ValueError("Step is missing 'id'")

    return str(raw)


def needs_ids(step: dict[str, Any]) -> list[str]:
    return [str(n) for n in step.get("needs", [])]


def unsatisfied_dependencies(
    step: dict[str, Any],
    status_by_step: dict[str, str],
) -> list[str]:
    """Dependency step ids that are not yet success."""

    return [
        dep
        for dep in needs_ids(step)
        if status_by_step.get(dep) != "success"
    ]


@dataclass(frozen=True)
class ManualStepRunCheck:
    """Result of validating a manual POST .../steps/{id}/run request."""

    allowed: bool
    error_code: str | None = None
    message: str | None = None
    unsatisfied_dependencies: list[str] = field(default_factory=list)


def check_manual_step_run(
    step: dict[str, Any],
    status_by_step: dict[str, str],
) -> ManualStepRunCheck:
    """Whether a single step may be queued manually (retry failed, not skip deps)."""

    sid = step_id_str(step)
    missing = unsatisfied_dependencies(step, status_by_step)

    if missing:
        return ManualStepRunCheck(
            allowed=False,
            error_code="dependencies_not_met",
            message=f"Dependencies not satisfied: {missing}",
            unsatisfied_dependencies=missing,
        )

    current = status_by_step.get(sid)

    if current == "success":
        return ManualStepRunCheck(
            allowed=False,
            error_code="already_completed",
            message=f"Step {sid!r} already completed",
        )

    if current in ("pending", "queued", "running"):
        return ManualStepRunCheck(
            allowed=False,
            error_code="already_in_progress",
            message=f"Step {sid!r} is already in progress",
        )

    return ManualStepRunCheck(allowed=True)


def all_step_ids(definition: dict[str, Any]) -> set[str]:
    return {
        step_id_str(step)
        for step in definition.get("steps", [])
        if step.get("id") is not None
    }


def find_ready_steps(
    definition: dict[str, Any],
    status_by_step: dict[str, str],
) -> list[dict[str, Any]]:
    """Steps with no task_run yet whose dependencies are all success."""

    ready: list[dict[str, Any]] = []

    for step in definition.get("steps", []):
        if step.get("id") is None:
            continue

        sid = step_id_str(step)

        if sid in status_by_step:
            continue

        if all(status_by_step.get(dep) == "success" for dep in needs_ids(step)):
            ready.append(step)

    return ready


def is_dag_complete(
    definition: dict[str, Any],
    status_by_step: dict[str, str],
) -> bool:
    ids = all_step_ids(definition)

    if not ids:
        return True

    return all(status_by_step.get(sid) == "success" for sid in ids)
