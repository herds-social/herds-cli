"""Calendar command tests via Click's CliRunner.

Exercises the new interactive picker in `herds calendar set-calendar` and the
non-interactive paths preserved as the scripting escape hatch. Mirrors the
spec at docs/superpowers/specs/2026-05-02-set-calendar-prompt-design.md.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import click
import pytest

from herds_cli.cli import cli
from tests.cli.conftest import strip_ansi


def _save_test_session(session_manager: Any, email: str = "test@example.com") -> None:
    session_manager.save_session(email, {
        "client_type": "mobile",
        "tokens": {"access_token": "tok"},
        "user_data": {"id": "u-123", "email": email},
    })


def _make_response(status_code: int = 200, json_body: Any = None) -> MagicMock:
    resp = MagicMock(status_code=status_code)
    resp.json.return_value = json_body if json_body is not None else {}
    resp.cookies = {}
    return resp


def _route_responses(cli_obj: Any, routes: dict) -> None:
    """Wire api_client.session.request to dispatch on (method, url-substring)."""

    def handler(method: str, url: str, **kwargs: Any) -> Any:
        for (m, sub), resp in routes.items():
            if method == m and sub in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected request: {method} {url}")

    cli_obj["api_client"].session.request.side_effect = handler


def _calendars_payload(*entries: tuple) -> dict:
    """entries: (name, id, primary) tuples → list-calendars response body."""
    return {
        "calendars": [
            {"id": id_, "name": name, "primary": primary}
            for name, id_, primary in entries
        ]
    }


CAL_LIST_3 = _calendars_payload(
    ("Personal", "primary", True),
    ("Work", "cal2", False),
    ("Family", "cal3", False),
)


@pytest.fixture
def interactive_tty(cli_obj):
    """Patch _is_interactive()→True and switch the test's output format to
    'table' so the JSON non-interactive guard doesn't trip."""
    cli_obj["format"] = "table"
    cli_obj["config"].output_format = "table"
    with patch(
        "herds_cli.commands.cmd_calendar._is_interactive",
        create=True,
        return_value=True,
    ) as p:
        yield p


@pytest.fixture
def non_tty(cli_obj):
    """Patch _is_interactive()→False and switch the test's output format to
    'table' so the failure clearly comes from TTY detection, not JSON mode."""
    cli_obj["format"] = "table"
    cli_obj["config"].output_format = "table"
    with patch(
        "herds_cli.commands.cmd_calendar._is_interactive",
        create=True,
        return_value=False,
    ) as p:
        yield p


def _put_bodies(cli_obj: Any) -> list:
    """Return the JSON bodies from every PUT call recorded on the mock."""
    return [
        c.kwargs.get("json")
        for c in cli_obj["api_client"].session.request.call_args_list
        if c.args and c.args[0] == "PUT"
    ]


