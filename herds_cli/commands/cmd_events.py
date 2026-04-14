"""
Event management commands for the Herds CLI.

This module contains commands for event CRUD operations and management.
"""

import click
import sys

from typing import Any, Optional

from herds_cli.output import OutputFormatter
from herds_cli.core.base import (
    APIResponseHandler,
    EventCommandBase,
    display_events_summary,
)


@click.group()
def events():
    """Event management commands (list, get, etc.)"""


@events.command("list")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--user-id", help="User ID to list events for (required when using --no-login)"
)
@click.option(
    "--limit", default=10, type=int, help="Maximum number of events to return"
)
@click.option("--offset", default=0, type=int, help="Number of events to skip")
@click.option(
    "--date-filter",
    default="upcoming",
    help="Date filter: 'all', 'upcoming', 'past-3-months', 'past-2-weeks', "
    "'past-7-days', '2025-12-01..2026-01-31', '2025-12-01..'",
    show_default=True,
)
@click.option(
    "--sort-by",
    default="utc_start",
    type=click.Choice(["utc_start", "date_start", "date_added", "date_modified"]),
    help="Field to sort events by",
    show_default=True,
)
@click.option(
    "--sort-order",
    default="asc",
    type=click.Choice(["asc", "desc"]),
    help="Sort order (ascending or descending)",
    show_default=True,
)
@click.option(
    "--summary",
    is_flag=True,
    help="Show a concise summary (title, date, time) instead of the full JSON response",
)
@click.pass_context
def list_events(
    ctx, email, user_id, limit, offset, date_filter, sort_by, sort_order, summary
):
    """List events for a user.

    By default shows upcoming events only. Use --date-filter to change:

    \b
    Examples:
        herds events list                              # upcoming events (default)
        herds events list --date-filter all             # all events
        herds events list --date-filter past-3-months   # past 3 months + future
        herds events list --date-filter past-2-weeks    # past 2 weeks + future
        herds events list --date-filter 2025-12-01..    # from Dec 2025 onward
    """
    cmd = EventCommandBase(ctx)

    # Get email and user_id from session
    email = cmd.setup_session(email, show_client_type=True)
    if not user_id:
        user_id = cmd.extract_user_id(email)

    OutputFormatter.print_info(f"Retrieving events for user {user_id}...")

    # Use the API client method directly (since it handles auth internally)
    result = cmd.api_client.get_events_by_user(
        email,
        user_id,
        limit=limit,
        offset=offset,
        timezone=cmd.ctx.obj["timezone"],
        date_filter=date_filter,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    events = result if isinstance(result, list) else []

    OutputFormatter.print_success(f"Successfully retrieved {len(events)} events")

    if summary:
        # Show concise summary only — no JSON blob
        _display_concise_summary(events)
    else:
        # Display events summary
        display_events_summary(events)

        # Output formatted response
        APIResponseHandler.format_and_output(result, cmd.output_format, skip_table=True)


@events.command()
@click.argument("event_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def get(ctx, event_id, email):
    """Get a specific event by ID."""
    cmd = EventCommandBase(ctx)

    # Get email from session
    email = cmd.setup_session(email, show_client_type=True)

    # Load session authentication
    cmd.load_session_auth(email)

    OutputFormatter.print_info(f"Retrieving event: {event_id}")

    # Build URL and execute API request with proper error handling
    url = f"{cmd.api_client.base_url}/api/events/{event_id}"
    params = {"timezone": cmd.ctx.obj["timezone"]}
    result = cmd.execute_api_request(
        "GET", url, "Successfully retrieved event", params=params
    )

    # Display event information using the base class method
    cmd.display_event_details(result)

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format, skip_table=True)


@events.command()
@click.argument("event_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def delete(ctx, event_id, email, yes):
    """Delete an event by ID.

    This action cannot be undone. The event and all associated data (image, S3 files, responses) will be permanently deleted.
    """
    cmd = EventCommandBase(ctx)

    # Get email and validate session exists
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)

    # Confirm deletion unless --yes flag is used
    if not yes:
        OutputFormatter.print_warning(f"You are about to delete event: {event_id}")
        OutputFormatter.print_warning("This action cannot be undone!")
        if not click.confirm("Are you sure you want to continue?"):
            OutputFormatter.print_info("Deletion cancelled.")
            return

    OutputFormatter.print_info(f"Deleting event: {event_id}")

    # Use the API client method
    result = cmd.api_client.delete_event(email, event_id)

    OutputFormatter.print_success(f"Successfully deleted event {event_id}")

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format, skip_table=True)


