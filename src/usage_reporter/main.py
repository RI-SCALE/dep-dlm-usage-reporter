"""Composition root: settings -> adapters -> one reporting run -> exit code.

Exit codes (Design-001): 0 ok, 1 config error, 2 unmapped accounts,
3 some records failed, 4 aborted (a dependency is unusable).
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime

from pydantic import ValidationError

from usage_reporter.adapters.argo import ArgoProject, ArgoSink
from usage_reporter.adapters.rucio import (
    RucioAttributeMapping,
    RucioClient,
    RucioRestSource,
    rucio_token_auth,
)
from usage_reporter.adapters.stdout import StdoutSink
from usage_reporter.adapters.token import ClientCredentials, TokenAuth
from usage_reporter.core.ports import AccountingSink
from usage_reporter.core.report import report_usage
from usage_reporter.core.window import window
from usage_reporter.settings import ConfigError, Settings

log = logging.getLogger("usage_reporter")


def _argo_sink(settings: Settings) -> ArgoSink:
    projects = {
        project_id: ArgoProject(
            project.installation_id,
            TokenAuth(
                ClientCredentials(
                    settings.argo_token_url,
                    project.client_id,
                    settings.client_secret(project_id),
                    scope=settings.argo_scope,
                    timeout_seconds=settings.timeout_seconds,
                )
            ),
        )
        for project_id, project in settings.projects.items()
    }
    return ArgoSink(
        settings.argo_endpoint,
        settings.argo_metric_definition_id,
        projects,
        timeout_seconds=settings.timeout_seconds,
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings()
        sink: AccountingSink = StdoutSink() if settings.dry_run else _argo_sink(settings)
    except (ValidationError, ConfigError) as exc:
        log.error("config error: %s", exc)
        return 1

    today = datetime.now(UTC).date()
    days = [settings.day] if settings.day else window(today, settings.lookback_days)
    log.info("reporting days=%s dry_run=%s", [d.isoformat() for d in days], settings.dry_run)
    rucio_credentials = ClientCredentials(
        settings.rucio_token_url,
        settings.rucio_client_id,
        settings.rucio_client_secret.get_secret_value(),
        scope=settings.rucio_scope,
        timeout_seconds=settings.timeout_seconds,
    )
    rucio = RucioClient(
        settings.rucio_host,
        rucio_token_auth(rucio_credentials),
        timeout_seconds=settings.timeout_seconds,
    )
    try:
        summary = report_usage(
            RucioRestSource(rucio),
            RucioAttributeMapping(rucio, settings.projects.keys()),
            sink,
            days,
        )
    except Exception as exc:
        log.error("aborted: %s: %s", type(exc).__name__, exc)
        log.debug("traceback", exc_info=True)
        return 4
    finally:
        rucio.close()
        rucio_credentials.close()
        if isinstance(sink, ArgoSink):
            sink.close()

    for account, nbytes in sorted(summary.unmapped.items()):
        log.warning("unmapped account=%r bytes=%d", account, nbytes)
    for record, reason in summary.failed:
        log.error("failed record=%s reason=%s", record, reason)
    log.info(
        "done outcomes=%s failed=%d unmapped=%d skipped=%d",
        {str(k): v for k, v in summary.outcomes.items()},
        len(summary.failed),
        len(summary.unmapped),
        summary.skipped,
    )
    return summary.exit_code


if __name__ == "__main__":
    sys.exit(main())