class TestSetCalendar:
    def test_flag_passed_skips_picker(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """--calendar-id passed → no list/status GETs, single PUT, no calendar_name."""
        _save_test_session(mock_session_manager)
        put_resp = _make_response(200, {
            "calendar_id": "abc123", "calendar_name": "Whatever",
        })
        _route_responses(cli_obj, {
            ("PUT", "/api/calendar/settings"): put_resp,
        })

        result = cli_runner.invoke(
            cli,
            ["calendar", "set-calendar", "--calendar-id", "abc123"],
            obj=cli_obj,
        )

        assert result.exit_code == 0, result.output
        calls = cli_obj["api_client"].session.request.call_args_list
        assert len(calls) == 1, f"expected 1 request, got {len(calls)}"
        assert calls[0].args[0] == "PUT"
        assert calls[0].kwargs.get("json") == {"calendar_id": "abc123"}

    def test_calendar_name_flag_rejected(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """--calendar-name was removed in 2.0; Click should reject it."""
        _save_test_session(mock_session_manager)
        result = cli_runner.invoke(
            cli,
            [
                "calendar", "set-calendar",
                "--calendar-id", "abc",
                "--calendar-name", "X",
            ],
            obj=cli_obj,
        )
        assert result.exit_code != 0
        out = (result.output or "").lower()
        assert "no such option" in out or "unrecognized" in out, out

    def test_interactive_picks_via_number(
        self, cli_runner, cli_obj, mock_session_manager, interactive_tty
    ):
        """TTY + no flag + status says cal2 current → picker shows [2] default."""
        _save_test_session(mock_session_manager)
        list_resp = _make_response(200, CAL_LIST_3)
        status_resp = _make_response(200, {
            "connected": True,
            "provider": "google",
            "calendar_id": "cal2",
            "calendar_name": "Work",
        })
        put_resp = _make_response(200, {
            "calendar_id": "primary",
            "calendar_name": "Personal",
        })
        _route_responses(cli_obj, {
            ("GET", "/api/calendar/list"): list_resp,
            ("GET", "/api/calendar/status"): status_resp,
            ("PUT", "/api/calendar/settings"): put_resp,
        })

        result = cli_runner.invoke(
            cli, ["calendar", "set-calendar"], obj=cli_obj, input="1\n"
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0, out
        assert "(primary)" in out
        assert "(current)" in out
        assert "Calendar [2]" in out, out
        assert _put_bodies(cli_obj) == [{"calendar_id": "primary"}]

    def test_default_acceptance_picks_smart_default(
        self, cli_runner, cli_obj, mock_session_manager, interactive_tty
    ):
        """Just-Enter accepts the smart default (current selection)."""
        _save_test_session(mock_session_manager)
        list_resp = _make_response(200, CAL_LIST_3)
        status_resp = _make_response(200, {
            "connected": True,
            "calendar_id": "cal2",
            "calendar_name": "Work",
        })
        put_resp = _make_response(200, {
            "calendar_id": "cal2", "calendar_name": "Work",
        })
        _route_responses(cli_obj, {
            ("GET", "/api/calendar/list"): list_resp,
            ("GET", "/api/calendar/status"): status_resp,
            ("PUT", "/api/calendar/settings"): put_resp,
        })

        result = cli_runner.invoke(
            cli, ["calendar", "set-calendar"], obj=cli_obj, input="\n"
        )

        assert result.exit_code == 0, result.output
        assert _put_bodies(cli_obj) == [{"calendar_id": "cal2"}]

    def test_no_current_falls_back_to_primary(
        self, cli_runner, cli_obj, mock_session_manager, interactive_tty
    ):
        """No current selection → default is the primary calendar."""
        _save_test_session(mock_session_manager)
        list_resp = _make_response(200, CAL_LIST_3)
        status_resp = _make_response(200, {"connected": False})
        put_resp = _make_response(200, {
            "calendar_id": "primary", "calendar_name": "Personal",
        })
        _route_responses(cli_obj, {
            ("GET", "/api/calendar/list"): list_resp,
            ("GET", "/api/calendar/status"): status_resp,
            ("PUT", "/api/calendar/settings"): put_resp,
        })

        result = cli_runner.invoke(
            cli, ["calendar", "set-calendar"], obj=cli_obj, input="\n"
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0, out
        assert "Calendar [1]" in out, out
        assert "(current)" not in out
        assert _put_bodies(cli_obj) == [{"calendar_id": "primary"}]

    def test_no_current_or_primary_requires_input(
        self, cli_runner, cli_obj, mock_session_manager, interactive_tty
    ):
        """Multi-calendar list with no current and no primary → no default."""
        _save_test_session(mock_session_manager)
        list_resp = _make_response(200, _calendars_payload(
            ("Holidays", "cal_hol", False),
            ("Birthdays", "cal_bday", False),
        ))
        status_resp = _make_response(200, {"connected": False})
        put_resp = _make_response(200, {
            "calendar_id": "cal_bday", "calendar_name": "Birthdays",
        })
        _route_responses(cli_obj, {
            ("GET", "/api/calendar/list"): list_resp,
            ("GET", "/api/calendar/status"): status_resp,
            ("PUT", "/api/calendar/settings"): put_resp,
        })

        result = cli_runner.invoke(
            cli, ["calendar", "set-calendar"], obj=cli_obj, input="2\n"
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0, out
        assert "Calendar [" not in out, out
        assert "(primary)" not in out
        assert "(current)" not in out
        assert _put_bodies(cli_obj) == [{"calendar_id": "cal_bday"}]

    def test_non_tty_no_flag_errors(
        self, cli_runner, cli_obj, mock_session_manager, non_tty
    ):
        """Non-TTY + no --calendar-id → exit 1, no requests."""
        _save_test_session(mock_session_manager)
        cli_obj["api_client"].session.request.side_effect = AssertionError(
            "no requests expected on non-tty error path"
        )

        result = cli_runner.invoke(cli, ["calendar", "set-calendar"], obj=cli_obj)

        out = strip_ansi(result.output)
        assert result.exit_code != 0
        assert "--calendar-id" in out
        assert "non-interactive" in out.lower()

    def test_format_json_no_flag_errors(
        self, cli_runner, cli_obj, mock_session_manager, interactive_tty
    ):
        """--format json + no flag → exit 1 even on a TTY."""
        _save_test_session(mock_session_manager)
        cli_obj["format"] = "json"
        cli_obj["config"].output_format = "json"
        cli_obj["api_client"].session.request.side_effect = AssertionError(
            "no requests expected on json non-interactive path"
        )

        result = cli_runner.invoke(cli, ["calendar", "set-calendar"], obj=cli_obj)

        out = strip_ansi(result.output)
        assert result.exit_code != 0
        assert "--calendar-id" in out

    def test_empty_calendar_list_errors(
        self, cli_runner, cli_obj, mock_session_manager, interactive_tty
    ):
        """list returns [] → exit 1 with 'No calendars found.'"""
        _save_test_session(mock_session_manager)
        list_resp = _make_response(200, {"calendars": []})
        _route_responses(cli_obj, {("GET", "/api/calendar/list"): list_resp})

        result = cli_runner.invoke(cli, ["calendar", "set-calendar"], obj=cli_obj)

        out = strip_ansi(result.output)
        assert result.exit_code != 0
        assert "No calendars found" in out

    def test_no_calendar_connection_errors(
        self, cli_runner, cli_obj, mock_session_manager, interactive_tty
    ):
        """list returns 400 no_calendar_connection → exit 1 with reused message."""
        _save_test_session(mock_session_manager)
        list_resp = _make_response(400, {
            "error_type": "no_calendar_connection",
            "message": "No calendar connected.",
        })
        _route_responses(cli_obj, {("GET", "/api/calendar/list"): list_resp})

        result = cli_runner.invoke(cli, ["calendar", "set-calendar"], obj=cli_obj)

        out = strip_ansi(result.output)
        assert result.exit_code != 0
        assert "No calendar connected" in out

    def test_status_failure_tolerated(
        self, cli_runner, cli_obj, mock_session_manager, interactive_tty
    ):
        """status raises → picker still works, no (current), default is primary."""
        _save_test_session(mock_session_manager)
        list_resp = _make_response(200, CAL_LIST_3)
        put_resp = _make_response(200, {
            "calendar_id": "primary", "calendar_name": "Personal",
        })
        _route_responses(cli_obj, {
            ("GET", "/api/calendar/list"): list_resp,
            ("GET", "/api/calendar/status"): ConnectionError("status unavailable"),
            ("PUT", "/api/calendar/settings"): put_resp,
        })

        result = cli_runner.invoke(
            cli, ["calendar", "set-calendar"], obj=cli_obj, input="1\n"
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0, out
        assert "(current)" not in out
        assert "Calendar [1]" in out, out

    def test_single_calendar_still_shows_picker(
        self, cli_runner, cli_obj, mock_session_manager, interactive_tty
    ):
        """One calendar → picker still shown, default [1] (only-calendar fallback)."""
        _save_test_session(mock_session_manager)
        list_resp = _make_response(200, _calendars_payload(
            ("Solo", "solo_id", False),
        ))
        status_resp = _make_response(200, {"connected": False})
        put_resp = _make_response(200, {
            "calendar_id": "solo_id", "calendar_name": "Solo",
        })
        _route_responses(cli_obj, {
            ("GET", "/api/calendar/list"): list_resp,
            ("GET", "/api/calendar/status"): status_resp,
            ("PUT", "/api/calendar/settings"): put_resp,
        })

        result = cli_runner.invoke(
            cli, ["calendar", "set-calendar"], obj=cli_obj, input="\n"
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0, out
        assert "Calendar [1]" in out, out
        assert _put_bodies(cli_obj) == [{"calendar_id": "solo_id"}]

    def test_ctrl_c_at_prompt_aborts(
        self, cli_runner, cli_obj, mock_session_manager, interactive_tty
    ):
        """Click Abort raised at the prompt → exit 1, no PUT."""
        _save_test_session(mock_session_manager)
        list_resp = _make_response(200, CAL_LIST_3)
        status_resp = _make_response(200, {"connected": False})
        # PUT route would raise loudly if reached.
        _route_responses(cli_obj, {
            ("GET", "/api/calendar/list"): list_resp,
            ("GET", "/api/calendar/status"): status_resp,
            ("PUT", "/api/calendar/settings"): AssertionError(
                "PUT must not happen after abort"
            ),
        })

        with patch("click.prompt", side_effect=click.exceptions.Abort()):
            result = cli_runner.invoke(
                cli, ["calendar", "set-calendar"], obj=cli_obj
            )

        assert result.exit_code != 0
