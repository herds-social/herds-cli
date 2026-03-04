"""
Event management commands for the Herds CLI.

This module contains commands for event CRUD operations and management.
"""

import click
import sys

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
        herds_cli events list                              # upcoming events (default)
        herds_cli events list --date-filter all             # all events
        herds_cli events list --date-filter past-3-months   # past 3 months + future
        herds_cli events list --date-filter past-2-weeks    # past 2 weeks + future
        herds_cli events list --date-filter 2025-12-01..    # from Dec 2025 onward
    """
    cmd = EventCommandBase(ctx)

    # Get email and user_id from session
    email = cmd.setup_session(email, show_client_type=True)
    if not user_id:
        user_id = cmd.extract_user_id(email)

    # Build parameters
    params = {
        "limit": limit,
        "offset": offset,
        "timezone": cmd.ctx.obj["timezone"],
        "date_filter": date_filter,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }

    OutputFormatter.print_info(f"Retrieving events for user {user_id}...")

    # Use the API client method directly (since it handles auth internally)
    result = cmd.api_client.get_events_by_user(email, user_id, **params)

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

    # Build parameters
    params = {
        "timezone": cmd.ctx.obj["timezone"],
    }

    OutputFormatter.print_info(f"Retrieving events for image {image_id}...")

    try:
        # Use the API client method directly
        result = cmd.api_client.get_events_by_image_id(
            email, image_id, user_id=user_id, **params
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
        herds_cli events update 507f1f77bcf86cd799439011 --title "Updated Event Title"
        herds_cli events update 507f1f77bcf86cd799439011 --date-start 2025-01-15 --time-start 14:30
        herds_cli events update 507f1f77bcf86cd799439011 --is-all-day=true
        herds_cli events update 507f1f77bcf86cd799439011 --is-all-day=false
        herds_cli events update 507f1f77bcf86cd799439011 --city "New York" --organizer "John Doe"
        herds_cli events update 507f1f77bcf86cd799439011 --apple-calendar-id evt_apple_12345
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

    # Build request data - only include non-None values
    data = {}

    # Core event fields
    if title is not None:
        data["title"] = title
    if description is not None:
        data["description"] = description
    if notes is not None:
        data["notes"] = notes

    # Date/time fields
    if date_start is not None:
        data["date_start"] = date_start
    if date_end is not None:
        data["date_end"] = date_end
    if time_start is not None:
        data["time_start"] = time_start
    if time_end is not None:
        data["time_end"] = time_end
    if is_all_day is not None:
        data["is_all_day"] = is_all_day

    # Location fields
    if street_address is not None:
        data["street_address"] = street_address
    if city is not None:
        data["city"] = city
    if state is not None:
        data["state"] = state

    # Contact fields
    if organizer is not None:
        data["organizer"] = organizer
    if email_contact is not None:
        data["email_contact"] = email_contact
    if phone is not None:
        data["phone"] = phone
    if website is not None:
        data["website"] = website

    # Category fields
    if category_level_1 is not None:
        data["category_level_1"] = category_level_1
    if age_demographic is not None:
        data["age_demographic"] = age_demographic

    # Calendar integration fields
    if apple_calendar_id is not None:
        data["apple_calendar_id"] = apple_calendar_id
    if google_calendar_id is not None:
        data["google_calendar_id"] = google_calendar_id
    if outlook_calendar_id is not None:
        data["outlook_calendar_id"] = outlook_calendar_id

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


# Helper functions (will be moved to core module later)
def get_or_detect_session_email(session_manager, email, show_client_type=False):
    """Get email from parameter or auto-detect from existing sessions.

    Returns the email to use, or exits with error if no valid session found.
    """
    if email:
        return email

    sessions = session_manager.list_sessions()
    if len(sessions) == 0:
        OutputFormatter.print_error("No active sessions found. Please login first.")
        OutputFormatter.print_info("Run: python herds_cli/cli.py user login")
        sys.exit(1)
    elif len(sessions) == 1:
        email = sessions[0]["email"]
        OutputFormatter.print_info(f"Auto-detected session: {email}")
        return email
    else:
        OutputFormatter.print_error("Multiple sessions found. Please specify --email")
        OutputFormatter.print_info("Available sessions:")
        for session in sessions:
            if show_client_type:
                full_session = session_manager.load_session(session["email"])
                client_type = (
                    full_session.get("client_type", "web")
                    if full_session
                    else "unknown"
                )
                click.echo(f"  • {session['email']} ({client_type})")
            else:
                click.echo(f"  • {session['email']}")
        sys.exit(1)


def validate_session_exists(session_manager, email):
    """Validate that a session exists for the given email.

    Returns session_data dict, or exits with error if session not found.
    """
    session_data = session_manager.load_session(email)
    if not session_data:
        OutputFormatter.print_error(
            f"No session found for {email}. Please login first."
        )
        sys.exit(1)
    return session_data


def extract_user_id_from_session(session_manager, email):
    """Extract user_id from session data.

    Returns user_id string, or exits with error if not found.
    """
    session_data = session_manager.load_session(email)
    if session_data and "user_data" in session_data:
        user_data = session_data["user_data"]
        user_id = user_data.get("id") or user_data.get("user_id")
        if user_id:
            return user_id

    OutputFormatter.print_error(
        "Could not determine user ID from session. Please specify --user-id"
    )
    sys.exit(1)


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


def display_events_summary(events):
    """Display a formatted summary of events.

    Args:
        events: List of event dictionaries (v2 format)
    """
    if not events:
        OutputFormatter.print_warning("No events found")
        return

    OutputFormatter.print_info("Events Summary:")
    for i, event in enumerate(events[:5], 1):  # Show first 5
        title = event.get("title", "Untitled")
        category = event.get("category_level_1", "Unknown category")

        # Extract date info from v2 nested structure
        date_info = event.get("date_info", {})
        raw_date = date_info.get("raw", {}).get("date", "Unknown date")
        local_info = date_info.get("local", {})
        local_date = local_info.get("date_start", "Unknown date")
        local_time = local_info.get("time_start", "")

        # Format display date
        display_date = raw_date if raw_date != "Unknown date" else local_date
        # Ensure display_date is never None
        if display_date is None:
            display_date = "Unknown date"
        if local_time and local_time != "":
            display_date += f" at {local_time}"

        # Extract location info from v2 nested structure
        location_info = event.get("location", {})
        city = location_info.get("city", "")
        state = location_info.get("state", "")

        # Format location display
        location_display = ""
        if city and state:
            location_display = f" in {city}, {state}"
        elif city:
            location_display = f" in {city}"

        # Extract contact info from v2 nested structure
        contact_info = event.get("contact", {})
        organizer = contact_info.get("organizer", "")

        # Format organizer display
        organizer_display = ""
        if organizer:
            organizer_display = f" by {organizer}"

        display_info = f"{display_date}{location_display}{organizer_display}"

        OutputFormatter.print_info(f"  {i}. {title} - {display_info} ({category})")

    if len(events) > 5:
        OutputFormatter.print_info(f"  ... and {len(events) - 5} more events")
