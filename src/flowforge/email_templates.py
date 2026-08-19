"""Jinja2 HTML email templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "email"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_execution_email(template_name: str, context: dict[str, Any]) -> str:
    """Render an HTML email body from a template under templates/email/."""

    template = _env.get_template(template_name)

    return template.render(**context)
