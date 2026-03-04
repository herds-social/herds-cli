"""
Event user data management commands for the Herds CLI.

This module contains commands for managing user-specific event data,
including calendar integration IDs.
"""

import click
import sys

from herds_cli.output import OutputFormatter
from herds_cli.core.base import (
    CommandBase,
    APIResponseHandler,
)


@click.group()
def event_user_data():
    """Event user data management commands (update, get, delete-all)"""
    pass


# Base classes for command handling (will be moved to core module later)
@event_user_data.command("update")
@click.option("--event-id", required=True, help="Event ID")
@click.option("--user-id", help="User ID (autodetected from session if not provided)")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option("--apple-calendar-id", help="Apple Calendar event ID")
@click.option("--google-calendar-id", help="Google Calendar event ID")
@click.option("--outlook-calendar-id", help="Outlook Calendar event ID")
@click.pass_context
def update_event_user_data(
    ctx, event_id, user_id, email, apple_calendar_id, google_calendar_id, outlook_calendar_id
):
    """Update event user data with calendar integration IDs.

    Set Apple and/or Google calendar event IDs for an event. Only specified fields are updated;
    existing field values are preserved if not specified.

    Examples:
        herds_cli event-user-data update --event-id 507f1f77bcf86cd799439011 --apple-calendar-id evt_apple_12345
        herds_cli event-user-data update --event-id 507f1f77bcf86cd799439011 --google-calendar-id evt_google_67890
        herds_cli event-user-data update --event-id 507f1f77bcf86cd799439011 --apple-calendar-id evt_apple_12345 --google-calendar-id evt_google_67890
    """
    cmd = CommandBase(ctx)

    # Get email and user_id from session
    email = cmd.setup_session(email, show_client_type=True)
    if not user_id:
        user_id = cmd.extract_user_id(email)

    # Load session authentication
    cmd.load_session_auth(email)

    # Validate that at least one calendar ID is provided
    if not apple_calendar_id and not google_calendar_id and not outlook_calendar_id:
        OutputFormatter.print_error(
            "At least one of --apple-calendar-id, --google-calendar-id, or --outlook-calendar-id must be provided"
        )
        sys.exit(1)

    OutputFormatter.print_info(f"Updating event user data for event {event_id}...")

    # Build request data and execute API request with proper error handling
    url = f"{cmd.api_client.base_url}/api/event-user-data"
    data = {"event_id": event_id}
    if user_id is not None:
        data["user_id"] = user_id
    if apple_calendar_id is not None:
        data["apple_calendar_id"] = apple_calendar_id
    if google_calendar_id is not None:
        data["google_calendar_id"] = google_calendar_id
    if outlook_calendar_id is not None:
        data["outlook_calendar_id"] = outlook_calendar_id

    result = cmd.execute_api_request(
        "POST", url, "Successfully updated event user data", json=data
    )
    OutputFormatter.print_info(f"Event ID: {result.get('event_id')}")
    OutputFormatter.print_info(f"User ID: {result.get('user_id')}")
    if apple_calendar_id:
        OutputFormatter.print_info(
            f"Apple Calendar ID: {result.get('apple_calendar_id')}"
        )
    if google_calendar_id:
        OutputFormatter.print_info(
            f"Google Calendar ID: {result.get('google_calendar_id')}"
        )
    if outlook_calendar_id:
        OutputFormatter.print_info(
            f"Outlook Calendar ID: {result.get('outlook_calendar_id')}"
        )
    OutputFormatter.print_info(f"Updated: {result.get('updated_at')}")

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format)


@event_user_data.command("get")
@click.argument("event_id")
@click.option("--user-id", help="User ID (autodetected from session if not provided)")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def get_event_user_data(ctx, event_id, user_id, email):
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

    # Display calendar integration fields
    apple_id = result.get("apple_calendar_id")
    google_id = result.get("google_calendar_id")
    outlook_id = result.get("outlook_calendar_id")

    if apple_id:
        OutputFormatter.print_info(f"Apple Calendar ID: {apple_id}")
    else:
        OutputFormatter.print_info("Apple Calendar ID: Not set")

    if google_id:
        OutputFormatter.print_info(f"Google Calendar ID: {google_id}")
    else:
        OutputFormatter.print_info("Google Calendar ID: Not set")

    if outlook_id:
        OutputFormatter.print_info(f"Outlook Calendar ID: {outlook_id}")
    else:
        OutputFormatter.print_info("Outlook Calendar ID: Not set")

    OutputFormatter.print_info(f"Created: {result.get('created_at')}")
    OutputFormatter.print_info(f"Updated: {result.get('updated_at')}")

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format)


@event_user_data.command("delete-all")
@click.argument("event_id")
@click.option("--user-id", help="User ID (autodetected from session if not provided)")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def delete_all_event_user_data(ctx, event_id, user_id, email):
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
