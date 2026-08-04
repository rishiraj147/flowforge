"""
DAG (Directed Acyclic Graph) validation for workflow definitions.

THE ALGORITHM: Kahn's topological sort.
- Compute in-degree for every node.
- Start a queue with all in-degree-0 nodes (ready to run).
- Pop one, append to output, decrement neighbors' in-degree; push any that hit 0.
  Loop until queue is empty.
- If output length == total nodes -> DAG (and output is a valid run order).
- Else -> cycle. Any node still with in-degree > 0 is involved in the cycle.

Complexity: O(V + E) — linear in nodes + edges. Cannot be beaten for this task.

This file deliberately has NO FastAPI / SQLAlchemy imports. It is a pure
algorithm — testable from a REPL, reusable from a CLI or background worker.
"""

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class DagValidationError(ValueError):
    """Raised when a workflow definition is structurally invalid.

    Inherits from ValueError so it integrates with general "bad input" handling,
    but carries extra fields so the API layer can return rich error responses
    (e.g., 422 with the list of cycle nodes).
    """

    message: str
    cycle_nodes: list[str] | None = None
    bad_step: str | None = None

    def __str__(self) -> str:
        return self.message


def validate_dag(definition: dict[str, Any]) -> list[str]:
    """Validate the dependency graph inside a workflow definition.

    Returns a topological order (a valid sequence in which to execute the steps).
    Raises DagValidationError with a human-readable message on any problem.

    Rules enforced:
        1. Every step has a unique 'id'.
        2. Every 'needs' entry references a known step id.
        3. The resulting graph has no cycles.

    An empty definition (or one with no "steps" key) is trivially valid -> [].
    """

    steps = definition.get("steps", [])
    if not steps:
        return []

    # ----- 1. Parse step ids + build "needs" map; check uniqueness -----

    needs_map: dict[str, list[str]] = {}
    step_order: list[str] = []  # remember declaration order for stable output

    for index, step in enumerate(steps):
        sid = step.get("id")

        if not sid:
            raise DagValidationError(
                f"Step at index {index} is missing an 'id'.",
                bad_step=None,
            )

        if sid in needs_map:
            raise DagValidationError(
                f"Duplicate step id: {sid!r}",
                bad_step=sid,
            )

        needs_map[sid] = list(step.get("needs", []))
        step_order.append(sid)

    # ----- 2. Check that every dependency points to a real step -----

    known = set(step_order)

    for sid, prereqs in needs_map.items():
        for p in prereqs:
            if p not in known:
                raise DagValidationError(
                    f"Step {sid!r} depends on unknown step {p!r}.",
                    bad_step=sid,
                )

    # ----- 3. Kahn's algorithm -----

    in_degree: dict[str, int] = {sid: 0 for sid in step_order}
    forward_edges: dict[str, list[str]] = {sid: [] for sid in step_order}

    # Translate "X needs Y, Z" into edges Y -> X and Z -> X.
    for sid, prereqs in needs_map.items():
        for prereq in prereqs:
            in_degree[sid] += 1
            forward_edges[prereq].append(sid)

    # Seed queue with everything that has zero unmet prerequisites.
    # Iterate step_order (not the dict) so the topological order is
    # deterministic — important for tests.
    queue = deque(sid for sid in step_order if in_degree[sid] == 0)
    topological_order: list[str] = []

    while queue:
        node = queue.popleft()
        topological_order.append(node)

        for neighbor in forward_edges[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # ----- 4. Cycle check -----

    if len(topological_order) != len(step_order):
        cycle_nodes = sorted(
            sid for sid in step_order if in_degree[sid] > 0
        )

        raise DagValidationError(
            f"Cycle detected. Involved steps: {', '.join(cycle_nodes)}.",
            cycle_nodes=cycle_nodes,
        )

    return topological_order