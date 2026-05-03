"""
User settings management commands for the Herds CLI.

This module contains commands for managing user preferences and settings.
"""

import re
from typing import Optional

import click
import sys

from herds_cli.output import OutputFormatter
from herds_cli.core.base import CommandBase, APIResponseHandler


# Maps server-side IgnoredField.reason enum values to human-readable
# explanations rendered in the partial-success warning. Unknown reasons fall
# through to their raw string via _format_ignored_field_reason — that is the
# forward-compatibility hinge for new server enum values.
_IGNORED_FIELD_REASON_MESSAGES: dict[str, str] = {
    "requires_paid_subscription": "requires a paid subscription",
}


def _format_ignored_field_reason(reason: str) -> str:
    """Map an IgnoredField.reason enum value to a human-readable explanation.

    Unknown reasons fall through to the raw string so a server-side enum
    addition (e.g., a future quota_exceeded) doesn't silently swallow the
    explanation in older CLI builds — the user still sees *something*.
    """
    return _IGNORED_FIELD_REASON_MESSAGES.get(reason, reason)


@click.group()
def user_settings() -> None:
    """User settings management commands (get, update, etc.)"""
    pass


@user_settings.command("get")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def get_settings(ctx: click.Context, email: Optional[str]) -> None:
    """Get user settings and preferences."""
    cmd = CommandBase(ctx)

    # Setup session (auto-detect if not specified)
    email = cmd.setup_session(email, show_client_type=True)

    # Load session authentication
    cmd.load_session_auth(email)

    OutputFormatter.print_info(f"Retrieving settings for {email}...")

    # Build URL and execute API request
    url = f"{cmd.api_client.base_url}/api/user/setting"
    result = cmd.execute_api_request("GET", url, "Successfully retrieved user settings")

    # Display settings
    settings = result.get("settings", {})
    OutputFormatter.print_info(f"Sort By: {settings.get('sort_by', 'Not set')}")
    OutputFormatter.print_info(f"Filter By: {settings.get('filter_by', 'Not set')}")
    OutputFormatter.print_info(f"Theme: {settings.get('theme', 'Not set')}")
    OutputFormatter.print_info(
        f"Auto Add to Calendar: {settings.get('auto_add_to_calendar_enabled', 'Not set')}"
    )
    date_filter = settings.get("date_filter")
    OutputFormatter.print_info(f"Date Filter: {_format_date_filter(date_filter)}")

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format, skip_table=True)


def parse_bool_value(ctx: click.Context, param: click.Parameter, value: str | bool | None) -> bool | None:
    """Parse boolean values from string format like 'True' or 'False'."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    raise click.BadParameter(
        f"Invalid boolean value: '{value}'. Use 'True' or 'False'."
    )


RELATIVE_PATTERN = re.compile(
    r"^past[- ](\d+)[- ](days?|weeks?|months?)$", re.IGNORECASE
)


def parse_date_filter(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Parse date filter from CLI shorthand into DSL string.

    Supported formats (all produce DSL strings):
        all                  → "all"
        upcoming             → "upcoming"
        past-3-months        → "past-3-months"
        past-2-weeks         → "past-2-weeks"
        past-7-days          → "past-7-days"
        2025-12-01..         → "2025-12-01.."
        2025-12-01..2026-01-31 → "2025-12-01..2026-01-31"

    Returns None when the flag was not provided. Otherwise returns the
    normalized DSL string (or raises BadParameter for unrecognized syntax).
    """
    if value is None:
        return None

    v = value.strip()

    # Keywords pass through directly
    if v.lower() in ("all", "upcoming"):
        return v.lower()

    # Relative patterns — normalize to DSL format
    m = RELATIVE_PATTERN.match(v)
    if m:
        num = int(m.group(1))
        unit = (
            m.group(2).rstrip("s") + "s"
        )  # normalize: day→days, week→weeks, month→months
        return f"past-{num}-{unit}"

    # Date range patterns pass through directly
    if re.match(r"^\d{4}-\d{2}-\d{2}\.\.", v):
        return v

    raise click.BadParameter(
        f"Unknown date filter: '{value}'. "
        "Use 'all', 'upcoming', 'past-N-days/weeks/months', or 'YYYY-MM-DD..YYYY-MM-DD'."
    )


def _format_date_filter(date_filter: str | None) -> str:
    """Format a date_filter DSL string for human-readable display."""
    if not date_filter:
        return "Not set"

    if date_filter == "all":
        return "all events"
    if date_filter == "upcoming":
        return "upcoming only"

    m = re.match(r"^past-(\d+)-(days|weeks|months)$", date_filter)
    if m:
        return f"past {m.group(1)} {m.group(2)} + future"

    if re.match(r"^\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}$", date_filter):
        start, end = date_filter.split("..")
        return f"from {start} to {end}"

    if re.match(r"^\d{4}-\d{2}-\d{2}\.\.$", date_filter):
        start = date_filter.rstrip(".")
        return f"from {start} onward"

    return date_filter