@events.command("by-image")
@click.argument("image_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--user-id", help="User ID to filter events for (required when using --no-login)"
)
@click.pass_context
def get_events_by_image_id(ctx, image_id, email, user_id):
    """Get events associated with a specific image ID."""
    cmd = EventCommandBase(ctx)

    # Get email and user_id from session
    email = cmd.setup_session(email, show_client_type=True)
    if not user_id:
        user_id = cmd.extract_user_id(email)

    OutputFormatter.print_info(f"Retrieving events for image {image_id}...")

    try:
        # Use the API client method directly
        result = cmd.api_client.get_events_by_image_id(
            email, image_id, user_id=user_id, timezone=cmd.ctx.obj["timezone"]
        )

        events = result if isinstance(result, list) else []

        OutputFormatter.print_success(
            f"Successfully retrieved {len(events)} events for image {image_id}"
        )

        # Display events summary
        display_events_summary(events)

        # Output formatted response
        APIResponseHandler.format_and_output(result, cmd.output_format, skip_table=True)

    except Exception as e:
        # Handle the case where no events are found (404)
        if "No events found" in str(e):
            OutputFormatter.print_warning(f"No events found for image {image_id}")
            # Return empty result for formatting
            APIResponseHandler.format_and_output([], cmd.output_format, skip_table=True)
        else:
            # Re-raise other exceptions
            raise


@events.command("update")
@click.argument("event_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option("--title", help="Event title")
@click.option("--description", help="Event description")
@click.option("--notes", help="Additional notes")
@click.option("--date-start", help="Event start date (YYYY-MM-DD format)")
@click.option("--date-end", help="Event end date (YYYY-MM-DD format)")
@click.option("--time-start", help="Event start time (HH:MM format, 24-hour)")
@click.option("--time-end", help="Event end time (HH:MM format, 24-hour)")
@click.option(
    "--is-all-day",
    type=bool,
    default=None,
    help="Mark event as all-day (true/false). Use --is-all-day=true or --is-all-day=false",
)
@click.option("--street-address", help="Street address of the event venue")
@click.option("--city", help="City where the event takes place")
@click.option("--state", help="State/province where the event takes place")
@click.option("--organizer", help="Event organizer or host name")
@click.option("--email-contact", help="Contact email address")
@click.option("--phone", help="Contact phone number")
@click.option("--website", help="Event website or registration URL")
@click.option("--category-level-1", help="Event category")
@click.option("--age-demographic", help="Event age demographic")
@click.option("--apple-calendar-id", help="Apple Calendar event ID")
@click.option("--google-calendar-id", help="Google Calendar event ID")
@click.option("--outlook-calendar-id", help="Outlook Calendar event ID")
@click.pass_context
def update_event(
    ctx,
    event_id,
    email,
    title,
    description,
    notes,
    date_start,
    date_end,
    time_start,
    time_end,
    is_all_day,
    street_address,
    city,
    state,
    organizer,
    email_contact,
    phone,
    website,
    category_level_1,
    age_demographic,
    apple_calendar_id,
    google_calendar_id,
    outlook_calendar_id,
):
    """Update an event with new details and calendar integration data.

    Allows updating event metadata (title, description, location, contact info, categories),
    date/time information, and all-day status. Also handles user-specific calendar integration data
    (Apple Calendar and Google Calendar event IDs).

    Only specified fields will be updated; existing values are preserved for unspecified fields.

    For single-day events:
    - Updating the start date will automatically sync the end date to match
    - Updating the start time will automatically adjust the end time to maintain the same duration
      (or default to 1 hour if no end time was previously set)

    Examples:
        herds events update 507f1f77bcf86cd799439011 --title "Updated Event Title"
        herds events update 507f1f77bcf86cd799439011 --date-start 2025-01-15 --time-start 14:30
        herds events update 507f1f77bcf86cd799439011 --is-all-day=true
        herds events update 507f1f77bcf86cd799439011 --is-all-day=false
        herds events update 507f1f77bcf86cd799439011 --city "New York" --organizer "John Doe"
        herds events update 507f1f77bcf86cd799439011 --apple-calendar-id evt_apple_12345
    """
    session_manager = ctx.obj["session_manager"]
    api_client = ctx.obj["api_client"]
    output_format = ctx.obj["format"]

    # Get email from session
    cmd = EventCommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)

    # Load session authentication
    cmd.load_session_auth(email)

    # Validate that at least one field is being updated
    update_fields = [
        title,
        description,
        notes,
        date_start,
        date_end,
        time_start,
        time_end,
        is_all_day,
        street_address,
        city,
        state,
        organizer,
        email_contact,
        phone,
        website,
        category_level_1,
        age_demographic,
        apple_calendar_id,
        google_calendar_id,
        outlook_calendar_id,
    ]

    if not any(field is not None for field in update_fields):
        OutputFormatter.print_error(
            "At least one field must be specified for update. Use --help to see available options."
        )
        sys.exit(1)

    OutputFormatter.print_info(f"Updating event {event_id}...")

    # Build request data — see also api.py:APIClient.update_event which
    # accepts the same field set as explicit keyword arguments.
    data = _build_event_update_data(
        title=title,
        description=description,
        notes=notes,
        date_start=date_start,
        date_end=date_end,
        time_start=time_start,
        time_end=time_end,
        is_all_day=is_all_day,
        street_address=street_address,
        city=city,
        state=state,
        organizer=organizer,
        email_contact=email_contact,
        phone=phone,
        website=website,
        category_level_1=category_level_1,
        age_demographic=age_demographic,
        apple_calendar_id=apple_calendar_id,
        google_calendar_id=google_calendar_id,
        outlook_calendar_id=outlook_calendar_id,
    )

    # Build URL and execute API request with proper error handling
    url = f"{cmd.api_client.base_url}/api/events/{event_id}"
    result = cmd.execute_api_request(
        "PUT", url, "Successfully updated event", json=data
    )

    OutputFormatter.print_success("Successfully updated event")

    # Display event information using the base class method
    cmd.display_event_details(result)

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format, skip_table=True)


