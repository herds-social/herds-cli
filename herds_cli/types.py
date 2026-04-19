"""
Typed schemas for data structures shared across the Herds CLI.

This module is a pure leaf — it imports only from the standard library
and has no project dependencies, so any module can import from it
without circular dependency risk.
"""

from typing import Dict, List, Literal, Optional, TypedDict, runtime_checkable, Protocol


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ClientType = Literal["web", "mobile"]
"""Valid values for the client_type field in session data and login requests."""


@runtime_checkable
class GoogleOAuthConfig(Protocol):
    """Structural contract for Google OAuth configuration.

    Any object with these three attributes satisfies the protocol — the
    OAuthConfig dataclass in oauth.py, the Config object from core/config.py,
    or an ad-hoc object in tests.
    """

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str


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
    """Per-user calendar integration data attached to an event.

    Populated by either the manual /api/event-user-data endpoint or by the
    server's auto-add flow (gated by the user's auto_add_to_calendar_enabled
    setting and/or the per-upload add_to_calendar flag).

    - {provider}_calendar_id: the event's ID *inside* the user's calendar
      (proves the add succeeded for that provider).
    - calendar_id: the *target* calendar (e.g. "primary") the event went into.
    - calendar_add_error: error code if the auto-add was attempted but failed
      (e.g. AUTO_ADD_DISABLED, NO_CALENDAR_CONNECTION). Mutually exclusive
      with the *_calendar_id fields in practice.
    """

    apple_calendar_id: str
    google_calendar_id: str
    outlook_calendar_id: str
    calendar_id: str
    calendar_add_error: str


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


# ---------------------------------------------------------------------------
# API response schemas
# ---------------------------------------------------------------------------

class LoginUserData(TypedDict, total=False):
    """User data embedded in login/auth responses."""

    id: str
    user_id: str
    email: str
    created_at: str


class LoginResponse(TypedDict, total=False):
    """Response from POST /api/users/login and POST /api/users/auth/google.

    Mobile responses include access_token, refresh_token, and expires_in.
    session_filename is added client-side by APIClient after saving the session.
    """

    user: LoginUserData
    access_token: str
    refresh_token: str
    expires_in: int
    session_filename: str


class UserSettings(TypedDict, total=False):
    """User preference settings from GET /api/users/me."""

    default_calendar: Optional[str]
    sort_by: Optional[str]
    filter_by: Optional[str]


class UserInfo(TypedDict, total=False):
    """Detailed user profile from GET /api/users/me."""

    id: str
    email: str
    sign_in_method: str
    created_at: str
    last_sign_in_at: str
    email_confirmed_at: str
    settings: UserSettings


class UserResponse(TypedDict, total=False):
    """Response from GET /api/users/me."""

    user: UserInfo


EventListResponse = List[EventV2]
"""Response from GET /api/events/v2 — a JSON array of EventV2 objects."""


class CreateUserResponse(TypedDict, total=False):
    """Response from POST /api/users/create-user."""

    user: LoginUserData
    message: str


class UpdatePasswordResponse(TypedDict, total=False):
    """Response from POST /api/users/update-password."""

    user_id: str


class ChangePasswordResponse(TypedDict, total=False):
    """Response from POST /api/users/change-password."""

    user_id: str


class UsageBucket(TypedDict, total=False):
    """Usage count with limit for a time period."""

    used: int
    limit: int


class UsageResponse(TypedDict, total=False):
    """Response from GET /api/users/me/usage."""

    tier: str
    monthly: UsageBucket
    total: UsageBucket


class EventUserDataResponse(TypedDict, total=False):
    """Response from POST/GET /api/event-user-data."""

    event_id: str
    user_id: str
    apple_calendar_id: Optional[str]
    google_calendar_id: Optional[str]
    outlook_calendar_id: Optional[str]
    updated_at: str
    created_at: str


class DeleteImageResponse(TypedDict, total=False):
    """Response from DELETE /api/images/v2/{image_id}."""

    message: str
    image_id: str


class DeleteEventResponse(TypedDict, total=False):
    """Response from DELETE /api/events/{event_id}."""

    message: str
    event_id: str


class ImageUploadResponse(TypedDict, total=False):
    """Response from POST /api/images/v2/upload, enriched client-side.

    file_path and media_type are added by ImageUploader after a successful upload.
    """

    image_id: str
    image_name: str
    image_extraction_status: str
    file_path: str
    media_type: str


class UploadResult(TypedDict, total=False):
    """Single entry returned by ImageUploader.upload_multiple_images.

    On success: all ImageUploadResponse fields plus status="success".
    On error: status="error", file_path, and error message.
    """

    status: str  # "success" or "error"
    file_path: str
    error: str
    # Fields inherited from a successful ImageUploadResponse
    image_id: str
    image_name: str
    image_extraction_status: str
    media_type: str


class ExtractionException(TypedDict, total=False):
    """Error details when image extraction fails."""

    type: str
    message: str
    traceback: str


class ImageV2Response(TypedDict, total=False):
    """Response from GET /api/images/v2/{image_id}.

    Contains image metadata, processing status, and paths to
    original/resized/thumbnail versions stored in S3.
    """

    image_id: str
    image_name: str
    image_media_type: str
    image_extraction_status: str
    image_cost: float
    image_created_at: str
    image_path: str
    resized_path: str
    thumbnail_path: str
    resize_status: str
    thumbnail_status: str
    original_size_mb: float
    extraction_exception: ExtractionException
