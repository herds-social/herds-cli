"""
Unit tests for APIClient.

Tests session auth loading, request handling, and error parsing.
"""

from unittest.mock import MagicMock

import pytest
import requests

from herds_cli.api import APIClient


class TestLoadSessionAuth:
    def test_mobile_sets_bearer_header(self, mock_api_client, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "my-token-123"},
            "user_data": {"id": "u1", "email": "test@example.com"},
        })

        # Use a real Session so we can inspect headers
        mock_api_client.session = requests.Session()
        result = mock_api_client.load_session_auth("test@example.com")

        assert result is True
        assert mock_api_client.session.headers["Authorization"] == "Bearer my-token-123"

    def test_web_sets_cookies(self, mock_api_client, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "web",
            "cookies": {
                "access_token": "cookie-access",
                "refresh_token": "cookie-refresh",
            },
            "user_data": {"id": "u1", "email": "test@example.com"},
        })

        mock_api_client.session = requests.Session()
        result = mock_api_client.load_session_auth("test@example.com")

        assert result is True
        assert mock_api_client.session.cookies.get("access_token") == "cookie-access"
        assert mock_api_client.session.cookies.get("refresh_token") == "cookie-refresh"

    def test_missing_session_returns_false(self, mock_api_client):
        result = mock_api_client.load_session_auth("nobody@example.com")
        assert result is False

    def test_mobile_no_token_returns_false(self, mock_api_client, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {},
            "user_data": {"id": "u1", "email": "test@example.com"},
        })

        result = mock_api_client.load_session_auth("test@example.com")
        assert result is False

    def test_web_no_cookies_returns_false(self, mock_api_client, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "web",
            "cookies": {},
            "user_data": {"id": "u1", "email": "test@example.com"},
        })

        result = mock_api_client.load_session_auth("test@example.com")
        assert result is False

    def test_no_login_mode_returns_true(self, mock_session_manager):
        client = APIClient(
            base_url="http://localhost:8000",
            session_manager=mock_session_manager,
            no_login=True,
        )
        result = client.load_session_auth("anyone@example.com")
        assert result is True

    def test_sets_current_session_email_on_success(self, mock_api_client, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tk"},
            "user_data": {"id": "u1", "email": "test@example.com"},
        })
        mock_api_client.session = requests.Session()

        mock_api_client.load_session_auth("test@example.com")

        assert mock_api_client._current_session_email == "test@example.com"

    def test_does_not_set_current_session_email_when_session_missing(self, mock_api_client):
        mock_api_client.load_session_auth("nobody@example.com")
        assert mock_api_client._current_session_email is None

    def test_no_login_mode_does_not_set_current_session_email(self, mock_session_manager):
        client = APIClient(
            base_url="http://localhost:8000",
            session_manager=mock_session_manager,
            no_login=True,
        )
        client.load_session_auth("anyone@example.com")
        assert client._current_session_email is None

    def test_failed_load_after_successful_one_clears_email(
        self, mock_api_client, mock_session_manager
    ):
        """load_session_auth(A) success then load_session_auth(B) where B has
        no session must reset _current_session_email to None — otherwise the
        field would be out of sync with the cleared credentials, and Task 4's
        refresh-on-401 would silently target the wrong account."""
        mock_session_manager.save_session("alice@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tk-alice"},
            "user_data": {"id": "u1", "email": "alice@example.com"},
        })
        mock_api_client.session = requests.Session()

        # First load: alice succeeds
        assert mock_api_client.load_session_auth("alice@example.com") is True
        assert mock_api_client._current_session_email == "alice@example.com"

        # Second load: bob has no session → must reset, not leave alice
        assert mock_api_client.load_session_auth("bob@example.com") is False
        assert mock_api_client._current_session_email is None


