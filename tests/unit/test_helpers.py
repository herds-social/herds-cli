"""
Unit tests for extracted helper functions introduced in the reasoning-gaps PR.

Tests _build_event_update_data, _resolve_api_url_shortcut,
_load_google_oauth_credentials, and format_error_message.
"""

import json
from unittest.mock import MagicMock

import pytest

from herds_cli.commands.cmd_events import _build_event_update_data
from herds_cli.commands.cmd_config import _resolve_api_url_shortcut
from herds_cli.commands.cmd_user import _load_google_oauth_credentials
from herds_cli.commands.cmd_user_settings import _format_ignored_field_reason
from herds_cli.core.base import APIResponseHandler
from herds_cli.core.config import Config


# ---------------------------------------------------------------------------
# _build_event_update_data
# ---------------------------------------------------------------------------


class TestBuildEventUpdateData:
    def test_all_none_returns_empty(self):
        result = _build_event_update_data()
        assert result == {}

    def test_single_field(self):
        result = _build_event_update_data(title="Jazz Night")
        assert result == {"title": "Jazz Night"}

    def test_multiple_fields(self):
        result = _build_event_update_data(
            title="Jazz Night",
            city="Austin",
            state="TX",
        )
        assert result == {"title": "Jazz Night", "city": "Austin", "state": "TX"}

    def test_none_values_excluded(self):
        result = _build_event_update_data(
            title="Jazz Night",
            description=None,
            city="Austin",
        )
        assert "description" not in result
        assert result == {"title": "Jazz Night", "city": "Austin"}

    def test_boolean_field_preserved(self):
        result = _build_event_update_data(is_all_day=True)
        assert result == {"is_all_day": True}

    def test_boolean_false_preserved(self):
        result = _build_event_update_data(is_all_day=False)
        assert result == {"is_all_day": False}

    def test_empty_string_preserved(self):
        """Empty string is a valid value (clears a field), not None."""
        result = _build_event_update_data(notes="")
        assert result == {"notes": ""}

    def test_all_fields_populated(self):
        result = _build_event_update_data(
            title="t",
            description="d",
            notes="n",
            date_start="2026-01-01",
            date_end="2026-01-02",
            time_start="10:00",
            time_end="12:00",
            is_all_day=False,
            street_address="123 Main",
            city="Austin",
            state="TX",
            organizer="Blue Note",
            email_contact="info@example.com",
            phone="555-1234",
            website="https://example.com",
            category_level_1="Music",
            age_demographic="Adults",
            apple_calendar_event_id="apple-1",
            google_calendar_event_id="google-1",
            outlook_calendar_event_id="outlook-1",
        )
        assert len(result) == 20

    def test_keyword_only_enforced(self):
        """Cannot pass positional arguments."""
        with pytest.raises(TypeError):
            _build_event_update_data("Jazz Night")  # type: ignore[misc]

    def test_calendar_event_ids(self):
        result = _build_event_update_data(
            apple_calendar_event_id="a1",
            google_calendar_event_id="g1",
            outlook_calendar_event_id="o1",
        )
        assert result == {
            "apple_calendar_event_id": "a1",
            "google_calendar_event_id": "g1",
            "outlook_calendar_event_id": "o1",
        }


# ---------------------------------------------------------------------------
# _resolve_api_url_shortcut
# ---------------------------------------------------------------------------


class TestResolveApiUrlShortcut:
    def test_local_flag(self):
        result = _resolve_api_url_shortcut(local=True, prod=False, key="api_url", value=None)
        assert result == "http://localhost:8000"

    def test_prod_flag(self):
        result = _resolve_api_url_shortcut(local=False, prod=True, key="api_url", value=None)
        assert result == "https://api.herds.events"

    def test_both_flags_exits(self):
        with pytest.raises(SystemExit):
            _resolve_api_url_shortcut(local=True, prod=True, key="api_url", value=None)

    def test_no_key_exits(self):
        with pytest.raises(SystemExit):
            _resolve_api_url_shortcut(local=True, prod=False, key=None, value=None)

    def test_wrong_key_exits(self):
        with pytest.raises(SystemExit):
            _resolve_api_url_shortcut(local=True, prod=False, key="timezone", value=None)

    def test_value_with_shortcut_exits(self):
        with pytest.raises(SystemExit):
            _resolve_api_url_shortcut(
                local=True, prod=False, key="api_url", value="http://custom.com"
            )

    def test_empty_key_exits(self):
        with pytest.raises(SystemExit):
            _resolve_api_url_shortcut(local=True, prod=False, key="", value=None)


