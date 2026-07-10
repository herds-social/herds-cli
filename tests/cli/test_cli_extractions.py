"""
CLI tests for `herds extractions` commands.
"""

import json
from unittest.mock import MagicMock

import pytest

from herds_cli.cli import cli
from herds_cli.commands.cmd_extractions import parse_before_timestamp
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
    if status_code != 200:
        mock.text = json.dumps(json_data or {"detail": "error"})
    mock.headers = {"content-type": "application/json"}
    return mock


URL_EXTRACTION = {
    "extraction_id": "68a3f1c2deadbeefdeadbeef",
    "source_type": "url",
    "extraction_status": "completed",
    "event_count": 3,
    "url": {
        "submitted_url": "https://venue.com/calendar",
        "candidate_link_count": 2,
        "fetched_link_count": 2,
    },
    "created_at": "2026-07-07T09:12:00Z",
    "acknowledged_at": None,
}

IMAGE_EXTRACTION = {
    "extraction_id": "68a3e011deadbeefdeadbeef",
    "source_type": "image",
    "extraction_status": "processing",
    "event_count": 0,
    "image": {"image_name": "flyer.jpg", "image_media_type": "image/jpeg"},
    "created_at": "2026-07-07T09:02:00Z",
    "acknowledged_at": None,
}

SAMPLE_EVENT = {
    "title": "Block Party",
    "category_level_1": "Community",
    "date_info": {"raw": {"date": "2026-08-01"}, "local": {}},
    "location": {"city": "Austin", "state": "TX"},
    "contact": {"organizer": "Neighborhood Org"},
}


class TestExtractionsList:
    def test_renders_url_and_image_rows(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200,
            {
                "extractions": [URL_EXTRACTION, IMAGE_EXTRACTION],
                "total_count": 2,
                "has_more": False,
                "next_offset": None,
            },
        )

        result = cli_runner.invoke(cli, ["extractions", "list"], obj=cli_obj)

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert URL_EXTRACTION["extraction_id"] in out
        assert "https://venue.com/calendar" in out
        assert "flyer.jpg" in out
        assert "[unread]" in out

    def test_forwards_filters(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200,
            {"extractions": [], "total_count": 0, "has_more": False, "next_offset": None},
        )

        cli_runner.invoke(
            cli,
            [
                "extractions",
                "list",
                "--status",
                "completed",
                "--source-type",
                "url",
                "--unacked",
                "--limit",
                "10",
                "--offset",
                "5",
            ],
            obj=cli_obj,
        )

        params = cli_obj["api_client"].session.request.call_args.kwargs["params"]
        assert params["status"] == "completed"
        assert params["source_type"] == "url"
        assert params["acknowledged"] is False
        assert params["limit"] == 10
        assert params["offset"] == 5

    def test_acked_filter(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200,
            {"extractions": [], "total_count": 0, "has_more": False, "next_offset": None},
        )

        cli_runner.invoke(cli, ["extractions", "list", "--acked"], obj=cli_obj)

        params = cli_obj["api_client"].session.request.call_args.kwargs["params"]
        assert params["acknowledged"] is True

    def test_empty_list_warning(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200,
            {"extractions": [], "total_count": 0, "has_more": False, "next_offset": None},
        )

        result = cli_runner.invoke(cli, ["extractions", "list"], obj=cli_obj)

        assert result.exit_code == 0
        assert "No extractions found" in strip_ansi(result.output)

    def test_api_error_exits(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            404, {"detail": "Not found"}
        )

        result = cli_runner.invoke(cli, ["extractions", "list"], obj=cli_obj)

        assert result.exit_code == 1