class TestRefreshSessionAuth:
    def _save_mobile_session(self, sm, email="test@example.com", refresh="rfr-abc"):
        sm.save_session(email, {
            "client_type": "mobile",
            "tokens": {"access_token": "old-access", "refresh_token": refresh, "expires_in": 3600},
            "user_data": {"id": "u1", "email": email},
        })

    def _save_web_session(self, sm, email="test@example.com"):
        sm.save_session(email, {
            "client_type": "web",
            "cookies": {"access_token": "old-cookie", "refresh_token": "rfr-cookie"},
            "user_data": {"id": "u1", "email": email},
        })

    def test_mobile_success_persists_rotated_tokens(self, mock_api_client, mock_session_manager):
        self._save_mobile_session(mock_session_manager)
        mock_api_client.session = requests.Session()
        mock_api_client.load_session_auth("test@example.com")

        # Replace session.request with a mock that returns the new tokens
        mock_api_client.session = MagicMock()
        mock_api_client.session.headers = {"Authorization": "Bearer old-access"}
        mock_api_client.session.cookies = MagicMock()
        refreshed = MagicMock(status_code=200)
        refreshed.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
        mock_api_client.session.request.return_value = refreshed

        result = mock_api_client.refresh_session_auth("test@example.com")

        assert result is True
        # Persisted to disk
        on_disk = mock_session_manager.load_session("test@example.com")
        assert on_disk["tokens"]["access_token"] == "new-access"
        assert on_disk["tokens"]["refresh_token"] == "new-refresh"
        # Applied in-memory
        assert mock_api_client.session.headers["Authorization"] == "Bearer new-access"
        # Hit the right endpoint with the right body
        call = mock_api_client.session.request.call_args
        assert call.args[0] == "POST"
        assert call.args[1].endswith("/api/users/refresh-token")
        assert call.kwargs["json"] == {
            "refresh_token": "rfr-abc",
            "client_type": "mobile",
        }

    def test_web_success_persists_rotated_cookies(self, mock_api_client, mock_session_manager):
        self._save_web_session(mock_session_manager)
        mock_api_client.session = MagicMock()
        mock_api_client.session.headers = {}
        mock_api_client.session.cookies = MagicMock()
        refreshed = MagicMock(status_code=200)
        refreshed.json.return_value = {
            "access_token": "new-cookie-access",
            "refresh_token": "new-cookie-refresh",
            "expires_in": 3600,
        }
        mock_api_client.session.request.return_value = refreshed

        result = mock_api_client.refresh_session_auth("test@example.com")

        assert result is True
        on_disk = mock_session_manager.load_session("test@example.com")
        assert on_disk["cookies"]["access_token"] == "new-cookie-access"
        assert on_disk["cookies"]["refresh_token"] == "new-cookie-refresh"
        mock_api_client.session.cookies.set.assert_any_call("access_token", "new-cookie-access")
        mock_api_client.session.cookies.set.assert_any_call("refresh_token", "new-cookie-refresh")

    def test_no_session_returns_false(self, mock_api_client):
        assert mock_api_client.refresh_session_auth("nobody@example.com") is False

    def test_no_refresh_token_returns_false(self, mock_api_client, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "old"},  # no refresh_token
            "user_data": {"id": "u1", "email": "test@example.com"},
        })

        result = mock_api_client.refresh_session_auth("test@example.com")
        assert result is False
        # Should never have called the server
        mock_api_client.session.request.assert_not_called()

    def test_server_401_returns_false_without_persisting(self, mock_api_client, mock_session_manager):
        self._save_mobile_session(mock_session_manager)
        denied = MagicMock(status_code=401)
        denied.json.return_value = {"detail": "Invalid refresh token"}
        mock_api_client.session.request.return_value = denied

        result = mock_api_client.refresh_session_auth("test@example.com")

        assert result is False
        on_disk = mock_session_manager.load_session("test@example.com")
        # Tokens unchanged
        assert on_disk["tokens"]["access_token"] == "old-access"

    def test_no_login_mode_returns_false(self, mock_session_manager):
        client = APIClient(
            base_url="http://localhost:8000",
            session_manager=mock_session_manager,
            no_login=True,
        )
        assert client.refresh_session_auth("any@example.com") is False

    def test_missing_access_token_in_response_returns_false(self, mock_api_client, mock_session_manager):
        self._save_mobile_session(mock_session_manager)
        broken = MagicMock(status_code=200)
        broken.json.return_value = {"refresh_token": "x"}  # missing access_token
        mock_api_client.session.request.return_value = broken

        assert mock_api_client.refresh_session_auth("test@example.com") is False

    def test_network_error_returns_false(self, mock_api_client, mock_session_manager):
        self._save_mobile_session(mock_session_manager)
        mock_api_client.session.request.side_effect = requests.exceptions.ConnectionError("down")

        assert mock_api_client.refresh_session_auth("test@example.com") is False


