"""Step runner unit tests."""

import pytest

from flowforge.step_runner import find_step, run_step


def test_find_step_by_string_id():
    definition = {
        "steps": [
            {"id": "welcome", "kind": "noop"},
            {"id": 2, "kind": "noop"},
        ]
    }

    assert find_step(definition, "welcome")["id"] == "welcome"
    assert find_step(definition, "2")["id"] == 2
    assert find_step(definition, "missing") is None


def test_run_step_noop():
    result = run_step({"id": "x", "kind": "noop"})

    assert result["kind"] == "noop"
    assert result["status"] == "ok"


def test_run_step_noop_with_log():
    lines: list[str] = []

    result = run_step({"id": "x", "kind": "noop"}, log=lines.append)

    assert result["status"] == "ok"
    assert len(lines) == 2
    assert "Starting" in lines[0]
    assert "complete" in lines[1]


def test_run_step_unknown_kind_raises():
    with pytest.raises(ValueError, match="Unknown step kind"):
        run_step({"id": "x", "kind": "explode"})
