"""Cron expression parser tests."""

import pytest

from flowforge.cron_parser import (
    CronExpressionError,
    current_fire_time,
    decode_cron_expression,
    validate_cron_expression,
)


def test_validate_accepts_weekday_range():
    expr = validate_cron_expression("0 2 * * MON-FRI")

    assert expr == "0 2 * * MON-FRI"


def test_validate_rejects_wrong_field_count():
    with pytest.raises(CronExpressionError):
        validate_cron_expression("0 2 *")


def test_decode_weekday_schedule():
    decoded = decode_cron_expression("0 2 * * MON-FRI")

    assert "MON-FRI" in decoded["summary"]
    assert decoded["fields"]["day_of_week"]["raw"] == "MON-FRI"
    assert len(decoded["next_runs_utc"]) == 3


def test_current_fire_time_is_utc_aware():
    fire_at = current_fire_time("0 2 * * *")

    assert fire_at.tzinfo is not None
