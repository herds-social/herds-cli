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
    _format_image_assets,
    _has_renderable_content,
    _render_event_fields,
)
from herds_cli.core.config import Config
from herds_cli.core.exceptions import (
    AmbiguousSessionError,
    NoSessionsError,
    SessionNotFoundError,
    UserIdNotFoundError,
)

# One fully-measured images_v3 entry (see ImageAssetsV3 in herds_cli/types.py
# for the contract), shared by the formatter and display tests.
SAMPLE_IMAGES_V3_ENTRY = {
    "image_id": "68a1",
    "original": {"url": None, "width": 4284, "height": 5712, "size_mb": 4.2},
    "resized": {"url": "https://x/r", "width": 1500, "height": 2000, "size_mb": 0.9},
    "thumbnail": {"url": "https://x/t", "width": 202, "height": 270, "size_mb": 0.02},
}


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

    def test_renders_parent_title_subline(self, capsys):
        events = [{
            "title": "Bilingual Worship",
            "parent_title": "Christmas Eve at Weddington",
            "date_info": {"raw": {"date": "2026-12-24"}},
        }]
        display_events_summary(events)
        out = capsys.readouterr().err
        assert "Bilingual Worship" in out
        assert "Parent: Christmas Eve at Weddington" in out

    def test_omits_parent_subline_when_absent(self, capsys):
        events = [{"title": "Solo Event", "date_info": {"raw": {"date": "2026-12-24"}}}]
        display_events_summary(events)
        out = capsys.readouterr().err
        assert "Solo Event" in out
        assert "Parent:" not in out


