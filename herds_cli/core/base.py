"""
Base classes and utilities for Herds CLI commands.

This module contains shared base classes and helper functions used across
all command modules.
"""

from typing import Any, Dict, List, Optional, TypedDict

import click
import requests

from herds_cli.api import APIClient
from herds_cli.core.config import Config
from herds_cli.types import EventV2, ImageV2Response, SessionData
from herds_cli.core.exceptions import (
    AmbiguousSessionError,
    APIRequestError,
    AuthenticationError,
    HerdsError,
    NoSessionsError,
    SessionNotFoundError,
    UserIdNotFoundError,
)
from herds_cli.images import ImageUploader
from herds_cli.output import OutputFormatter
from herds_cli.sessions import SessionManager


class HerdsContext(TypedDict):
    """Typed schema for the Click ctx.obj dict shared by all commands.

    Built by cli.cli() and consumed by CommandBase.__init__().

    Tests may bypass initialization by setting ctx.obj = {"_initialized": True, ...}
    with all required keys pre-populated. The _initialized key is not part of this
    TypedDict because it only exists in the test-injection path.
    """

    config: Config
    session_manager: SessionManager
    api_client: APIClient
    image_uploader: ImageUploader
    output_formatter: OutputFormatter
    timezone: str
    format: str
    base_url: str