def _build_event_update_data(
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    notes: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    is_all_day: Optional[bool] = None,
    street_address: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    organizer: Optional[str] = None,
    email_contact: Optional[str] = None,
    phone: Optional[str] = None,
    website: Optional[str] = None,
    category_level_1: Optional[str] = None,
    age_demographic: Optional[str] = None,
    apple_calendar_id: Optional[str] = None,
    google_calendar_id: Optional[str] = None,
    outlook_calendar_id: Optional[str] = None,
) -> dict[str, Any]:
    """Build the update payload from optional fields, omitting None values.

    Returns a dict containing only the fields the caller explicitly provided.
    The key names match the API's expected request body (see api.py:APIClient.update_event).
    """
    fields: dict[str, Any] = {
        "title": title,
        "description": description,
        "notes": notes,
        "date_start": date_start,
        "date_end": date_end,
        "time_start": time_start,
        "time_end": time_end,
        "is_all_day": is_all_day,
        "street_address": street_address,
        "city": city,
        "state": state,
        "organizer": organizer,
        "email_contact": email_contact,
        "phone": phone,
        "website": website,
        "category_level_1": category_level_1,
        "age_demographic": age_demographic,
        "apple_calendar_id": apple_calendar_id,
        "google_calendar_id": google_calendar_id,
        "outlook_calendar_id": outlook_calendar_id,
    }
    return {k: v for k, v in fields.items() if v is not None}


def _display_concise_summary(events):
    """Display a concise summary of events showing title, date, and time.

    Args:
        events: List of event dictionaries (v2 format)
    """
    if not events:
        OutputFormatter.print_warning("No events found")
        return

    for i, event in enumerate(events, 1):
        title = event.get("title", "Untitled")

        # Extract date/time from v2 nested structure
        date_info = event.get("date_info", {})
        local_info = date_info.get("local", {})
        raw_info = date_info.get("raw", {})

        # Prefer local date, fall back to raw
        date_start = local_info.get("date_start") or raw_info.get(
            "date", "Unknown date"
        )
        date_end = local_info.get("date_end")
        time_start = local_info.get("time_start", "")
        time_end = local_info.get("time_end", "")

        # Format date
        if date_start is None:
            date_start = "Unknown date"
        date_display = date_start
        if date_end and date_end != date_start:
            date_display += f" – {date_end}"

        # Format time
        time_display = ""
        if time_start:
            time_display = time_start
            if time_end:
                time_display += f"–{time_end}"

        # Build line
        line = f"  {i}. {title}  |  {date_display}"
        if time_display:
            line += f"  {time_display}"

        click.echo(line)
