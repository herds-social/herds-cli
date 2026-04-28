# Auth Auto-Refresh on 401 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the saved access token expires, the CLI silently refreshes via the existing server endpoint and retries the request. If refresh also fails, surface a tailored "log in again" hint per account. Independently, stop printing progress lines before the upload actually starts.

**Architecture:** Add a one-shot 401 retry to `APIClient._make_request` — the single chokepoint for every authenticated request. The retry calls a new `refresh_session_auth(email)` method that POSTs to `/api/users/refresh-token`, persists rotated tokens, and updates the in-memory `requests.Session`. On refresh failure, `_make_request` raises a new `SessionExpiredError` whose tailored login-hint message uses the session file's `auth_provider` field. Pre-action progress prints in `cmd_image.py` move into `images.upload_image()`, emitted only after `load_session_auth(email)` confirms credentials are loadable.

**Tech Stack:** Python 3.11+, Click, Rich, requests, pytest.

**Spec:** [docs/design-docs/auth-auto-refresh.md](../../design-docs/auth-auto-refresh.md)

---

## File Structure

**Modify (production):**

- `herds_cli/core/exceptions.py` — add `SessionExpiredError(HerdsError)` class.
- `herds_cli/api.py` — add `_current_session_email` field; set it inside `load_session_auth`; add `refresh_session_auth(email)` method; add 401-retry to `_make_request` via a private `_retried: bool = False` keyword.
- `herds_cli/images.py` — move five pre-action prints from `cmd_image.py` into `upload_image()` so they fire only after `load_session_auth()` succeeds.
- `herds_cli/commands/cmd_image.py` — remove the same five pre-action prints (now done by `upload_image`).

**Modify (tests):**

- `tests/unit/test_api_client.py` — add `TestRefreshSessionAuth` and `TestMakeRequestRetry` classes.
- `tests/unit/test_image_uploader.py` — update `test_upload_http_error_raises` to reflect the new SessionExpiredError path; add a test that pre-action prints appear inside `upload_image`.
- `tests/cli/test_cli_image.py` — add `TestUploadAuthFailure` covering tailored-hint output and the no-pre-action-chatter ordering.

Prefer modifying existing files. If exception tests are not present in
`tests/unit/test_helpers.py`, adding `tests/unit/test_exceptions.py` is allowed.

---

## Task 1: Add `SessionExpiredError` exception type

**Why first:** Tasks 2 and 3 import this class. Defining it up-front lets every later task be tested independently.

**Files:**

- Modify: `herds_cli/core/exceptions.py`

- [ ] **Step 1.1: Read the existing file**

Confirm the existing `HerdsError` base class and contract docstring (callers print before raising). The new class must follow that contract.

```bash
cat herds_cli/core/exceptions.py
```

- [ ] **Step 1.2: Write the failing test**

Append to `tests/unit/test_helpers.py` (existing exception tests live here — verify by `grep -n "class TestHerds\|HerdsError\|AmbiguousSessionError" tests/unit/test_helpers.py`). If the file has no exception tests, instead add a new file `tests/unit/test_exceptions.py`:

```python
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
```

- [ ] **Step 1.3: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_exceptions.py -v
```

Expected: ImportError (`SessionExpiredError` not defined) or `AttributeError`.

- [ ] **Step 1.4: Implement `SessionExpiredError`**

Add to the bottom of `herds_cli/core/exceptions.py`:

```python
from typing import Optional


class SessionExpiredError(HerdsError):
    """Refresh-and-retry failed; user must re-authenticate.

    Raised by APIClient._make_request when a 401 response is followed by a
    failed refresh attempt (no refresh_token saved, refresh-token endpoint
    returned non-200, or network error during refresh).

    The constructed message embeds the exact `herds user login` command
    appropriate for the account's auth_provider.
    """

    def __init__(self, email: str, auth_provider: Optional[str] = None):
        self.email = email
        self.auth_provider = auth_provider
        if auth_provider == "google":
            cmd = "herds user login-google"
        else:
            cmd = f"herds user login --email {email}"
        super().__init__(f"Session expired. Please log in again:\n  {cmd}")
```

If `from typing import Optional` is already at the top of the file, place the new class after the last existing exception (do not duplicate the import).

- [ ] **Step 1.5: Run the test to verify it passes**

```bash
uv run pytest tests/unit/test_exceptions.py -v
```

Expected: 3 passed.

- [ ] **Step 1.6: Commit**

```bash
git add herds_cli/core/exceptions.py tests/unit/test_exceptions.py
git commit -m "feat: add SessionExpiredError exception with tailored login hint"
```

---

## Task 2: Track current session email in `APIClient`

**Why:** `_make_request` (Task 3) needs to know which email's session to refresh. The natural place is to remember the most-recent `load_session_auth(email)` call.

**Files:**

- Modify: `herds_cli/api.py:56-91` (constructor and `load_session_auth`)
- Modify: `tests/unit/test_api_client.py` (add tests to existing `TestLoadSessionAuth` class)

- [ ] **Step 2.1: Write the failing tests**

Append to `tests/unit/test_api_client.py` inside the existing `TestLoadSessionAuth` class:

```python
    def test_sets_current_session_email_on_success(self, mock_api_client, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tk"},
            "user_data": {"id": "u1", "email": "test@example.com"},
        })
        mock_api_client.session = requests.Session()

        mock_api_client.load_session_auth("test@example.com")

        assert mock_api_client._current_session_email == "test@example.com"

    def test_does_not_set_current_session_email_when_session_missing(self, mock_api_client):
        mock_api_client.load_session_auth("nobody@example.com")
        assert mock_api_client._current_session_email is None

    def test_no_login_mode_does_not_set_current_session_email(self, mock_session_manager):
        client = APIClient(
            base_url="http://localhost:8000",
            session_manager=mock_session_manager,
            no_login=True,
        )
        client.load_session_auth("anyone@example.com")
        assert client._current_session_email is None
