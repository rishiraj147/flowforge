"""DAG scheduler unit tests."""

from flowforge.dag_scheduler import (
    check_manual_step_run,
    find_ready_steps,
    is_dag_complete,
    unsatisfied_dependencies,
)


def test_find_ready_steps_wave_zero():
    definition = {
        "steps": [
            {"id": "A", "needs": []},
            {"id": "B", "needs": ["A"]},
        ]
    }

    ready = find_ready_steps(definition, {})

    assert [s["id"] for s in ready] == ["A"]


def test_find_ready_steps_after_a():
    definition = {
        "steps": [
            {"id": "A", "needs": []},
            {"id": "B", "needs": ["A"]},
            {"id": "C", "needs": ["A"]},
        ]
    }

    ready = find_ready_steps(definition, {"A": "success"})

    assert {s["id"] for s in ready} == {"B", "C"}


def test_is_dag_complete():
    definition = {
        "steps": [
            {"id": "A", "needs": []},
            {"id": "B", "needs": ["A"]},
        ]
    }

    assert not is_dag_complete(definition, {"A": "success"})
    assert is_dag_complete(definition, {"A": "success", "B": "success"})


def test_unsatisfied_dependencies():
    step = {"id": "C", "needs": ["A", "B"]}

    assert unsatisfied_dependencies(step, {}) == ["A", "B"]
    assert unsatisfied_dependencies(step, {"A": "success", "B": "running"}) == ["B"]
    assert unsatisfied_dependencies(step, {"A": "success", "B": "success"}) == []


def test_check_manual_step_run_blocks_missing_deps():
    step = {"id": "B", "needs": ["A"]}
    check = check_manual_step_run(step, {})

    assert not check.allowed
    assert check.error_code == "dependencies_not_met"
    assert check.unsatisfied_dependencies == ["A"]


def test_check_manual_step_run_allows_retry_after_failure():
    step = {"id": "B", "needs": ["A"]}
    check = check_manual_step_run(step, {"A": "success", "B": "failed"})

    assert check.allowed


def test_check_manual_step_run_blocks_completed():
    step = {"id": "A", "needs": []}
    check = check_manual_step_run(step, {"A": "success"})

    assert not check.allowed
    assert check.error_code == "already_completed"
