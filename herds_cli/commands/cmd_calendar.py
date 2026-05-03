"""
Calendar OAuth integration commands for the Herds CLI.

This module contains commands for connecting and managing calendar providers
(Google Calendar, Microsoft Outlook) via OAuth.
"""

import click
import sys
import webbrowser
from typing import Any, Dict, List, Optional

from herds_cli.output import OutputFormatter
from herds_cli.core.base import CommandBase, APIResponseHandler


def _is_interactive() -> bool:
    """Whether the command is running attached to a terminal.

    Wrapped as a module-level function so tests can patch it independently
    of CliRunner's stdin replacement.
    """
    return sys.stdin.isatty()


def _prompt_for_calendar(
    calendars: List[Dict[str, Any]],
    status: Optional[Dict[str, Any]],
) -> str:
    """Show a numbered picker over `calendars` and return the chosen calendar's id.

    `status` is the GET /api/calendar/status payload (or None if the read
    failed). Used only to mark the currently-selected calendar with `(current)`
    and to compute the smart default. The default picks the current selection
    if present in the list, else the primary calendar, else the only calendar
    when the list has one entry, else no default.

    All list and prompt output goes to stderr (Click's default), keeping
    stdout clean for `--format json` callers.
    """
    current_id = (status or {}).get("calendar_id") if (status or {}).get("connected") else None
    current_idx: Optional[int] = None
    primary_idx: Optional[int] = None

    OutputFormatter.print_info("Select a calendar:")
    for i, cal in enumerate(calendars, 1):
        tags: List[str] = []
        if cal.get("primary"):
            tags.append("primary")
            if primary_idx is None:
                primary_idx = i
        if current_id is not None and cal.get("id") == current_id:
            tags.append("current")
            current_idx = i
        suffix = f" ({', '.join(tags)})" if tags else ""
        OutputFormatter.print_info(f"  {i}. {cal.get('name', 'Unnamed')}{suffix}")

    default_idx: Optional[int] = current_idx or primary_idx
    if default_idx is None and len(calendars) == 1:
        default_idx = 1

    choice = click.prompt(
        "Calendar",
        type=click.IntRange(1, len(calendars)),
        default=default_idx,
        show_default=default_idx is not None,
    )
    return calendars[choice - 1]["id"]


@click.group()
def calendar() -> None:
    """Calendar integration commands (connect, status, calendars, etc.)"""
    pass


@calendar.command("connect")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--provider",
    type=click.Choice(["google", "outlook"]),
    required=True,
    help="Calendar provider to connect",
)
@click.option(
    "--open",
    "open_browser",
    is_flag=True,
    default=False,
    help="Automatically open the OAuth URL in your browser",
)
@click.pass_context
def connect(ctx: click.Context, email: Optional[str], provider: str, open_browser: bool) -> None:
    """Start OAuth flow to connect a calendar provider.

    Returns an OAuth URL to open in a browser. The server handles the callback.

    Examples:
        herds calendar connect --provider google
        herds calendar connect --provider outlook --open
    """
    cmd = CommandBase(ctx)

    email = cmd.setup_session(email, show_client_type=True)
    cmd.load_session_auth(email)

    OutputFormatter.print_info(f"Starting {provider} calendar OAuth flow...")

    url = f"{cmd.api_client.base_url}/api/calendar/connect"
    result = cmd.execute_api_request(
        "GET", url, "OAuth URL generated", params={"provider": provider}
    )

    oauth_url = result.get("oauth_url", "")
    if not oauth_url:
        OutputFormatter.print_error("No OAuth URL returned from server.")
        sys.exit(1)

    OutputFormatter.print_info("")
    OutputFormatter.print_info("Open this URL in your browser to authorize:")
    OutputFormatter.print_info("")
    click.echo(oauth_url)
    OutputFormatter.print_info("")

    if open_browser:
        OutputFormatter.print_info("Opening browser...")
        webbrowser.open(oauth_url)
    else:
        OutputFormatter.print_info("Tip: Use --open to auto-open in your browser.")

    OutputFormatter.print_info("")
    OutputFormatter.print_info(
        "After authorizing, run 'calendar status' to verify the connection."
    )


@calendar.command("status")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def status(ctx: click.Context, email: Optional[str]) -> None:
    """Check current calendar connection status.

    Examples:
        herds calendar status
    """
    cmd = CommandBase(ctx)

    email = cmd.setup_session(email, show_client_type=True)
    cmd.load_session_auth(email)

    url = f"{cmd.api_client.base_url}/api/calendar/status"
    result = cmd.execute_api_request("GET", url)

    connected = result.get("connected", False)
    if connected:
        OutputFormatter.print_success("Calendar connected!")
        OutputFormatter.print_info(f"  Provider:  {result.get('provider', 'N/A')}")
        OutputFormatter.print_info(f"  Calendar:  {result.get('calendar_name') or 'Not set'}")
        OutputFormatter.print_info(f"  Connected: {result.get('connected_at', 'N/A')}")
    else:
        OutputFormatter.print_warning("No calendar connected.")
        OutputFormatter.print_info(
            "Use 'calendar connect --provider google' or '--provider outlook' to connect."
        )

    APIResponseHandler.format_and_output(result, cmd.output_format)


