"""Unit tests for core/exceptions.py."""

import pytest

from herds_cli.core.exceptions import HerdsError, SessionExpiredError


class TestSessionExpiredError:
    def test_password_account_uses_email_login_hint(self):
        err = SessionExpiredError("alice@example.com", auth_provider=None)
        assert str(err) == (
            "Session expired. Please log in again:\n"
            "  herds user login --email alice@example.com"
        )
        assert err.email == "alice@example.com"
        assert err.auth_provider is None

    def test_google_account_uses_google_login_hint(self):
        err = SessionExpiredError("bob@example.com", auth_provider="google")
        assert str(err) == (
            "Session expired. Please log in again:\n"
            "  herds user login-google"
        )
        assert err.auth_provider == "google"

    def test_is_a_herds_error(self):
        err = SessionExpiredError("u@example.com", None)
        assert isinstance(err, HerdsError)