```

- [ ] **Step 2.2: Run the tests to verify they fail**

```bash
uv run pytest tests/unit/test_api_client.py::TestLoadSessionAuth -v
```

Expected: 3 new tests fail with `AttributeError: ... _current_session_email`.

- [ ] **Step 2.3: Add the field and the assignment**

In `herds_cli/api.py`, modify the `__init__` method to add the new field at the end:

```python
        self.session = requests.Session()
        # Set by load_session_auth; consumed by _make_request for refresh-on-401.
        self._current_session_email: Optional[str] = None
```

In `load_session_auth`, set the field on the success paths and clear on miss. The full updated method:

```python
    def load_session_auth(self, email: str) -> bool:
        """Load session authentication for the given account.

        Mutates self.session in place: sets Authorization headers (mobile)
        or cookies (web) so subsequent requests are authenticated. Called
        by CommandBase.setup_session() during command initialisation.

        Clears any previous auth state first so that switching between
        accounts or client types never leaves stale credentials.

        Also records the email in self._current_session_email so that
        _make_request can attempt a refresh-on-401 against the right
        session. no_login mode and a missing session both leave the
        field as None.
        """
        if self.no_login:
            return True

        # Clear previous auth state to prevent stale credentials from
        # leaking when switching accounts or between mobile/web modes.
        self.session.headers.pop("Authorization", None)
        for cookie_name in ("access_token", "refresh_token"):
            self.session.cookies.pop(cookie_name, None)

        session_data = self.session_manager.load_session(email)
        if not session_data:
            return False

        client_type = session_data.get("client_type", "web")

        if client_type == "mobile":
            tokens = session_data.get("tokens", {})
            access_token = tokens.get("access_token")
            if access_token:
                self.session.headers.update({"Authorization": f"Bearer {access_token}"})
                self._current_session_email = email
                return True
            return False
        else:
            cookies = session_data.get("cookies", {})
            if not cookies:
                return False

            if "access_token" in cookies:
                self.session.cookies.set("access_token", cookies["access_token"])
            if "refresh_token" in cookies:
                self.session.cookies.set("refresh_token", cookies["refresh_token"])
            self._current_session_email = email
            return True
```

- [ ] **Step 2.4: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_api_client.py::TestLoadSessionAuth -v
```

Expected: all `TestLoadSessionAuth` tests pass (the original 6 plus 3 new = 9).

- [ ] **Step 2.5: Run the full unit suite to catch regressions**

```bash
uv run pytest tests/unit/ -q
```

Expected: 0 failures.

- [ ] **Step 2.6: Commit**

```bash
git add herds_cli/api.py tests/unit/test_api_client.py
git commit -m "feat(api): track current session email for refresh-on-401"
```

---

## Task 3: Add `refresh_session_auth()` method

**Why:** The piece that actually calls the server's `/api/users/refresh-token` endpoint, persists rotated tokens, and applies them to the live `requests.Session`. Returns True/False so the caller (Task 4) decides whether to retry or raise.

**Files:**

- Modify: `herds_cli/api.py` (new method, place after `load_session_auth`)
- Modify: `tests/unit/test_api_client.py` (new `TestRefreshSessionAuth` class)

- [ ] **Step 3.1: Write the failing tests**

Add a new class to `tests/unit/test_api_client.py` after `TestLoadSessionAuth`:

