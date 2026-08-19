"""
CLI tests for `herds sources` commands.
"""

import json
from unittest.mock import MagicMock

import pytest

from herds_cli.cli import cli
from herds_cli.commands.cmd_sources import parse_before_timestamp
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


URL_SOURCE = {
    "source_id": "68a3f1c2deadbeefdeadbeef",
    "source_type": "url",
    "extraction_status": "completed",
    "event_count": 3,
    "can_reprocess": False,
    "share_url": None,
    "url": {
        "submitted_url": "https://venue.com/calendar/[red]",
        "candidate_link_count": 2,
        "fetched_link_count": 2,
    },
    "created_at": "2026-07-07T09:12:00Z",
    "acknowledged_at": None,
}

IMAGE_SOURCE = {
    "source_id": "68a3e011deadbeefdeadbeef",
    "source_type": "image",
    "extraction_status": "processing",
    "event_count": 0,
    "can_reprocess": False,
    "image": {"image_name": "flyer.jpg", "image_media_type": "image/jpeg"},
    "created_at": "2026-07-07T09:02:00Z",
    "acknowledged_at": None,
}

BOOKMARK_SOURCE = {
    "source_id": "68a3b00cdeadbeefdeadbeef",
    "source_type": "bookmark",
    "extraction_status": "completed",
    "event_count": 2,
    "can_reprocess": False,
    "bookmark_source_id": "68a3f1c2deadbeefdeadbeef",
    "share_url": None,
    "created_at": "2026-08-16T12:00:00Z",
    "acknowledged_at": None,
}

SAMPLE_EVENT = {
    "title": "Block Party",
    "category_level_1": "Community",
    "date_info": {"raw": {"date": "2026-08-01"}, "local": {}},
    "location": {"city": "Austin", "state": "TX"},
    "contact": {"organizer": "Neighborhood Org"},
}

SHARE_RESPONSE = {
    "share_token": "3fk9tok",
    "share_url": "https://app.herds.events/s/3fk9tok",
}


class TestExtractionsCommandGone:
    def test_extractions_is_unknown(self, cli_runner, cli_obj):
        result = cli_runner.invoke(cli, ["extractions", "list"], obj=cli_obj)

        assert result.exit_code != 0
        assert "No such command" in result.output
        assert "extractions" in result.output


class TestSourcesList:
    def test_renders_url_image_and_bookmark_rows(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200,
            {
                "sources": [URL_SOURCE, IMAGE_SOURCE, BOOKMARK_SOURCE],
                "total_count": 3,
                "has_more": False,
                "next_offset": None,
            },
        )

        result = cli_runner.invoke(cli, ["sources", "list"], obj=cli_obj)

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert URL_SOURCE["source_id"] in out
        assert "https://venue.com/calendar/[red]" in out
        assert "flyer.jpg" in out
        assert BOOKMARK_SOURCE["bookmark_source_id"] in out
        assert "bookmark" in out
        assert "[unread]" in out

    def test_forwards_filters(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200,
            {"sources": [], "total_count": 0, "has_more": False, "next_offset": None},
        )

        cli_runner.invoke(
            cli,
            [
                "sources",
                "list",
                "--status",
                "completed",
                "--source-type",
                "bookmark",
                "--unacked",
                "--limit",
                "10",
                "--offset",
                "5",
            ],
            obj=cli_obj,
        )

        params = cli_obj["api_client"].session.request.call_args.kwargs["params"]
        assert params["extraction_status"] == "completed"
        assert params["source_type"] == "bookmark"
        assert params["acknowledged"] is False
        assert params["limit"] == 10
        assert params["offset"] == 5

    def test_acked_filter(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200,
            {"sources": [], "total_count": 0, "has_more": False, "next_offset": None},
        )

        cli_runner.invoke(cli, ["sources", "list", "--acked"], obj=cli_obj)

        params = cli_obj["api_client"].session.request.call_args.kwargs["params"]
        assert params["acknowledged"] is True

    def test_empty_list_warning(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200,
            {"sources": [], "total_count": 0, "has_more": False, "next_offset": None},
        )

        result = cli_runner.invoke(cli, ["sources", "list"], obj=cli_obj)

        assert result.exit_code == 0
        assert "No sources found" in strip_ansi(result.output)

    def test_api_error_exits(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            404, {"detail": "Not found"}
        )

        result = cli_runner.invoke(cli, ["sources", "list"], obj=cli_obj)

        assert result.exit_code == 1