@user_settings.command("update")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--sort-by",
    type=click.Choice(["utc_start", "date_start", "date_added", "date_modified"]),
    help="Default sort field for events",
)
@click.option(
    "--sort-order",
    type=click.Choice(["asc", "desc"]),
    help="Default sort direction for events",
)
@click.option(
    "--filter-by",
    type=click.Choice(["all", "in_calendar", "not_in_calendar"]),
    help="Default filter for events",
)
@click.option(
    "--theme",
    type=click.Choice(["dark", "light", "system"]),
    help="Application theme preference (paid plan only)",
)
@click.option(
    "--auto-add-to-calendar",
    callback=parse_bool_value,
    help="Automatically add events to calendar (paid plan only). Use --auto-add-to-calendar=True or --auto-add-to-calendar=False",
)
@click.option(
    "--date-filter",
    callback=parse_date_filter,
    default=None,
    help="Default date filter for event listing. "
    "Presets: 'all', 'upcoming'. "
    "Relative: 'past-3-months', 'past-2-weeks', 'past-7-days'. "
    "Date range: '2025-12-01..2026-01-31', '2025-12-01..'",
)
@click.pass_context
def update_settings(
    ctx: click.Context,
    email: Optional[str],
    sort_by: Optional[str],
    sort_order: Optional[str],
    filter_by: Optional[str],
    theme: Optional[str],
    auto_add_to_calendar: Optional[bool],
    date_filter: str | None,
) -> None:
    """Update user settings and preferences.

    Only specified fields will be updated; existing values are preserved for unspecified fields.

    Examples:
        herds user-settings update --sort-by date_start --sort-order desc --filter-by in_calendar
        herds user-settings update --theme dark --auto-add-to-calendar=True
        herds user-settings update --theme system --auto-add-to-calendar=False
        herds user-settings update --date-filter upcoming
        herds user-settings update --date-filter all
        herds user-settings update --date-filter past-3-months
        herds user-settings update --date-filter past-2-weeks
    """
    cmd = CommandBase(ctx)

    # Setup session
    email = cmd.setup_session(email, show_client_type=True)

    # Load session authentication
    cmd.load_session_auth(email)

    # Validate at least one field is being updated
    date_filter_provided = date_filter is not None
    if not any(
        [
            sort_by,
            sort_order,
            filter_by,
            theme,
            auto_add_to_calendar is not None,
            date_filter_provided,
        ]
    ):
        OutputFormatter.print_error(
            "At least one setting must be specified. Use --help for options."
        )
        sys.exit(1)

    OutputFormatter.print_info(f"Updating settings for {email}...")

    # Build request data - only include non-None values
    settings = {}
    if sort_by is not None:
        settings["sort_by"] = sort_by
    if sort_order is not None:
        settings["sort_order"] = sort_order
    if filter_by is not None:
        settings["filter_by"] = filter_by
    if theme is not None:
        settings["theme"] = theme
    if auto_add_to_calendar is not None:
        settings["auto_add_to_calendar_enabled"] = auto_add_to_calendar
    if date_filter_provided:
        settings["date_filter"] = date_filter

    data = {"settings": settings}

    # Execute API request
    url = f"{cmd.api_client.base_url}/api/user/setting"
    result = cmd.execute_api_request(
        "PUT", url, "Successfully updated user settings", json=data
    )

    # Display updated settings — branch on ignored_fields to honor partial
    # success. The server returns a non-empty ignored_fields when free-tier
    # users PATCH premium-only fields (the silent-drop behavior). Older
    # servers omit the field entirely, which we treat as an empty list.
    updated_settings = result.get("settings", {})
    ignored_fields = result.get("ignored_fields", [])

    if ignored_fields:
        count = len(ignored_fields)
        plural = "field" if count == 1 else "fields"
        OutputFormatter.print_warning(
            f"Settings partially updated — {count} {plural} ignored:"
        )
        for entry in ignored_fields:
            field_name = entry.get("field", "<unknown>")
            reason = _format_ignored_field_reason(entry.get("reason", ""))
            OutputFormatter.print_info(f"  • {field_name} — {reason}")
        OutputFormatter.print_info("Saved values:")
    else:
        OutputFormatter.print_success("Settings updated:")

    OutputFormatter.print_info(
        f"  Sort By: {updated_settings.get('sort_by', 'Not set')}"
    )
    OutputFormatter.print_info(
        f"  Filter By: {updated_settings.get('filter_by', 'Not set')}"
    )
    OutputFormatter.print_info(f"  Theme: {updated_settings.get('theme', 'Not set')}")
    OutputFormatter.print_info(
        f"  Auto Add to Calendar: {updated_settings.get('auto_add_to_calendar_enabled', 'Not set')}"
    )
    date_filter_val = updated_settings.get("date_filter")
    date_filter = date_filter_val if isinstance(date_filter_val, str) else None
    OutputFormatter.print_info(f"  Date Filter: {_format_date_filter(date_filter)}")

    # Output formatted response (JSON path includes ignored_fields verbatim)
    APIResponseHandler.format_and_output(result, cmd.output_format, skip_table=True)