```python
class TestRefreshSessionAuth:
    def _save_mobile_session(self, sm, email="test@example.com", refresh="rfr-abc"):
        sm.save_session(email, {
            "client_type": "mobile",
            "tokens": {"access_token": "old-access", "refresh_token": refresh, "expires_in": 3600},
            "user_data": {"id": "u1", "email": email},
        })

    def _save_web_session(self, sm, email="test@example.com"):
        sm.save_session(email, {
            "client_type": "web",
            "cookies": {"access_token": "old-cookie", "refresh_token": "rfr-cookie"},
            "user_data": {"id": "u1", "email": email},
        })

    def test_mobile_success_persists_rotated_tokens(self, mock_api_client, mock_session_manager):
        self._save_mobile_session(mock_session_manager)
        mock_api_client.session = requests.Session()
        mock_api_client.load_session_auth("test@example.com")

        # Replace session.request with a mock that returns the new tokens
        with_mock = MagicMock()
        with_mock.session = MagicMock()
        # Use a spy on a fresh MagicMock so we can verify the request body
        mock_api_client.session = MagicMock()
        mock_api_client.session.headers = {"Authorization": "Bearer old-access"}
        mock_api_client.session.cookies = MagicMock()
        refreshed = MagicMock(status_code=200)
        refreshed.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
        mock_api_client.session.request.return_value = refreshed

        result = mock_api_client.refresh_session_auth("test@example.com")

        assert result is True
        # Persisted to disk
        on_disk = mock_session_manager.load_session("test@example.com")
        assert on_disk["tokens"]["access_token"] == "new-access"
        assert on_disk["tokens"]["refresh_token"] == "new-refresh"
        # Applied in-memory
        assert mock_api_client.session.headers["Authorization"] == "Bearer new-access"
        # Hit the right endpoint with the right body
        call = mock_api_client.session.request.call_args
        assert call.args[0] == "POST"
        assert call.args[1].endswith("/api/users/refresh-token")
        assert call.kwargs["json"] == {
            "refresh_token": "rfr-abc",
            "client_type": "mobile",
        }

    def test_web_success_persists_rotated_cookies(self, mock_api_client, mock_session_manager):
        self._save_web_session(mock_session_manager)
        mock_api_client.session = MagicMock()
        mock_api_client.session.headers = {}
        mock_api_client.session.cookies = MagicMock()
        refreshed = MagicMock(status_code=200)
        refreshed.json.return_value = {
            "access_token": "new-cookie-access",
            "refresh_token": "new-cookie-refresh",
            "expires_in": 3600,
        }
        mock_api_client.session.request.return_value = refreshed

        result = mock_api_client.refresh_session_auth("test@example.com")

        assert result is True
        on_disk = mock_session_manager.load_session("test@example.com")
        assert on_disk["cookies"]["access_token"] == "new-cookie-access"
        assert on_disk["cookies"]["refresh_token"] == "new-cookie-refresh"
        mock_api_client.session.cookies.set.assert_any_call("access_token", "new-cookie-access")
        mock_api_client.session.cookies.set.assert_any_call("refresh_token", "new-cookie-refresh")

    def test_no_session_returns_false(self, mock_api_client):
        assert mock_api_client.refresh_session_auth("nobody@example.com") is False

    def test_no_refresh_token_returns_false(self, mock_api_client, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "old"},  # no refresh_token
            "user_data": {"id": "u1", "email": "test@example.com"},
        })

        result = mock_api_client.refresh_session_auth("test@example.com")
        assert result is False
        # Should never have called the server
        mock_api_client.session.request.assert_not_called()

    def test_server_401_returns_false_without_persisting(self, mock_api_client, mock_session_manager):
        self._save_mobile_session(mock_session_manager)
        denied = MagicMock(status_code=401)
        denied.json.return_value = {"detail": "Invalid refresh token"}
        mock_api_client.session.request.return_value = denied

        result = mock_api_client.refresh_session_auth("test@example.com")

        assert result is False
        on_disk = mock_session_manager.load_session("test@example.com")
        # Tokens unchanged
        assert on_disk["tokens"]["access_token"] == "old-access"

    def test_no_login_mode_returns_false(self, mock_session_manager):
        client = APIClient(
            base_url="http://localhost:8000",
            session_manager=mock_session_manager,
            no_login=True,
        )
        assert client.refresh_session_auth("any@example.com") is False

    def test_missing_access_token_in_response_returns_false(self, mock_api_client, mock_session_manager):
        self._save_mobile_session(mock_session_manager)
        broken = MagicMock(status_code=200)
        broken.json.return_value = {"refresh_token": "x"}  # missing access_token
        mock_api_client.session.request.return_value = broken

        assert mock_api_client.refresh_session_auth("test@example.com") is False

    def test_network_error_returns_false(self, mock_api_client, mock_session_manager):
        self._save_mobile_session(mock_session_manager)
        mock_api_client.session.request.side_effect = requests.exceptions.ConnectionError("down")

        assert mock_api_client.refresh_session_auth("test@example.com") is False
```

- [ ] **Step 3.2: Run the tests to verify they fail**

```bash
uv run pytest tests/unit/test_api_client.py::TestRefreshSessionAuth -v
```

Expected: all 8 fail with `AttributeError: ... refresh_session_auth`.

- [ ] **Step 3.3: Implement `refresh_session_auth`**

Add to `herds_cli/api.py` immediately after `load_session_auth`:

```python
    def refresh_session_auth(self, email: str) -> bool:
        """Refresh the access token using the saved refresh token.

        On success: persists rotated tokens to the session file via
        SessionManager.save_session and mutates self.session in place
        (Authorization header for mobile, cookies for web). Returns True.

        Returns False on any of: no_login mode, no session on disk, no
        refresh_token in the session, server returned non-200, response
        body missing access_token, or network/timeout error.

        Callers (specifically _make_request's 401-retry branch) use the
        boolean return to decide between retrying the original request
        and raising SessionExpiredError.
        """
        if self.no_login:
            return False

        session_data = self.session_manager.load_session(email)
        if not session_data:
            return False

        client_type = session_data.get("client_type", "web")
        if client_type == "mobile":
            refresh_token = session_data.get("tokens", {}).get("refresh_token")
        else:
            refresh_token = session_data.get("cookies", {}).get("refresh_token")

        if not refresh_token:
            return False

        url = f"{self.base_url}/api/users/refresh-token"
        try:
            response = self.session.request(
                "POST",
                url,
                json={"refresh_token": refresh_token, "client_type": client_type},
                timeout=self.timeout,
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            return False

        if response.status_code != 200:
            return False

        try:
            body = response.json()
        except ValueError:
            return False

        new_access = body.get("access_token")
        if not new_access:
            return False
        new_refresh = body.get("refresh_token")
        new_expires_in = body.get("expires_in")

        # Persist rotated tokens to the session file. Mutate a copy so we
        # don't leak partial state if save_session raises.
        if client_type == "mobile":
            tokens = dict(session_data.get("tokens", {}))
            tokens["access_token"] = new_access
            if new_refresh:
                tokens["refresh_token"] = new_refresh
            if new_expires_in is not None:
                tokens["expires_in"] = new_expires_in
            session_data["tokens"] = tokens
        else:
            cookies = dict(session_data.get("cookies", {}))
            cookies["access_token"] = new_access
            if new_refresh:
                cookies["refresh_token"] = new_refresh
            session_data["cookies"] = cookies

        self.session_manager.save_session(email, session_data)

        # Apply the new credentials to the live requests.Session in place.
        if client_type == "mobile":
            self.session.headers.update({"Authorization": f"Bearer {new_access}"})
        else:
            self.session.cookies.set("access_token", new_access)
            if new_refresh:
                self.session.cookies.set("refresh_token", new_refresh)

        return True
```

