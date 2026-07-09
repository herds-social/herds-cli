"""
Unit tests for URL submission and extractions APIClient methods.
"""

from unittest.mock import MagicMock

import pytest

from herds_cli.api import APIClient


def _save_session(session_manager, email="test@example.com"):
    session_manager.save_session(email, {
        "client_type": "mobile",
        "tokens": {"access_token": "tok"},
        "user_data": {"id": "u1", "email": email},
    })


def _ok_response(json_data):
    resp = MagicMock(status_code=200)
    resp.json.return_value = json_data
    return resp


class TestSubmitUrl:
    def test_posts_json_body(self, mock_api_client, mock_session_manager):
        _save_session(mock_session_manager)
        mock_api_client.session.request.return_value = _ok_response({
            "status": "success",
            "message": "URL accepted for processing",
            "event_source_id": "src-1",
        })

        result = mock_api_client.submit_url(
            "test@example.com",
            "https://example.com/event",
            "America/New_York",
            mock_mode=True,
            add_to_calendar=True,
        )

        assert result["event_source_id"] == "src-1"
        call = mock_api_client.session.request.call_args
        assert call.args[0] == "POST"
        assert call.args[1] == "http://localhost:8000/api/url/submit"
        assert call.kwargs["json"] == {
            "url": "https://example.com/event",
            "timezone": "America/New_York",
            "mock_mode": True,
            "add_to_calendar": True,
        }

    def test_omits_add_to_calendar_when_none(self, mock_api_client, mock_session_manager):
        _save_session(mock_session_manager)
        mock_api_client.session.request.return_value = _ok_response({
            "status": "success",
            "message": "URL accepted for processing",
            "event_source_id": "src-1",
        })

        mock_api_client.submit_url(
            "test@example.com", "https://example.com", "UTC"
        )

        body = mock_api_client.session.request.call_args.kwargs["json"]
        assert "add_to_calendar" not in body


class TestGetExtraction:
    def test_gets_by_id(self, mock_api_client, mock_session_manager):
        _save_session(mock_session_manager)
        mock_api_client.session.request.return_value = _ok_response({
            "extraction_id": "ext-1",
            "extraction_status": "completed",
        })

        result = mock_api_client.get_extraction("test@example.com", "ext-1")

        assert result["extraction_id"] == "ext-1"
        call = mock_api_client.session.request.call_args
        assert call.args == ("GET", "http://localhost:8000/api/extractions/ext-1")


class TestGetExtractionEvents:
    def test_passes_timezone_param(self, mock_api_client, mock_session_manager):
        _save_session(mock_session_manager)
        mock_api_client.session.request.return_value = _ok_response([])

        mock_api_client.get_extraction_events(
            "test@example.com", "ext-1", timezone="America/New_York"
        )

        call = mock_api_client.session.request.call_args
        assert call.kwargs["params"] == {"timezone": "America/New_York"}


class TestListExtractions:
    def test_omits_none_filters(self, mock_api_client, mock_session_manager):
        _save_session(mock_session_manager)
        mock_api_client.session.request.return_value = _ok_response({
            "extractions": [],
            "total_count": 0,
            "has_more": False,
            "next_offset": None,
        })

        mock_api_client.list_extractions("test@example.com")

        params = mock_api_client.session.request.call_args.kwargs["params"]
        assert params == {"limit": 50, "offset": 0}
        assert "status" not in params
        assert "source_type" not in params
        assert "acknowledged" not in params

    def test_forwards_filters(self, mock_api_client, mock_session_manager):
        _save_session(mock_session_manager)
        mock_api_client.session.request.return_value = _ok_response({
            "extractions": [],
            "total_count": 0,
            "has_more": False,
            "next_offset": None,
        })

        mock_api_client.list_extractions(
            "test@example.com",
            status="completed",
            source_type="url",
            acknowledged=False,
            limit=10,
            offset=5,
        )

        params = mock_api_client.session.request.call_args.kwargs["params"]
        assert params == {
            "limit": 10,
            "offset": 5,
            "status": "completed",
            "source_type": "url",
            "acknowledged": False,
        }


class TestAcknowledgeExtractions:
    def test_ids_only_body(self, mock_api_client, mock_session_manager):
        _save_session(mock_session_manager)
        mock_api_client.session.request.return_value = _ok_response({
            "acknowledged_count": 2,
        })

        mock_api_client.acknowledge_extractions(
            "test@example.com", extraction_ids=["a", "b"]
        )

        assert mock_api_client.session.request.call_args.kwargs["json"] == {
            "extraction_ids": ["a", "b"],
        }

    def test_empty_body_for_ack_all(self, mock_api_client, mock_session_manager):
        _save_session(mock_session_manager)
        mock_api_client.session.request.return_value = _ok_response({
            "acknowledged_count": 5,
        })

        mock_api_client.acknowledge_extractions("test@example.com")

        assert mock_api_client.session.request.call_args.kwargs["json"] == {}

    def test_before_and_ids(self, mock_api_client, mock_session_manager):
        _save_session(mock_session_manager)
        mock_api_client.session.request.return_value = _ok_response({
            "acknowledged_count": 1,
        })

        mock_api_client.acknowledge_extractions(
            "test@example.com",
            before="2026-07-07T15:00:00Z",
            extraction_ids=["x"],
        )

        assert mock_api_client.session.request.call_args.kwargs["json"] == {
            "before": "2026-07-07T15:00:00Z",
            "extraction_ids": ["x"],
        }

    def test_no_session_raises(self, mock_api_client):
        with pytest.raises(Exception, match="No valid session"):
            mock_api_client.submit_url("nobody@example.com", "https://x.com", "UTC")
