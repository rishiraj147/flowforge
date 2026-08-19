"""Mount Prometheus /metrics and HTTP request instrumentation."""

from fastapi import FastAPI

from flowforge.config import Settings


def setup_prometheus(app: FastAPI, settings: Settings) -> None:
    """Attach RED HTTP metrics and expose /metrics for Prometheus scraping."""

    if not settings.metrics_enabled:
        return

    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics"],
        inprogress_name="http_requests_inprogress",
        inprogress_labels=True,
    ).instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
    )
