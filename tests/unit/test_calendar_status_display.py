"""Unit tests for herds_cli.calendar_status_display.render_calendar_status.

The rendering function is purely data-in / data-out: given an event's
user_data dict (and optionally a ReconnectProviderResolver), it returns a
list of (severity, message) tuples that the caller dispatches to
OutputFormatter. No I/O, no Click context.
"""

from unittest.mock import MagicMock

import pytest

from herds_cli.calendar_status_display import (
    ReconnectProviderResolver,
    render_calendar_status,
)


class TestRenderCalendarStatus:
    """Each branch maps a calendar_add_error code (or its absence) to the
    expected (severity, message) output. Severity is the string the caller
    dispatches through OutputFormatter — 'info' or 'warning'."""

    def test_no_error_code_renders_neutral_fallback(self):
        """Defensive fallback: when neither a provider id nor a calendar_add_error
        is present we still produce one info line so the user knows the calendar
        status was checked. Should not happen post server-fix but kept harmless."""
        result = render_calendar_status({})
        assert result == [("info", "Not added to a calendar")]

    def test_auto_add_disabled_renders_info_with_settings_hint(self):
        result = render_calendar_status(
            {"calendar_add_error": "auto_add_disabled"}
        )
        assert len(result) == 1
        severity, message = result[0]
        assert severity == "info"
        assert "auto-add is disabled in your settings" in message
        assert "herds user-settings update --auto-add-to-calendar=True" in message

    def test_no_calendar_connection_renders_info_with_connect_hint(self):
        result = render_calendar_status(
            {"calendar_add_error": "no_calendar_connection"}
        )
        severity, message = result[0]
        assert severity == "info"
        assert "no calendar provider connected" in message
        assert "herds calendar connect --provider google" in message
        assert "outlook" in message  # the (or --provider outlook) parenthetical

    def test_calendar_provider_error_renders_warning_with_status_hint(self):
        result = render_calendar_status(
            {"calendar_add_error": "calendar_provider_error"}
        )
        severity, message = result[0]
        assert severity == "warning"
        assert "your calendar provider rejected the event" in message
        assert "herds calendar status" in message

    def test_calendar_add_exception_renders_warning_with_status_hint(self):
        result = render_calendar_status(
            {"calendar_add_error": "calendar_add_exception"}
        )
        severity, message = result[0]
        assert severity == "warning"
        assert "unexpected error occurred during auto-add" in message
        assert "herds calendar status" in message

    def test_unknown_code_falls_back_to_raw(self):
        """If the server adds a new code we haven't taught the CLI yet,
        we surface the raw code rather than swallowing it."""
        result = render_calendar_status(
            {"calendar_add_error": "calendar_quota_exhausted"}
        )
        severity, message = result[0]
        assert severity == "warning"
        assert "calendar_quota_exhausted" in message

    def test_uppercase_code_is_normalized(self):
        """Server emits lowercase but defensive-normalize so older test fixtures
        and any case drift don't drop into the unknown-code branch."""
        result = render_calendar_status(
            {"calendar_add_error": "AUTO_ADD_DISABLED"}
        )
        severity, message = result[0]
        assert severity == "info"
        assert "auto-add is disabled in your settings" in message

    # ----- calendar_needs_reconnect: the only code that consults the resolver -----

    def test_needs_reconnect_with_resolver_returning_provider(self):
        """When the resolver supplies the provider, the hint names it."""
        resolver = MagicMock(spec=ReconnectProviderResolver)
        resolver.get_provider.return_value = "google"
        result = render_calendar_status(
            {"calendar_add_error": "calendar_needs_reconnect"},
            resolver=resolver,
        )
        severity, message = result[0]
        assert severity == "warning"
        assert "expired" in message
        assert "herds calendar connect --provider google" in message
        # Placeholder must not appear when we have a real provider.
        assert "<google|outlook>" not in message
        resolver.get_provider.assert_called_once()

    def test_needs_reconnect_with_resolver_returning_none(self):
        """Resolver returning None (network error or not connected) → fallback."""
        resolver = MagicMock(spec=ReconnectProviderResolver)
        resolver.get_provider.return_value = None
        result = render_calendar_status(
            {"calendar_add_error": "calendar_needs_reconnect"},
            resolver=resolver,
        )
        _, message = result[0]
        assert "<google|outlook>" in message

    def test_needs_reconnect_with_no_resolver_uses_placeholder(self):
        """Caller didn't pass a resolver → same fallback as resolver=None."""
        result = render_calendar_status(
            {"calendar_add_error": "calendar_needs_reconnect"}
        )
        _, message = result[0]
        assert "<google|outlook>" in message

    def test_needs_reconnect_does_not_call_resolver_for_other_codes(self):
        """Other codes must never hit the network — the resolver is only
        consulted when the code actually needs it."""
        resolver = MagicMock(spec=ReconnectProviderResolver)
        for code in [
            "auto_add_disabled",
            "no_calendar_connection",
            "calendar_provider_error",
            "calendar_add_exception",
        ]:
            render_calendar_status(
                {"calendar_add_error": code}, resolver=resolver
            )
        resolver.get_provider.assert_not_called()
