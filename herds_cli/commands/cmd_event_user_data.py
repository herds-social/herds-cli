"""
Event user data management commands for the Herds CLI.

This module contains commands for managing user-specific event data,
including calendar integration IDs.
"""

import click
import sys
from typing import Optional

from herds_cli.output import OutputFormatter
from herds_cli.core.base import (
    CommandBase,
    APIResponseHandler,
)


@click.group()
def event_user_data() -> None:
    """Event user data management commands (update, get, delete-all)"""
    pass


@event_user_data.command("update")
@click.option("--event-id", required=True, help="Event ID")
@click.option("--user-id", help="User ID (autodetected from session if not provided)")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option("--apple-calendar-event-id", help="Apple Calendar event ID")
@click.option("--google-calendar-event-id", help="Google Calendar event ID")
@click.option("--outlook-calendar-event-id", help="Outlook Calendar event ID")
@click.pass_context
def update_event_user_data(
    ctx: click.Context,
    event_id: str,
    user_id: Optional[str],
    email: Optional[str],
    apple_calendar_event_id: Optional[str],
    google_calendar_event_id: Optional[str],
    outlook_calendar_event_id: Optional[str],
) -> None:
    """Update event user data with provider calendar event IDs.

    Set Apple, Google, and/or Outlook provider event IDs for an event. Only specified fields are
    updated; existing field values are preserved if not specified.

    Examples:
        herds event-user-data update --event-id 507f1f77bcf86cd799439011 --apple-calendar-event-id evt_apple_12345
        herds event-user-data update --event-id 507f1f77bcf86cd799439011 --google-calendar-event-id evt_google_67890
        herds event-user-data update --event-id 507f1f77bcf86cd799439011 --apple-calendar-event-id evt_apple_12345 --google-calendar-event-id evt_google_67890
    """
    cmd = CommandBase(ctx)

    # Get email and user_id from session
    email = cmd.setup_session(email, show_client_type=True)
    if not user_id:
        user_id = cmd.extract_user_id(email)

    # Load session authentication
    cmd.load_session_auth(email)

    # Validate that at least one provider event ID is provided
    if not apple_calendar_event_id and not google_calendar_event_id and not outlook_calendar_event_id:
        OutputFormatter.print_error(
            "At least one of --apple-calendar-event-id, --google-calendar-event-id, or --outlook-calendar-event-id must be provided"
        )
        sys.exit(1)

    OutputFormatter.print_info(f"Updating event user data for event {event_id}...")

    # Build request data and execute API request with proper error handling
    url = f"{cmd.api_client.base_url}/api/event-user-data"
    data = {"event_id": event_id}
    if user_id is not None:
        data["user_id"] = user_id
    if apple_calendar_event_id is not None:
        data["apple_calendar_event_id"] = apple_calendar_event_id
    if google_calendar_event_id is not None:
        data["google_calendar_event_id"] = google_calendar_event_id
    if outlook_calendar_event_id is not None:
        data["outlook_calendar_event_id"] = outlook_calendar_event_id

    result = cmd.execute_api_request(
        "POST", url, "Successfully updated event user data", json=data
    )
    OutputFormatter.print_info(f"Event ID: {result.get('event_id')}")
    OutputFormatter.print_info(f"User ID: {result.get('user_id')}")
    if apple_calendar_event_id:
        OutputFormatter.print_info(
            f"Apple Calendar event ID: {result.get('apple_calendar_event_id')}"
        )
    if google_calendar_event_id:
        OutputFormatter.print_info(
            f"Google Calendar event ID: {result.get('google_calendar_event_id')}"
        )
    if outlook_calendar_event_id:
        OutputFormatter.print_info(
            f"Outlook Calendar event ID: {result.get('outlook_calendar_event_id')}"
        )
    OutputFormatter.print_info(f"Updated: {result.get('updated_at')}")

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format)


@event_user_data.command("get")
@click.argument("event_id")
@click.option("--user-id", help="User ID (autodetected from session if not provided)")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def get_event_user_data(ctx: click.Context, event_id: str, user_id: Optional[str], email: Optional[str]) -> None:
    """Get all user data for a specific event."""
    cmd = CommandBase(ctx)

    # Get email and user_id from session
    email = cmd.setup_session(email, show_client_type=True)
    if not user_id:
        user_id = cmd.extract_user_id(email)

    # Load session authentication
    cmd.load_session_auth(email)

    OutputFormatter.print_info(f"Retrieving user data for event {event_id}...")

    # Build URL and execute API request with proper error handling
    url = f"{cmd.api_client.base_url}/api/event-user-data/{event_id}"
    params = {"user_id": user_id}
    result = cmd.execute_api_request(
        "GET", url, "Successfully retrieved user data", params=params
    )

    OutputFormatter.print_success("Successfully retrieved user data")
    OutputFormatter.print_info(f"Event ID: {result.get('event_id')}")
    OutputFormatter.print_info(f"User ID: {result.get('user_id')}")

    # Display provider calendar event IDs
    apple_event_id = result.get("apple_calendar_event_id")
    google_event_id = result.get("google_calendar_event_id")
    outlook_event_id = result.get("outlook_calendar_event_id")

    if apple_event_id:
        OutputFormatter.print_info(f"Apple Calendar event ID: {apple_event_id}")
    else:
        OutputFormatter.print_info("Apple Calendar event ID: Not set")

    if google_event_id:
        OutputFormatter.print_info(f"Google Calendar event ID: {google_event_id}")
    else:
        OutputFormatter.print_info("Google Calendar event ID: Not set")

    if outlook_event_id:
        OutputFormatter.print_info(f"Outlook Calendar event ID: {outlook_event_id}")
    else:
        OutputFormatter.print_info("Outlook Calendar event ID: Not set")

    OutputFormatter.print_info(f"Created: {result.get('created_at')}")
    OutputFormatter.print_info(f"Updated: {result.get('updated_at')}")

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format)


@event_user_data.command("delete-all")
@click.argument("event_id")
@click.option("--user-id", help="User ID (autodetected from session if not provided)")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def delete_all_event_user_data(ctx: click.Context, event_id: str, user_id: Optional[str], email: Optional[str]) -> None:
    """Delete all user data for a specific event."""
    cmd = CommandBase(ctx)

    # Get email and user_id from session
    email = cmd.setup_session(email, show_client_type=True)
    if not user_id:
        user_id = cmd.extract_user_id(email)

    # Load session authentication
    cmd.load_session_auth(email)

    OutputFormatter.print_info(f"Deleting all user data for event {event_id}...")

    # Build URL and execute API request with proper error handling
    url = f"{cmd.api_client.base_url}/api/event-user-data/{event_id}"
    params = {"user_id": user_id}
    result = cmd.execute_api_request(
        "DELETE", url, "Successfully deleted all user data", params=params
    )

    OutputFormatter.print_success("Successfully deleted all user data")
    OutputFormatter.print_info(f"Event ID: {event_id}")
    OutputFormatter.print_info(f"User ID: {user_id}")

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format)
