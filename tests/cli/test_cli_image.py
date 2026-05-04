"""
CLI tests for `herds image upload`, focused on --poll behavior.

Polling is exercised end-to-end through CliRunner: the upload POST is mocked,
followed by a sequence of GETs that drive the image record through the
resize → extraction stages, finishing with a GET of the by-image events.

`time.sleep` is patched in the cmd_image module to keep tests fast; tests
that exercise the polling timeout patch `time.monotonic` instead so they
can fast-forward past the deadline.
"""

from unittest.mock import MagicMock, patch

import pytest

from herds_cli.cli import cli
from tests.cli.conftest import strip_ansi


def _create_session(session_manager, email="test@example.com"):
    """Create a mobile session in the tmp_path-backed manager."""
    session_manager.save_session(email, {
        "client_type": "mobile",
        "tokens": {"access_token": "fake-token"},
        "user_data": {"id": "user-123", "email": email},
    })


def _create_image_file(tmp_path, name="flyer.jpg"):
    """Write a minimal JPEG file (just the magic bytes) and return its path."""
    path = tmp_path / name
    path.write_bytes(b"\xff\xd8\xff")
    return path


def _make_response(status_code=200, json_data=None):
    """Build a mock requests.Response that satisfies APIClient consumers."""
    mock = MagicMock(status_code=status_code)
    mock.json.return_value = json_data if json_data is not None else {}
    mock.text = ""
    mock.headers = {"content-type": "application/json"}
    mock.content = b"{}"
    return mock


UPLOAD_RESPONSE = {
    "image_id": "img-001",
    "image_extraction_status": "processing",
}

SAMPLE_EVENT = {
    "title": "Summer Concert",
    "category_level_1": "Music",
    "date_info": {
        "raw": {"date": "2026-07-15"},
        "local": {
            "date_start": "2026-07-15",
            "time_start": "19:00",
        },
    },
    "location": {"city": "Austin", "state": "TX"},
    "contact": {"organizer": "Live Nation"},
}

SECOND_EVENT = {
    "title": "Afterparty",
    "category_level_1": "Music",
    "date_info": {"raw": {"date": "2026-07-15"}, "local": {}},
    "location": {"city": "Austin", "state": "TX"},
    "contact": {"organizer": "Side Bar"},
}


def _poll_response(*, resize="processing", thumbnail="processing", extraction="processing", **extra):
    """Build an image-status GET response with the given stage states."""
    body = {
        "image_id": "img-001",
        "resize_status": resize,
        "thumbnail_status": thumbnail,
        "image_extraction_status": extraction,
    }
    body.update(extra)
    return _make_response(json_data=body)


