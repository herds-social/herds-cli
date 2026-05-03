"""
Unit tests for base.py helper functions and APIResponseHandler.

Tests session detection, user ID extraction, and error response handling.
These functions raise domain-specific exceptions on failure.
"""

from unittest.mock import MagicMock

import pytest

from herds_cli.core.base import (
    EventCommandBase,
    get_or_detect_session_email,
    validate_session_exists,
    extract_user_id_from_session,
    display_events_summary,
    APIResponseHandler,
)
from herds_cli.core.config import Config
from herds_cli.core.exceptions import (
    AmbiguousSessionError,
    NoSessionsError,
    SessionNotFoundError,
    UserIdNotFoundError,
)


class TestGetOrDetectSessionEmail:
    def test_explicit_email_returned_directly(self, mock_session_manager):
        result = get_or_detect_session_email(
            mock_session_manager, "explicit@example.com"
        )
        assert result == "explicit@example.com"

    def test_single_session_auto_detected(self, mock_session_manager):
        mock_session_manager.save_session("only@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "only@example.com"},
        })

        result = get_or_detect_session_email(mock_session_manager, None)
        assert result == "only@example.com"

    def test_no_sessions_raises(self, mock_session_manager):
        with pytest.raises(NoSessionsError):
            get_or_detect_session_email(mock_session_manager, None)

    def test_multiple_sessions_no_default_raises(self, mock_session_manager):
        mock_session_manager.save_session("a@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "a@example.com"},
        })
        mock_session_manager.save_session("b@example.com", {
            "client_type": "web",
            "cookies": {"access_token": "tok"},
            "user_data": {"id": "u2", "email": "b@example.com"},
        })

        with pytest.raises(AmbiguousSessionError) as exc_info:
            get_or_detect_session_email(mock_session_manager, None)
        assert "a@example.com" in exc_info.value.emails
        assert "b@example.com" in exc_info.value.emails

    def test_multiple_sessions_with_default_account(self, mock_session_manager):
        mock_session_manager.save_session("a@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "a@example.com"},
        })
        mock_session_manager.save_session("b@example.com", {
            "client_type": "web",
            "cookies": {"access_token": "tok"},
            "user_data": {"id": "u2", "email": "b@example.com"},
        })

        config = Config(default_account="b@example.com")
        result = get_or_detect_session_email(
            mock_session_manager, None, config=config
        )
        assert result == "b@example.com"

    def test_default_account_not_found_raises(self, mock_session_manager):
        mock_session_manager.save_session("a@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "a@example.com"},
        })
        mock_session_manager.save_session("b@example.com", {
            "client_type": "web",
            "cookies": {"access_token": "tok"},
            "user_data": {"id": "u2", "email": "b@example.com"},
        })

        config = Config(default_account="unknown@example.com")
        with pytest.raises(AmbiguousSessionError):
            get_or_detect_session_email(
                mock_session_manager, None, config=config
            )

    def test_multiple_sessions_shows_client_type(self, mock_session_manager, capsys):
        mock_session_manager.save_session("a@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "a@example.com"},
        })
        mock_session_manager.save_session("b@example.com", {
            "client_type": "web",
            "cookies": {"access_token": "tok"},
            "user_data": {"id": "u2", "email": "b@example.com"},
        })

        with pytest.raises(AmbiguousSessionError):
            get_or_detect_session_email(
                mock_session_manager, None, show_client_type=True
            )

        captured = capsys.readouterr()
        # The "mobile"/"web" client_type tags are emitted via click.echo,
        # which (unlike OutputFormatter.print_*) writes to stdout.
        assert "mobile" in captured.out
        assert "web" in captured.out


class TestValidateSessionExists:
    def test_valid_session_returns_data(self, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "test@example.com"},
        })

        result = validate_session_exists(mock_session_manager, "test@example.com")
        assert result["email"] == "test@example.com"

    def test_missing_session_raises(self, mock_session_manager):
        with pytest.raises(SessionNotFoundError) as exc_info:
            validate_session_exists(mock_session_manager, "nobody@example.com")
        assert exc_info.value.email == "nobody@example.com"


