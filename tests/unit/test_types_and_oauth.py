"""
Unit tests for new TypedDicts, Protocols, and OAuthConfig dataclass.

Tests GoogleOAuthConfig Protocol satisfaction, OAuthConfig defaults,
and API method explicit parameter contracts.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from herds_cli.oauth import OAuthConfig
from herds_cli.types import GoogleOAuthConfig


# ---------------------------------------------------------------------------
# GoogleOAuthConfig Protocol
# ---------------------------------------------------------------------------


class TestGoogleOAuthConfigProtocol:
    def test_oauth_config_satisfies_protocol(self):
        config = OAuthConfig(
            google_client_id="cid",
            google_client_secret="csec",
        )
        assert isinstance(config, GoogleOAuthConfig)

    def test_plain_object_satisfies_protocol(self):
        """Any object with the right attributes satisfies the Protocol."""

        @dataclass
        class CustomConfig:
            google_client_id: str
            google_client_secret: str
            google_redirect_uri: str

        custom = CustomConfig("a", "b", "c")
        assert isinstance(custom, GoogleOAuthConfig)

    def test_missing_attribute_fails_protocol(self):
        """Object missing a required attribute does NOT satisfy the Protocol."""

        @dataclass
        class IncompleteConfig:
            google_client_id: str
            google_client_secret: str
            # Missing google_redirect_uri

        incomplete = IncompleteConfig("a", "b")
        assert not isinstance(incomplete, GoogleOAuthConfig)

    def test_dict_does_not_satisfy_protocol(self):
        """A plain dict should not satisfy the Protocol."""
        d = {
            "google_client_id": "a",
            "google_client_secret": "b",
            "google_redirect_uri": "c",
        }
        assert not isinstance(d, GoogleOAuthConfig)


# ---------------------------------------------------------------------------
# OAuthConfig dataclass
# ---------------------------------------------------------------------------


class TestOAuthConfig:
    def test_default_redirect_uri(self):
        config = OAuthConfig(
            google_client_id="cid",
            google_client_secret="csec",
        )
        assert config.google_redirect_uri == "http://localhost:8080/callback"

    def test_custom_redirect_uri(self):
        config = OAuthConfig(
            google_client_id="cid",
            google_client_secret="csec",
            google_redirect_uri="http://custom:9090/cb",
        )
        assert config.google_redirect_uri == "http://custom:9090/cb"

    def test_fields_stored(self):
        config = OAuthConfig(
            google_client_id="my-id",
            google_client_secret="my-secret",
        )
        assert config.google_client_id == "my-id"
        assert config.google_client_secret == "my-secret"


# ---------------------------------------------------------------------------
# API explicit keyword-only parameters
# ---------------------------------------------------------------------------


class TestAPIExplicitParams:
    """Verify the new keyword-only parameter signatures on API methods."""

    @pytest.fixture
    def api_client(self, mock_api_client):
        """Use the mock_api_client with a mocked successful response."""
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = []
        mock_api_client.session.request.return_value = mock_response
        # Bypass auth
        mock_api_client.load_session_auth = MagicMock(return_value=True)
        return mock_api_client

    def test_get_events_by_user_default_params(self, api_client):
        api_client.get_events_by_user("test@example.com", "user-1")

        call_args = api_client.session.request.call_args
        params = call_args.kwargs.get("params", {})
        assert params["user_id"] == "user-1"
        assert params["limit"] == 10
        assert params["offset"] == 0
        assert params["timezone"] == "UTC"
        assert params["date_filter"] == "upcoming"
        assert params["sort_by"] == "utc_start"
        assert params["sort_order"] == "asc"

    def test_get_events_by_user_custom_params(self, api_client):
        api_client.get_events_by_user(
            "test@example.com",
            "user-1",
            limit=25,
            offset=10,
            timezone="America/New_York",
            date_filter="past",
            sort_by="title",
            sort_order="desc",
        )

        call_args = api_client.session.request.call_args
        params = call_args.kwargs.get("params", {})
        assert params["limit"] == 25
        assert params["offset"] == 10
        assert params["timezone"] == "America/New_York"
        assert params["date_filter"] == "past"
        assert params["sort_by"] == "title"
        assert params["sort_order"] == "desc"

    def test_get_events_by_user_keyword_only(self, api_client):
        """Cannot pass query params as positional args."""
        with pytest.raises(TypeError):
            api_client.get_events_by_user("test@example.com", "user-1", 25)  # type: ignore

    def test_get_event_by_id_default_timezone(self, api_client):
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"event_id": "e1"}
        api_client.session.request.return_value = mock_response

        api_client.get_event_by_id("test@example.com", "e1")

        call_args = api_client.session.request.call_args
        params = call_args.kwargs.get("params", {})
        assert params == {"timezone": "UTC"}

    def test_get_event_by_id_custom_timezone(self, api_client):
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"event_id": "e1"}
        api_client.session.request.return_value = mock_response

        api_client.get_event_by_id("test@example.com", "e1", timezone="US/Pacific")

        call_args = api_client.session.request.call_args
        params = call_args.kwargs.get("params", {})
        assert params == {"timezone": "US/Pacific"}

    def test_get_events_by_image_id_without_user_id(self, api_client):
        api_client.get_events_by_image_id("test@example.com", "img-1")

        call_args = api_client.session.request.call_args
        params = call_args.kwargs.get("params", {})
        assert params == {"timezone": "UTC"}
        assert "user_id" not in params

    def test_get_events_by_image_id_with_user_id(self, api_client):
        api_client.get_events_by_image_id(
            "test@example.com", "img-1", user_id="user-1"
        )

        call_args = api_client.session.request.call_args
        params = call_args.kwargs.get("params", {})
        assert params["timezone"] == "UTC"
        assert params["user_id"] == "user-1"

    def test_get_events_by_image_id_keyword_only(self, api_client):
        """Cannot pass user_id or timezone as positional args."""
        with pytest.raises(TypeError):
            api_client.get_events_by_image_id(
                "test@example.com", "img-1", "user-1"  # type: ignore
            )

    def test_no_double_parameter_bug(self, api_client):
        """Params should NOT appear both URL-encoded in the path AND as params= kwarg."""
        api_client.get_events_by_user("test@example.com", "user-1", limit=5)

        call_args = api_client.session.request.call_args
        url = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("url", "")
        # The URL should not contain query parameters — they should only be in params=
        assert "?" not in url
        assert "limit=" not in url