class TestDisplayEventDetails:
    """Unit tests for EventCommandBase.display_event_details, focused on
    the calendar add status block. Calendar status is *data-driven*:
    if the server populated `user_data.{provider}_calendar_event_id` (success)
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
        assert "In Google calendar" not in out
        assert "In Outlook calendar" not in out
        assert "In Apple calendar" not in out
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
                "google_calendar_event_id": "g-evt-123",
                "calendar_id": "primary",
            },
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "In Google calendar" in out
        assert "primary" in out
        assert "g-evt-123" in out

    def test_outlook_add_success_no_target(self, capsys):
        """Outlook add without a target calendar id: omit the parenthetical."""
        event = {
            **self.BASE_EVENT,
            "user_data": {"outlook_calendar_event_id": "o-evt-456"},
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "In Outlook calendar" in out
        assert "o-evt-456" in out
        assert "(calendar:" not in out  # no target → no parenthetical

    def test_apple_add_success(self, capsys):
        event = {
            **self.BASE_EVENT,
            "user_data": {"apple_calendar_event_id": "a-evt-789"},
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "In Apple calendar" in out
        assert "a-evt-789" in out

    def test_add_failure_with_known_code_renders_friendly_message(self, capsys):
        """Known calendar_add_error codes get a translated message + remediation
        hint sourced from herds_cli.calendar_status_display. The raw enum string
        no longer appears in the output for known codes."""
        event = {
            **self.BASE_EVENT,
            "user_data": {"calendar_add_error": "no_calendar_connection"},
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "Not added to calendar: no calendar provider connected" in out
        assert "herds calendar connect --provider google" in out
        # The literal "Calendar add failed" wording is gone for known codes.
        assert "Calendar add failed" not in out

    def test_add_failure_with_unknown_code_falls_back_to_raw(self, capsys):
        """Defensive fallback: a code we haven't taught the CLI about is
        surfaced verbatim so the user isn't lied to about the cause."""
        event = {
            **self.BASE_EVENT,
            "user_data": {"calendar_add_error": "calendar_quota_exhausted"},
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "calendar_quota_exhausted" in out

    def test_success_takes_precedence_over_error(self, capsys):
        """Defensive: if both a success ID and an error are somehow set,
        prefer the success message — the event IS in the calendar."""
        event = {
            **self.BASE_EVENT,
            "user_data": {
                "google_calendar_event_id": "g-evt-1",
                "calendar_add_error": "STALE_ERROR",
            },
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "In Google calendar" in out
        assert "Calendar add failed" not in out

    def test_parent_title_rendered_above_title(self, capsys):
        """When parent_title is present, a 'Parent:' line precedes the 'Title:' line."""
        event = {**self.BASE_EVENT, "parent_title": "Christmas Eve at Weddington"}
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "Parent: Christmas Eve at Weddington" in out
        assert "Title: Summer Concert" in out
        # Parent must appear before Title in the output.
        assert out.index("Parent: Christmas Eve") < out.index("Title: Summer Concert")

    def test_parent_title_omitted_when_absent(self, capsys):
        """No 'Parent:' line is printed when parent_title is missing or None."""
        self._make_cmd().display_event_details(self.BASE_EVENT)
        out = capsys.readouterr().err
        assert "Parent:" not in out

    @pytest.mark.parametrize("raw_date", [None, ""])
    def test_null_raw_date_uses_local_date_and_time(self, capsys, raw_date):
        """API may return raw.date null/empty while local fields are populated."""
        event = {
            **self.BASE_EVENT,
            "date_info": {
                "raw": {"date": raw_date},
                "local": {
                    "date_start": "2026-08-01",
                    "time_start": "7:00 PM",
                },
            },
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "2026-08-01 at 7:00 PM" in out

    def test_images_block_renders_between_calendar_and_dump(self, capsys):
        """images_v3 gets a curated block: one numbered line per image,
        placed after the calendar status and before the full dump."""
        event = {
            **self.BASE_EVENT,
            "images_v3": [{**SAMPLE_IMAGES_V3_ENTRY, "thumbnail": None}],
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "Images (1):" in out
        assert "1. original 4284x5712" in out
        assert "(id 68a1)" in out
        assert out.index("Images (1):") < out.index("Full event data")

    def test_images_block_numbers_multiple_entries(self, capsys):
        event = {
            **self.BASE_EVENT,
            "images_v3": [
                {"original": {"url": "u1", "width": 10, "height": 20, "size_mb": None},
                 "resized": None, "thumbnail": None},
                {"original": None, "resized": None,
                 "thumbnail": {"url": "u2", "width": None, "height": None, "size_mb": None}},
            ],
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "Images (2):" in out
        assert "1. original 10x20" in out
        assert "2. thumbnail (dimensions pending)" in out

    def test_no_images_block_when_field_absent(self, capsys):
        """Older servers send no images_v3; output stays exactly as before."""
        self._make_cmd().display_event_details(self.BASE_EVENT)
        out = capsys.readouterr().err
        assert "Images (" not in out

    def test_no_images_block_when_empty_list(self, capsys):
        event = {**self.BASE_EVENT, "images_v3": []}
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "Images (" not in out

    def test_full_event_data_dump_appears_after_curated_header(self, capsys):
        """The dump heading follows the curated block, so casual reads see
        the friendly summary first."""
        self._make_cmd().display_event_details(self.BASE_EVENT)
        out = capsys.readouterr().err
        assert "Full event data" in out
        assert out.index("Category:") < out.index("Full event data")

    def test_dump_includes_fields_the_header_omits(self, capsys):
        """street_address and contact.website are modeled but not in the
        curated header; the dump must surface them."""
        event = {
            **self.BASE_EVENT,
            "location": {
                "city": "Austin",
                "state": "TX",
                "street_address": "1300 South Blvd",
            },
            "contact": {
                "organizer": "Live Nation",
                "website": "https://example.com/gig",
            },
        }
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "street_address: 1300 South Blvd" in out
        assert "website: https://example.com/gig" in out

    def test_dump_includes_unmodeled_server_fields(self, capsys):
        """Fields absent from the EventV2 TypedDict still appear: the walker
        reads the live dict, so new server fields need no CLI change."""
        event = {**self.BASE_EVENT, "confidence_score": 0.97}
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        assert "confidence_score: 0.97" in out

    def test_dump_omits_none_and_empty_fields(self, capsys):
        """None/empty fields stay out of the dump (the curated header is
        unchanged and may still print 'Category: None')."""
        event = {**self.BASE_EVENT, "event_description": None, "tags": []}
        self._make_cmd().display_event_details(event)
        out = capsys.readouterr().err
        dump = out[out.index("Full event data"):]
        assert "event_description" not in dump
        assert "tags" not in dump


class TestRenderEventFields:
    """Unit tests for the recursive full-event-data walker.

    The walker prints every populated field of the live event dict via
    OutputFormatter.print_info (stderr), so new server fields appear
    without a CLI change. Empty values are pruned recursively."""

    def test_scalar_fields_render_indented(self, capsys):
        _render_event_fields({"title": "Game Night", "id": "abc123"})
        err = capsys.readouterr().err
        assert "  title: Game Night" in err
        assert "  id: abc123" in err

    def test_nested_dict_recurses_with_deeper_indent(self, capsys):
        _render_event_fields(
            {"location": {"city": "Charlotte", "street_address": "1300 South Blvd"}}
        )
        err = capsys.readouterr().err
        assert "  location:" in err
        assert "    city: Charlotte" in err
        assert "    street_address: 1300 South Blvd" in err

    def test_none_and_empty_values_omitted(self, capsys):
        _render_event_fields(
            {
                "title": "Kept",
                "category_level_1": None,
                "notes": "",
                "tags": [],
                "extra": {},
            }
        )
        err = capsys.readouterr().err
        assert "title: Kept" in err
        assert "category_level_1" not in err
        assert "notes" not in err
        assert "tags" not in err
        assert "extra" not in err

    def test_dict_of_all_empty_values_omitted_entirely(self, capsys):
        """A nested dict whose members are all empty must not leave a
        dangling 'contact:' heading with nothing under it."""
        _render_event_fields(
            {"title": "Kept", "contact": {"email": None, "phone": ""}}
        )
        err = capsys.readouterr().err
        assert "title: Kept" in err
        assert "contact" not in err

    def test_falsy_but_meaningful_values_kept(self, capsys):
        """0 and False are real data (price: 0, is_free: False), not emptiness."""
        _render_event_fields({"price": 0, "recurring": False})
        err = capsys.readouterr().err
        assert "  price: 0" in err
        assert "  recurring: False" in err

    def test_list_of_scalars_renders_as_dash_items(self, capsys):
        _render_event_fields({"tags": ["music", "outdoor"]})
        err = capsys.readouterr().err
        assert "  tags:" in err
        assert "    - music" in err
        assert "    - outdoor" in err

    def test_list_of_dicts_recurses(self, capsys):
        _render_event_fields(
            {"occurrences": [{"date": "2026-07-13"}, {"date": "2026-07-20"}]}
        )
        err = capsys.readouterr().err
        assert "  occurrences:" in err
        assert "date: 2026-07-13" in err
        assert "date: 2026-07-20" in err

    def test_has_renderable_content_predicate(self):
        assert _has_renderable_content("x") is True
        assert _has_renderable_content(0) is True
        assert _has_renderable_content(False) is True
        assert _has_renderable_content(None) is False
        assert _has_renderable_content("") is False
        assert _has_renderable_content({}) is False
        assert _has_renderable_content([]) is False
        assert _has_renderable_content({"a": None, "b": ""}) is False
        assert _has_renderable_content({"a": {"b": "deep"}}) is True
        assert _has_renderable_content([None, ""]) is False
        assert _has_renderable_content([None, "x"]) is True

    def test_markup_like_values_render_literally_without_crashing(self, capsys):
        """Server values are arbitrary text; Rich markup in them must be
        escaped, not interpreted. An unmatched closing tag would otherwise
        raise MarkupError and abort the command."""
        _render_event_fields(
            {
                "description": "see [/red] tag",
                "notes": ["[bold]not bold[/bold]"],
                "nested": {"[key]": "[red]literal[/red]"},
            }
        )
        err = capsys.readouterr().err
        assert "see [/red] tag" in err
        assert "[bold]not bold[/bold]" in err
        assert "[red]literal[/red]" in err


class TestFormatImageAssets:
    """Unit tests for the images_v3 per-entry formatter (contract details
    on ImageAssetsV3/ImageVariantV3 in herds_cli/types.py)."""

    def test_all_variants_measured(self):
        line = _format_image_assets(SAMPLE_IMAGES_V3_ENTRY)
        assert line == (
            "original 4284x5712 (4.2MB), "
            "resized 1500x2000 (0.9MB), "
            "thumbnail 202x270 (0.02MB)"
        )

    def test_null_variant_omitted(self):
        assets = {**SAMPLE_IMAGES_V3_ENTRY, "thumbnail": None}
        line = _format_image_assets(assets)
        assert "thumbnail" not in line
        assert "original" in line and "resized" in line

    def test_unmeasured_variant_marked_pending_not_absent(self):
        assets = {
            "image_id": "68a1",
            "original": None,
            "resized": {"url": "https://x/r", "width": None, "height": None, "size_mb": None},
            "thumbnail": None,
        }
        assert _format_image_assets(assets) == "resized (dimensions pending)"

    def test_null_url_with_dimensions_still_renders(self):
        """URL presence is not an existence signal (see ImageVariantV3)."""
        assets = {
            "original": {"url": None, "width": 100, "height": 200, "size_mb": None},
            "resized": None,
            "thumbnail": None,
        }
        assert _format_image_assets(assets) == "original 100x200"

    def test_all_variants_null(self):
        assets = {"image_id": "68a1", "original": None, "resized": None, "thumbnail": None}
        assert _format_image_assets(assets) == "(no renderable variants)"

    def test_missing_variant_keys_treated_as_null(self):
        assert _format_image_assets({"image_id": "68a1"}) == "(no renderable variants)"


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