class TestUploadPollValidation:
    """--poll flag input validation runs before any HTTP work."""

    def test_poll_with_explicit_json_format_rejected(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """--poll + an *explicit* --format json is disallowed (exits before upload).

        Sets _format_explicit=True to simulate the user passing `--format json`
        on the command line (vs. inheriting it from the config default)."""
        _create_session(mock_session_manager)
        cli_obj["format"] = "json"
        cli_obj["config"].output_format = "json"
        cli_obj["_format_explicit"] = True
        path = _create_image_file(tmp_path)

        result = cli_runner.invoke(
            cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
        )

        assert result.exit_code != 0
        assert "--poll cannot be combined with --format json" in strip_ansi(
            result.output
        )
        # Crucially, the upload must NOT have been issued — validation gates it.
        assert not cli_obj["api_client"].session.request.called

    def test_poll_with_default_json_format_allowed(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """When format=json comes from the config default (not an explicit flag),
        --poll should proceed normally — the polling output replaces the JSON dump."""
        _create_session(mock_session_manager)
        cli_obj["format"] = "json"
        cli_obj["config"].output_format = "json"
        cli_obj["_format_explicit"] = False  # default — no --format flag passed
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(
                resize="completed",
                thumbnail="completed",
                extraction="completed",
            ),
            _make_response(json_data=[SAMPLE_EVENT]),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "Event extracted" in out
        assert "Summer Concert" in out

    def test_no_poll_json_format_unchanged(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """Without --poll, --format json continues to work as before."""
        _create_session(mock_session_manager)
        cli_obj["format"] = "json"
        cli_obj["config"].output_format = "json"
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.return_value = _make_response(
            json_data=UPLOAD_RESPONSE
        )

        result = cli_runner.invoke(
            cli, ["image", "upload", str(path)], obj=cli_obj
        )

        assert result.exit_code == 0, result.output
        # JSON body should be in stdout; only one HTTP call (the upload).
        assert cli_obj["api_client"].session.request.call_count == 1


class TestUploadPollSuccess:
    """End-to-end happy path: upload, poll through stages, render events."""

    def test_poll_completes_and_displays_event(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        _create_session(mock_session_manager)
        cli_obj["format"] = "text"
        cli_obj["config"].output_format = "text"
        path = _create_image_file(tmp_path)

        # Sequence: POST upload → 3 GET polls → GET events-by-image.
        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(),                                   # stage 1 in flight
            _poll_response(resize="completed", thumbnail="completed"),  # stage 1 done
            _poll_response(
                resize="completed",
                thumbnail="completed",
                extraction="completed",
            ),                                                  # stage 2 done
            _make_response(json_data=[SAMPLE_EVENT]),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "Image processed" in out
        assert "Event extracted" in out
        assert "Extracted 1 event(s)" in out
        assert "Summer Concert" in out
        assert "Austin, TX" in out
        assert "Live Nation" in out

    def test_poll_completes_in_one_shot(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """If extraction races to completed before we observe stage 1 done,
        we still print 'Image resized' exactly once before 'Event extracted'."""
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(
                resize="completed",
                thumbnail="completed",
                extraction="completed",
            ),
            _make_response(json_data=[SAMPLE_EVENT]),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        # Both stage transitions are announced exactly once.
        assert out.count("Image processed") == 1
        assert out.count("Event extracted") == 1

    def test_multiple_events_all_displayed(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(
                resize="completed",
                thumbnail="completed",
                extraction="completed",
            ),
            _make_response(json_data=[SAMPLE_EVENT, SECOND_EVENT]),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "Extracted 2 event(s)" in out
        assert "Summer Concert" in out
        assert "Afterparty" in out
        assert "Event 1 of 2" in out
        assert "Event 2 of 2" in out

    def test_no_events_extracted_warns(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """Extraction may complete with zero events — that's a warning, not a failure."""
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(
                resize="completed",
                thumbnail="completed",
                extraction="completed",
            ),
            _make_response(json_data=[]),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "No events were extracted" in out


class TestUploadPollCalendarSuccessAndDefault:
    """Coverage for the calendar-status display branches that aren't tied
    to a specific calendar_add_error code: the auto-add-success branch and
    the absent-user_data default. Per-error-code coverage lives in
    TestUploadPollCalendarStatus below."""

    def test_event_added_to_google_calendar_displayed(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        added_event = {
            **SAMPLE_EVENT,
            "user_data": {
                "google_calendar_id": "google-evt-001",
                "calendar_id": "primary",
            },
        }

        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(
                resize="completed",
                thumbnail="completed",
                extraction="completed",
            ),
            _make_response(json_data=[added_event]),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "In Google calendar" in out
        assert "primary" in out
        assert "google-evt-001" in out

    def test_no_calendar_add_attempted_displayed(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """When the server didn't attempt an auto-add (no per-upload flag and
        no user setting), the polling output should still tell the user that
        the event wasn't added to any calendar — not stay silent."""
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        # SAMPLE_EVENT has no user_data → server did not attempt an add.
        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(
                resize="completed",
                thumbnail="completed",
                extraction="completed",
            ),
            _make_response(json_data=[SAMPLE_EVENT]),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "Not added to a calendar" in out


class TestUploadPollFailures:
    """Failure paths: each must exit non-zero and surface useful diagnostics."""

    def test_resize_failure_exits_with_error(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(resize="failed", thumbnail="completed"),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code != 0
        out = strip_ansi(result.output)
        assert "Image resize failed" in out
        assert "resize=failed" in out

    def test_thumbnail_failure_exits_with_error(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(resize="completed", thumbnail="failed"),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code != 0
        assert "Image resize failed" in strip_ansi(result.output)

    def test_extraction_failure_shows_exception_details(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(
                resize="completed",
                thumbnail="completed",
                extraction="failed",
                extraction_exception={
                    "type": "LLMTimeoutError",
                    "message": "model did not respond in time",
                },
            ),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code != 0
        out = strip_ansi(result.output)
        assert "Event extraction failed" in out
        assert "LLMTimeoutError" in out
        assert "model did not respond in time" in out

    def test_polling_timeout_exits(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """When the deadline elapses, we exit non-zero with the last-seen status."""
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(),  # one poll, still in stage 1
        ]

        # First monotonic() sets deadline; second observes we're past it.
        with patch("herds_cli.commands.cmd_image.time.sleep"), patch(
            "herds_cli.commands.cmd_image.time.monotonic",
            side_effect=[0.0, 9999.0],
        ):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code != 0
        out = strip_ansi(result.output)
        assert "Polling timed out" in out
        assert "extraction=processing" in out

    def test_missing_image_id_exits(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """If the upload response lacks image_id we can't poll — fail loudly."""
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.return_value = _make_response(
            json_data={"image_extraction_status": "processing"},  # no image_id
        )

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code != 0
        assert "missing image_id" in strip_ansi(result.output)

    def test_poll_status_http_error_propagates(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """A non-200 from the poll endpoint should surface as an upload failure
        (the surrounding try/except in upload() catches it)."""
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.side_effect = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _make_response(status_code=500, json_data={"detail": "internal"}),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

        assert result.exit_code != 0
        out = strip_ansi(result.output)
        assert "Failed to fetch image status" in out


class TestUploadAddToCalendarFlag:
    """The CLI flag is tri-state, mirroring the server's UploadRequest contract:
    --add-to-calendar → 'true', --no-add-to-calendar → 'false', omitted → field
    is not sent at all (server defers to the user setting)."""

    def _run_upload(self, cli_runner, cli_obj, mock_session_manager, tmp_path, *flag_args):
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)
        cli_obj["api_client"].session.request.return_value = _make_response(
            json_data=UPLOAD_RESPONSE
        )
        return cli_runner.invoke(
            cli, ["image", "upload", str(path), *flag_args], obj=cli_obj
        )

    def _form_data(self, cli_obj):
        call_args = cli_obj["api_client"].session.request.call_args
        return call_args.kwargs.get("data") or call_args[1].get("data", {})

    def test_add_to_calendar_sends_true(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        result = self._run_upload(
            cli_runner, cli_obj, mock_session_manager, tmp_path,
            "--add-to-calendar",
        )
        assert result.exit_code == 0, result.output
        assert self._form_data(cli_obj).get("add_to_calendar") == "true"
        assert "Requesting auto-add to calendar" in strip_ansi(result.output)

    def test_no_add_to_calendar_sends_false(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        result = self._run_upload(
            cli_runner, cli_obj, mock_session_manager, tmp_path,
            "--no-add-to-calendar",
        )
        assert result.exit_code == 0, result.output
        assert self._form_data(cli_obj).get("add_to_calendar") == "false"
        assert "Skipping calendar auto-add" in strip_ansi(result.output)

    def test_omitted_does_not_send_field(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """Default behavior — neither flag — must NOT send add_to_calendar.
        Otherwise we'd silently override the user's auto-add setting."""
        result = self._run_upload(
            cli_runner, cli_obj, mock_session_manager, tmp_path,
        )
        assert result.exit_code == 0, result.output
        assert "add_to_calendar" not in self._form_data(cli_obj)


class TestUploadDefaultBehavior:
    """Without --poll, upload returns immediately — no polling, no events fetch."""

    def test_no_poll_makes_only_upload_request(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        _create_session(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        path = _create_image_file(tmp_path)

        cli_obj["api_client"].session.request.return_value = _make_response(
            json_data=UPLOAD_RESPONSE
        )

        result = cli_runner.invoke(
            cli, ["image", "upload", str(path)], obj=cli_obj
        )

        assert result.exit_code == 0, result.output
        # Single request: just the upload POST.
        assert cli_obj["api_client"].session.request.call_count == 1
        out = strip_ansi(result.output)
        assert "Successfully uploaded" in out
        # Nothing from the polling code path should appear.
        assert "Image processed" not in out
        assert "Event extracted" not in out


class TestUploadAuthFailure:
    """End-to-end coverage for the auto-refresh + tailored-hint behaviour."""

    def _create_session_with_refresh(self, sm, email="test@example.com", refresh_token="rfr"):
        sm.save_session(email, {
            "client_type": "mobile",
            "tokens": {"access_token": "old", "refresh_token": refresh_token},
            "user_data": {"id": "user-123", "email": email},
        })

    def _create_google_session_no_refresh(self, sm, email="g@example.com"):
        sm.save_session(email, {
            "client_type": "mobile",
            "auth_provider": "google",
            "tokens": {"access_token": "old"},  # no refresh_token
            "user_data": {"id": "user-456", "email": email},
        })

    def test_upload_auto_refreshes_on_401_and_succeeds(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path, mock_api_client,
    ):
        """A stale access_token with a valid refresh_token uploads cleanly:
        the user sees no auth error."""
        self._create_session_with_refresh(mock_session_manager)
        flyer = _create_image_file(tmp_path)

        unauthorized = _make_response(status_code=401, json_data={"detail": "expired"})
        refreshed = _make_response(json_data={
            "access_token": "new", "refresh_token": "new-rfr", "expires_in": 3600,
        })
        ok = _make_response(json_data={"image_id": "img-001"})
        mock_api_client.session.request.side_effect = [unauthorized, refreshed, ok]

        result = cli_runner.invoke(
            cli, ["image", "upload", str(flyer)], obj=cli_obj,
        )

        assert result.exit_code == 0, strip_ansi(result.output)
        out = strip_ansi(result.output)
        assert "Successfully uploaded" in out
        assert "Session expired" not in out  # never surfaced

    def test_upload_session_expired_password_account_shows_email_hint(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path, mock_api_client,
    ):
        """Stale access_token with no refresh_token → exit 1 with the tailored
        password-account login hint."""
        # Session has no refresh_token
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "old"},
            "user_data": {"id": "user-123", "email": "test@example.com"},
        })
        flyer = _create_image_file(tmp_path)

        unauthorized = _make_response(status_code=401, json_data={"detail": "expired"})
        mock_api_client.session.request.return_value = unauthorized

        result = cli_runner.invoke(
            cli, ["image", "upload", str(flyer)], obj=cli_obj,
        )

        assert result.exit_code == 1
        out = strip_ansi(result.output)
        assert "Session expired" in out
        assert "herds user login --email test@example.com" in out

    def test_upload_session_expired_google_account_shows_google_hint(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path, mock_api_client,
    ):
        """A google-OAuth session that fails to refresh shows `login-google`."""
        self._create_google_session_no_refresh(mock_session_manager, email="g@example.com")
        flyer = _create_image_file(tmp_path)

        unauthorized = _make_response(status_code=401, json_data={"detail": "expired"})
        mock_api_client.session.request.return_value = unauthorized

        result = cli_runner.invoke(
            cli, ["image", "upload", str(flyer), "--email", "g@example.com"],
            obj=cli_obj,
        )

        assert result.exit_code == 1
        out = strip_ansi(result.output)
        assert "Session expired" in out
        assert "herds user login-google" in out
        # The password-flavored hint must NOT appear:
        assert "login --email" not in out

    def test_no_pre_action_prints_when_session_missing(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path,
    ):
        """When the session lookup fails, the CLI must not print 'Uploading…'
        or 'Using timezone…' — those should appear only after auth is loaded."""
        # Add a single session for an UNRELATED email so the email arg path is
        # exercised without a matching session.
        mock_session_manager.save_session("other@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "x"},
            "user_data": {"id": "u9", "email": "other@example.com"},
        })
        flyer = _create_image_file(tmp_path)

        result = cli_runner.invoke(
            cli, ["image", "upload", str(flyer), "--email", "ghost@example.com"],
            obj=cli_obj,
        )

        assert result.exit_code != 0
        out = strip_ansi(result.output)
        assert "Uploading" not in out
        assert "Using timezone" not in out

    def test_upload_with_poll_auto_refreshes_then_polls_to_completion(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path, mock_api_client,
    ):
        """The auto-refresh path composes correctly with --poll: a stale
        access_token triggers a transparent refresh during the upload POST,
        and the subsequent polling GETs proceed normally to render events.
        Pins that the recursive _make_request retry doesn't interfere with
        the polling loop in cmd_image."""
        self._create_session_with_refresh(mock_session_manager)
        cli_obj["config"].output_format = "text"
        cli_obj["format"] = "text"
        flyer = _create_image_file(tmp_path)

        unauthorized = _make_response(status_code=401, json_data={"detail": "expired"})
        refreshed = _make_response(json_data={
            "access_token": "new", "refresh_token": "new-rfr", "expires_in": 3600,
        })
        # Sequence after refresh: upload-200, one poll showing all stages
        # completed, then the events-by-image GET.
        mock_api_client.session.request.side_effect = [
            unauthorized,
            refreshed,
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(
                resize="completed",
                thumbnail="completed",
                extraction="completed",
            ),
            _make_response(json_data=[SAMPLE_EVENT]),
        ]

        with patch("herds_cli.commands.cmd_image.time.sleep"):
            result = cli_runner.invoke(
                cli, ["image", "upload", str(flyer), "--poll"], obj=cli_obj,
            )

        assert result.exit_code == 0, strip_ansi(result.output)
        out = strip_ansi(result.output)
        # Refresh happened invisibly; user sees only normal upload+poll output.
        assert "Session expired" not in out
        assert "Successfully uploaded" in out
        assert "Image processed" in out
        assert "Event extracted" in out
        assert "Summer Concert" in out  # rendered from SAMPLE_EVENT
        # Sanity: 5 calls total — original 401, refresh, retried upload, poll, events.
        assert mock_api_client.session.request.call_count == 5


class TestUploadPollCalendarStatus:
    """End-to-end checks for the calendar_add_error display branch in the
    upload --poll flow. Each test plants a calendar_add_error code in the
    by-image events response and asserts the rendered output."""

    def _event_with_error(self, code):
        """Clone SAMPLE_EVENT and stamp a calendar_add_error code into user_data."""
        return {**SAMPLE_EVENT, "user_data": {"calendar_add_error": code}}

    def _setup_poll_responses(self, cli_obj, events_response, *extra_responses):
        """Wire up upload → one-shot poll → events response, with optional
        trailing responses (e.g. /api/calendar/status for reconnect tests)."""
        responses = [
            _make_response(json_data=UPLOAD_RESPONSE),
            _poll_response(
                resize="completed",
                thumbnail="completed",
                extraction="completed",
            ),
            _make_response(json_data=events_response),
        ]
        responses.extend(extra_responses)
        cli_obj["api_client"].session.request.side_effect = responses

    def _run_upload(self, cli_runner, cli_obj, tmp_path):
        path = _create_image_file(tmp_path)
        with patch("herds_cli.commands.cmd_image.time.sleep"):
            return cli_runner.invoke(
                cli, ["image", "upload", str(path), "--poll"], obj=cli_obj
            )

    def test_auto_add_disabled_renders_settings_hint(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        _create_session(mock_session_manager)
        cli_obj["format"] = "table"
        cli_obj["config"].output_format = "table"
        self._setup_poll_responses(
            cli_obj, [self._event_with_error("auto_add_disabled")]
        )

        result = self._run_upload(cli_runner, cli_obj, tmp_path)

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "auto-add is disabled in your settings" in out
        assert "herds user-settings update --auto-add-to-calendar=True" in out

    def test_no_calendar_connection_renders_connect_hint(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        _create_session(mock_session_manager)
        cli_obj["format"] = "table"
        cli_obj["config"].output_format = "table"
        self._setup_poll_responses(
            cli_obj, [self._event_with_error("no_calendar_connection")]
        )

        result = self._run_upload(cli_runner, cli_obj, tmp_path)

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "no calendar provider connected" in out
        assert "herds calendar connect --provider google" in out

    def test_calendar_provider_error_renders_status_hint(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        _create_session(mock_session_manager)
        cli_obj["format"] = "table"
        cli_obj["config"].output_format = "table"
        self._setup_poll_responses(
            cli_obj, [self._event_with_error("calendar_provider_error")]
        )

        result = self._run_upload(cli_runner, cli_obj, tmp_path)

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "your calendar provider rejected the event" in out
        assert "herds calendar status" in out

    def test_calendar_add_exception_renders_status_hint(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        _create_session(mock_session_manager)
        cli_obj["format"] = "table"
        cli_obj["config"].output_format = "table"
        self._setup_poll_responses(
            cli_obj, [self._event_with_error("calendar_add_exception")]
        )

        result = self._run_upload(cli_runner, cli_obj, tmp_path)

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "unexpected error occurred during auto-add" in out
        assert "herds calendar status" in out

    def test_needs_reconnect_fetches_provider_and_renders_specific_hint(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """When the events response includes calendar_needs_reconnect, the
        CLI follows up with one GET /api/calendar/status to learn the
        provider and bakes the result into the reconnect hint."""
        _create_session(mock_session_manager)
        cli_obj["format"] = "table"
        cli_obj["config"].output_format = "table"
        status_response = _make_response(
            json_data={"connected": True, "provider": "google"}
        )
        self._setup_poll_responses(
            cli_obj,
            [self._event_with_error("calendar_needs_reconnect")],
            status_response,
        )

        result = self._run_upload(cli_runner, cli_obj, tmp_path)

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "expired" in out
        assert "herds calendar connect --provider google" in out
        assert "<google|outlook>" not in out  # placeholder must not leak

    def test_needs_reconnect_falls_back_when_status_call_fails(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """A 5xx on /api/calendar/status must not crash the upload — we still
        print the reconnect message with the placeholder hint."""
        _create_session(mock_session_manager)
        cli_obj["format"] = "table"
        cli_obj["config"].output_format = "table"
        status_response = _make_response(status_code=500)
        self._setup_poll_responses(
            cli_obj,
            [self._event_with_error("calendar_needs_reconnect")],
            status_response,
        )

        result = self._run_upload(cli_runner, cli_obj, tmp_path)

        assert result.exit_code == 0, result.output
        out = strip_ansi(result.output)
        assert "expired" in out
        assert "<google|outlook>" in out  # placeholder shows up on fallback

    def test_status_lookup_skipped_when_no_event_needs_reconnect(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """When no event carries calendar_needs_reconnect, the resolver is
        constructed but never consulted — so /api/calendar/status is not
        called. We assert by exact request count: 1 upload + 1 poll + 1 events
        = 3 calls, with no fourth."""
        _create_session(mock_session_manager)
        cli_obj["format"] = "table"
        cli_obj["config"].output_format = "table"
        self._setup_poll_responses(
            cli_obj, [self._event_with_error("auto_add_disabled")]
        )

        result = self._run_upload(cli_runner, cli_obj, tmp_path)

        assert result.exit_code == 0, result.output
        assert cli_obj["api_client"].session.request.call_count == 3

    def test_status_lookup_runs_once_for_multi_event_reconnect(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path
    ):
        """Two events both flagged calendar_needs_reconnect must trigger
        exactly one /api/calendar/status call thanks to resolver caching.
        Total: 1 upload + 1 poll + 1 events + 1 status = 4 calls."""
        _create_session(mock_session_manager)
        cli_obj["format"] = "table"
        cli_obj["config"].output_format = "table"
        events = [
            {**SAMPLE_EVENT, "user_data": {"calendar_add_error": "calendar_needs_reconnect"}},
            {**SECOND_EVENT, "user_data": {"calendar_add_error": "calendar_needs_reconnect"}},
        ]
        status_response = _make_response(
            json_data={"connected": True, "provider": "outlook"}
        )
        self._setup_poll_responses(cli_obj, events, status_response)

        result = self._run_upload(cli_runner, cli_obj, tmp_path)

        assert result.exit_code == 0, result.output
        assert cli_obj["api_client"].session.request.call_count == 4
        out = strip_ansi(result.output)
        # Both events get the same resolved provider in their reconnect hints.
        assert out.count("herds calendar connect --provider outlook") == 2
