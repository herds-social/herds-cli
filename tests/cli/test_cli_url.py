"""
CLI tests for `herds url submit` and --poll behavior.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from herds_cli.cli import cli
from tests.cli.conftest import strip_ansi


def _create_session(session_manager, email="test@example.com"):
    session_manager.save_session(email, {
        "client_type": "mobile",
        "tokens": {"access_token": "fake-token"},
        "user_data": {"id": "user-123", "email": email},
    })


def _make_response(status_code=200, json_data=None):
    mock = MagicMock(status_code=status_code)
    mock.json.return_value = json_data if json_data is not None else {}
    mock.text = ""
    mock.headers = {"content-type": "application/json"}
    return mock


SUBMIT_RESPONSE = {
    "status": "success",
    "message": "URL accepted for processing",
    "event_source_id": "src-001",
}

SAMPLE_EVENT = {
    "title": "Jazz Night",
    "category_level_1": "Music",
    "date_info": {
        "raw": {"date": "2026-07-15"},
        "local": {"date_start": "2026-07-15", "time_start": "20:00"},
    },
    "location": {"city": "Austin", "state": "TX"},
    "contact": {"organizer": "Venue Co"},
}


def _extraction_response(*, status="processing", **extra):
    body = {
        "extraction_id": "src-001",
        "source_type": "url",
        "extraction_status": status,
        "event_count": 0,
        "url": {
            "submitted_url": "https://venue.com/event",
            "candidate_link_count": 3,
            "fetched_link_count": 1,
        },
        "created_at": "2026-07-07T09:00:00Z",
        "acknowledged_at": None,
    }
    body.update(extra)
    return body


class TestUrlSubmit:
    def test_success_prints_event_source_id(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, SUBMIT_RESPONSE
        )

        result = cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event"],
            obj=cli_obj,
        )

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert "Event source ID: src-001" in out

    def test_submit_body_includes_url_timezone_mock(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, SUBMIT_RESPONSE
        )

        cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event", "--mock"],
            obj=cli_obj,
        )

        call = cli_obj["api_client"].session.request.call_args
        assert call.kwargs["json"] == {
            "url": "https://venue.com/event",
            "timezone": "America/New_York",
            "mock_mode": True,
        }

    def test_add_to_calendar_true_in_body(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, SUBMIT_RESPONSE
        )

        cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event", "--add-to-calendar"],
            obj=cli_obj,
        )

        assert cli_obj["api_client"].session.request.call_args.kwargs["json"][
            "add_to_calendar"
        ] is True

    def test_no_add_to_calendar_false_in_body(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, SUBMIT_RESPONSE
        )

        cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event", "--no-add-to-calendar"],
            obj=cli_obj,
        )

        assert cli_obj["api_client"].session.request.call_args.kwargs["json"][
            "add_to_calendar"
        ] is False

    def test_add_to_calendar_omitted_from_body(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, SUBMIT_RESPONSE
        )

        cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event"],
            obj=cli_obj,
        )

        assert "add_to_calendar" not in (
            cli_obj["api_client"].session.request.call_args.kwargs["json"]
        )

    def test_duplicate_submission_warning(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200,
            {
                "status": "success",
                "message": "URL already submitted",
                "event_source_id": "src-dup",
            },
        )

        result = cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event"],
            obj=cli_obj,
        )

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert "URL was recently submitted" in out
        assert "src-dup" in out
        assert "Event source ID" not in out


class TestUrlSubmitPoll:
    @patch("herds_cli.commands.cmd_extractions.time.sleep")
    def test_poll_completes_and_displays_events(
        self, mock_sleep, cli_runner, cli_obj
    ):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.side_effect = [
            _make_response(200, SUBMIT_RESPONSE),
            _make_response(200, _extraction_response(status="processing")),
            _make_response(200, _extraction_response(status="completed", event_count=1)),
            _make_response(200, [SAMPLE_EVENT]),
        ]

        result = cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event", "--poll"],
            obj=cli_obj,
        )

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert "Jazz Night" in out
        assert "Extraction completed" in out

    @patch("herds_cli.commands.cmd_extractions.time.sleep")
    def test_poll_failed_exits_with_error_type(
        self, mock_sleep, cli_runner, cli_obj
    ):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.side_effect = [
            _make_response(200, SUBMIT_RESPONSE),
            _make_response(
                200,
                _extraction_response(
                    status="failed", extraction_error_type="url_fetch_error"
                ),
            ),
        ]

        result = cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event", "--poll"],
            obj=cli_obj,
        )

        assert result.exit_code == 1
        out = strip_ansi(result.output)
        assert "Event extraction failed" in out
        assert "url_fetch_error" in out

    @patch("herds_cli.commands.cmd_extractions.time.monotonic")
    @patch("herds_cli.commands.cmd_extractions.time.sleep")
    def test_poll_timeout_exits(
        self, mock_sleep, mock_monotonic, cli_runner, cli_obj
    ):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        mock_monotonic.side_effect = [0.0, 9999.0]
        cli_obj["api_client"].session.request.side_effect = [
            _make_response(200, SUBMIT_RESPONSE),
            _make_response(200, _extraction_response(status="processing")),
        ]

        result = cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event", "--poll"],
            obj=cli_obj,
        )

        assert result.exit_code == 1
        assert "Polling timed out" in strip_ansi(result.output)

    @patch("herds_cli.commands.cmd_extractions.time.sleep")
    def test_poll_zero_events_warning(
        self, mock_sleep, cli_runner, cli_obj
    ):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.side_effect = [
            _make_response(200, SUBMIT_RESPONSE),
            _make_response(200, _extraction_response(status="completed")),
            _make_response(200, []),
        ]

        result = cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event", "--poll"],
            obj=cli_obj,
        )

        assert result.exit_code == 0
        assert "No events were extracted from this URL" in strip_ansi(result.output)

    def test_poll_with_explicit_json_format_rejected(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "json"
        cli_obj["_format_explicit"] = True

        result = cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event", "--poll"],
            obj=cli_obj,
        )

        assert result.exit_code != 0
        assert "--poll cannot be combined with --format json" in strip_ansi(
            result.output
        )

    @patch("herds_cli.commands.cmd_extractions.time.sleep")
    def test_poll_with_default_json_format_allowed(
        self, mock_sleep, cli_runner, cli_obj
    ):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "json"
        cli_obj["api_client"].session.request.side_effect = [
            _make_response(200, SUBMIT_RESPONSE),
            _make_response(200, _extraction_response(status="completed")),
            _make_response(200, [SAMPLE_EVENT]),
        ]

        result = cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event", "--poll"],
            obj=cli_obj,
        )

        assert result.exit_code == 0

    def test_no_poll_json_dumps_response(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "json"
        cli_obj["format"] = "json"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, SUBMIT_RESPONSE
        )

        result = cli_runner.invoke(
            cli,
            ["url", "submit", "https://venue.com/event"],
            obj=cli_obj,
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["event_source_id"] == "src-001"
