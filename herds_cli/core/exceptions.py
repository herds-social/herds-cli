"""
Domain-specific exceptions for the Herds CLI.

These replace sys.exit(1) calls in helper functions, keeping process lifecycle
decisions at the CLI command boundary where they belong.
"""


class HerdsError(Exception):
    """Base exception for all Herds CLI domain errors.

    Contract: callers MUST print a user-friendly error message (via
    OutputFormatter.print_error) BEFORE raising a HerdsError subclass.
    HerdsGroup.invoke() in cli.py catches HerdsError and calls sys.exit(1)
    without printing anything — it relies on the message already being
    displayed. Raising without printing first causes a silent exit.
    """


class NoSessionsError(HerdsError):
    """No active sessions found."""

    def __init__(self):
        super().__init__("No active sessions found. Please login first.")


class AmbiguousSessionError(HerdsError):
    """Multiple sessions found and no default account configured."""

    def __init__(self, emails):
        self.emails = emails
        super().__init__(
            f"Multiple sessions found ({', '.join(emails)}). "
            "Please specify --email or set a default account."
        )


class SessionNotFoundError(HerdsError):
    """No session exists for the given email."""

    def __init__(self, email):
        self.email = email
        super().__init__(f"No session found for {email}. Please login first.")


class AuthenticationError(HerdsError):
    """Session auth could not be loaded."""

    def __init__(self, email):
        self.email = email
        super().__init__(
            f"No valid session found for {email}. Please login first."
        )


class UserIdNotFoundError(HerdsError):
    """Could not extract user_id from session data."""

    def __init__(self, email=None):
        self.email = email
        msg = "Could not determine user ID from session."
        if email:
            msg += f" (email: {email})"
        msg += " Please specify --user-id"
        super().__init__(msg)


class APIRequestError(HerdsError):
    """An API request failed (non-success status or network error)."""

    def __init__(self, message, status_code=None):
        self.status_code = status_code
        super().__init__(message)