@calendar.command("list")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def list_calendars(ctx: click.Context, email: Optional[str]) -> None:
    """List available calendars from the connected provider.

    Requires an active calendar connection.

    Examples:
        herds calendar list
    """
    cmd = CommandBase(ctx)

    email = cmd.setup_session(email, show_client_type=True)
    cmd.load_session_auth(email)

    url = f"{cmd.api_client.base_url}/api/calendar/list"

    try:
        response = cmd.api_client._make_request("GET", url)

        if response.status_code == 200:
            result = response.json()
            calendars = result.get("calendars", [])
            if not calendars:
                OutputFormatter.print_warning("No calendars found.")
                return

            OutputFormatter.print_info(f"Found {len(calendars)} calendar(s):")
            OutputFormatter.print_info("")
            for i, cal in enumerate(calendars, 1):
                primary_tag = " (primary)" if cal.get("primary") else ""
                OutputFormatter.print_info(f"  {i}. {cal.get('name', 'Unnamed')}{primary_tag}")
                OutputFormatter.print_info(f"     ID: {cal.get('id', 'N/A')}")

            OutputFormatter.print_info("")
            OutputFormatter.print_info(
                "Use 'calendar set-calendar --calendar-id <ID>' to select one."
            )

            APIResponseHandler.format_and_output(result, cmd.output_format)
            return

        # Error path — parse body once, branch on known error types.
        try:
            error_data = response.json()
        except Exception:
            error_data = {}

        error_type = error_data.get("error_type", "")
        message = error_data.get("message", "")

        if response.status_code == 400 and error_type == "no_calendar_connection":
            OutputFormatter.print_error(message or "No calendar connected.")
            OutputFormatter.print_info(
                "Run 'herds calendar connect --provider google' (or outlook) to connect."
            )
        elif response.status_code == 502 and error_type == "calendar_provider_error":
            OutputFormatter.print_error(message or "Calendar provider error.")
        else:
            APIResponseHandler.handle_error_response(response, "list calendars")

        sys.exit(1)
    except Exception as e:
        OutputFormatter.print_error(f"API request failed: {e}")
        sys.exit(1)


@calendar.command("set-calendar")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--calendar-id",
    default=None,
    help="Calendar ID to use for new events. If omitted on a TTY, an interactive picker is shown.",
)
@click.pass_context
def set_calendar(ctx: click.Context, email: Optional[str], calendar_id: Optional[str]) -> None:
    """Set which calendar to use for new events.

    Run without arguments to pick a calendar interactively. Pass --calendar-id
    to bypass the picker (required for non-interactive contexts: scripts, CI,
    pipes, or --format json).

    Examples:
        herds calendar set-calendar
        herds calendar set-calendar --calendar-id primary
    """
    cmd = CommandBase(ctx)

    email = cmd.setup_session(email, show_client_type=True)
    cmd.load_session_auth(email)

    if calendar_id is None:
        if not _is_interactive():
            OutputFormatter.print_error(
                "--calendar-id is required when running non-interactively."
            )
            OutputFormatter.print_info(
                "Run 'herds calendar list' to see available calendars."
            )
            sys.exit(1)

        calendars = _fetch_calendars_for_picker(cmd)
        status = _fetch_status_for_picker(cmd)
        calendar_id = _prompt_for_calendar(calendars, status)

    url = f"{cmd.api_client.base_url}/api/calendar/settings"
    result = cmd.execute_api_request(
        "PUT", url, "Calendar selection updated", json={"calendar_id": calendar_id}
    )

    OutputFormatter.print_info(f"  Calendar ID:   {result.get('calendar_id', 'N/A')}")
    OutputFormatter.print_info(f"  Calendar Name: {result.get('calendar_name') or 'N/A'}")

    APIResponseHandler.format_and_output(result, cmd.output_format)


def _fetch_calendars_for_picker(cmd: CommandBase) -> List[Dict[str, Any]]:
    """Fetch the user's calendars for the picker. Exits on connection / empty errors."""
    url = f"{cmd.api_client.base_url}/api/calendar/list"
    response = cmd.api_client._make_request("GET", url)

    if response.status_code != 200:
        try:
            error_data = response.json()
        except Exception:
            error_data = {}
        error_type = error_data.get("error_type", "")
        message = error_data.get("message", "")
        if response.status_code == 400 and error_type == "no_calendar_connection":
            OutputFormatter.print_error(message or "No calendar connected.")
            OutputFormatter.print_info(
                "Run 'herds calendar connect --provider google' (or outlook) to connect."
            )
        else:
            APIResponseHandler.handle_error_response(response, "list calendars")
        sys.exit(1)

    calendars = response.json().get("calendars", [])
    if not calendars:
        OutputFormatter.print_error(
            "No calendars found. Verify your provider connection."
        )
        sys.exit(1)
    return calendars