- [ ] **Step 3.4: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_api_client.py::TestRefreshSessionAuth -v
```

Expected: 8 passed.

- [ ] **Step 3.5: Run the full unit suite**

```bash
uv run pytest tests/unit/ -q
```

Expected: 0 failures.

- [ ] **Step 3.6: Commit**

```bash
git add herds_cli/api.py tests/unit/test_api_client.py
git commit -m "feat(api): add refresh_session_auth using server refresh-token endpoint"
```

---

## Task 4: Wire 401-retry into `_make_request`

**Why:** Now we connect the pieces. `_make_request` learns to attempt one refresh on 401 and either retry (on success) or print the tailored message and raise `SessionExpiredError` (on failure).

**Files:**

- Modify: `herds_cli/api.py:231-254` (`_make_request`)
- Modify: `tests/unit/test_api_client.py` (new `TestMakeRequestRetry` class)

- [ ] **Step 4.1: Write the failing tests**

Add a new class to `tests/unit/test_api_client.py` after `TestRefreshSessionAuth`:

```python
class TestMakeRequestRetry:
    def _save_mobile_session(self, sm, email="test@example.com"):
        sm.save_session(email, {
            "client_type": "mobile",
            "tokens": {"access_token": "old", "refresh_token": "rfr"},
            "user_data": {"id": "u1", "email": email},
        })

    def test_401_then_refresh_then_retry_returns_200(self, mock_api_client, mock_session_manager):
        self._save_mobile_session(mock_session_manager)
        # Simulate that load_session_auth was called previously
        mock_api_client._current_session_email = "test@example.com"

        unauthorized = MagicMock(status_code=401)
        unauthorized.json.return_value = {"detail": "Invalid token"}
        refreshed = MagicMock(status_code=200)
        refreshed.json.return_value = {
            "access_token": "new", "refresh_token": "new-rfr", "expires_in": 3600,
        }
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"data": "yay"}
        mock_api_client.session.request.side_effect = [unauthorized, refreshed, ok]

        result = mock_api_client._make_request("GET", "http://localhost/api/x")

        assert result.status_code == 200
        assert result.json() == {"data": "yay"}
        # Three calls: original, refresh, retry
        assert mock_api_client.session.request.call_count == 3

    def test_401_refresh_fails_raises_session_expired(self, mock_api_client, mock_session_manager):
        from herds_cli.core.exceptions import SessionExpiredError

        # Mobile session with NO refresh_token → refresh_session_auth returns False
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "old"},  # no refresh_token
            "user_data": {"id": "u1", "email": "test@example.com"},
        })
        mock_api_client._current_session_email = "test@example.com"

        unauthorized = MagicMock(status_code=401)
        unauthorized.json.return_value = {"detail": "Invalid token"}
        mock_api_client.session.request.return_value = unauthorized

        with pytest.raises(SessionExpiredError) as exc_info:
            mock_api_client._make_request("GET", "http://localhost/api/x")

        assert exc_info.value.email == "test@example.com"
        assert exc_info.value.auth_provider is None

    def test_401_google_session_uses_google_hint(self, mock_api_client, mock_session_manager):
        from herds_cli.core.exceptions import SessionExpiredError

        mock_session_manager.save_session("g@example.com", {
            "client_type": "mobile",
            "auth_provider": "google",
            "tokens": {"access_token": "old"},  # no refresh_token
            "user_data": {"id": "u1", "email": "g@example.com"},
        })
        mock_api_client._current_session_email = "g@example.com"

        unauthorized = MagicMock(status_code=401)
        unauthorized.json.return_value = {"detail": "Invalid token"}
        mock_api_client.session.request.return_value = unauthorized

        with pytest.raises(SessionExpiredError) as exc_info:
            mock_api_client._make_request("GET", "http://localhost/api/x")

        assert exc_info.value.auth_provider == "google"
        assert "herds user login-google" in str(exc_info.value)

    def test_401_with_no_current_session_does_not_retry(self, mock_api_client):
        # No session loaded → _current_session_email is None → bubble 401 unchanged
        unauthorized = MagicMock(status_code=401)
        unauthorized.json.return_value = {}
        mock_api_client.session.request.return_value = unauthorized

        result = mock_api_client._make_request("GET", "http://localhost/api/x")

        assert result.status_code == 401
        # Exactly one call — no refresh attempted
        assert mock_api_client.session.request.call_count == 1

    def test_retried_kwarg_disables_retry(self, mock_api_client, mock_session_manager):
        self._save_mobile_session(mock_session_manager)
        mock_api_client._current_session_email = "test@example.com"

        unauthorized = MagicMock(status_code=401)
        unauthorized.json.return_value = {}
        mock_api_client.session.request.return_value = unauthorized

        # _retried=True → no refresh, just return the 401
        result = mock_api_client._make_request(
            "GET", "http://localhost/api/x", _retried=True,
        )

        assert result.status_code == 401
        assert mock_api_client.session.request.call_count == 1

    def test_second_401_after_successful_refresh_does_not_loop(self, mock_api_client, mock_session_manager):
        self._save_mobile_session(mock_session_manager)
        mock_api_client._current_session_email = "test@example.com"

        unauthorized_1 = MagicMock(status_code=401)
        unauthorized_1.json.return_value = {}
        refreshed = MagicMock(status_code=200)
        refreshed.json.return_value = {
            "access_token": "new", "refresh_token": "new-rfr", "expires_in": 3600,
        }
        unauthorized_2 = MagicMock(status_code=401)
        unauthorized_2.json.return_value = {}
        mock_api_client.session.request.side_effect = [
            unauthorized_1, refreshed, unauthorized_2,
        ]

        # Second 401 (after a successful refresh) should NOT trigger another
        # refresh — it's returned as-is so handle_api_error can act on it.
        result = mock_api_client._make_request("GET", "http://localhost/api/x")

        assert result.status_code == 401
        assert mock_api_client.session.request.call_count == 3

    def test_prints_tailored_hint_before_raising(
        self, mock_api_client, mock_session_manager, capsys
    ):
        from herds_cli.core.exceptions import SessionExpiredError

        mock_session_manager.save_session("alice@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "old"},
            "user_data": {"id": "u1", "email": "alice@example.com"},
        })
        mock_api_client._current_session_email = "alice@example.com"

        unauthorized = MagicMock(status_code=401)
        unauthorized.json.return_value = {}
        mock_api_client.session.request.return_value = unauthorized

        with pytest.raises(SessionExpiredError):
            mock_api_client._make_request("GET", "http://localhost/api/x")

        captured = capsys.readouterr()
        out = captured.out + captured.err
        # Print happens via OutputFormatter.print_error which uses Rich
        # console; combining stdout+stderr makes the assertion robust.
        # We just check that the tailored command appears somewhere.
        # (Note: Rich may color; strip is unnecessary for substring search.)
        assert "herds user login --email alice@example.com" in out or \
               "Session expired" in out