class CommandBase:
    """Shared helper for CLI commands providing session resolution, auth loading,
    and API request execution.

    Instantiated per-command as ``cmd = CommandBase(ctx)``.  Subclasses
    EventCommandBase and ImageCommandBase add domain-specific display methods.
    Not subclassed by individual command functions — they use it by composition.
    """

    def __init__(self, ctx: click.Context) -> None:
        self.ctx = ctx
        self.config: Config = ctx.obj["config"]
        self.session_manager: SessionManager = ctx.obj["session_manager"]
        self.api_client: APIClient = ctx.obj["api_client"]
        self.output_format: str = self.config.output_format

    def setup_session(self, email: Optional[str] = None, show_client_type: bool = False) -> str:
        """Get email from parameter or auto-detect from existing sessions.

        Returns the email to use, or raises NoSessionsError/AmbiguousSessionError.
        """
        return get_or_detect_session_email(
            self.session_manager, email, show_client_type, self.config
        )

    def validate_session(self, email: str) -> SessionData:
        """Validate that a session exists for the given email.

        Returns session_data dict, or raises SessionNotFoundError.
        """
        return validate_session_exists(self.session_manager, email)

    def extract_user_id(self, email: str) -> str:
        """Extract user_id from session data.

        Returns user_id string, or raises UserIdNotFoundError.
        """
        return extract_user_id_from_session(self.session_manager, email)

    def load_session_auth(self, email: str) -> bool:
        """Load session authentication for API requests.

        Returns True if successful, raises AuthenticationError if failed.
        """
        if not self.api_client.load_session_auth(email):
            OutputFormatter.print_error(
                f"No valid session found for {email}. Please login first."
            )
            raise AuthenticationError(email)
        return True

    def execute_api_request(
        self, method: str, url: str, success_msg: Optional[str] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """Execute an API request with standardized error handling.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            url: Full API URL
            success_msg: Message to display on success
            **kwargs: Additional arguments for _make_request

        Returns:
            Parsed JSON response data on success, raises APIRequestError on error.
            The return type is Dict[str, Any] as a generic wrapper. Callers
            working with specific endpoints should reference the corresponding
            TypedDict in herds_cli/types.py for the expected response shape
            (e.g., DeleteEventResponse, UsageResponse).
        """
        try:
            response = self.api_client._make_request(method, url, **kwargs)

            if response.status_code == 200:
                result = response.json()
                if success_msg:
                    OutputFormatter.print_success(success_msg)
                return result
            else:
                APIResponseHandler.handle_error_response(response, f"{method} {url}")
                raise APIRequestError(
                    f"Failed to {method} {url}: HTTP {response.status_code}",
                    status_code=response.status_code,
                )

        except HerdsError:
            raise
        except Exception as e:
            OutputFormatter.print_error(f"API request failed: {e}")
            raise APIRequestError(f"API request failed: {e}")


class APIResponseHandler:
    """Utility class for standardized API response handling."""

    # Shared status-code-to-message defaults for HTTP error responses.
    _STATUS_DEFAULTS = {
        400: "Bad request",
        401: "Authentication required",
        403: "Access forbidden",
        404: "Not found",
        429: "Rate limit exceeded",
        500: "Internal server error",
        502: "Bad gateway",
        503: "Service unavailable",
        504: "Gateway timeout",
    }

    @staticmethod
    def format_error_message(response: requests.Response) -> str:
        """Extract a human-readable error string from an HTTP error response.

        Reads the Herds server error contract first:
            {"status": "error", "error_type": "<code>", "message": "<human>"}
        Falls back to FastAPI's ``detail`` (validation errors and any
        endpoint not using HerdsHTTPException), then a status-code default,
        then raw response text.

        When an ``error_type`` is present, it is appended in brackets so the
        machine-readable code is visible to users pasting errors into bug
        reports.

        Returns:
            Formatted string like
            ``"HTTP 400: No calendar connected. [no_calendar_connection]"``
            or ``"HTTP 401: Authentication required"`` when no error_type
            is present.
        """
        try:
            error_data = response.json()
            server_error_msg = error_data.get("message") or error_data.get("detail")
            error_type = error_data.get("error_type")

            if not server_error_msg:
                server_error_msg = APIResponseHandler._STATUS_DEFAULTS.get(
                    response.status_code, f"HTTP {response.status_code} error"
                )

            result = f"HTTP {response.status_code}: {server_error_msg}"
            if error_type:
                result += f" [{error_type}]"
            return result
        except Exception:
            error_msg = f"HTTP {response.status_code}"
            if response.text:
                error_msg += f": {response.text.strip()}"
            return error_msg

    @staticmethod
    def handle_error_response(response: requests.Response, operation_name: str) -> str:
        """Handle HTTP error responses with consistent formatting.

        Returns:
            The formatted error message string.
        """
        error_msg = APIResponseHandler.format_error_message(response)
        OutputFormatter.print_error(f"Failed to {operation_name}: {error_msg}")
        return error_msg

    @staticmethod
    def format_and_output(result: Any, output_format: str, skip_table: bool = False) -> None:
        """Format and output response data.

        Args:
            result: The data to format and output
            output_format: The output format ('json', 'table', etc.)
            skip_table: If True, skip output when format is 'table' (for commands with custom table formatting)
        """
        # Always output non-table formats (json, etc.)
        # Only skip table format if skip_table is True
        if output_format != "table" or not skip_table:
            output = OutputFormatter.format_output(result, output_format)
            if output:
                click.echo(output)


class EventCommandBase(CommandBase):
    """Base class for event-related commands with common event display logic."""

    def display_event_details(self, event_data: EventV2) -> None:
        """Extract and display event information consistently."""
        title = event_data.get("title", "Untitled")
        category = event_data.get("category_level_1", "Unknown category")

        # Extract date info from v2 nested structure
        date_info = event_data.get("date_info", {})
        raw_date = date_info.get("raw", {}).get("date", "Unknown date")
        local_info = date_info.get("local", {})
        local_date = local_info.get("date_start", "Unknown date")
        local_time = local_info.get("time_start", "")

        # Format display date
        display_date = raw_date if raw_date != "Unknown date" else local_date
        if local_time and local_time != "":
            display_date += f" at {local_time}"

        # Extract location info from v2 nested structure
        location_info = event_data.get("location", {})
        city = location_info.get("city", "")
        state = location_info.get("state", "")

        # Format location display
        location_display = ""
        if city and state:
            location_display = f" in {city}, {state}"
        elif city:
            location_display = f" in {city}"

        # Extract contact info from v2 nested structure
        contact_info = event_data.get("contact", {})
        organizer = contact_info.get("organizer", "")

        # Format organizer display
        organizer_display = ""
        if organizer:
            organizer_display = f" by {organizer}"

        display_info = f"{display_date}{location_display}{organizer_display}"

        OutputFormatter.print_info(f"Title: {title}")
        OutputFormatter.print_info(f"Date: {display_info}")
        OutputFormatter.print_info(f"Category: {category}")

        description = event_data.get("event_description")
        if description:
            OutputFormatter.print_info(f"Description: {description}")

        # Display calendar integration info if available
        user_data = event_data.get("user_data", {})
        apple_id = user_data.get("apple_calendar_id")
        if apple_id:
            OutputFormatter.print_info(f"Apple Calendar ID: {apple_id}")
        google_id = user_data.get("google_calendar_id")
        if google_id:
            OutputFormatter.print_info(f"Google Calendar ID: {google_id}")
        outlook_id = user_data.get("outlook_calendar_id")
        if outlook_id:
            OutputFormatter.print_info(f"Outlook Calendar ID: {outlook_id}")


class ImageCommandBase(CommandBase):
    """Base class for image-related commands with common image display logic."""

    def display_image_summary(self, image_data: ImageV2Response) -> None:
        """Extract and display image information consistently."""
        OutputFormatter.print_info(f"Image Name: {image_data.get('image_name', 'N/A')}")
        OutputFormatter.print_info(
            f"Media Type: {image_data.get('image_media_type', 'N/A')}"
        )
        OutputFormatter.print_info(
            f"Status: {image_data.get('image_extraction_status', 'N/A')}"
        )
        cost = image_data.get("image_cost", 0)
        cost_display = f"${cost:.4f}" if cost is not None else "Not yet calculated"
        OutputFormatter.print_info(f"Cost: {cost_display}")
        OutputFormatter.print_info(
            f"Created: {image_data.get('image_created_at', 'N/A')}"
        )

        # Display extraction error information if present
        extraction_exception = image_data.get("extraction_exception")
        if extraction_exception:
            OutputFormatter.print_error("Extraction Exception:")
            exception_type = extraction_exception.get("type", "Unknown")
            exception_message = extraction_exception.get("message", "No message")
            OutputFormatter.print_error(f"  Type: {exception_type}")
            OutputFormatter.print_error(f"  Message: {exception_message}")

            # Show additional exception details if available
            if "traceback" in extraction_exception:
                OutputFormatter.print_error(
                    "  Traceback: Available (use --format json for full details)"
                )


# Shared utility functions
def get_or_detect_session_email(
    session_manager: SessionManager,
    email: Optional[str],
    show_client_type: bool = False,
    config: Optional[Config] = None,
) -> str:
    """Get email from parameter or auto-detect from existing sessions.

    Returns the email to use, or raises NoSessionsError/AmbiguousSessionError.
    """
    if email:
        return email

    sessions = session_manager.list_sessions()
    if len(sessions) == 0:
        OutputFormatter.print_error("No active sessions found. Please login first.")
        OutputFormatter.print_info("Run: herds user login")
        raise NoSessionsError()
    elif len(sessions) == 1:
        email = sessions[0]["email"]
        OutputFormatter.print_info(f"Auto-detected session: {email}")
        return email
    else:
        # If we have a default account configured, try to use it
        if config and config.default_account:
            for session in sessions:
                if session["email"] == config.default_account:
                    return config.default_account

        # Multiple sessions and no default account configured
        OutputFormatter.print_error(
            "Multiple sessions found. Please specify --email or set a default account with:\n"
            "  herds config set default_account <email>"
        )
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

        if config and not config.default_account:
            OutputFormatter.print_info("\nTo set a default account, use:")
            OutputFormatter.print_info("  config save my-config.json")
            OutputFormatter.print_info(
                "  # Edit the file and set 'default_account' field"
            )
            OutputFormatter.print_info(
                "  # Or use: export HERDS_DEFAULT_ACCOUNT=your@email.com"
            )

        emails = [s["email"] for s in sessions]
        raise AmbiguousSessionError(emails)


def validate_session_exists(session_manager: SessionManager, email: str) -> SessionData:
    """Validate that a session exists for the given email.

    Returns session_data dict, or raises SessionNotFoundError.
    """
    session_data = session_manager.load_session(email)
    if not session_data:
        OutputFormatter.print_error(
            f"No session found for {email}. Please login first."
        )
        raise SessionNotFoundError(email)
    return session_data


def extract_user_id_from_session(session_manager: SessionManager, email: str) -> str:
    """Extract user_id from session data.

    Returns user_id string, or raises UserIdNotFoundError.
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
    raise UserIdNotFoundError(email)


def display_events_summary(events: List[EventV2]) -> None:
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