# ---------------------------------------------------------------------------
# _load_google_oauth_credentials
# ---------------------------------------------------------------------------


class TestLoadGoogleOAuthCredentials:
    def test_loads_from_json_file(self, tmp_path, monkeypatch):
        config_file = tmp_path / "herds-google-oauth-config.json"
        config_file.write_text(json.dumps({
            "installed": {
                "client_id": "json-client-id",
                "client_secret": "json-client-secret",
                "redirect_uris": ["http://localhost:8080/callback"],
            }
        }))
        monkeypatch.chdir(tmp_path)

        client_id, client_secret, redirect_uri = _load_google_oauth_credentials()

        assert client_id == "json-client-id"
        assert client_secret == "json-client-secret"
        assert redirect_uri == "http://localhost:8080/callback"

    def test_localhost_redirect_expanded(self, tmp_path, monkeypatch):
        """http://localhost (no path) is expanded to the full callback URL."""
        config_file = tmp_path / "herds-google-oauth-config.json"
        config_file.write_text(json.dumps({
            "installed": {
                "client_id": "cid",
                "client_secret": "csec",
                "redirect_uris": ["http://localhost"],
            }
        }))
        monkeypatch.chdir(tmp_path)

        _, _, redirect_uri = _load_google_oauth_credentials()

        assert redirect_uri == "http://localhost:8080/callback"

    def test_custom_redirect_uri_preserved(self, tmp_path, monkeypatch):
        config_file = tmp_path / "herds-google-oauth-config.json"
        config_file.write_text(json.dumps({
            "installed": {
                "client_id": "cid",
                "client_secret": "csec",
                "redirect_uris": ["http://custom:9090/cb"],
            }
        }))
        monkeypatch.chdir(tmp_path)

        _, _, redirect_uri = _load_google_oauth_credentials()

        assert redirect_uri == "http://custom:9090/cb"

    def test_falls_back_to_config(self, tmp_path, monkeypatch):
        """When no JSON file, reads from Config object."""
        monkeypatch.chdir(tmp_path)  # no herds-google-oauth-config.json here

        config = Config()
        config.google_client_id = "config-cid"
        config.google_client_secret = "config-csec"

        client_id, client_secret, redirect_uri = _load_google_oauth_credentials(config=config)

        assert client_id == "config-cid"
        assert client_secret == "config-csec"
        assert redirect_uri == "http://localhost:8080/callback"

    def test_no_credentials_exits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit):
            _load_google_oauth_credentials(config=None)

    def test_json_without_installed_key_falls_back(self, tmp_path, monkeypatch):
        """JSON file exists but doesn't have 'installed' key — falls back to config."""
        config_file = tmp_path / "herds-google-oauth-config.json"
        config_file.write_text(json.dumps({"web": {"client_id": "web-cid"}}))
        monkeypatch.chdir(tmp_path)

        config = Config()
        config.google_client_id = "config-cid"
        config.google_client_secret = "config-csec"

        client_id, _, _ = _load_google_oauth_credentials(config=config)

        assert client_id == "config-cid"

    def test_partial_json_falls_back_for_missing_fields(self, tmp_path, monkeypatch):
        """JSON has client_id but not client_secret — secret comes from config."""
        config_file = tmp_path / "herds-google-oauth-config.json"
        config_file.write_text(json.dumps({
            "installed": {
                "client_id": "json-cid",
            }
        }))
        monkeypatch.chdir(tmp_path)

        config = Config()
        config.google_client_id = "config-cid"
        config.google_client_secret = "config-csec"

        client_id, client_secret, _ = _load_google_oauth_credentials(config=config)

        assert client_id == "json-cid"  # JSON takes precedence
        assert client_secret == "config-csec"  # Falls back to config

    def test_flat_json_format(self, tmp_path, monkeypatch):
        """Flat JSON format (google_client_id/google_client_secret at top level)."""
        config_file = tmp_path / "herds-google-oauth-config.json"
        config_file.write_text(json.dumps({
            "google_client_id": "flat-cid",
            "google_client_secret": "flat-csec",
        }))
        monkeypatch.chdir(tmp_path)

        client_id, client_secret, redirect_uri = _load_google_oauth_credentials()

        assert client_id == "flat-cid"
        assert client_secret == "flat-csec"
        assert redirect_uri == "http://localhost:8080/callback"

    def test_config_without_google_attrs_no_error(self, tmp_path, monkeypatch):
        """Config with no google_client_* attrs must not raise AttributeError."""
        monkeypatch.chdir(tmp_path)

        config = Config()  # No google_client_id or google_client_secret

        with pytest.raises(SystemExit):
            _load_google_oauth_credentials(config=config)


