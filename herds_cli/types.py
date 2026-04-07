"""
Typed schemas for data structures shared across the Herds CLI.

This module is a pure leaf — it imports only from the standard library
and has no project dependencies, so any module can import from it
without circular dependency risk.
"""

from typing import Dict, List, Literal, TypedDict


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ClientType = Literal["web", "mobile"]
"""Valid values for the client_type field in session data and login requests."""


# ---------------------------------------------------------------------------
# Session data (persisted as JSON in ~/.herds/)
# ---------------------------------------------------------------------------

class TokenData(TypedDict, total=False):
    """Bearer token credentials for mobile client sessions."""

    access_token: str
    refresh_token: str
    expires_in: int


class SessionUserData(TypedDict, total=False):
    """User profile data embedded in a session file.

    The server returns either 'id' or 'user_id' depending on the endpoint;
    consumers should check both (see extract_user_id_from_session).
    """

    id: str
    user_id: str
    email: str
    created_at: str


class SessionData(TypedDict, total=False):
    """Full schema for a persisted session JSON file.

    Fields are total=False because web sessions lack 'tokens' and mobile
    sessions lack 'cookies'. The metadata fields (email, created_at,
    session_filename) are added by SessionManager.save_session().
    """

    # Auth — one of these is present depending on client_type
    client_type: ClientType
    cookies: Dict[str, str]
    tokens: TokenData
    auth_provider: str  # e.g. "google" for OAuth sessions

    # User profile from the server
    user_data: SessionUserData

    # Connection
    base_url: str

    # Metadata (added by save_session)
    email: str
    created_at: str
    session_filename: str


class SessionListEntry(TypedDict):
    """Summary returned by SessionManager.list_sessions()."""

    filename: str
    email: str
    created_at: str


# ---------------------------------------------------------------------------
# Event v2 response schema (from /api/events/v2)
# ---------------------------------------------------------------------------

class DateInfoRaw(TypedDict, total=False):
    """Raw date string as extracted from the event flyer."""

    date: str


class DateInfoLocal(TypedDict, total=False):
    """Date/time values localized to the requested timezone."""

    date_start: str
    date_end: str
    time_start: str
    time_end: str


class DateInfo(TypedDict, total=False):
    """Date information with raw and localized representations."""

    raw: DateInfoRaw
    local: DateInfoLocal


class LocationInfo(TypedDict, total=False):
    """Event venue location."""

    city: str
    state: str
    street_address: str


class ContactInfo(TypedDict, total=False):
    """Event organizer and contact details."""

    organizer: str
    email: str
    phone: str
    website: str


class EventUserData(TypedDict, total=False):
    """Per-user calendar integration IDs attached to an event."""

    apple_calendar_id: str
    google_calendar_id: str
    outlook_calendar_id: str


class EventV2(TypedDict, total=False):
    """Event object from the v2 API (/api/events/v2).

    This captures the fields accessed by display_event_details() and
    display_events_summary(). The actual server response may contain
    additional fields not listed here.
    """

    title: str
    category_level_1: str
    event_description: str
    date_info: DateInfo
    location: LocationInfo
    contact: ContactInfo
    user_data: EventUserData