class TestMakeRequest:
    def test_success_returns_response(self, mock_api_client):
        mock_response = MagicMock(status_code=200)
        mock_api_client.session.request.return_value = mock_response

        result = mock_api_client._make_request("GET", "http://localhost/api/test")

        assert result.status_code == 200
        mock_api_client.session.request.assert_called_once()

    def test_sets_default_timeout(self, mock_api_client):
        mock_api_client.session.request.return_value = MagicMock(status_code=200)

        mock_api_client._make_request("GET", "http://localhost/api/test")

        call_kwargs = mock_api_client.session.request.call_args
        assert call_kwargs.kwargs.get("timeout") == 5  # fixture sets timeout=5

    def test_custom_timeout_not_overridden(self, mock_api_client):
        mock_api_client.session.request.return_value = MagicMock(status_code=200)

        mock_api_client._make_request("GET", "http://localhost/api/test", timeout=99)

        call_kwargs = mock_api_client.session.request.call_args
        assert call_kwargs.kwargs.get("timeout") == 99

    def test_timeout_raises_exception(self, mock_api_client):
        mock_api_client.session.request.side_effect = requests.exceptions.Timeout()

        with pytest.raises(Exception, match="timed out"):
            mock_api_client._make_request("GET", "http://localhost/api/test")

    def test_connection_error_raises_exception(self, mock_api_client):
        mock_api_client.session.request.side_effect = (
            requests.exceptions.ConnectionError("refused")
        )

        with pytest.raises(Exception, match="Failed to connect"):
            mock_api_client._make_request("GET", "http://localhost/api/test")


class TestHandleApiError:
    def test_401_raises_auth_error(self, mock_api_client):
        resp = MagicMock(status_code=401, text="")
        resp.json.return_value = {"detail": "Invalid token"}

        with pytest.raises(Exception, match="Authentication failed"):
            mock_api_client.handle_api_error(resp)

    def test_401_no_login_mode(self, mock_session_manager):
        client = APIClient(
            base_url="http://localhost:8000",
            session_manager=mock_session_manager,
            no_login=True,
        )
        resp = MagicMock(status_code=401, text="")
        resp.json.return_value = {}

        with pytest.raises(Exception, match="requires login"):
            client.handle_api_error(resp)

    def test_403_raises_forbidden(self, mock_api_client):
        resp = MagicMock(status_code=403, text="")
        resp.json.return_value = {}

        with pytest.raises(Exception, match="forbidden"):
            mock_api_client.handle_api_error(resp)

    def test_409_raises_conflict(self, mock_api_client):
        resp = MagicMock(status_code=409, text="")
        resp.json.return_value = {}

        with pytest.raises(Exception, match="already exists"):
            mock_api_client.handle_api_error(resp)

    def test_422_raises_validation(self, mock_api_client):
        resp = MagicMock(status_code=422, text="")
        resp.json.return_value = {"detail": "field required"}

        with pytest.raises(Exception, match="Validation error"):
            mock_api_client.handle_api_error(resp)

    def test_429_raises_rate_limit(self, mock_api_client):
        resp = MagicMock(status_code=429, text="")
        resp.json.return_value = {}

        with pytest.raises(Exception, match="Rate limited"):
            mock_api_client.handle_api_error(resp)

    def test_unknown_status_raises_generic(self, mock_api_client):
        resp = MagicMock(status_code=418, text="I'm a teapot")
        resp.json.return_value = {"detail": "teapot"}

        with pytest.raises(Exception, match="418.*teapot"):
            mock_api_client.handle_api_error(resp)


class TestSanitizeData:
    def test_redacts_password(self, mock_api_client):
        data = {"email": "user@example.com", "password": "secret123"}
        result = mock_api_client._sanitize_data(data)
        assert result["email"] == "user@example.com"
        assert result["password"] == "[REDACTED]"

    def test_redacts_token_fields(self, mock_api_client):
        data = {"access_token": "abc", "refresh_token": "def"}
        result = mock_api_client._sanitize_data(data)
        assert result["access_token"] == "[REDACTED]"
        assert result["refresh_token"] == "[REDACTED]"

    def test_redacts_authorization_by_default(self, mock_api_client):
        data = {"Authorization": "Bearer xyz"}
        result = mock_api_client._sanitize_data(data)
        assert result["Authorization"] == "[REDACTED]"

    def test_skip_auth_redaction(self, mock_api_client):
        data = {"Authorization": "Bearer xyz"}
        result = mock_api_client._sanitize_data(data, skip_auth_redaction=True)
        assert result["Authorization"] == "Bearer xyz"

    def test_recursive_dict(self, mock_api_client):
        data = {"user": {"password": "secret", "name": "Alice"}}
        result = mock_api_client._sanitize_data(data)
        assert result["user"]["password"] == "[REDACTED]"
        assert result["user"]["name"] == "Alice"

    def test_recursive_list(self, mock_api_client):
        data = [{"token": "abc"}, {"name": "ok"}]
        result = mock_api_client._sanitize_data(data)
        assert result[0]["token"] == "[REDACTED]"
        assert result[1]["name"] == "ok"

    def test_falsy_input_passthrough(self, mock_api_client):
        assert mock_api_client._sanitize_data(None) is None
        assert mock_api_client._sanitize_data({}) == {}
        assert mock_api_client._sanitize_data([]) == []