```

- [ ] **Step 4.2: Run the tests to verify they fail**

```bash
uv run pytest tests/unit/test_api_client.py::TestMakeRequestRetry -v
```

Expected: all 7 fail (most with status_code 401 instead of 200, or no `SessionExpiredError`).

- [ ] **Step 4.3: Modify `_make_request` to retry on 401**

Replace the existing `_make_request` in `herds_cli/api.py` (lines 231-254) with:

```python
    def _make_request(
        self,
        method: str,
        url: str,
        _retried: bool = False,
        **kwargs,
    ) -> requests.Response:
        """Make an HTTP request with optional debug logging.

        On 401, attempts one refresh-and-retry against the session
        recorded in self._current_session_email. If the refresh
        succeeds, the original request is replayed once and that
        response is returned. If the refresh fails, prints the
        tailored "log in again" hint and raises SessionExpiredError.

        The private _retried kwarg disables the retry — used by the
        recursive replay call so a second 401 propagates to the
        caller's handle_api_error untouched.
        """
        self._log_request(method, url, **kwargs)

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

        # Auto-refresh on 401 (one shot per outer call). Skipped when:
        #   - we already retried (recursive call passes _retried=True)
        #   - no session is loaded (e.g. during login itself)
        if (
            response.status_code == 401
            and not _retried
            and self._current_session_email is not None
        ):
            email = self._current_session_email
            if self.refresh_session_auth(email):
                # Replay the original request with refreshed credentials.
                return self._make_request(
                    method, url, _retried=True, **kwargs,
                )

            # Refresh failed — surface tailored hint and bail.
            # Lazy imports avoid a circular dependency through output.py.
            from .core.exceptions import SessionExpiredError
            from .output import OutputFormatter

            session_data = self.session_manager.load_session(email)
            auth_provider = (session_data or {}).get("auth_provider")
            exc = SessionExpiredError(email, auth_provider)
            OutputFormatter.print_error(str(exc))
            raise exc

        return response
```

- [ ] **Step 4.4: Run the new tests to verify they pass**

```bash
uv run pytest tests/unit/test_api_client.py::TestMakeRequestRetry -v
```

Expected: 7 passed.

- [ ] **Step 4.5: Run the full unit suite to find regressions**

```bash
uv run pytest tests/unit/ -q
```

Expected outcome: most tests pass, but one or two earlier tests in `tests/unit/test_image_uploader.py` may now fail because the upload-401 path now raises `SessionExpiredError` instead of "Upload failed". Note the failures — Task 6 fixes them.

- [ ] **Step 4.6: Commit**

```bash
git add herds_cli/api.py tests/unit/test_api_client.py
git commit -m "feat(api): auto-refresh and retry on 401 in _make_request"
```

---

## Task 5: Move pre-action progress prints into `images.upload_image()`

**Why:** Right now, `cmd_image.upload` prints five "ℹ️" lines _before_ `image_uploader.upload_image()` is called — which means they fire even when auth is broken and no upload actually happens. Moving them inside `upload_image()`, after `load_session_auth()` confirms credentials are loadable, ensures nothing is printed before real work begins.

**Files:**

- Modify: `herds_cli/images.py:97-184` (`upload_image`)
- Modify: `herds_cli/commands/cmd_image.py:103-113` (drop the prints)

- [ ] **Step 5.1: Write the failing tests**

Add to `tests/unit/test_image_uploader.py` inside the existing `TestUploadImage` class:

```python
    def test_pre_action_lines_printed_after_auth_load(
        self, uploader, mock_session_manager, tmp_path, capsys
    ):
        """All info lines (Uploading, Using timezone, etc.) must be emitted
        from upload_image — not the CLI command — and only after
        load_session_auth has succeeded."""
        _create_image_file(tmp_path, "flyer.jpg")
        self._setup_auth_and_response(uploader, mock_session_manager)

        uploader.upload_image(
            str(tmp_path / "flyer.jpg"),
            "test@example.com",
            timezone="UTC",
            alg_version="v3",
            mock_mode=True,
            add_to_calendar=True,
        )

        captured = capsys.readouterr().out + capsys.readouterr().err
        # Combine stdout+stderr because Rich routes info to stdout.
        assert "Uploading" in captured
        assert "Using timezone: UTC" in captured
        assert "Using algorithm version: v3" in captured
        assert "Using mock AI processing mode" in captured
        assert "Requesting auto-add to calendar" in captured

    def test_no_pre_action_prints_when_session_missing(
        self, uploader, tmp_path, capsys
    ):
        """If load_session_auth fails, NOTHING about uploading should be
        printed — the upload never happens. This is the regression we're
        fixing."""
        _create_image_file(tmp_path, "flyer.jpg")
        # No session saved → load_session_auth returns False.

        with pytest.raises(Exception, match="No valid session"):
            uploader.upload_image(
                str(tmp_path / "flyer.jpg"),
                "nobody@example.com",
                timezone="UTC",
            )

        captured = capsys.readouterr().out + capsys.readouterr().err
        assert "Uploading" not in captured
        assert "Using timezone" not in captured
