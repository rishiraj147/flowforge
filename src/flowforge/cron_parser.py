"""Cron expression parsing and human-readable decoding.

Uses standard 5-field Unix cron (minute hour day month day_of_week), e.g.
`0 2 * * MON-FRI` = 02:00 UTC every weekday.

croniter evaluates expressions; this module validates and explains them for APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from croniter import croniter


class CronExpressionError(ValueError):
    """Invalid cron expression."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_cron_expression(expression: str) -> str:
    """Normalize and validate a cron expression. Raises CronExpressionError."""

    expr = expression.strip()

    if not expr:
        raise CronExpressionError("Cron expression cannot be empty")

    parts = expr.split()

    if len(parts) != 5:
        raise CronExpressionError(
            f"Cron expression must have 5 fields (minute hour day month day_of_week), "
            f"got {len(parts)}"
        )

    try:
        croniter(expr, _utc_now())
    except (KeyError, ValueError) as exc:
        raise CronExpressionError(str(exc)) from exc

    return expr


def cron_field_labels() -> list[str]:
    return ["minute", "hour", "day_of_month", "month", "day_of_week"]


def decode_cron_expression(expression: str) -> dict[str, Any]:
    """Decode a cron expression into field breakdown + next fire times."""

    expr = validate_cron_expression(expression)
    parts = expr.split()
    labels = cron_field_labels()

    fields = {
        label: {"raw": part, "description": _describe_field(label, part)}
        for label, part in zip(labels, parts, strict=True)
    }

    base = _utc_now()
    it = croniter(expr, base)

    next_runs = [it.get_next(datetime).isoformat() for _ in range(3)]

    return {
        "expression": expr,
        "summary": _build_summary(expr, fields),
        "fields": fields,
        "next_runs_utc": next_runs,
    }


def current_fire_time(expression: str, at: datetime | None = None) -> datetime:
    """Canonical fire time for the cron slot containing `at` (UTC)."""

    expr = validate_cron_expression(expression)
    anchor = at or _utc_now()

    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)

    it = croniter(expr, anchor)
    fire_at = it.get_prev(datetime)

    if fire_at.tzinfo is None:
        fire_at = fire_at.replace(tzinfo=timezone.utc)

    return fire_at


def _describe_field(label: str, part: str) -> str:
    if part == "*":
        return "every value"

    if label == "minute":
        return f"at minute {part}"

    if label == "hour":
        return f"at hour {part} (UTC)"

    if label == "day_of_month":
        return f"on day-of-month {part}"

    if label == "month":
        return f"in month {part}"

    return f"on day-of-week {part}"


def _build_summary(expression: str, fields: dict[str, Any]) -> str:
    minute = fields["minute"]["raw"]
    hour = fields["hour"]["raw"]
    dom = fields["day_of_month"]["raw"]
    month = fields["month"]["raw"]
    dow = fields["day_of_week"]["raw"]

    if minute == "*" and hour == "*":
        time_part = "every minute"
    elif hour == "*":
        time_part = f"at minute {minute} of every hour UTC"
    elif minute == "*":
        time_part = f"every minute during hour {hour} UTC"
    else:
        time_part = f"at {hour.zfill(2)}:{minute.zfill(2)} UTC"

    if dom != "*" or month != "*" or dow != "*":
        return f"Runs {time_part} when day={dom}, month={month}, weekday={dow}"

    return f"Runs {time_part} ({expression})"
