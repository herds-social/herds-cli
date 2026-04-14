"""
HTTP client for the Herds API.

Provides authenticated REST methods for users, events, images, and
event-user-data.  Two auth modes (web=cookies, mobile=Bearer token) are
resolved by load_session_auth().  Most methods call load_session_auth(email)
internally.

Exceptions: login(), create_user(), and google_auth() authenticate directly
and do not require a prior session.

All error paths go through handle_api_error() which always raises (NoReturn).

Used by CommandBase (core/base.py) and ImageUploader (images.py).
"""

import requests
import time
import json
from typing import Any, Dict, List, Literal, NoReturn, Optional, overload

from .sessions import SessionManager
from .types import (
    ChangePasswordResponse,
    CreateUserResponse,
    DeleteEventResponse,
    DeleteImageResponse,
    EventUserDataResponse,
    EventV2,
    LoginResponse,
    SessionData,
    UpdatePasswordResponse,
    UsageResponse,
    UserResponse,
)


class APIClient:
    """HTTP client for the Herds API with dual auth support.

    Supports two authentication modes determined at login time:
    - **web**: cookie-based (access_token/refresh_token set on requests.Session.cookies)
    - **mobile**: Bearer token (Authorization header set on requests.Session.headers)

    Authenticated methods call load_session_auth(email) internally to load
    credentials from SessionManager before making requests. This mutates
    the shared requests.Session — headers and cookies persist across calls.

    All error responses go through handle_api_error(), which always raises
    (typed -> NoReturn). The else branches in API methods are therefore
    terminal — the declared Dict[str, Any] return type is correct.

    Debug logging (request/response details) is controlled by debug_requests.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        session_manager: Optional[SessionManager] = None,
        no_login: bool = False,
        debug_requests: bool = False,
        timeout: int = 30,
        app_api_key: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.session_manager = session_manager or SessionManager()
        self.no_login = no_login
        self.debug_requests = debug_requests
        self.timeout = timeout
        self.app_api_key = app_api_key
        self.session = requests.Session()

    def load_session_auth(self, email: str) -> bool:
        """Load session authentication for the given account.

        Mutates self.session in place: sets Authorization headers (mobile)
        or cookies (web) so subsequent requests are authenticated. Called
        by CommandBase.setup_session() during command initialisation.
        """
        # If no_login is enabled, skip authentication entirely
        if self.no_login:
            return True

        session_data = self.session_manager.load_session(email)
        if not session_data:
            return False

        client_type = session_data.get("client_type", "web")

        if client_type == "mobile":
            # Mobile client - use Authorization header
            tokens = session_data.get("tokens", {})
            access_token = tokens.get("access_token")
            if access_token:
                self.session.headers.update({"Authorization": f"Bearer {access_token}"})
                return True
            return False
        else:
            # Web client - use cookies (backwards compatible)
            cookies = session_data.get("cookies", {})
            if not cookies:
                return False

            if "access_token" in cookies:
                self.session.cookies.set("access_token", cookies["access_token"])
            if "refresh_token" in cookies:
                self.session.cookies.set("refresh_token", cookies["refresh_token"])
            return True

    @overload
    def _sanitize_data(self, data: Dict[str, Any], skip_auth_redaction: bool = ...) -> Dict[str, Any]: ...
    @overload
    def _sanitize_data(self, data: List[Any], skip_auth_redaction: bool = ...) -> List[Any]: ...
    @overload
    def _sanitize_data(self, data: None, skip_auth_redaction: bool = ...) -> None: ...

    def _sanitize_data(self, data: Any, skip_auth_redaction: bool = False) -> Any:
        """Sanitize sensitive data for logging."""
        if not data:
            return data

        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                key_lower = key.lower()
                sensitive_fields = [
                    "password",
                    "token",
                    "secret",
                    "key",
                ]
                if not skip_auth_redaction:
                    sensitive_fields.append("authorization")

                if any(sensitive in key_lower for sensitive in sensitive_fields):
                    sanitized[key] = "[REDACTED]"
                elif isinstance(value, (dict, list)):
                    sanitized[key] = self._sanitize_data(value, skip_auth_redaction)
                else:
                    sanitized[key] = value
            return sanitized
        elif isinstance(data, list):
            return [self._sanitize_data(item, skip_auth_redaction) for item in data]
        else:
            return data

    def _log_request(self, method: str, url: str, **kwargs: Any) -> None:
        """Log HTTP request details if debug mode is enabled."""
        if not self.debug_requests:
            return

        print(f"[DEBUG REQUEST] {method.upper()} {url}")

        # Log headers (sanitized, but show authorization when debug is enabled)
        headers = kwargs.get("headers", {})
        if headers or self.session.headers:
            combined_headers = {**self.session.headers, **headers}
            sanitized_headers = self._sanitize_data(
                dict(combined_headers), skip_auth_redaction=True
            )
            print(f"[DEBUG REQUEST] Headers: {json.dumps(sanitized_headers, indent=2)}")

        # Log request body for POST requests
        if method.upper() in ["POST", "PUT", "PATCH"]:
            if "json" in kwargs:
                sanitized_json = self._sanitize_data(kwargs["json"])
                print(
                    f"[DEBUG REQUEST] JSON Body: {json.dumps(sanitized_json, indent=2)}"
                )
            elif "data" in kwargs:
                print(f"[DEBUG REQUEST] Data: {kwargs['data']}")
            elif "files" in kwargs:
                files_info = {}
                for key, file_data in kwargs["files"].items():
                    if isinstance(file_data, tuple) and len(file_data) >= 2:
                        files_info[key] = f"<file: {file_data[0]}>"
                    else:
                        files_info[key] = "<file data>"
                print(f"[DEBUG REQUEST] Files: {json.dumps(files_info, indent=2)}")

    def _log_response(self, response: requests.Response, start_time: float) -> None:
        """Log HTTP response details if debug mode is enabled."""
        if not self.debug_requests:
            return

        elapsed_time = time.time() - start_time
        print(
            f"[DEBUG RESPONSE] {response.status_code} {response.reason} ({elapsed_time:.2f}s)"
        )

        # Log response headers (sanitized)
        if response.headers:
            sanitized_headers = self._sanitize_data(dict(response.headers))
            print(
                f"[DEBUG RESPONSE] Headers: {json.dumps(sanitized_headers, indent=2)}"
            )

        # Log response body info
        try:
            content_length = len(response.content)
            print(f"[DEBUG RESPONSE] Body: {content_length} bytes")

            # For small responses, show the actual content (sanitized)
            if content_length < 1000 and response.headers.get(
                "content-type", ""
            ).startswith("application/json"):
                try:
                    response_json = response.json()
                    sanitized_json = self._sanitize_data(response_json)
                    print(
                        f"[DEBUG RESPONSE] JSON Content: {json.dumps(sanitized_json, indent=2)}"
                    )
                except:
                    pass
        except:
            print("[DEBUG RESPONSE] Body: Unable to determine size")

    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make an HTTP request with optional debug logging."""
        self._log_request(method, url, **kwargs)

        # Set timeout if not already specified in kwargs
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout

        start_time = time.time()
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.exceptions.Timeout:
            raise Exception(
                f"Request timed out after {self.timeout} seconds. "
                f"Please check if the server is running at {self.base_url}"
            )
        except requests.exceptions.ConnectionError as e:
            raise Exception(
                f"Failed to connect to {self.base_url}. "
                f"Please check if the server is running. Error: {e}"
            )

        self._log_response(response, start_time)
        return response

    def login(
        self, email: str, password: str, client_type: Literal["web", "mobile"] = "web"
    ) -> LoginResponse:
        """Authenticate with the API and save session."""
        url = f"{self.base_url}/api/users/login"

        response = self._make_request(
            "POST",
            url,
            json={"email": email, "password": password, "client_type": client_type},
        )

        if response.status_code == 200:
            result = response.json()

            # Handle different response types based on client_type
            session_data: SessionData

            if client_type == "mobile":
                # Mobile client - tokens are in response body
                session_data = {
                    "base_url": self.base_url,
                    "client_type": client_type,
                    "tokens": {
                        "access_token": result.get("access_token"),
                        "refresh_token": result.get("refresh_token"),
                        "expires_in": result.get("expires_in", 3600),
                    },
                    "user_data": result.get("user", {}),
                }
            else:
                # Web client - extract cookies from response
                cookies = {}
                if "access_token" in response.cookies:
                    cookies["access_token"] = response.cookies["access_token"]
                if "refresh_token" in response.cookies:
                    cookies["refresh_token"] = response.cookies["refresh_token"]

                session_data = {
                    "base_url": self.base_url,
                    "client_type": client_type,
                    "cookies": cookies,
                    "user_data": result.get("user", {}),
                }

            filename = self.session_manager.save_session(email, session_data)
            result["session_filename"] = filename

            return result
        else:
            self.handle_api_error(response)

    def create_user(self, email: str, password: str) -> CreateUserResponse:
        """Create a new user account."""
        url = f"{self.base_url}/api/users/create-user"

        headers = {}
        if self.app_api_key:
            headers["X-API-Key"] = self.app_api_key

        response = self._make_request(
            "POST", url, json={"email": email, "password": password}, headers=headers
        )

        if response.status_code == 200:
            result = response.json()
            return result
        else:
            self.handle_api_error(response)

    def google_auth(self, id_token: str, nonce: Optional[str] = None) -> LoginResponse:
        """Authenticate with Google ID token."""
        url = f"{self.base_url}/api/users/auth/google"

        request_data = {"id_token": id_token}
        if nonce:
            request_data["nonce"] = nonce

        response = self._make_request("POST", url, json=request_data)

        if response.status_code == 200:
            result = response.json()

            # Handle Google auth response (similar to login but mobile-only)
            session_data: SessionData = {
                "base_url": self.base_url,
                "client_type": "mobile",
                "auth_provider": "google",
                "tokens": {
                    "access_token": result.get("access_token"),
                    "refresh_token": result.get("refresh_token"),
                    "expires_in": result.get("expires_in", 3600),
                },
                "user_data": result.get("user", {}),
            }

            # Extract email from user data for session filename
            user_email = result.get("user", {}).get("email", "unknown")
            filename = self.session_manager.save_session(user_email, session_data)
            result["session_filename"] = filename

            return result
        else:
            self.handle_api_error(response)

    def update_password(self, email: str, new_password: str) -> UpdatePasswordResponse:
        """Update password for authenticated user (password reset flow)."""
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/users/update-password"

        response = self._make_request("POST", url, json={"password": new_password})

        if response.status_code == 200:
            return response.json()
        else:
            self.handle_api_error(response)

    def change_password(
        self,
        email: str,
        current_password: str,
        new_password: str,
        refresh_token: Optional[str] = None,
    ) -> ChangePasswordResponse:
        """Change password for authenticated user (requires current password verification)."""
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/users/change-password"

        # Prepare request data
        request_data = {
            "current_password": current_password,
            "new_password": new_password,
        }

        # Add refresh token if provided (for mobile clients)
        if refresh_token:
            request_data["refresh_token"] = refresh_token

        response = self._make_request("POST", url, json=request_data)

        if response.status_code == 200:
            return response.json()
        else:
            self.handle_api_error(response)

    def get_current_user(self, email: str) -> UserResponse:
        """Get current user information."""
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/users/me"

        response = self._make_request("GET", url)

        if response.status_code == 200:
            return response.json()
        else:
            self.handle_api_error(response)

    def get_current_usage(self, email: str) -> UsageResponse:
        """Get current usage statistics for the authenticated user."""
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/users/me/usage"

        response = self._make_request("GET", url)

        if response.status_code == 200:
            return response.json()
        else:
            self.handle_api_error(response)

    def get_events_by_user(
        self,
        email: str,
        user_id: str,
        *,
        limit: int = 10,
        offset: int = 0,
        timezone: str = "UTC",
        date_filter: str = "upcoming",
        sort_by: str = "utc_start",
        sort_order: str = "asc",
    ) -> List[EventV2]:
        """Get events for a specific user."""
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/events/v2"

        query_params = {
            "user_id": user_id,
            "limit": limit,
            "offset": offset,
            "timezone": timezone,
            "date_filter": date_filter,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }

        response = self._make_request("GET", url, params=query_params)

        if response.status_code == 200:
            return response.json()
        else:
            self.handle_api_error(response)

    def get_event_by_id(
        self,
        email: str,
        event_id: str,
        *,
        timezone: str = "UTC",
    ) -> EventV2:
        """Get a specific event by ID."""
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/events/{event_id}"

        response = self._make_request("GET", url, params={"timezone": timezone})

        if response.status_code == 200:
            return response.json()
        else:
            self.handle_api_error(response)

    def get_events_by_image_id(
        self,
        email: str,
        image_id: str,
        *,
        user_id: Optional[str] = None,
        timezone: str = "UTC",
    ) -> List[EventV2]:
        """Get events associated with a specific image ID."""
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/events/by-image/{image_id}"

        query_params: Dict[str, str] = {"timezone": timezone}
        if user_id:
            query_params["user_id"] = user_id

        response = self._make_request("GET", url, params=query_params)

        if response.status_code == 200:
            return response.json()
        else:
            self.handle_api_error(response)

    def update_event_user_data(
        self,
        email: str,
        event_id: str,
        user_id: Optional[str],
        apple_calendar_id: Optional[str],
        google_calendar_id: Optional[str],
        outlook_calendar_id: Optional[str] = None,
        no_login: bool = False,
    ) -> EventUserDataResponse:
        """Update event user data with calendar integration IDs."""
        # Load session authentication (skip when no_login=True)
        if not no_login and not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/event-user-data"

        data = {
            "event_id": event_id,
        }

        # Include user_id if provided (API will validate based on auth state)
        if user_id is not None:
            data["user_id"] = user_id

        # Only include calendar IDs that are provided
        if apple_calendar_id is not None:
            data["apple_calendar_id"] = apple_calendar_id
        if google_calendar_id is not None:
            data["google_calendar_id"] = google_calendar_id
        if outlook_calendar_id is not None:
            data["outlook_calendar_id"] = outlook_calendar_id

        response = self._make_request("POST", url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            self.handle_api_error(response)

    def get_event_user_data(
        self, email: str, event_id: str, user_id: str
    ) -> EventUserDataResponse:
        """Get all user data for a specific event."""
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/event-user-data/{event_id}"

        response = self._make_request("GET", url, params={"user_id": user_id})

        if response.status_code == 200:
            return response.json()
        else:
            self.handle_api_error(response)

    def delete_all_event_user_data(
        self, email: str, event_id: str, user_id: str
    ) -> Dict[str, Any]:
        """Delete all user data for a specific event."""
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/event-user-data/{event_id}"

        response = self._make_request("DELETE", url, params={"user_id": user_id})

        if response.status_code == 204:
            return {"message": "All user data deleted successfully"}
        else:
            self.handle_api_error(response)

    def handle_api_error(self, response: requests.Response) -> NoReturn:
        """Handle API error responses."""
        try:
            error_data = response.json()
            detail = error_data.get("detail", "Unknown error")
        except:
            detail = response.text or f"HTTP {response.status_code}"

        if response.status_code == 401:
            if self.no_login:
                raise Exception(
                    f"Authentication required: This endpoint requires login. Remove --no-login flag or authenticate first. Error: {detail}"
                )
            else:
                raise Exception(f"Authentication failed: {detail}")
        elif response.status_code == 403:
            if self.no_login:
                raise Exception(
                    f"Access forbidden: This endpoint requires authentication. Remove --no-login flag or authenticate first. Error: {detail}"
                )
            else:
                raise Exception(f"Access forbidden: {detail}")
        elif response.status_code == 409:
            raise Exception(f"User already exists: {detail}")
        elif response.status_code == 422:
            raise Exception(f"Validation error: {detail}")
        elif response.status_code == 429:
            raise Exception(f"Rate limited: {detail}")
        else:
            raise Exception(f"API error ({response.status_code}): {detail}")

    def delete_image(self, email: str, image_id: str) -> DeleteImageResponse:
        """Delete an image by ID."""
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/images/v2/{image_id}"

        response = self._make_request("DELETE", url)

        if response.status_code == 204:
            return {"message": "Image deleted successfully", "image_id": image_id}
        else:
            self.handle_api_error(response)

    def update_event(
        self,
        email: str,
        event_id: str,
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
    ) -> EventV2:
        """Update an event with new details and calendar integration data.

        The field set here mirrors cmd_events.py:_build_event_update_data —
        keep both in sync when adding or removing event fields.
        """
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/events/{event_id}"

        # Build update data - only include non-None values
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
            data["email"] = email_contact
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

        response = self._make_request("PUT", url, json=data)

        if response.status_code == 200:
            return response.json()
        else:
            self.handle_api_error(response)

    def delete_event(self, email: str, event_id: str) -> DeleteEventResponse:
        """Delete an event by ID."""
        # Load session authentication
        if not self.load_session_auth(email):
            raise Exception(f"No valid session found for {email}. Please login first.")

        url = f"{self.base_url}/api/events/{event_id}"

        response = self._make_request("DELETE", url)

        if response.status_code == 204:
            return {"message": "Event deleted successfully", "event_id": event_id}
        else:
            self.handle_api_error(response)

    def fetch_authenticated_image(self, url: str) -> bytes:
        """Fetch an image from an authenticated URL.

        Args:
            url: The authenticated URL to fetch the image from

        Returns:
            bytes: The raw image bytes

        Raises:
            Exception: If the request fails or returns an error status
        """
        response = self._make_request("GET", url)

        if response.status_code == 200:
            return response.content
        else:
            self.handle_api_error(response)