class TestExtractUserIdFromSession:
    def test_extracts_id_field(self, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "user-123", "email": "test@example.com"},
        })

        result = extract_user_id_from_session(mock_session_manager, "test@example.com")
        assert result == "user-123"

    def test_falls_back_to_user_id_field(self, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"user_id": "user-456", "email": "test@example.com"},
        })

        result = extract_user_id_from_session(mock_session_manager, "test@example.com")
        assert result == "user-456"

    def test_no_user_data_raises(self, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
        })

        with pytest.raises(UserIdNotFoundError):
            extract_user_id_from_session(mock_session_manager, "test@example.com")

    def test_missing_session_raises(self, mock_session_manager):
        with pytest.raises(UserIdNotFoundError):
            extract_user_id_from_session(mock_session_manager, "nobody@example.com")


class TestDisplayEventsSummary:
    def test_empty_list_warns(self, capsys):
        display_events_summary([])
        captured = capsys.readouterr()
        assert "No events found" in captured.err

    def test_shows_event_details(self, capsys):
        events = [{
            "title": "Jazz Night",
            "category_level_1": "Music",
            "date_info": {
                "raw": {"date": "2026-06-15"},
                "local": {"date_start": "2026-06-15", "time_start": "20:00"},
            },
            "location": {"city": "Austin", "state": "TX"},
            "contact": {"organizer": "Blue Note"},
        }]

        display_events_summary(events)
        captured = capsys.readouterr()
        assert "Jazz Night" in captured.err
        assert "Austin, TX" in captured.err
        assert "Blue Note" in captured.err

    def test_truncates_at_five(self, capsys):
        events = [
            {"title": f"Event {i}", "date_info": {"raw": {"date": "2026-01-01"}}}
            for i in range(8)
        ]

        display_events_summary(events)
        captured = capsys.readouterr()
        assert "Event 0" in captured.err
        assert "Event 4" in captured.err
        assert "Event 5" not in captured.err
        assert "3 more events" in captured.err

    def test_handles_missing_fields(self, capsys):
        events = [{"title": "Minimal Event"}]
        display_events_summary(events)
        captured = capsys.readouterr()
        assert "Minimal Event" in captured.err


