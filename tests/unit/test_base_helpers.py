"""
Unit tests for base.py helper functions and APIResponseHandler.

Tests session detection, user ID extraction, and error response handling.
These functions call sys.exit() on failure, so we catch SystemExit.
"""

from unittest.mock import MagicMock

import pytest

from herds_cli.core.base import (
    get_or_detect_session_email,
    validate_session_exists,
    extract_user_id_from_session,
    display_events_summary,
    APIResponseHandler,
)
from herds_cli.core.config import Config


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

    def test_no_sessions_exits(self, mock_session_manager):
        with pytest.raises(SystemExit):
            get_or_detect_session_email(mock_session_manager, None)

    def test_multiple_sessions_no_default_exits(self, mock_session_manager):
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

        with pytest.raises(SystemExit):
            get_or_detect_session_email(mock_session_manager, None)

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

    def test_default_account_not_found_exits(self, mock_session_manager):
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
        with pytest.raises(SystemExit):
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

        with pytest.raises(SystemExit):
            get_or_detect_session_email(
                mock_session_manager, None, show_client_type=True
            )

        captured = capsys.readouterr()
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

    def test_missing_session_exits(self, mock_session_manager):
        with pytest.raises(SystemExit):
            validate_session_exists(mock_session_manager, "nobody@example.com")


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

    def test_no_user_data_exits(self, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
        })

        with pytest.raises(SystemExit):
            extract_user_id_from_session(mock_session_manager, "test@example.com")

    def test_missing_session_exits(self, mock_session_manager):
        with pytest.raises(SystemExit):
            extract_user_id_from_session(mock_session_manager, "nobody@example.com")


class TestDisplayEventsSummary:
    def test_empty_list_warns(self, capsys):
        display_events_summary([])
        captured = capsys.readouterr()
        assert "No events found" in captured.out

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
        assert "Jazz Night" in captured.out
        assert "Austin, TX" in captured.out
        assert "Blue Note" in captured.out

    def test_truncates_at_five(self, capsys):
        events = [
            {"title": f"Event {i}", "date_info": {"raw": {"date": "2026-01-01"}}}
            for i in range(8)
        ]

        display_events_summary(events)
        captured = capsys.readouterr()
        assert "Event 0" in captured.out
        assert "Event 4" in captured.out
        assert "Event 5" not in captured.out
        assert "3 more events" in captured.out

    def test_handles_missing_fields(self, capsys):
        events = [{"title": "Minimal Event"}]
        display_events_summary(events)
        captured = capsys.readouterr()
        assert "Minimal Event" in captured.out


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
        assert "Missing required field" in captured.out

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
            assert expected in captured.out

    def test_unknown_status_code(self, capsys):
        resp = self._make_response(418, {})
        APIResponseHandler.handle_error_response(resp, "test")
        captured = capsys.readouterr()
        assert "418" in captured.out

    def test_no_json_falls_back_to_text(self, capsys):
        resp = self._make_response(502, json_data=None, text="Bad Gateway")
        APIResponseHandler.handle_error_response(resp, "test")
        captured = capsys.readouterr()
        assert "Bad Gateway" in captured.out

    def test_includes_operation_name(self, capsys):
        resp = self._make_response(404, {"detail": "not found"})
        APIResponseHandler.handle_error_response(resp, "GET /api/events/123")
        captured = capsys.readouterr()
        assert "GET /api/events/123" in captured.out