```

- [ ] **Step 5.2: Run the tests to verify they fail**

```bash
uv run pytest tests/unit/test_image_uploader.py::TestUploadImage::test_pre_action_lines_printed_after_auth_load tests/unit/test_image_uploader.py::TestUploadImage::test_no_pre_action_prints_when_session_missing -v
```

Expected: both fail (`upload_image` doesn't print anything yet).

- [ ] **Step 5.3: Move the prints into `upload_image`**

In `herds_cli/images.py`, add the import at the top (under existing imports):

```python
from .output import OutputFormatter
```

Then update the `upload_image` method, inserting the print block immediately after `load_session_auth` succeeds and before `detect_media_type`:

```python
    def upload_image(
        self,
        file_path: str,
        email: str,
        endpoint: str = "/api/images/v2/upload",
        timezone: Optional[str] = None,
        alg_version: Optional[str] = None,
        mock_mode: bool = False,
        ocr_text: Optional[str] = None,
        barcode: Optional[str] = None,
        add_to_calendar: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Upload an image file using authenticated session.

        Pre-action info lines (Uploading…, Using timezone…, etc.) are
        emitted here — after load_session_auth confirms credentials are
        loadable, before the multipart POST. This guarantees nothing is
        printed when the upload won't actually happen.
        """
        # Validate file
        image_path = self.validate_image_file(file_path)

        # Load session authentication
        if not self.api_client.load_session_auth(email):
            raise Exception(
                f"No valid session found for {email}. Please login first using: "
                "herds user login"
            )

        # Pre-action info — only after auth has been loaded successfully.
        OutputFormatter.print_info(f"Uploading {file_path}...")
        if timezone:
            OutputFormatter.print_info(f"Using timezone: {timezone}")
        if alg_version:
            OutputFormatter.print_info(f"Using algorithm version: {alg_version}")
        if mock_mode:
            OutputFormatter.print_info("Using mock AI processing mode")
        if add_to_calendar is True:
            OutputFormatter.print_info("Requesting auto-add to calendar")
        elif add_to_calendar is False:
            OutputFormatter.print_info(
                "Skipping calendar auto-add (overrides user setting)"
            )

        # Detect media type
        media_type = self.detect_media_type(image_path)

        # Prepare file for upload
        with open(image_path, "rb") as f:
            files = {"image": (image_path.name, f, media_type)}

            data = {}
            if timezone:
                data["timezone"] = timezone
            if alg_version:
                data["alg_version"] = alg_version
            if mock_mode:
                data["mock_mode"] = "true"
            if ocr_text:
                data["ocr_text"] = ocr_text
            if barcode:
                data["barcode"] = barcode
            if add_to_calendar is not None:
                data["add_to_calendar"] = "true" if add_to_calendar else "false"

            url = f"{self.api_client.base_url}{endpoint}"
            response = self.api_client._make_request(
                "POST", url, files=files, data=data
            )

            if response.status_code == 200:
                result = response.json()
                result["file_path"] = str(image_path)
                result["media_type"] = media_type
                return result
            else:
                # Lazy import to avoid circular dependency.
                from herds_cli.core.base import APIResponseHandler

                error_msg = APIResponseHandler.format_error_message(response)
                raise Exception(f"Upload failed: {error_msg}")
```

Note: the `timezone:` line is now guarded by `if timezone:` to match the existing form-data behavior — previously, the CLI command always passed a timezone (resolved earlier), so the raw `print_info` was unconditional. Inside `upload_image`, the contract is that the parameter may be `None`, so we only print when it's set. This aligns with the data forwarding below.

- [ ] **Step 5.4: Remove the prints from `cmd_image.upload`**

In `herds_cli/commands/cmd_image.py`, replace lines 103-113 (the inside of the `try:` block up through the `result = image_uploader.upload_image(...)` call) so the `try:` body now starts directly at the upload call:

```python
    try:
        result = image_uploader.upload_image(
            file_path,
            email,
            endpoint,
            timezone=timezone,
            alg_version=alg_version,
            mock_mode=mock,
            ocr_text=ocr_text,
            barcode=barcode,
            add_to_calendar=add_to_calendar,
        )

        OutputFormatter.print_success(f"Successfully uploaded {Path(file_path).name}")
        OutputFormatter.print_info(f"Media type: {result.get('media_type', 'unknown')}")
```

- [ ] **Step 5.5: Run the new image-uploader tests**

```bash
uv run pytest tests/unit/test_image_uploader.py -v
```

Expected: the 2 new tests pass; one or two old tests (especially `test_upload_http_error_raises`) may now fail because the 401 path raises `SessionExpiredError`. Note them — Task 6 fixes them.

- [ ] **Step 5.6: Commit**

```bash
git add herds_cli/images.py herds_cli/commands/cmd_image.py tests/unit/test_image_uploader.py
git commit -m "refactor(images): move pre-action prints into upload_image after auth load"
```

---

## Task 6: Update existing tests broken by the new 401 contract

**Why:** Two existing tests assumed a 401 from upload bubbles as `Exception("Upload failed: HTTP 401: ...")`. With Task 4 in place, a 401 response triggers refresh-and-retry; if refresh also fails, `SessionExpiredError` is raised instead. Update those tests to match the new contract.

**Files:**

- Modify: `tests/unit/test_image_uploader.py` (`test_upload_http_error_raises`, `test_upload_http_error_no_json`)

- [ ] **Step 6.1: Read the existing tests**

```bash
sed -n '180,210p' tests/unit/test_image_uploader.py
```

You should see `test_upload_http_error_raises` (status=401) and `test_upload_http_error_no_json` (status=500). Only the 401 test needs an update; 500 still bubbles as `Exception("Upload failed: ...")`.

- [ ] **Step 6.2: Update `test_upload_http_error_raises`**

The session set up by `_setup_auth_and_response` saves only an `access_token` (no `refresh_token`). So in the new world, the upload's 401 triggers `refresh_session_auth`, which returns False (no refresh_token), which causes `_make_request` to raise `SessionExpiredError`. Update the assertion:

```python
    def test_upload_http_error_raises(self, uploader, mock_session_manager, tmp_path):
        """When the upload returns 401 and the session has no refresh_token,
        _make_request raises SessionExpiredError with the tailored hint."""
        from herds_cli.core.exceptions import SessionExpiredError

        _create_image_file(tmp_path, "flyer.jpg")
        mock_resp = self._setup_auth_and_response(
            uploader, mock_session_manager, status=401,
        )
        mock_resp.json.return_value = {"detail": "Token expired"}

        with pytest.raises(SessionExpiredError) as exc_info:
            uploader.upload_image(str(tmp_path / "flyer.jpg"), "test@example.com")

        assert exc_info.value.email == "test@example.com"
        assert "herds user login --email test@example.com" in str(exc_info.value)
```

The 500 test (`test_upload_http_error_no_json`) needs no changes — only 401 triggers the refresh path.

- [ ] **Step 6.3: Run the full unit suite**

```bash
uv run pytest tests/unit/ -q
```

Expected: 0 failures.

- [ ] **Step 6.4: Run the full CLI suite**

```bash
uv run pytest tests/cli/ -q
```

Expected: 0 failures (the CLI tests use 200-response mocks, so they don't hit the 401 path). If any fail, report and stop.

- [ ] **Step 6.5: Commit**

```bash
git add tests/unit/test_image_uploader.py
git commit -m "test: align upload-401 tests with new SessionExpiredError contract"
```

---

## Task 7: CLI-level integration tests for the new behaviour

**Why:** Unit tests pin per-function behavior; this task verifies the whole stack — Click command → ImageUploader → APIClient — produces the right user-visible output.

**Files:**

- Modify: `tests/cli/test_cli_image.py` (new `TestUploadAuthFailure` class)

- [ ] **Step 7.1: Read the existing test patterns**

Skim the top of `tests/cli/test_cli_image.py` and `tests/cli/conftest.py` to confirm:

- `_create_session(session_manager, email)` saves a mobile session.
- `cli_obj` fixture builds a ctx.obj with a real `ImageUploader` and a mocked-`session.request` `APIClient`.
- Existing tests do `cli_runner.invoke(cli, [...], obj=cli_obj)`.

- [ ] **Step 7.2: Add the new test class**

Append to `tests/cli/test_cli_image.py`:

```python
class TestUploadAuthFailure:
    """End-to-end coverage for the auto-refresh + tailored-hint behaviour."""

    def _create_session_with_refresh(self, sm, email="test@example.com", refresh_token="rfr"):
        sm.save_session(email, {
            "client_type": "mobile",
            "tokens": {"access_token": "old", "refresh_token": refresh_token},
            "user_data": {"id": "user-123", "email": email},
        })

    def _create_google_session_no_refresh(self, sm, email="g@example.com"):
        sm.save_session(email, {
            "client_type": "mobile",
            "auth_provider": "google",
            "tokens": {"access_token": "old"},  # no refresh_token
            "user_data": {"id": "user-456", "email": email},
        })

    def test_upload_auto_refreshes_on_401_and_succeeds(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path, mock_api_client,
    ):
        """A stale access_token with a valid refresh_token uploads cleanly:
        the user sees no auth error."""
        self._create_session_with_refresh(mock_session_manager)
        flyer = _create_image_file(tmp_path)

        unauthorized = _make_response(status_code=401, json_data={"detail": "expired"})
        refreshed = _make_response(json_data={
            "access_token": "new", "refresh_token": "new-rfr", "expires_in": 3600,
        })
        ok = _make_response(json_data={"image_id": "img-001"})
        mock_api_client.session.request.side_effect = [unauthorized, refreshed, ok]

        result = cli_runner.invoke(
            cli, ["image", "upload", str(flyer)], obj=cli_obj,
        )

        assert result.exit_code == 0, strip_ansi(result.output)
        out = strip_ansi(result.output)
        assert "Successfully uploaded" in out
        assert "Session expired" not in out  # never surfaced

    def test_upload_session_expired_password_account_shows_email_hint(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path, mock_api_client,
    ):
        """Stale access_token with no refresh_token → exit 1 with the tailored
        password-account login hint."""
        # Session has no refresh_token
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "old"},
            "user_data": {"id": "user-123", "email": "test@example.com"},
        })
        flyer = _create_image_file(tmp_path)

        unauthorized = _make_response(status_code=401, json_data={"detail": "expired"})
        mock_api_client.session.request.return_value = unauthorized

        result = cli_runner.invoke(
            cli, ["image", "upload", str(flyer)], obj=cli_obj,
        )

        assert result.exit_code == 1
        out = strip_ansi(result.output)
        assert "Session expired" in out
        assert "herds user login --email test@example.com" in out

    def test_upload_session_expired_google_account_shows_google_hint(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path, mock_api_client,
    ):
        """A google-OAuth session that fails to refresh shows `login-google`."""
        self._create_google_session_no_refresh(mock_session_manager, email="g@example.com")
        flyer = _create_image_file(tmp_path)

        unauthorized = _make_response(status_code=401, json_data={"detail": "expired"})
        mock_api_client.session.request.return_value = unauthorized

        result = cli_runner.invoke(
            cli, ["image", "upload", str(flyer), "--email", "g@example.com"],
            obj=cli_obj,
        )

        assert result.exit_code == 1
        out = strip_ansi(result.output)
        assert "Session expired" in out
        assert "herds user login-google" in out
        # The password-flavored hint must NOT appear:
        assert "login --email" not in out

    def test_no_pre_action_prints_when_session_missing(
        self, cli_runner, cli_obj, mock_session_manager, tmp_path,
    ):
        """When the session lookup fails, the CLI must not print 'Uploading…'
        or 'Using timezone…' — those should appear only after auth is loaded."""
        # No session saved — get_or_detect_session_email will trigger the
        # NoSessionsError path. We add a single session for an UNRELATED email
        # so the email arg path is exercised without a matching session.
        mock_session_manager.save_session("other@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "x"},
            "user_data": {"id": "u9", "email": "other@example.com"},
        })
        flyer = _create_image_file(tmp_path)

        result = cli_runner.invoke(
            cli, ["image", "upload", str(flyer), "--email", "ghost@example.com"],
            obj=cli_obj,
        )

        assert result.exit_code != 0
        out = strip_ansi(result.output)
        assert "Uploading" not in out
        assert "Using timezone" not in out
```

- [ ] **Step 7.3: Run the new tests**

```bash
uv run pytest tests/cli/test_cli_image.py::TestUploadAuthFailure -v
```

Expected: 4 passed.

- [ ] **Step 7.4: Run the full test suite**

```bash
uv run pytest -q
```

Expected: 0 failures, total count = (original 214) + (Task 1: 3) + (Task 2: 3) + (Task 3: 8) + (Task 4: 7) + (Task 5: 2) + (Task 7: 4) = ~241. Net new: ~27.

- [ ] **Step 7.5: Commit**

```bash
git add tests/cli/test_cli_image.py
git commit -m "test(cli): add upload auto-refresh and tailored-hint coverage"
```

---

## Task 8: Manual smoke and design-doc status update

**Why:** Verify in a real terminal that the 401-on-upload now refreshes silently when possible and emits the tailored hint when not. Then mark the design doc as Implemented.

**Files:**

- Modify: `docs/design-docs/auth-auto-refresh.md` (Status field)
- Move: `docs/exec-plans/active/auth-auto-refresh.md` → `docs/exec-plans/completed/auth-auto-refresh.md`

- [ ] **Step 8.1: Verify the build**

```bash
uv run python -m build 2>&1 | tail -5
```

Expected: `Successfully built ...`. (Skip if `python-build` isn't installed; the unit tests are the load-bearing verification.)

- [ ] **Step 8.2: Manual smoke (optional, if you have a real test server)**

If `~/dev/herds` is running and you have a session with an expired access token but valid refresh token:

```bash
uv run herds image upload <test-flyer> --poll
```

Expected: no auth error surfaces. The upload proceeds; debug logging (with `--debug-requests`) shows two `POST /api/images/v2/upload` and one `POST /api/users/refresh-token` between them.

If you don't have a real test server, this step is optional — the CLI tests in Task 7 cover the same flow with mocks.

- [ ] **Step 8.3: Update the design doc Status**

Edit `docs/design-docs/auth-auto-refresh.md` line 4:

```markdown
## Status

Implemented
```

- [ ] **Step 8.4: Move the plan to `completed/`**

```bash
git mv docs/exec-plans/active/auth-auto-refresh.md docs/exec-plans/completed/auth-auto-refresh.md
```

- [ ] **Step 8.5: Commit**

```bash
git add docs/design-docs/auth-auto-refresh.md docs/exec-plans/completed/auth-auto-refresh.md
git commit -m "docs: mark auth auto-refresh implemented and move plan to completed"
```

- [ ] **Step 8.6: Push**

```bash
git push
```

---

## Self-Review

**Spec coverage** (against `docs/design-docs/auth-auto-refresh.md`):

| Spec section                                        | Tasks                                                                       |
| --------------------------------------------------- | --------------------------------------------------------------------------- |
| Transparent refresh-and-retry at HTTP chokepoint    | Task 2 (track email), Task 3 (refresh method), Task 4 (wire it in)          |
| `SessionExpiredError` with tailored hint            | Task 1 (define), Task 4 (raise on refresh fail)                             |
| Move pre-action prints into `upload_image()`        | Task 5                                                                      |
| Negative — extra round-trip on 401                  | Inherent in Task 4                                                          |
| Negative — token rotation persisted                 | Task 3 (`save_session` call)                                                |
| Skipped — `no_login` mode                           | Task 3 (early return), Task 4 (skips when `_current_session_email is None`) |
| Skipped — network errors during refresh             | Task 3 (caught and returns False)                                           |
| Skipped — only one retry per call                   | Task 4 (`_retried` kwarg)                                                   |
| Test: refresh happy path mobile + web               | Task 3                                                                      |
| Test: refresh failure paths                         | Task 3                                                                      |
| Test: 401-retry round trip                          | Task 4                                                                      |
| Test: SessionExpiredError on refresh fail           | Task 4                                                                      |
| Test: token rotation persists                       | Task 3                                                                      |
| Test: CLI upload with stale-but-refreshable session | Task 7                                                                      |
| Test: CLI tailored hint                             | Task 7                                                                      |
| Test: pre-action lines absent on auth fail          | Tasks 5, 7                                                                  |

All spec sections covered. No gaps.

**Placeholder scan**: No "TBD/TODO", no "implement appropriate handling", every code step contains the literal code to write.

**Type consistency**: `_current_session_email`, `refresh_session_auth`, `SessionExpiredError(email, auth_provider)`, `_retried` kwarg name — used identically across Tasks 1–7.

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-driven (recommended)** — fresh subagent per task, review between tasks. Best when you want isolated context per task and explicit checkpoints.
2. **Inline execution** — execute tasks in this session via `superpowers:executing-plans`, batch with checkpoints. Faster turnaround.

Tell me which to use.
