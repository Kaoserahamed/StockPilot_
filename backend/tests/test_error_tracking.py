"""Unit tests for error tracking and Sentry integration.

Verifies the tracker captures exceptions with full context, forwards them to
sentry-sdk when SENTRY_DSN is configured, and gracefully degrades to log-only
mode when Sentry is unavailable.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from app.core.error_tracking import (
    ErrorReport,
    ErrorTracker,
    bind_actor,
    current_context,
    get_error_tracker,
)

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def tracker() -> ErrorTracker:
    """Isolated error tracker for each test."""
    return ErrorTracker(
        environment="test",
        release="test-1.0.0",
        enabled=True,
        sentry_dsn=None,
    )


@pytest.fixture
def captured_reports(tracker: ErrorTracker) -> list[ErrorReport]:
    """Collect every report emitted by the tracker during a test."""
    reports: list[ErrorReport] = []
    tracker.add_sink(lambda report: reports.append(report))
    try:
        yield reports
    finally:
        tracker.clear_sinks()


def test_capture_basic_exception(tracker: ErrorTracker) -> None:
    """Tracker records exception type, message and fingerprint."""
    exc = ValueError("payment declined")
    report = tracker.capture(exc)

    assert report.exception_type == "ValueError"
    assert report.message == "payment declined"
    assert len(report.fingerprint) == 16
    assert report.environment == "test"
    assert report.release == "test-1.0.0"


def test_capture_correlates_route_context(tracker: ErrorTracker) -> None:
    """Captured exceptions include route metadata from context."""
    with tracker.route(method="POST", path="/api/v1/sales", request_id="req-123"):
        exc = RuntimeError("stock check failed")
        report = tracker.capture(exc)

    assert report.method == "POST"
    assert report.path == "/api/v1/sales"
    assert report.request_id == "req-123"


def test_capture_correlates_actor_context(tracker: ErrorTracker) -> None:
    """Captured exceptions include user_id and business_id from actor binding."""
    bind_actor(user_id=42, business_id=100)
    try:
        exc = PermissionError("role check failed")
        report = tracker.capture(exc)

        assert report.user_id == 42
        assert report.business_id == 100
    finally:
        # Clean up context for other tests
        from app.core.error_tracking import _actor_context

        _actor_context.set(None)


def test_capture_increments_fingerprint_counter(tracker: ErrorTracker) -> None:
    """Identical errors are grouped and counted."""
    exc1 = ValueError("duplicate invoice")
    exc2 = ValueError("duplicate invoice")

    report1 = tracker.capture(exc1)
    report2 = tracker.capture(exc2)

    assert report1.fingerprint == report2.fingerprint
    assert tracker.counts[report1.fingerprint] == 2


def test_capture_forwards_to_custom_sink(
    tracker: ErrorTracker, captured_reports: list[ErrorReport]
) -> None:
    """Reports are fanned out to registered sinks."""
    exc = RuntimeError("payment gateway timeout")
    tracker.capture(exc)

    assert len(captured_reports) == 1
    assert captured_reports[0].exception_type == "RuntimeError"
    assert captured_reports[0].message == "payment gateway timeout"


def test_tracker_disabled_skips_sinks(tracker: ErrorTracker) -> None:
    """When disabled, tracker counts but never forwards reports."""
    tracker.enabled = False
    sink_called = False

    def test_sink(report: ErrorReport) -> None:
        nonlocal sink_called
        sink_called = True

    tracker.add_sink(test_sink)
    tracker.capture(ValueError("test"))

    assert not sink_called
    assert len(tracker.counts) == 1  # Counting still works


def test_recent_reports_bounded(tracker: ErrorTracker) -> None:
    """Tracker never holds more than MAX_RECENT_REPORTS in memory."""
    from app.core.error_tracking import MAX_RECENT_REPORTS

    for i in range(MAX_RECENT_REPORTS + 10):
        tracker.capture(ValueError(f"error {i}"))

    assert len(tracker.recent) == MAX_RECENT_REPORTS


def test_status_summary(tracker: ErrorTracker) -> None:
    """Status dict exposes diagnostic counters."""
    tracker.capture(ValueError("first"))
    tracker.capture(ValueError("first"))  # Same fingerprint
    tracker.capture(RuntimeError("second"))  # Different fingerprint

    status = tracker.status()

    assert status["enabled"] is True
    assert status["environment"] == "test"
    assert status["release"] == "test-1.0.0"
    assert status["total_captured"] == 3
    assert status["unique_fingerprints"] == 2
    assert status["last_error_at"] is not None


def test_recent_reports_api(tracker: ErrorTracker) -> None:
    """recent_reports returns newest-first, limited slice."""
    tracker.capture(ValueError("first"))
    tracker.capture(RuntimeError("second"))
    tracker.capture(TypeError("third"))

    reports = tracker.recent_reports(limit=2)

    assert len(reports) == 2
    assert reports[0]["message"] == "third"  # Newest
    assert reports[1]["message"] == "second"


def test_sentry_disabled_when_dsn_unset() -> None:
    """Tracker runs in log-only mode when SENTRY_DSN is empty."""
    tracker = ErrorTracker(
        environment="production",
        release="v1.0.0",
        enabled=True,
        sentry_dsn=None,
    )
    assert tracker._sentry_installed is False


@patch.dict(os.environ, {"SENTRY_DSN": ""}, clear=False)
def test_get_error_tracker_singleton() -> None:
    """get_error_tracker returns the module-level singleton."""
    tracker1 = get_error_tracker()
    tracker2 = get_error_tracker()
    assert tracker1 is tracker2


def test_sentry_initializes_when_dsn_set() -> None:
    """Tracker calls sentry_sdk.init when SENTRY_DSN is configured."""
    fake_dsn = "https://public@sentry.io/123456"

    mock_sentry = MagicMock()
    
    # Patch the import inside _install_sentry
    import sys
    sys.modules["sentry_sdk"] = mock_sentry
    
    try:
        tracker = ErrorTracker(
            environment="production",
            release="v1.2.3",
            enabled=True,
            sentry_dsn=fake_dsn,
        )

        mock_sentry.init.assert_called_once_with(
            dsn=fake_dsn,
            environment="production",
            release="v1.2.3",
            traces_sample_rate=0.0,
        )
        assert tracker._sentry_installed is True
    finally:
        # Clean up the mock module
        if "sentry_sdk" in sys.modules:
            del sys.modules["sentry_sdk"]


def test_sentry_import_error_handled_gracefully() -> None:
    """Tracker degrades to log-only if sentry-sdk is not installed."""
    fake_dsn = "https://public@sentry.io/123456"
    
    # Ensure sentry_sdk is NOT importable
    import sys
    sentry_backup = sys.modules.get("sentry_sdk")
    if "sentry_sdk" in sys.modules:
        del sys.modules["sentry_sdk"]

    # Block the import
    sys.modules["sentry_sdk"] = None  # type: ignore

    try:
        tracker = ErrorTracker(
            environment="production",
            release="v1.0.0",
            enabled=True,
            sentry_dsn=fake_dsn,
        )
        # Tracker still works, just without Sentry forwarding
        assert tracker._sentry_installed is False
        assert tracker.enabled is True
    finally:
        # Restore original state
        if sentry_backup is not None:
            sys.modules["sentry_sdk"] = sentry_backup
        elif "sentry_sdk" in sys.modules:
            del sys.modules["sentry_sdk"]


def test_sentry_init_failure_handled_gracefully() -> None:
    """Tracker survives a bad SENTRY_DSN without crashing startup."""
    bad_dsn = "not-a-valid-dsn"

    mock_sentry = MagicMock()
    mock_sentry.init.side_effect = Exception("Invalid DSN format")
    
    import sys
    sys.modules["sentry_sdk"] = mock_sentry

    try:
        tracker = ErrorTracker(
            environment="production",
            release="v1.0.0",
            enabled=True,
            sentry_dsn=bad_dsn,
        )

        # Tracker is still operational, just without Sentry
        assert tracker._sentry_installed is False
        assert tracker.enabled is True
    finally:
        if "sentry_sdk" in sys.modules:
            del sys.modules["sentry_sdk"]


def test_bind_actor_and_current_context() -> None:
    """bind_actor stores actor metadata in ambient context."""
    from app.core.error_tracking import _actor_context

    _actor_context.set(None)  # Clean slate
    bind_actor(user_id=100, business_id=42)

    ctx = current_context()
    assert ctx["user_id"] == 100
    assert ctx["business_id"] == 42

    _actor_context.set(None)  # Clean up


def test_error_report_as_dict_serializable() -> None:
    """ErrorReport.as_dict produces JSON-serializable output."""
    report = ErrorReport(
        fingerprint="abc123",
        exception_type="ValueError",
        message="test error",
        path="/api/test",
        method="POST",
        request_id="req-456",
        business_id=10,
        user_id=20,
        environment="test",
        release="v1.0.0",
    )

    data = report.as_dict()

    assert data["fingerprint"] == "abc123"
    assert data["exception_type"] == "ValueError"
    assert data["message"] == "test error"
    assert data["path"] == "/api/test"
    assert data["method"] == "POST"
    assert data["request_id"] == "req-456"
    assert data["business_id"] == 10
    assert data["user_id"] == 20


def test_capture_traceback_formatting(tracker: ErrorTracker) -> None:
    """capture_traceback returns formatted exception traceback."""
    try:
        raise ValueError("test exception with traceback")
    except ValueError as exc:
        tb = tracker.capture_traceback(exc)

    assert "ValueError: test exception with traceback" in tb
    assert "Traceback" in tb


def test_reset_clears_state(tracker: ErrorTracker) -> None:
    """reset clears counters and buffered reports."""
    tracker.capture(ValueError("test"))
    tracker.add_sink(lambda r: None)

    assert len(tracker.counts) > 0
    assert len(tracker.recent) > 0
    assert len(tracker._sinks) > 0

    tracker.reset(keep_sinks=True)

    assert len(tracker.counts) == 0
    assert len(tracker.recent) == 0
    assert len(tracker._sinks) > 0  # Sinks kept

    tracker.reset(keep_sinks=False)
    assert len(tracker._sinks) == 0  # Sinks cleared