class TestExtractionsGet:
    def test_summary_for_url_extraction(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, URL_EXTRACTION
        )

        result = cli_runner.invoke(
            cli, ["extractions", "get", URL_EXTRACTION["extraction_id"]], obj=cli_obj
        )

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert "Source type: url" in out
        assert "https://venue.com/calendar" in out

    def test_failed_shows_error_type(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "text"
        failed = dict(URL_EXTRACTION)
        failed["extraction_status"] = "failed"
        failed["extraction_error_type"] = "processing_error"
        cli_obj["api_client"].session.request.return_value = _make_response(200, failed)

        result = cli_runner.invoke(
            cli, ["extractions", "get", failed["extraction_id"]], obj=cli_obj
        )

        assert result.exit_code == 0
        assert "processing_error" in strip_ansi(result.output)

    def test_404_exits(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            404, {"detail": "Extraction x not found"}
        )

        result = cli_runner.invoke(
            cli, ["extractions", "get", "bad-id"], obj=cli_obj
        )

        assert result.exit_code == 1


class TestExtractionsEvents:
    def test_renders_events(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, [SAMPLE_EVENT]
        )

        result = cli_runner.invoke(
            cli, ["extractions", "events", "ext-1"], obj=cli_obj
        )

        assert result.exit_code == 0
        assert "Block Party" in strip_ansi(result.output)

    def test_renders_events_with_null_raw_date(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        event = {
            **SAMPLE_EVENT,
            "date_info": {
                "raw": {"date": None},
                "local": {
                    "date_start": "2026-08-01",
                    "time_start": "7:00 PM",
                },
            },
        }
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, [event]
        )

        result = cli_runner.invoke(
            cli, ["extractions", "events", "ext-1"], obj=cli_obj
        )

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert "Block Party" in out
        assert "2026-08-01 at 7:00 PM" in out

    def test_empty_warning_exit_zero(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(200, [])

        result = cli_runner.invoke(
            cli, ["extractions", "events", "ext-1"], obj=cli_obj
        )

        assert result.exit_code == 0
        assert "No events were extracted" in strip_ansi(result.output)

    def test_json_mode(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "json"
        cli_obj["format"] = "json"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, [SAMPLE_EVENT]
        )

        result = cli_runner.invoke(
            cli, ["extractions", "events", "ext-1"], obj=cli_obj
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload[0]["title"] == "Block Party"


class TestExtractionsAck:
    def test_ids_only_body(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, {"acknowledged_count": 2}
        )

        result = cli_runner.invoke(
            cli, ["extractions", "ack", "id1", "id2"], obj=cli_obj
        )

        assert result.exit_code == 0
        body = cli_obj["api_client"].session.request.call_args.kwargs["json"]
        assert body == {"extraction_ids": ["id1", "id2"]}
        assert "before" not in body
        assert "Acknowledged 2 extraction(s)" in strip_ansi(result.output)

    def test_all_empty_body(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, {"acknowledged_count": 5}
        )

        cli_runner.invoke(cli, ["extractions", "ack", "--all"], obj=cli_obj)

        assert cli_obj["api_client"].session.request.call_args.kwargs["json"] == {}

    def test_before_and_ids(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, {"acknowledged_count": 1}
        )

        cli_runner.invoke(
            cli,
            ["extractions", "ack", "id1", "--before", "2026-07-07T15:00:00Z"],
            obj=cli_obj,
        )

        body = cli_obj["api_client"].session.request.call_args.kwargs["json"]
        assert body["extraction_ids"] == ["id1"]
        assert body["before"] == "2026-07-07T15:00:00Z"

    def test_usage_error_no_args(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])

        result = cli_runner.invoke(cli, ["extractions", "ack"], obj=cli_obj)

        assert result.exit_code != 0

    def test_usage_error_all_with_ids(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])

        result = cli_runner.invoke(
            cli, ["extractions", "ack", "--all", "id1"], obj=cli_obj
        )

        assert result.exit_code != 0


class TestParseBeforeTimestamp:
    def test_plain_date_midnight_local_to_utc(self):
        # America/New_York is UTC-4 in July
        result = parse_before_timestamp("2026-07-07", "America/New_York")
        assert result == "2026-07-07T04:00:00Z"

    def test_iso_timestamp_with_z(self):
        result = parse_before_timestamp("2026-07-07T15:00:00Z", "America/New_York")
        assert result == "2026-07-07T15:00:00Z"

    def test_naive_iso_uses_local_tz(self):
        result = parse_before_timestamp("2026-07-07T15:00:00", "America/New_York")
        assert result == "2026-07-07T19:00:00Z"

    def test_invalid_raises_usage_error(self):
        with pytest.raises(Exception, match="Invalid --before"):
            parse_before_timestamp("not-a-date", "UTC")
