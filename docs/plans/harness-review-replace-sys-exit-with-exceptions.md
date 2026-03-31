# Harness Review: Replace sys.exit() with Domain Exceptions

**Status: Completed** (2026-03-30)

## Context

A harness engineering review of the full `herds_cli/` codebase rated all four pillars (Encapsulation, OOP Design, Testability, Harness-Friendliness) at 5/10. The highest-leverage single refactor identified was replacing `sys.exit(1)` calls in `core/base.py` helper functions with domain-specific exceptions.

## Problem

Six locations in `core/base.py` called `sys.exit(1)` on error:

| Location | Function | Trigger |
|----------|----------|---------|
| `base.py:56` | `CommandBase.load_session_auth()` | Auth load fails |
| `base.py:81` | `CommandBase.execute_api_request()` | Non-200 response |
| `base.py:85` | `CommandBase.execute_api_request()` | Any exception |
| `base.py:259` | `get_or_detect_session_email()` | No sessions / ambiguous |
| `base.py:303,316` | `validate_session_exists()` | Session missing |
| `base.py:335` | `extract_user_id_from_session()` | No user_id in session |

### Impact across pillars

- **Testability (critical):** Tests had to catch `SystemExit`, conflating "expected business error" with "process termination." Error-recovery paths were untestable.
- **Harness-Friendliness:** `sys.exit()` lost error context. An agent or automated tool could not distinguish session-not-found from user-id-missing.
- **OOP Design:** Utility functions owned process lifecycle, violating single responsibility. They could not be reused outside CLI context.

## What Was Done

### 1. Created `herds_cli/core/exceptions.py`

Seven domain exception classes, each with structured data for programmatic access:

| Exception | Raised when | Structured data |
|-----------|------------|-----------------|
| `HerdsError` | Base class for all domain errors | — |
| `NoSessionsError` | No active sessions found | — |
| `AmbiguousSessionError` | Multiple sessions, no default | `.emails` (list) |
| `SessionNotFoundError` | Session missing for email | `.email` |
| `AuthenticationError` | Session auth load failed | `.email` |
| `UserIdNotFoundError` | No user_id in session data | `.email` |
| `APIRequestError` | API request failed | `.status_code` |

### 2. Refactored `herds_cli/core/base.py`

Replaced all 6 `sys.exit(1)` calls with the corresponding domain exception. The `import sys` was removed entirely. `OutputFormatter.print_error()` calls remain in place — they print the user-friendly message before the exception is raised.

Mapping applied:

- `load_session_auth()` → `raise AuthenticationError(email)`
- `execute_api_request()` error response → `raise APIRequestError(msg, status_code=...)`
- `execute_api_request()` exception → `raise APIRequestError(str(e))`
- `get_or_detect_session_email()` no sessions → `raise NoSessionsError()`
- `get_or_detect_session_email()` ambiguous → `raise AmbiguousSessionError(emails)`
- `validate_session_exists()` → `raise SessionNotFoundError(email)`
- `extract_user_id_from_session()` → `raise UserIdNotFoundError(email)`

In `execute_api_request()`, a `except HerdsError: raise` guard was added before the generic `except Exception` to prevent domain exceptions from being wrapped in `APIRequestError`.

### 3. Updated `herds_cli/core/__init__.py`

All 7 exception classes are now exported.

### 4. Added global error handler via `HerdsGroup` in `herds_cli/cli.py`

Instead of a per-command decorator, a custom `HerdsGroup(click.Group)` subclass overrides `invoke()` to catch `HerdsError` and call `sys.exit(1)`. This gives global handling for all commands without touching any command function.

This works because:
- All commands are nested under the root `cli` group
- Session/auth helper calls happen *before* command-level `try/except Exception` blocks
- Error messages are already printed before the exception is raised, so the handler only needs to exit

No changes were needed to any command module (`cmd_user.py`, `cmd_events.py`, etc.).

### 5. Updated `tests/unit/test_base_helpers.py`

7 tests updated from `pytest.raises(SystemExit)` to specific exception types:

| Test | Before | After |
|------|--------|-------|
| `test_no_sessions_exits` | `SystemExit` | `NoSessionsError` |
| `test_multiple_sessions_no_default_exits` | `SystemExit` | `AmbiguousSessionError` + asserts `.emails` |
| `test_default_account_not_found_exits` | `SystemExit` | `AmbiguousSessionError` |
| `test_multiple_sessions_shows_client_type` | `SystemExit` | `AmbiguousSessionError` |
| `test_missing_session_exits` (validate) | `SystemExit` | `SessionNotFoundError` + asserts `.email` |
| `test_no_user_data_exits` | `SystemExit` | `UserIdNotFoundError` |
| `test_missing_session_exits` (extract) | `SystemExit` | `UserIdNotFoundError` |

Test names updated to use `_raises` suffix instead of `_exits`.

## Files Changed

- **New:** `herds_cli/core/exceptions.py`
- **Modified:** `herds_cli/core/base.py` — replaced `sys.exit(1)` with exceptions, removed `import sys`
- **Modified:** `herds_cli/core/__init__.py` — added exception exports
- **Modified:** `herds_cli/cli.py` — added `HerdsGroup` with global `HerdsError` handler
- **Modified:** `tests/unit/test_base_helpers.py` — updated 7 tests to assert specific exception types
- **New:** `docs/plans/harness-review-replace-sys-exit-with-exceptions.md` (this file)

## Verification

All 120 tests pass. End-user CLI behavior is unchanged — the same error messages are printed and the process exits with code 1 on the same failure conditions.

## Trade-offs

| Better | Consideration |
|--------|---------------|
| Tests assert specific error types, not SystemExit | Slightly more exception classes to know about |
| Helpers reusable outside CLI context | `HerdsGroup` handler needed at CLI boundary |
| Agents get typed errors with structured data (`.email`, `.emails`, `.status_code`) | — |
| Error recovery paths become testable | — |
| Global handler: zero changes to command modules | — |

## Remaining review findings (not addressed)

These were identified by the harness review but are separate concerns:

- Duplicated & diverged helper functions in `cmd_events.py` (dead code)
- `_make_request` called as private method by external callers
- `OutputFormatter` / `APIResponseHandler` as all-static classes with global `Console()`
- Bare `except:` clauses in `api.py`, `images.py`, `config.py`
- `ctx.obj` as untyped dict
- Missing `google_client_id` / `google_client_secret` fields on `Config`
