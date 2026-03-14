"""
User command tests via Click's CliRunner.

Tests login success/failure, session listing, and logout
by injecting mock dependencies through the _initialized guard.
"""

from unittest.mock import MagicMock

from tests.cli.conftest import strip_ansi
from herds_cli.cli import cli


class TestUserLogin:
    def test_login_success(self, cli_runner, cli_obj, mock_session_manager):
        """Successful login saves session and shows success message."""
        # Mock the HTTP response for login
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {
            "access_token": "fake-access-token",
            "refresh_token": "fake-refresh-token",
            "expires_in": 3600,
            "user": {"id": "user-123", "email": "test@example.com"},
        }
        mock_response.cookies = {}
        cli_obj["api_client"].session.request.return_value = mock_response

        result = cli_runner.invoke(
            cli,
            ["user", "login", "--email", "test@example.com", "--password", "secret123"],
            obj=cli_obj,
        )

        assert result.exit_code == 0
        assert "Login successful" in strip_ansi(result.output)

        # Verify session was saved
        loaded = mock_session_manager.load_session("test@example.com")
        assert loaded is not None
        assert loaded["client_type"] == "mobile"

    def test_login_failure_401(self, cli_runner, cli_obj):
        """Failed login (401) shows error and exits non-zero."""
        mock_response = MagicMock(status_code=401)
        mock_response.json.return_value = {"detail": "Invalid credentials"}
        mock_response.text = "Invalid credentials"
        cli_obj["api_client"].session.request.return_value = mock_response

        result = cli_runner.invoke(
            cli,
            ["user", "login", "--email", "bad@example.com", "--password", "wrong"],
            obj=cli_obj,
        )

        assert result.exit_code != 0
        assert "Login failed" in strip_ansi(result.output)


class TestUserSessions:
    def test_sessions_empty(self, cli_runner, cli_obj):
        """With no sessions, shows a warning."""
        result = cli_runner.invoke(cli, ["user", "sessions"], obj=cli_obj)

        assert result.exit_code == 0
        assert "No active sessions" in strip_ansi(result.output)

    def test_sessions_populated(self, cli_runner, cli_obj, mock_session_manager):
        """With saved sessions, lists them."""
        mock_session_manager.save_session("alice@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "alice@example.com"},
        })

        result = cli_runner.invoke(cli, ["user", "sessions"], obj=cli_obj)

        assert result.exit_code == 0
        assert "alice@example.com" in strip_ansi(result.output)


class TestUserLogout:
    def test_logout_single_session(self, cli_runner, cli_obj, mock_session_manager):
        """Logout auto-detects the single session and deletes it."""
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "test@example.com"},
        })

        result = cli_runner.invoke(cli, ["user", "logout"], obj=cli_obj)

        assert result.exit_code == 0
        assert "Logged out" in strip_ansi(result.output)
        assert mock_session_manager.load_session("test@example.com") is None

    def test_logout_no_sessions(self, cli_runner, cli_obj):
        """Logout with no sessions shows a warning."""
        result = cli_runner.invoke(cli, ["user", "logout"], obj=cli_obj)

        assert result.exit_code == 0
        assert "No active sessions" in strip_ansi(result.output)
