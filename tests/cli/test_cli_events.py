"""
Event command tests via Click's CliRunner.

Tests events list, get, and delete by injecting mock dependencies
through the _initialized guard.
"""

from unittest.mock import MagicMock

from tests.cli.conftest import strip_ansi
from herds_cli.cli import cli


def _create_session(session_manager, email="test@example.com"):
    """Helper: create a mobile session in the tmp_path-backed manager."""
    session_manager.save_session(email, {
        "client_type": "mobile",
        "tokens": {"access_token": "fake-token"},
        "user_data": {"id": "user-123", "email": email},
    })


def _mock_json_response(api_client, data, status_code=200):
    """Helper: configure the mock session to return a JSON response."""
    mock_response = MagicMock(status_code=status_code)
    mock_response.json.return_value = data
    mock_response.text = ""
    mock_response.headers = {"content-type": "application/json"}
    mock_response.content = b"{}"
    api_client.session.request.return_value = mock_response
    return mock_response


SAMPLE_EVENT = {
    "id": "evt-001",
    "title": "Summer Concert",
    "category_level_1": "Music",
    "date_info": {
        "raw": {"date": "2026-07-15"},
        "local": {
            "date_start": "2026-07-15",
            "date_end": "2026-07-15",
            "time_start": "19:00",
            "time_end": "22:00",
        },
    },
    "location": {"city": "Austin", "state": "TX"},
    "contact": {"organizer": "Live Nation"},
}


class TestEventsList:
    def test_list_events_success(self, cli_runner, cli_obj, mock_session_manager):
        """List events returns results and shows success."""
        _create_session(mock_session_manager)
        _mock_json_response(cli_obj["api_client"], [SAMPLE_EVENT])

        result = cli_runner.invoke(cli, ["events", "list"], obj=cli_obj)

        assert result.exit_code == 0
        assert "Successfully retrieved 1 events" in strip_ansi(result.output)
        assert "Summer Concert" in strip_ansi(result.output)

    def test_list_events_no_session(self, cli_runner, cli_obj):
        """List events with no session exits with error."""
        result = cli_runner.invoke(cli, ["events", "list"], obj=cli_obj)

        assert result.exit_code != 0
        assert "No active sessions" in strip_ansi(result.output)

    def test_list_events_empty(self, cli_runner, cli_obj, mock_session_manager):
        """List events with empty response shows no events."""
        _create_session(mock_session_manager)
        _mock_json_response(cli_obj["api_client"], [])

        result = cli_runner.invoke(cli, ["events", "list"], obj=cli_obj)

        assert result.exit_code == 0
        assert "Successfully retrieved 0 events" in strip_ansi(result.output)

    def test_list_events_summary_flag(self, cli_runner, cli_obj, mock_session_manager):
        """--summary shows concise output without JSON blob."""
        _create_session(mock_session_manager)
        _mock_json_response(cli_obj["api_client"], [SAMPLE_EVENT])

        result = cli_runner.invoke(
            cli, ["events", "list", "--summary"], obj=cli_obj
        )

        assert result.exit_code == 0
        assert "Summer Concert" in strip_ansi(result.output)
        assert "2026-07-15" in strip_ansi(result.output)

    def test_list_events_summary_renders_parent_title(self, cli_runner, cli_obj, mock_session_manager):
        """--summary surfaces parent_title as an indented sub-line below the event row."""
        _create_session(mock_session_manager)
        multi_event = {**SAMPLE_EVENT, "parent_title": "Christmas Eve at Weddington"}
        _mock_json_response(cli_obj["api_client"], [multi_event])

        result = cli_runner.invoke(
            cli, ["events", "list", "--summary"], obj=cli_obj
        )

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert "Summer Concert" in out
        assert "Parent: Christmas Eve at Weddington" in out

    def test_get_event_shows_parent_title(self, cli_runner, cli_obj, mock_session_manager):
        """`events get` prints a 'Parent:' row above 'Title:' when parent_title is set."""
        _create_session(mock_session_manager)
        multi_event = {**SAMPLE_EVENT, "parent_title": "Christmas Eve at Weddington"}
        _mock_json_response(cli_obj["api_client"], multi_event)

        result = cli_runner.invoke(cli, ["events", "get", "evt-001"], obj=cli_obj)

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert "Parent: Christmas Eve at Weddington" in out
        assert "Title: Summer Concert" in out
        assert out.index("Parent: Christmas Eve") < out.index("Title: Summer Concert")


class TestEventsGet:
    def test_get_event_renders_images_v3_block(self, cli_runner, cli_obj, mock_session_manager):
        """`events get` surfaces per-variant dimensions from images_v3."""
        _create_session(mock_session_manager)
        event = {
            **SAMPLE_EVENT,
            "images_v3": [
                {
                    "image_id": "68a1",
                    "original": {"url": None, "width": 4284, "height": 5712, "size_mb": 4.2},
                    "resized": {"url": "https://x/r", "width": 1500, "height": 2000, "size_mb": 0.9},
                    "thumbnail": None,
                }
            ],
        }
        _mock_json_response(cli_obj["api_client"], event)

        result = cli_runner.invoke(cli, ["events", "get", "evt-001"], obj=cli_obj)

        assert result.exit_code == 0
        out = strip_ansi(result.output)
        assert "Images (1):" in out
        assert "original 4284x5712 (4.2MB)" in out
        assert "resized 1500x2000 (0.9MB)" in out

    def test_get_event_success(self, cli_runner, cli_obj, mock_session_manager):
        """Get event by ID shows event details."""
        _create_session(mock_session_manager)
        _mock_json_response(cli_obj["api_client"], SAMPLE_EVENT)

        result = cli_runner.invoke(cli, ["events", "get", "evt-001"], obj=cli_obj)

        assert result.exit_code == 0
        assert "Summer Concert" in strip_ansi(result.output)


class TestEventsDelete:
    def test_delete_event_success(self, cli_runner, cli_obj, mock_session_manager):
        """Delete with --yes skips confirmation and succeeds."""
        _create_session(mock_session_manager)
        _mock_json_response(cli_obj["api_client"], {
            "message": "Event deleted successfully",
            "event_id": "evt-001",
        }, status_code=204)

        result = cli_runner.invoke(
            cli, ["events", "delete", "evt-001", "--yes"], obj=cli_obj
        )

        assert result.exit_code == 0
        assert "Successfully deleted" in strip_ansi(result.output)

    def test_delete_event_no_session(self, cli_runner, cli_obj):
        """Delete with no session exits with error."""
        result = cli_runner.invoke(
            cli, ["events", "delete", "evt-001", "--yes"], obj=cli_obj
        )

        assert result.exit_code != 0
        assert "No active sessions" in strip_ansi(result.output)