# ---------------------------------------------------------------------------
# APIResponseHandler.format_error_message
# ---------------------------------------------------------------------------


class TestFormatErrorMessage:
    def _make_response(self, status_code, json_data=None, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        if json_data is not None:
            resp.json.return_value = json_data
        else:
            resp.json.side_effect = ValueError("no json")
        return resp

    def test_extracts_detail_from_json(self):
        resp = self._make_response(400, {"detail": "Missing field"})
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 400: Missing field"

    def test_falls_back_to_status_defaults(self):
        resp = self._make_response(401, {})
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 401: Authentication required"

    def test_403_default(self):
        resp = self._make_response(403, {})
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 403: Access forbidden"

    def test_404_default(self):
        resp = self._make_response(404, {})
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 404: Not found"

    def test_429_default(self):
        resp = self._make_response(429, {})
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 429: Rate limit exceeded"

    def test_500_default(self):
        resp = self._make_response(500, {})
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 500: Internal server error"

    def test_unknown_status_generic_message(self):
        resp = self._make_response(418, {})
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 418: HTTP 418 error"

    def test_no_json_falls_back_to_text(self):
        resp = self._make_response(502, json_data=None, text="Bad Gateway")
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 502: Bad Gateway"

    def test_no_json_no_text(self):
        resp = self._make_response(503, json_data=None, text="")
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 503"

    def test_detail_takes_precedence_over_status_default(self):
        resp = self._make_response(401, {"detail": "Token expired"})
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 401: Token expired"

    def test_handle_error_response_returns_formatted_message(self, capsys):
        resp = self._make_response(404, {"detail": "Event not found"})
        msg = APIResponseHandler.handle_error_response(resp, "get event")
        assert msg == "HTTP 404: Event not found"
        captured = capsys.readouterr()
        assert "get event" in captured.err

    def test_reads_herds_message_and_error_type(self):
        resp = self._make_response(
            400,
            {
                "status": "error",
                "error_type": "no_calendar_connection",
                "message": "No calendar connected. Connect a calendar provider first.",
            },
        )
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == (
            "HTTP 400: No calendar connected. Connect a calendar provider first. "
            "[no_calendar_connection]"
        )

    def test_prefers_message_over_detail_when_both_present(self):
        resp = self._make_response(
            400,
            {"message": "from message field", "detail": "from detail field"},
        )
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 400: from message field"

    def test_appends_error_type_even_when_only_detail_present(self):
        # Unusual shape: error_type without message but with detail.
        # Still surface error_type so it's visible in bug reports.
        resp = self._make_response(
            422,
            {"detail": "Validation failed", "error_type": "invalid_input"},
        )
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == "HTTP 422: Validation failed [invalid_input]"

    def test_provider_error_502(self):
        resp = self._make_response(
            502,
            {
                "status": "error",
                "error_type": "calendar_provider_error",
                "message": "Access denied by Google. Ensure the Calendar API is enabled.",
            },
        )
        msg = APIResponseHandler.format_error_message(resp)
        assert msg == (
            "HTTP 502: Access denied by Google. Ensure the Calendar API is enabled. "
            "[calendar_provider_error]"
        )


# ---------------------------------------------------------------------------
# _format_ignored_field_reason
# ---------------------------------------------------------------------------


class TestFormatIgnoredFieldReason:
    def test_known_reason_returns_human_string(self):
        assert (
            _format_ignored_field_reason("requires_paid_subscription")
            == "requires a paid subscription"
        )

    def test_unknown_reason_falls_back_to_raw_string(self):
        # Forward-compatibility: a future server reason like quota_exceeded
        # should print as-is rather than disappear, so the user still gets
        # *some* explanation even on an outdated CLI.
        assert _format_ignored_field_reason("quota_exceeded") == "quota_exceeded"

    def test_empty_string_returns_empty_string(self):
        assert _format_ignored_field_reason("") == ""
