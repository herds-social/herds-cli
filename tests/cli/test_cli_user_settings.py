"""User settings command tests via Click's CliRunner.

Exercises the rendering branches of `herds user-settings update`,
particularly the partial-success path triggered by ignored_fields in
the server response.
"""

import json
from unittest.mock import MagicMock

from tests.cli.conftest import strip_ansi
from herds_cli.cli import cli


def _make_settings_response(ignored_fields=None, **settings_overrides):
    """Build a UserSettingsUpdateResponse-shaped dict for mocking the PUT.

    Defaults match a free-tier user: theme=light, auto_add=False. Override
    any field via kwargs. ignored_fields defaults to an empty list; pass a
    list of {field, reason} dicts to simulate a partial-success response.
    Pass ignored_fields=False (the boolean) to omit the key entirely,
    simulating an older server that doesn't return the field.
    """
    settings = {
        "sort_by": "utc_start",
        "sort_order": "asc",
        "filter_by": "all",
        "theme": "light",
        "auto_add_to_calendar_enabled": False,
        "date_filter": "all",
    }
    settings.update(settings_overrides)
    body = {
        "user_id": "u-123",
        "settings": settings,
        "created_at": "2026-04-29T00:00:00Z",
        "updated_at": "2026-04-29T00:00:00Z",
    }
    if ignored_fields is not False:
        body["ignored_fields"] = ignored_fields or []
    return body


def _save_test_session(session_manager, email="test@example.com"):
    """Persist a minimal mobile session so cmd.setup_session/load_session_auth pass."""
    session_manager.save_session(email, {
        "client_type": "mobile",
        "tokens": {"access_token": "tok"},
        "user_data": {"id": "u-123", "email": email},
    })


def _mock_put_response(cli_obj, body):
    """Wire the mocked HTTP session to return `body` from the next request."""
    response = MagicMock(status_code=200)
    response.json.return_value = body
    response.cookies = {}
    cli_obj["api_client"].session.request.return_value = response
    return response


class TestUpdateSettings:
    def test_no_ignored_fields_renders_success_header(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """Empty ignored_fields → existing green ✅ Settings updated: header."""
        _save_test_session(mock_session_manager)
        _mock_put_response(cli_obj, _make_settings_response(ignored_fields=[]))

        result = cli_runner.invoke(
            cli,
            ["user-settings", "update", "--sort-by", "date_start"],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "Settings updated:" in out
        assert "partially updated" not in out.lower()

    def test_ignored_fields_renders_partial_success_header(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """Non-empty ignored_fields → ⚠️ partial-success header + reason bullets."""
        _save_test_session(mock_session_manager)
        _mock_put_response(
            cli_obj,
            _make_settings_response(
                ignored_fields=[
                    {"field": "theme", "reason": "requires_paid_subscription"}
                ]
            ),
        )

        result = cli_runner.invoke(
            cli,
            ["user-settings", "update", "--theme", "dark"],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "partially updated" in out.lower()
        assert "1 field" in out  # singular: "1 field ignored"
        assert "theme" in out
        assert "requires a paid subscription" in out
        # The success header MUST NOT appear when partial.
        assert "Settings updated:" not in out
        # Saved values should still be displayed under a neutral header.
        assert "Saved values:" in out

    def test_multiple_ignored_fields_listed(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """Two ignored fields → both appear in the bullet list."""
        _save_test_session(mock_session_manager)
        _mock_put_response(
            cli_obj,
            _make_settings_response(
                ignored_fields=[
                    {"field": "theme", "reason": "requires_paid_subscription"},
                    {
                        "field": "auto_add_to_calendar_enabled",
                        "reason": "requires_paid_subscription",
                    },
                ]
            ),
        )

        result = cli_runner.invoke(
            cli,
            [
                "user-settings",
                "update",
                "--theme",
                "dark",
                "--auto-add-to-calendar=True",
            ],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "2 field" in out  # plural: "2 fields ignored"
        assert "theme" in out
        assert "auto_add_to_calendar_enabled" in out
        # Both reasons rendered.
        assert out.count("requires a paid subscription") == 2

    def test_unknown_reason_code_falls_back_to_raw_string(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """A future reason code unknown to this CLI prints raw, doesn't crash."""
        _save_test_session(mock_session_manager)
        _mock_put_response(
            cli_obj,
            _make_settings_response(
                ignored_fields=[
                    {"field": "theme", "reason": "quota_exceeded"}
                ]
            ),
        )

        result = cli_runner.invoke(
            cli,
            ["user-settings", "update", "--theme", "dark"],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "theme" in out
        # Falls back to raw enum string rather than swallowing or crashing.
        assert "quota_exceeded" in out

    def test_json_format_passes_through_ignored_fields(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """--format json includes the ignored_fields array verbatim."""
        _save_test_session(mock_session_manager)
        ignored = [{"field": "theme", "reason": "requires_paid_subscription"}]
        _mock_put_response(
            cli_obj, _make_settings_response(ignored_fields=ignored)
        )

        # Override format on the injected obj — cmd code reads cmd.output_format.
        cli_obj["format"] = "json"
        cli_obj["config"].output_format = "json"

        result = cli_runner.invoke(
            cli,
            ["user-settings", "update", "--theme", "dark"],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        # Locate the JSON object embedded in the output and confirm it carries
        # the ignored_fields array unmodified.
        start = out.find("{")
        end = out.rfind("}")
        assert start != -1 and end != -1, f"no JSON found in output: {out!r}"
        parsed = json.loads(out[start : end + 1])
        assert parsed["ignored_fields"] == ignored

    def test_missing_ignored_fields_treated_as_empty(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """Older server without the field → no warning, success header renders."""
        _save_test_session(mock_session_manager)
        # ignored_fields=False (sentinel) tells the helper to OMIT the key.
        _mock_put_response(
            cli_obj, _make_settings_response(ignored_fields=False)
        )

        result = cli_runner.invoke(
            cli,
            ["user-settings", "update", "--sort-by", "date_start"],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "Settings updated:" in out
        assert "partially updated" not in out.lower()
