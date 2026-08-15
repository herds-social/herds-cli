"""
Ping command tests via Click's CliRunner.

GET /ping is authenticated: identity fields (supabase_ref, mongo_db,
git_sha) are only populated for a logged-in caller. The CLI loads a
session before it hits the endpoint, the same as every other command.

Exit-code policy under test: HTTP-status only. Any 200 response from
the server exits 0, regardless of body content (DB-failure messages
and null identity fields are still rendered for the user, but don't
change the exit code).
"""

import json
from unittest.mock import MagicMock

from tests.cli.conftest import strip_ansi
from herds_cli.cli import cli


def _mock_ping_response(api_client, payload):
    """Configure the mocked HTTP session to return ``payload`` on the next request."""
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = payload
    mock_response.text = ""
    mock_response.headers = {"content-type": "application/json"}
    mock_response.content = b"{}"
    api_client.session.request.return_value = mock_response
    return mock_response


HEALTHY_PAYLOAD = {
    "message": "Ping!",
    "env": "production",
    "supabase_ref": "abcxyz",
    "mongo_db": "herds",
    "git_sha": "87f1870",
}

DB_FAILURE_PAYLOAD = {
    "message": "Failed to ping your deployment. Please check your MongoDB connection.",
    "env": "production",
    "supabase_ref": "abcxyz",
    "mongo_db": None,
    "git_sha": "87f1870",
}


def _create_session(session_manager, email="test@example.com"):
    """Persist a mobile session so setup_session / load_session_auth pass."""
    session_manager.save_session(email, {
        "client_type": "mobile",
        "tokens": {"access_token": "fake-token"},
        "user_data": {"id": "user-123", "email": email},
    })


class TestPing:
    def test_ping_no_session_exits_with_error(self, cli_runner, cli_obj):
        """Ping with no session exits with an error and does not hit the API.

        The cli_obj fixture's SessionManager points at an empty tmp dir.
        """
        result = cli_runner.invoke(cli, ["ping"], obj=cli_obj)

        assert result.exit_code != 0
        assert "No active sessions" in strip_ansi(result.output)
        cli_obj["api_client"].session.request.assert_not_called()

    def test_healthy_ping_with_session(self, cli_runner, cli_obj, mock_session_manager):
        """A healthy /ping response exits 0 and prints the identity fields."""
        _create_session(mock_session_manager)
        _mock_ping_response(cli_obj["api_client"], HEALTHY_PAYLOAD)

        result = cli_runner.invoke(cli, ["ping"], obj=cli_obj)

        assert result.exit_code == 0, result.output
        parsed = json.loads(strip_ansi(result.stdout))
        assert parsed["message"] == "Ping!"
        assert parsed["env"] == "production"
        assert parsed["mongo_db"] == "herds"
        assert parsed["git_sha"] == "87f1870"

    def test_db_failure_still_exits_zero_and_renders_body(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """A DB-failure body (mongo_db null, "Failed to ping" message) still
        exits 0. The CLI reports reachability only. The body is rendered
        verbatim so the operator can see what's wrong.
        """
        _create_session(mock_session_manager)
        _mock_ping_response(cli_obj["api_client"], DB_FAILURE_PAYLOAD)

        result = cli_runner.invoke(cli, ["ping"], obj=cli_obj)

        assert result.exit_code == 0, result.output
        parsed = json.loads(strip_ansi(result.stdout))
        assert parsed["mongo_db"] is None
        assert parsed["env"] == "production"
        assert parsed["message"].startswith("Failed to ping")

    def test_text_format_substitutes_em_dash_for_nulls(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """Text mode renders each field via print_info, substituting an
        em-dash for ``None`` (literal ``str(None)`` would read as the word
        'None'). Output goes to stderr; CliRunner captures it into
        ``result.output`` because the default runner mixes the streams.

        The cli() group short-circuits when ``_initialized`` is set, so
        CLI flags like ``--format`` never reach the config in tests; we
        mutate the config directly to exercise text mode.
        """
        cli_obj["config"].output_format = "text"
        _create_session(mock_session_manager)
        _mock_ping_response(cli_obj["api_client"], DB_FAILURE_PAYLOAD)

        result = cli_runner.invoke(cli, ["ping"], obj=cli_obj)

        assert result.exit_code == 0, result.output
        assert "—" in strip_ansi(result.output)
        assert "production" in strip_ansi(result.output)

    def test_invalid_json_body_emits_friendly_error(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """A 200 response with a non-JSON body produces a CLI-friendly error,
        not a raw JSONDecodeError traceback. Defends the JSON-parse guard.
        """
        _create_session(mock_session_manager)
        mock_response = MagicMock(status_code=200)
        mock_response.json.side_effect = ValueError("Expecting value")
        mock_response.text = "<html>upstream proxy error page</html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"<html>upstream proxy error page</html>"
        cli_obj["api_client"].session.request.return_value = mock_response

        result = cli_runner.invoke(cli, ["ping"], obj=cli_obj)

        assert result.exit_code != 0
        assert "Failed to parse ping response as JSON" in strip_ansi(result.output)

    def test_http_non_200_raises_api_error(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """If the server returns a non-200 (network blip, 502, etc.), ping fails fast."""
        _create_session(mock_session_manager)
        mock_response = MagicMock(status_code=502)
        mock_response.json.return_value = {"detail": "Bad gateway"}
        mock_response.text = "Bad gateway"
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"detail": "Bad gateway"}'
        cli_obj["api_client"].session.request.return_value = mock_response

        result = cli_runner.invoke(cli, ["ping"], obj=cli_obj)

        assert result.exit_code != 0
        assert "502" in strip_ansi(result.output) or "Bad gateway" in strip_ansi(
            result.output
        )
