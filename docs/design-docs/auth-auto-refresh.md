# Auth Auto-Refresh on 401

## Status

Approved

## Context

When a saved access token expires, every authenticated CLI command fails with
`HTTP 401: Invalid authentication token. Please log in again.` This is jarring
because:

1. Mobile sessions persist a `refresh_token` (`api.py:281`) and the server
   already exposes `POST /api/users/refresh-token` (`user_endpoints.py:1551`),
   yet the CLI never calls it. The user has to manually re-run `herds user
login` to get back to a working state.
2. Commands print progress claims ("Uploading {file*path}...") \_before* any
   HTTP work happens. When the call then fails on auth, the output reads as if
   work was attempted when in fact nothing was sent over the wire.
3. The follow-up "log in again" message is generic — the user has to figure
   out whether to use `herds user login --email <email>` (password account) or
   `herds user login-google` (OAuth account).

## Decision

### 1. Transparent refresh-and-retry at the HTTP chokepoint

Add the retry loop to `APIClient._make_request` (`api.py:231`), the single
function every authenticated request flows through. When a request returns
401 and a session email is associated with the client, attempt one refresh
via the existing server endpoint, persist the rotated tokens to the session
file, and retry the original request once.

New `APIClient` method:

```
def refresh_session_auth(self, email: str) -> bool:
    """Use the saved refresh_token to obtain a new access_token.

    On success: updates the session file with rotated tokens and mutates
    self.session.headers (mobile) or cookies (web). Returns True.
    On any non-200 or missing refresh_token: returns False.
    """
```

`_make_request` tracks the email of the most recently loaded session via a
new `self._current_session_email: Optional[str]` field, set inside
`load_session_auth(email)` and never set when `no_login` is true. The retry
is gated by a private `_make_request(..., _retried: bool = False)` keyword
argument: the recursive retry call passes `_retried=True`, which prevents a
second refresh attempt and guarantees at most one retry per outer call.

### 2. Tailored "log in again" hint via typed exception

Add `SessionExpiredError(HerdsError)` to `core/exceptions.py`:

```
class SessionExpiredError(HerdsError):
    def __init__(self, email: str, auth_provider: Optional[str]):
        if auth_provider == "google":
            cmd = "herds user login-google"
        else:
            cmd = f"herds user login --email {email}"
        super().__init__(
            f"Session expired. Please log in again:\n  {cmd}"
        )
```

When `refresh_session_auth` returns False inside `_make_request`'s 401 branch,
look up `auth_provider` via `self.session_manager.load_session(email)` (which
returns the on-disk `SessionData`) and raise
`SessionExpiredError(email, session_data.get("auth_provider"))`. `HerdsGroup`
(the existing CLI boundary handler) catches `HerdsError` subclasses and
exits cleanly.

### 3. Move pre-action progress lines into `upload_image()`

Currently `cmd_image.py:104-113` prints five lines (Uploading…, Using
timezone…, Using algorithm version…, Using mock…, Requesting auto-add…)
*before* any HTTP work. Move all five into `images.upload_image()`, emitted
just before the multipart POST is issued, after `load_session_auth(email)` has
verified credentials are loadable.

This applies the user's preference for no pre-action chatter strictly:
nothing is printed until the upload is actually about to happen.

## Consequences

### Positive

- All authenticated commands (events list, image upload, calendar, etc.)
  silently survive expired access tokens — same fix, every command.
- Session files stay current: rotated refresh tokens are persisted after
  every successful refresh.
- The "log in again" hint is now copy-pasteable per account.
- "Uploading…" no longer lies about what just happened.

### Negative / trade-offs

- One extra round-trip on the 401 path. Acceptable — it only happens when the
  access token has actually expired.
- We now persist the refresh-token rotation, which means a crash mid-rotation
  could leave a stale refresh token on disk. The server's refresh endpoint
  rejects that with 401 and we'd surface the tailored login prompt — same
  recovery as before, no new failure mode.
- `_current_session_email` is per-`APIClient` instance state. Acceptable
  because each CLI invocation builds a fresh `APIClient` and uses one email.

### Skipped paths

- `no_login` mode and unset `_current_session_email` skip refresh entirely
  (no behavior change for those flows).
- Network errors during refresh are not converted to `SessionExpiredError`;
  they bubble as today, so users distinguish "auth expired" from "server
  unreachable."
- Only one retry per `_make_request` call. A 401 after a successful refresh
  is treated as a real auth problem and bubbles to `handle_api_error`.

## Testing

- Unit: `refresh_session_auth` happy path (mobile and web), failure path
  (401 from refresh, missing refresh_token in session).
- Unit: `_make_request` 401 → refresh → retry → 200; 401 → refresh fails →
  `SessionExpiredError` with the right `auth_provider`.
- Unit: rotated tokens are persisted via `SessionManager.save_session`.
- CLI: image upload with a stale-but-refreshable session uploads cleanly;
  with a stale refresh token, exits 1 with the tailored hint.
- CLI: pre-action lines do not appear in the output when auth load fails.
