"""Unit tests for herds_cli.calendar_status_display.render_calendar_status.

The rendering function is purely data-in / data-out: given an event's
user_data dict (and optionally a ReconnectProviderResolver), it returns a
list of (severity, message) tuples that the caller dispatches to
OutputFormatter. No I/O, no Click context.
"""

from unittest.mock import MagicMock

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
        """Locks in the canonical full-message string for one known code:
        the 'Not added to calendar:' prefix, the '\\n   ' (3-space) indent,
        and the exact remediation command. Other known-code tests stay loose
        (substring-only) so a wording tweak can update one canonical assertion
        rather than five."""
        result = render_calendar_status(
            {"calendar_add_error": "auto_add_disabled"}
        )
        assert result == [(
            "info",
            "Not added to calendar: auto-add is disabled in your settings\n"
            "   Enable with: herds user-settings update --auto-add-to-calendar=True",
        )]

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

    def test_non_string_code_falls_back_safely(self):
        """A non-string truthy value (e.g. an integer from a server bug) must
        not raise. It bypasses the truthy fallback (it's truthy), bypasses the
        lowercase normalization (not str), and lands in the unknown-code branch
        where the raw value gets stringified into the warning message."""
        result = render_calendar_status({"calendar_add_error": 42})
        assert len(result) == 1
        severity, message = result[0]
        assert severity == "warning"
        assert "42" in message

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


class TestReconnectProviderResolver:
    """The resolver caches one /api/calendar/status fetch per instance and
    converts every non-success outcome (HTTP error, connected=False, exception)
    into a None return so the renderer's placeholder fallback applies."""

    def _make_api_client(self, response_or_exc):
        """Build an APIClient stub whose _make_request returns the given mock
        response, or raises if `response_or_exc` is an Exception."""
        client = MagicMock()
        client.base_url = "https://api.test"
        if isinstance(response_or_exc, Exception):
            client._make_request.side_effect = response_or_exc
        else:
            client._make_request.return_value = response_or_exc
        return client

    def _make_response(self, status_code=200, json_data=None):
        resp = MagicMock(status_code=status_code)
        resp.json.return_value = json_data if json_data is not None else {}
        return resp

    def test_caches_response_across_calls(self):
        """Multiple get_provider() calls hit the API at most once."""
        api_client = self._make_api_client(
            self._make_response(json_data={"connected": True, "provider": "google"})
        )
        resolver = ReconnectProviderResolver(api_client)

        for _ in range(3):
            assert resolver.get_provider() == "google"

        assert api_client._make_request.call_count == 1

    def test_caches_none_result(self):
        """A None result is also cached — we don't retry the API after a miss."""
        api_client = self._make_api_client(
            self._make_response(json_data={"connected": False})
        )
        resolver = ReconnectProviderResolver(api_client)

        for _ in range(3):
            assert resolver.get_provider() is None

        assert api_client._make_request.call_count == 1

    def test_returns_provider_on_connected(self):
        api_client = self._make_api_client(
            self._make_response(json_data={"connected": True, "provider": "outlook"})
        )
        assert ReconnectProviderResolver(api_client).get_provider() == "outlook"

    def test_returns_none_when_not_connected(self):
        api_client = self._make_api_client(
            self._make_response(
                json_data={"connected": False, "provider": "google"}
            )
        )
        # Even if `provider` is set in the response, connected=False means
        # there's no live connection to reconnect to.
        assert ReconnectProviderResolver(api_client).get_provider() is None

    def test_returns_none_on_http_error_status(self):
        api_client = self._make_api_client(self._make_response(status_code=500))
        assert ReconnectProviderResolver(api_client).get_provider() is None

    def test_returns_none_on_request_exception(self):
        """Network/connection errors must not bubble up — the caller wants a
        calendar-status line, not a crash."""
        api_client = self._make_api_client(ConnectionError("boom"))
        assert ReconnectProviderResolver(api_client).get_provider() is None

    def test_returns_none_when_provider_field_missing(self):
        api_client = self._make_api_client(
            self._make_response(json_data={"connected": True})
        )
        assert ReconnectProviderResolver(api_client).get_provider() is None

    def test_returns_none_when_provider_field_empty_string(self):
        api_client = self._make_api_client(
            self._make_response(json_data={"connected": True, "provider": ""})
        )
        assert ReconnectProviderResolver(api_client).get_provider() is None