class TestDisplayEventDetails:
    """Unit tests for EventCommandBase.display_event_details, focused on
    the calendar add status block. Calendar status is *data-driven*:
    if the server populated `user_data.{provider}_calendar_id` (success)
    or `user_data.calendar_add_error` (failure), we surface it — regardless
    of whether the CLI passed --add-to-calendar, since the server's per-user
    auto_add_to_calendar_enabled setting can trigger an add independently."""

    def _make_cmd(self):
        """Build an EventCommandBase with a minimal stub ctx.

        display_event_details only reads from `event_data`, never from `self`,
        so a stub ctx is sufficient — we just need __init__ to succeed."""
        ctx = MagicMock()
        config = MagicMock()
        config.output_format = "text"
        ctx.obj = {
            "config": config,
            "session_manager": MagicMock(),
            "api_client": MagicMock(),
        }
        return EventCommandBase(ctx)

    BASE_EVENT = {
        "title": "Summer Concert",
        "category_level_1": "Music",
        "date_info": {"raw": {"date": "2026-07-15"}, "local": {}},
        "location": {"city": "Austin", "state": "TX"},
        "contact": {"organizer": "Live Nation"},
    }

    def test_no_calendar_data_shows_not_added(self, capsys):
        """When user_data is absent or empty, an explicit 'Not added' line
        appears so the user isn't left wondering whether the add ran."""
        self._make_cmd().display_event_details(self.BASE_EVENT)
        out = capsys.readouterr().err
        assert "Summer Concert" in out  # sanity: rest of the display ran
        assert "Not added to a calendar" in out
        # The success/failure variants must NOT also appear in this state.
        assert "Added to" not in out
        assert "Calendar add failed" not in out

    def test_empty_user_data_shows_not_added(self, capsys):
        """An explicit empty user_data dict behaves the same as missing one."""
        event = {**self.BASE_EVENT, "user_data": {}}
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "Not added to a calendar" in out

    def test_google_add_success_with_target(self, capsys):
        """Google add: shows provider, target calendar, and event id."""
        event = {
            **self.BASE_EVENT,
            "user_data": {
                "google_calendar_id": "g-evt-123",
                "calendar_id": "primary",
            },
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "Added to Google calendar" in out
        assert "primary" in out
        assert "g-evt-123" in out

    def test_outlook_add_success_no_target(self, capsys):
        """Outlook add without a target calendar id: omit the parenthetical."""
        event = {
            **self.BASE_EVENT,
            "user_data": {"outlook_calendar_id": "o-evt-456"},
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "Added to Outlook calendar" in out
        assert "o-evt-456" in out
        assert "(calendar:" not in out  # no target → no parenthetical

    def test_apple_add_success(self, capsys):
        event = {
            **self.BASE_EVENT,
            "user_data": {"apple_calendar_id": "a-evt-789"},
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "Added to Apple calendar" in out
        assert "a-evt-789" in out

    def test_add_failure_shows_error_code(self, capsys):
        """When the auto-add was attempted but failed, surface the error code
        as a warning so the user knows *why* the event isn't in their calendar."""
        event = {
            **self.BASE_EVENT,
            "user_data": {"calendar_add_error": "NO_CALENDAR_CONNECTION"},
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "Calendar add failed" in out
        assert "NO_CALENDAR_CONNECTION" in out

    def test_success_takes_precedence_over_error(self, capsys):
        """Defensive: if both a success ID and an error are somehow set,
        prefer the success message — the event IS in the calendar."""
        event = {
            **self.BASE_EVENT,
            "user_data": {
                "google_calendar_id": "g-evt-1",
                "calendar_add_error": "STALE_ERROR",
            },
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "Added to Google calendar" in out
        assert "Calendar add failed" not in out


class TestAPIResponseHandler:
    def _make_response(self, status_code, json_data=None, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        if json_data is not None:
            resp.json.return_value = json_data
        else:
            resp.json.side_effect = ValueError("no json")
        return resp

    def test_detail_from_json(self, capsys):
        resp = self._make_response(400, {"detail": "Missing required field"})
        APIResponseHandler.handle_error_response(resp, "create event")
        captured = capsys.readouterr()
        assert "Missing required field" in captured.err

    def test_status_code_default_messages(self, capsys):
        for code, expected in [
            (401, "Authentication required"),
            (403, "Access forbidden"),
            (404, "Not found"),
            (429, "Rate limit"),
            (500, "Internal server error"),
        ]:
            resp = self._make_response(code, {})
            APIResponseHandler.handle_error_response(resp, "test")
            captured = capsys.readouterr()
            assert expected in captured.err

    def test_unknown_status_code(self, capsys):
        resp = self._make_response(418, {})
        APIResponseHandler.handle_error_response(resp, "test")
        captured = capsys.readouterr()
        assert "418" in captured.err

    def test_no_json_falls_back_to_text(self, capsys):
        resp = self._make_response(502, json_data=None, text="Bad Gateway")
        APIResponseHandler.handle_error_response(resp, "test")
        captured = capsys.readouterr()
        assert "Bad Gateway" in captured.err

    def test_includes_operation_name(self, capsys):
        resp = self._make_response(404, {"detail": "not found"})
        APIResponseHandler.handle_error_response(resp, "GET /api/events/123")
        captured = capsys.readouterr()
        assert "GET /api/events/123" in captured.err
