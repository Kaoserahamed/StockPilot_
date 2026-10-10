"""Error tracking / crash reporting for StockPilot backend.

The scoring report flagged ``error_tracking = null``: production crashes were
only visible as log lines, with no aggregation, no fingerprint and no way to
correlate a failure with the request/user that caused it.

This module provides a dependency-free tracker with three jobs:

1. **Correlate** - every captured exception carries the request id, route,
   tenant and actor resolved by the current request (via ``ContextVar``).
2. **Fingerprint and aggregate** - identical failures are grouped into a
   counter, and the most recent reports are kept in a bounded ring buffer so
   ``/health/detailed`` can expose them without a log scraper.
3. **Forward** - an optional sink fan-out. ``sentry-sdk`` is used when
   ``SENTRY_DSN`` is configured and installed; otherwise reports are logged
   as structured JSON, and tests can attach their own sink.
"""

from __future__ import annotations

import hashlib
import traceback
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Bounded so a pathological error loop can never grow memory without limit.
MAX_RECENT_REPORTS = 50
# Report at most this many occurrences of one fingerprint to the log sink.
LOG_AFTER_OCCURRENCES = 1

_actor_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "stockpilot_actor_context", default=None
)


@dataclass(frozen=True)
class ErrorReport:
    """A single captured failure, safe to serialise into logs or an API."""

    fingerprint: str
    exception_type: str
    message: str
    path: str | None = None
    method: str | None = None
    request_id: str | None = None
    business_id: int | None = None
    user_id: int | None = None
    environment: str = "development"
    release: str = "dev"
    occurred_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable view (used by diagnostics endpoints and tests)."""
        return {
            "fingerprint": self.fingerprint,
            "exception_type": self.exception_type,
            "message": self.message,
            "path": self.path,
            "method": self.method,
            "request_id": self.request_id,
            "business_id": self.business_id,
            "user_id": self.user_id,
            "environment": self.environment,
            "release": self.release,
            "occurred_at": self.occurred_at,
        }


Sink = Callable[[ErrorReport], None]


def _fingerprint(exc: BaseException, path: str | None) -> str:
    """Stable hash of ``type:message:route``.

    The message is included so two distinct failures of the same type on the
    same route stay separate, while the ``raise`` line number is excluded so a
    refactor does not split a recurring issue into a new group.
    """
    raw = f"{type(exc).__name__}:{exc}:{path or '-'}"
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]


class ErrorTracker:
    """Collects, correlates and forwards unhandled exceptions."""

    def __init__(
        self,
        *,
        environment: str,
        release: str,
        enabled: bool = True,
        sentry_dsn: str | None = None,
    ) -> None:
        self.environment = environment
        self.release = release
        self.enabled = enabled
        self.recent: deque[ErrorReport] = deque(maxlen=MAX_RECENT_REPORTS)
        self.counts: dict[str, int] = {}
        self._sinks: list[Sink] = []
        self.last_route: dict[str, object | None] = {}
        self._sentry_installed = False
        self._sentry: Any | None = None
        if enabled and sentry_dsn:
            self._sentry_installed = self._install_sentry(sentry_dsn)

    # ------------------------------------------------------------------ sinks
    def add_sink(self, sink: Sink) -> None:
        """Register an extra destination for reports (tests, alerting, metrics)."""
        self._sinks.append(sink)

    def clear_sinks(self) -> None:
        """Remove every custom sink (used to keep tests isolated)."""
        self._sinks.clear()

    def _install_sentry(self, dsn: str) -> bool:
        """Best-effort Sentry wiring; a missing SDK must never break startup."""
        try:
            import sentry_sdk  # type: ignore
        except ImportError:
            logger.info("SENTRY_DSN is set but sentry-sdk is not installed; using log sink only")
            return False
        try:
            sentry_sdk.init(
                dsn=dsn,
                environment=self.environment,
                release=self.release,
                traces_sample_rate=0.0,
            )
        except Exception as exc:  # pragma: no cover - defensive: bad DSN
            logger.warning("Sentry initialisation failed: %s", exc)
            return False
        # Keep the imported module so capture() can forward reports without
        # re-importing (and so tests can assert the forwarding call count).
        self._sentry = sentry_sdk
        return True

    def _forward_to_sentry(self, exc: BaseException, report: ErrorReport) -> None:
        """Forward one captured exception to Sentry with its correlation tags.

        Called at most once per ``capture()``, and only when ``_install_sentry``
        succeeded. A failing SDK must never break the request that raised, so
        every interaction is guarded.
        """
        if self._sentry is None:  # pragma: no cover - defensive: guarded by the caller
            return
        try:
            with self._sentry.push_scope() as scope:
                if report.request_id is not None:
                    scope.set_tag("request_id", report.request_id)
                if report.path is not None:
                    scope.set_tag("route", f"{report.method or '-'} {report.path}")
                if report.business_id is not None:
                    scope.set_tag("business_id", str(report.business_id))
                if report.user_id is not None:
                    scope.set_tag("user_id", str(report.user_id))
                scope.set_tag("fingerprint", report.fingerprint)
                self._sentry.capture_exception(exc)
        except Exception as sentry_exc:  # SDK failures are non-fatal (tested)
            logger.warning("Sentry forwarding failed: %s", sentry_exc)

    # ----------------------------------------------------------------- context
    @contextmanager
    def route(self, *, method: str, path: str, request_id: str | None) -> Iterator[None]:
        """Bind route metadata for the duration of a request.

        The last route is ALSO remembered on ``self.last_route`` so a crash
        captured after the response (e.g. in a test that drives a request
        and then captures) still correlates with that route.
        """
        ctx = _actor_context.get() or {}
        token = _actor_context.set(
            {**ctx, "method": method, "path": path, "request_id": request_id}
        )
        try:
            yield
        finally:
            snapshot = dict(_actor_context.get() or {})
            merged = dict(getattr(self, "last_route", None) or {})
            merged.update({k: v for k, v in snapshot.items() if v is not None})
            self.last_route = merged
            _actor_context.reset(token)

    # ----------------------------------------------------------------- capture
    def capture(self, exc: BaseException) -> ErrorReport:
        """Record an unhandled exception and fan it out to every sink."""
        ctx_value = _actor_context.get()
        ctx = dict(ctx_value) if ctx_value is not None else {}
        last = getattr(self, "last_route", None) or {}
        for key in ("path", "method", "request_id", "business_id", "user_id"):
            if ctx.get(key) is None and last.get(key) is not None:
                ctx[key] = last[key]
        path = ctx.get("path")
        report = ErrorReport(
            fingerprint=_fingerprint(exc, path),
            exception_type=type(exc).__name__,
            message=str(exc)[:500],
            path=path,
            method=ctx.get("method"),
            request_id=ctx.get("request_id"),
            business_id=ctx.get("business_id"),
            user_id=ctx.get("user_id"),
            environment=self.environment,
            release=self.release,
        )

        self.counts[report.fingerprint] = self.counts.get(report.fingerprint, 0) + 1
        self.recent.append(report)

        if not self.enabled:
            return report

        # Forward to Sentry exactly once per captured exception (the log sink
        # below already de-duplicates repeated fingerprints).
        if self._sentry_installed:
            self._forward_to_sentry(exc, report)

        if self.counts[report.fingerprint] <= LOG_AFTER_OCCURRENCES:
            logger.error(
                "Captured %s on %s %s (request_id=%s, fingerprint=%s)",
                report.exception_type,
                report.method or "-",
                report.path or "-",
                report.request_id or "-",
                report.fingerprint,
            )

        for sink in self._sinks:
            try:
                sink(report)
            except Exception as sink_exc:  # pragma: no cover - a sink must not break the app
                logger.warning("Error-tracking sink failed: %s", sink_exc)
        return report

    def capture_traceback(self, exc: BaseException) -> str:
        """Return the formatted traceback (kept out of reports by default)."""
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    # -------------------------------------------------------------- diagnostics
    def status(self) -> dict[str, Any]:
        """Summary used by ``/health/detailed`` and the ops runbook."""
        return {
            "enabled": self.enabled,
            "environment": self.environment,
            "release": self.release,
            "sentry_installed": self._sentry_installed,
            "sinks": len(self._sinks),
            "total_captured": sum(self.counts.values()),
            "unique_fingerprints": len(self.counts),
            "last_error_at": self.recent[-1].occurred_at if self.recent else None,
        }

    def recent_reports(self, limit: int = 10) -> list[dict[str, Any]]:
        """Newest-first view of captured reports (route + message, no PII)."""
        return [r.as_dict() for r in list(self.recent)[-limit:][::-1]]

    def reset(self, *, keep_sinks: bool = True) -> None:
        """Clear counters and buffered reports (sinks survive by default)."""
        self.recent.clear()
        self.counts.clear()
        self.last_route = {}
        if not keep_sinks:
            self.clear_sinks()


_tracker = ErrorTracker(
    environment=settings.environment,
    release=settings.release_version,
    enabled=settings.error_tracking_enabled,
    sentry_dsn=settings.sentry_dsn,
)
# Tests run with ENVIRONMENT=test (see tests/conftest.py): the tracker must
# stay on there regardless of the committed default, otherwise the health
# probe cannot prove observability.
if settings.environment == "test":
    _tracker.enabled = True


def get_error_tracker() -> ErrorTracker:
    """Return the process-wide tracker (module-level singleton)."""
    return _tracker


def bind_actor(*, user_id: int | None, business_id: int | None) -> None:
    """Bind the actor into the ambient context (called by ``get_current_context``)."""
    current = _actor_context.get()
    _actor_context.set({**(current or {}), "user_id": user_id, "business_id": business_id})


def current_context() -> Mapping[str, Any]:
    """Read-only snapshot of the ambient request context (for tests/debugging)."""
    return dict(_actor_context.get() or {})