def _fetch_status_for_picker(cmd: CommandBase) -> Optional[Dict[str, Any]]:
    """Best-effort fetch of the connection status. Returns None on any failure
    so the picker can still run without the (current) tag."""
    url = f"{cmd.api_client.base_url}/api/calendar/status"
    try:
        response = cmd.api_client._make_request("GET", url)
    except Exception:
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except Exception:
        return None


@calendar.command("disconnect")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def disconnect(ctx: click.Context, email: Optional[str], yes: bool) -> None:
    """Disconnect the calendar provider and remove stored tokens.

    Examples:
        herds calendar disconnect
        herds calendar disconnect -y
    """
    cmd = CommandBase(ctx)

    email = cmd.setup_session(email, show_client_type=True)
    cmd.load_session_auth(email)

    if not yes:
        click.confirm(
            "This will disconnect your calendar and remove stored tokens. Continue?",
            abort=True,
        )

    url = f"{cmd.api_client.base_url}/api/calendar/disconnect"

    try:
        response = cmd.api_client._make_request("DELETE", url)

        if response.status_code == 204:
            OutputFormatter.print_success("Calendar disconnected successfully.")
        else:
            APIResponseHandler.handle_error_response(response, "disconnect calendar")
            sys.exit(1)
    except Exception as e:
        OutputFormatter.print_error(f"API request failed: {e}")
        sys.exit(1)


@calendar.command("add-event")
@click.argument("event_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def add_event(ctx: click.Context, event_id: str, email: Optional[str]) -> None:
    """Add a Herds event to your connected calendar.

    Examples:
        herds calendar add-event abc123
    """
    cmd = CommandBase(ctx)

    email = cmd.setup_session(email, show_client_type=True)
    cmd.load_session_auth(email)

    url = f"{cmd.api_client.base_url}/api/calendar/events/{event_id}"

    try:
        response = cmd.api_client._make_request("POST", url)

        if response.status_code == 201:
            result = response.json()
            OutputFormatter.print_success("Event added to calendar!")
            OutputFormatter.print_info(f"  Provider:          {result.get('provider', 'N/A')}")
            OutputFormatter.print_info(f"  Calendar Event ID: {result.get('calendar_event_id', 'N/A')}")
            APIResponseHandler.format_and_output(result, cmd.output_format)
            return

        # Handle known error types
        try:
            error_data = response.json()
        except Exception:
            error_data = {}

        error_type = error_data.get("error_type", "")
        message = error_data.get("message", "")

        # 409 already_in_calendar: event was previously added to the user's
        # calendar — safe to ignore, but surface the existing calendar ID.
        if response.status_code == 409 and error_type == "already_in_calendar":
            OutputFormatter.print_warning("Event is already in your calendar.")
            cal_id = error_data.get("calendar_event_id", "")
            if cal_id:
                OutputFormatter.print_info(f"  Calendar Event ID: {cal_id}")
            return
        # 400 no_calendar_connection: user hasn't run 'calendar connect' yet,
        # so the server has no OAuth token for their calendar provider.
        elif response.status_code == 400 and error_type == "no_calendar_connection":
            OutputFormatter.print_error(message or "No calendar connected.")
            OutputFormatter.print_info("Run 'calendar connect --provider google' (or outlook) first.")
        # 400 no_calendar_selected: user connected a provider but hasn't
        # chosen which calendar to write events to via 'calendar set-calendar'.
        elif response.status_code == 400 and error_type == "no_calendar_selected":
            OutputFormatter.print_error(message or "No calendar selected.")
            OutputFormatter.print_info("Run 'calendar set-calendar --calendar-id <ID>' first.")
        # 502 calendar_provider_error: the upstream calendar API (Google/Outlook)
        # returned an error — transient or permissions-related.
        elif response.status_code == 502 and error_type == "calendar_provider_error":
            OutputFormatter.print_error(message or "Calendar provider error.")
        # 404: the event_id doesn't match any event in the Herds database.
        elif response.status_code == 404:
            OutputFormatter.print_error("Event not found.")
        else:
            APIResponseHandler.handle_error_response(response, "add event to calendar")

        sys.exit(1)
    except Exception as e:
        OutputFormatter.print_error(f"API request failed: {e}")
        sys.exit(1)


@calendar.command("remove-event")
@click.argument("event_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def remove_event(ctx: click.Context, event_id: str, email: Optional[str]) -> None:
    """Remove a Herds event from your connected calendar.

    Idempotent — succeeds even if the event isn't in a calendar.

    Examples:
        herds calendar remove-event abc123
    """
    cmd = CommandBase(ctx)

    email = cmd.setup_session(email, show_client_type=True)
    cmd.load_session_auth(email)

    url = f"{cmd.api_client.base_url}/api/calendar/events/{event_id}"

    try:
        response = cmd.api_client._make_request("DELETE", url)

        if response.status_code == 204:
            OutputFormatter.print_success("Event removed from calendar.")
        elif response.status_code == 404:
            OutputFormatter.print_error("Event not found.")
            sys.exit(1)
        else:
            APIResponseHandler.handle_error_response(response, "remove event from calendar")
            sys.exit(1)
    except Exception as e:
        OutputFormatter.print_error(f"API request failed: {e}")
        sys.exit(1)