class TestSourcesGet:
    def test_summary_for_url_source(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, URL_SOURCE
        )

        result = cli_runner.invoke(
            cli, ["sources", "get", URL_SOURCE["source_id"]], obj=cli_obj
        )

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert "Source type: url" in out
        assert "https://venue.com/calendar" in out
        assert "Can reprocess: no" in out

    def test_prints_share_url_when_live(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "text"
        live = dict(URL_SOURCE)
        live["share_url"] = "https://app.herds.events/s/3fk9tok"
        cli_obj["api_client"].session.request.return_value = _make_response(200, live)

        result = cli_runner.invoke(
            cli, ["sources", "get", live["source_id"]], obj=cli_obj
        )

        assert result.exit_code == 0
        assert "https://app.herds.events/s/3fk9tok" in strip_ansi(result.output)

    def test_failed_shows_error_type(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "text"
        failed = dict(URL_SOURCE)
        failed["extraction_status"] = "failed"
        failed["extraction_error_type"] = "timed_out"
        failed["can_reprocess"] = True
        cli_obj["api_client"].session.request.return_value = _make_response(200, failed)

        result = cli_runner.invoke(
            cli, ["sources", "get", failed["source_id"]], obj=cli_obj
        )

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert "timed_out" in out
        assert "Can reprocess: yes" in out

    def test_404_exits(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            404, {"detail": "Source x not found"}
        )

        result = cli_runner.invoke(cli, ["sources", "get", "bad-id"], obj=cli_obj)

        assert result.exit_code == 1


class TestSourcesEvents:
    def test_renders_events(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, [SAMPLE_EVENT]
        )

        result = cli_runner.invoke(cli, ["sources", "events", "src-1"], obj=cli_obj)

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

        result = cli_runner.invoke(cli, ["sources", "events", "src-1"], obj=cli_obj)

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert "Block Party" in out
        assert "2026-08-01 at 7:00 PM" in out

    def test_empty_warning_exit_zero(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(200, [])

        result = cli_runner.invoke(cli, ["sources", "events", "src-1"], obj=cli_obj)

        assert result.exit_code == 0
        assert "No events were extracted" in strip_ansi(result.output)

    def test_json_mode(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "json"
        cli_obj["format"] = "json"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, [SAMPLE_EVENT]
        )

        result = cli_runner.invoke(cli, ["sources", "events", "src-1"], obj=cli_obj)

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload[0]["title"] == "Block Party"


class TestSourcesAck:
    def test_ids_only_body(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, {"acknowledged_count": 2}
        )

        result = cli_runner.invoke(cli, ["sources", "ack", "id1", "id2"], obj=cli_obj)

        assert result.exit_code == 0
        body = cli_obj["api_client"].session.request.call_args.kwargs["json"]
        assert body == {"source_ids": ["id1", "id2"]}
        assert "before" not in body
        assert "Acknowledged 2 source(s)" in strip_ansi(result.output)

    def test_all_empty_body(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, {"acknowledged_count": 5}
        )

        cli_runner.invoke(cli, ["sources", "ack", "--all"], obj=cli_obj)

        assert cli_obj["api_client"].session.request.call_args.kwargs["json"] == {}

    def test_before_and_ids(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            200, {"acknowledged_count": 1}
        )

        cli_runner.invoke(
            cli,
            ["sources", "ack", "id1", "--before", "2026-07-07T15:00:00Z"],
            obj=cli_obj,
        )

        body = cli_obj["api_client"].session.request.call_args.kwargs["json"]
        assert body["source_ids"] == ["id1"]
        assert body["before"] == "2026-07-07T15:00:00Z"

    def test_usage_error_no_args(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])

        result = cli_runner.invoke(cli, ["sources", "ack"], obj=cli_obj)

        assert result.exit_code != 0

    def test_usage_error_all_with_ids(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])

        result = cli_runner.invoke(
            cli, ["sources", "ack", "--all", "id1"], obj=cli_obj
        )

        assert result.exit_code != 0


class TestParseBeforeTimestamp:
    def test_plain_date_midnight_local_to_utc(self):
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


class TestSourcesReprocess:
    def test_posts_and_confirms(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            202, {"source_id": "src-1", "extraction_status": "processing"}
        )

        result = cli_runner.invoke(cli, ["sources", "reprocess", "src-1"], obj=cli_obj)

        assert result.exit_code == 0
        call = cli_obj["api_client"].session.request.call_args
        assert call.args == (
            "POST",
            "http://localhost:8000/api/sources/src-1/reprocess",
        )
        assert "Reprocessing source src-1" in strip_ansi(result.output)


class TestSourcesShare:
    def test_text_mode_prints_bare_url_on_stdout(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            201, SHARE_RESPONSE
        )

        result = cli_runner.invoke(cli, ["sources", "share", "src-1"], obj=cli_obj)

        assert result.exit_code == 0
        assert strip_ansi(result.stdout) == "https://app.herds.events/s/3fk9tok\n"
        assert "Share link: https://app.herds.events/s/3fk9tok" in strip_ansi(
            result.stderr
        )
        call = cli_obj["api_client"].session.request.call_args
        assert call.args == (
            "POST",
            "http://localhost:8000/api/sources/src-1/share",
        )

    def test_json_mode_emits_server_response_verbatim(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            201, SHARE_RESPONSE
        )

        result = cli_runner.invoke(cli, ["sources", "share", "src-1"], obj=cli_obj)

        assert result.exit_code == 0
        assert json.loads(result.stdout) == SHARE_RESPONSE
        assert "Share link:" in strip_ansi(result.stderr)

    def test_piped_default_auto_resolves_to_text(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["_raw_format"] = "auto"
        cli_obj["api_client"].session.request.return_value = _make_response(
            201, SHARE_RESPONSE
        )

        result = cli_runner.invoke(cli, ["sources", "share", "src-1"], obj=cli_obj)

        assert result.exit_code == 0
        assert strip_ansi(result.stdout) == "https://app.herds.events/s/3fk9tok\n"

    def test_web_url_rebuilds_local_url_in_text_mode(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(
            201, SHARE_RESPONSE
        )

        result = cli_runner.invoke(
            cli,
            [
                "sources",
                "share",
                "src-1",
                "--web-url",
                "http://localhost:5173/",
            ],
            obj=cli_obj,
        )

        assert result.exit_code == 0
        assert strip_ansi(result.stdout) == "http://localhost:5173/s/3fk9tok\n"
        err = strip_ansi(result.stderr)
        assert "Share link: https://app.herds.events/s/3fk9tok" in err
        assert "Local share link: http://localhost:5173/s/3fk9tok" in err

    def test_web_url_adds_local_share_url_in_json_mode(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            201, SHARE_RESPONSE
        )

        result = cli_runner.invoke(
            cli,
            [
                "sources",
                "share",
                "src-1",
                "--web-url",
                "http://localhost:5173",
            ],
            obj=cli_obj,
        )

        assert json.loads(result.stdout) == {
            **SHARE_RESPONSE,
            "local_share_url": "http://localhost:5173/s/3fk9tok",
        }

    def test_404_exits_nonzero_with_friendly_message(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            404, {"detail": "Source not found"}
        )

        result = cli_runner.invoke(cli, ["sources", "share", "src-1"], obj=cli_obj)

        assert result.exit_code != 0
        assert "Source not found (or not yours): src-1" in strip_ansi(result.stderr)


class TestSourcesUnshare:
    def test_text_mode_confirms_and_keeps_stdout_empty(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        cli_obj["api_client"].session.request.return_value = _make_response(204)

        result = cli_runner.invoke(cli, ["sources", "unshare", "src-1"], obj=cli_obj)

        assert result.exit_code == 0
        assert strip_ansi(result.stdout) == ""
        assert "Share link revoked." in strip_ansi(result.stderr)
        call = cli_obj["api_client"].session.request.call_args
        assert call.args == (
            "DELETE",
            "http://localhost:8000/api/sources/src-1/share",
        )

    def test_json_mode_emits_revoked_payload(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(204)

        result = cli_runner.invoke(cli, ["sources", "unshare", "src-1"], obj=cli_obj)

        assert result.exit_code == 0
        assert json.loads(result.stdout) == {
            "source_id": "src-1",
            "revoked": True,
        }

    def test_422_bookmark_is_not_eligible(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            422, {"detail": "Source src-1 is not eligible"}
        )

        result = cli_runner.invoke(cli, ["sources", "unshare", "src-1"], obj=cli_obj)

        assert result.exit_code != 0
        assert "not eligible" in strip_ansi(result.stderr)

    def test_404_exits_nonzero_with_friendly_message(self, cli_runner, cli_obj):
        _create_session(cli_obj["session_manager"])
        cli_obj["api_client"].session.request.return_value = _make_response(
            404, {"detail": "Source not found"}
        )

        result = cli_runner.invoke(cli, ["sources", "unshare", "src-1"], obj=cli_obj)

        assert result.exit_code != 0
        assert "Source not found (or not yours): src-1" in strip_ansi(result.stderr)
