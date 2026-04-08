# AI Reasoning Gap Remediation Plan

**Date:** 2026-04-06
**Scope:** Full package scan — all 21 source files in `herds_cli/`
**Overall Score:** 4.9/10 (Grade C)

## Ratings Summary

| Dimension | Score | Summary |
|-----------|-------|---------|
| Type & Data Contracts | 3/10 | Pervasive untyped params, bare containers, dict-based data passing with implicit schemas |
| Implicit Flow & State | 6/10 | Straightforward CLI; notable gaps in HerdsGroup exception swallowing, session auth mutation |
| Structure & Documentation | 6/10 | Good module docstrings, but dead-code duplication, long functions, missing architectural context |
| **Overall** | **4.9/10 (C)** | Type gaps drive the low score; implicit flow and structure are adequate with hotspots |

## Cross-Dimension Findings (highest leverage)

These locations were flagged by 2+ specialist agents. Fixing them improves multiple dimensions at once.

### cli.py:144-231 — `ctx.obj` as untyped dict (Type + Implicit Flow + Structure)
Every command accesses `ctx.obj["api_client"]`, `ctx.obj["config"]`, etc. with zero type safety. An AI agent adding a command cannot discover required keys or types without reading cli.py:204-231. The `_initialized` test bypass at line 157 is undocumented.

### cmd_events.py:417-591 — Duplicate dead-code helpers (Type + Implicit Flow + Structure)
Stale copies of `get_or_detect_session_email`, `validate_session_exists`, `extract_user_id_from_session`, and `display_events_summary` that still use `sys.exit(1)` while canonical versions in `core/base.py` raise domain exceptions. The module already imports from `core.base` (line 11-15).

### core/base.py:24 — CommandBase constructor (Type + Structure)
`__init__(self, ctx)` — untyped ctx, no documentation of what `ctx.obj` must contain.

## All Findings

### Critical

| File:Line | Tag | Description | Dimension |
|-----------|-----|-------------|-----------|
| cli.py:204-231 | data-contract | ctx.obj populated as plain dict with 8 string keys; any key rename breaks all commands silently | Type |
| api.py:196-693 | data-contract | All 17 API methods annotated `-> Dict[str, Any]` but response schemas are implicit; callers guess keys | Type |
| sessions.py:74 | data-contract | `load_session()` returns implicit schema with nested `tokens`, `cookies`, `user_data`; consumed by 15+ sites | Type |
| core/base.py:66 | type-gap | `execute_api_request()` — primary API method for all commands — no param types, no return type | Type |

### Important

| File:Line | Tag | Description | Dimension |
|-----------|-----|-------------|-----------|
| cli.py:33-45 | implicit-flow | HerdsGroup catches HerdsError → sys.exit(1); relies on invisible "print-then-raise" contract | Implicit Flow |
| api.py:36-66 | state-mutation | `load_session_auth()` permanently mutates session headers/cookies; name suggests read-only | Implicit Flow |
| cli.py:157-159 | implicit-flow | Test injection bypass via `_initialized` flag — undocumented | Implicit Flow |
| core/base.py:31-52 | type-gap | `setup_session`, `validate_session`, `extract_user_id` — all untyped | Type |
| core/base.py:104-151 | type-gap | APIResponseHandler static methods — all parameters untyped | Type |
| core/base.py:156 | data-contract | `display_event_details(event_data)` accesses deeply nested v2 schema with no typed model | Type |
| core/base.py:257-348 | type-gap | Standalone helpers (3 functions, 4+ params each) — zero type annotations | Type |
| api.py:524 | type-gap | `handle_api_error` always raises but lacks `-> NoReturn`; affects all 17 API methods | Type |
| api.py:46 | data-contract | `client_type` is plain str checked against "web"/"mobile" in 10+ locations | Type |
| sessions.py:103 | data-contract | `list_sessions() -> list` — bare list of dicts with implicit keys | Type |
| oauth.py:84 | type-gap | `GoogleOAuthFlow(config=None)` — config expects undocumented protocol attributes | Type + Structure |
| api.py:17 | documentation | APIClient docstring doesn't explain web/mobile auth split or method pattern | Structure |
| core/config.py:17-18 | documentation | Config docstring doesn't explain loading precedence | Structure |
| sessions.py:23 | documentation | SessionManager docstring missing filename convention and security model | Structure |
| cmd_user.py:118-229 | structural | `login_google` is 112 lines with inline OAuthConfig class | Structure |
| images.py:162-195 | structural | Duplicated error-handling logic (identical status_defaults dict as core/base.py) | Structure |
| output.py:14 + sessions.py:17 | state-mutation | Two independent module-level Console() instances | Implicit Flow |

### Minor

| File:Line | Tag | Description | Dimension |
|-----------|-----|-------------|-----------|
| output.py:69 | type-gap | `display_configuration(config_obj)` — config_obj untyped | Type |
| cli.py:41 | type-gap | `HerdsGroup.invoke(self, ctx)` — ctx untyped | Type |
| cli.py:144-153 | type-gap | `cli()` — 8 parameters, zero type annotations | Type |
| images.py:75 | type-gap | `validate_image_file` missing `-> Path` return type | Type |
| images.py:197 | type-gap | `upload_multiple_images` returns bare `list` | Type |
| core/config.py:41 | type-gap | `_validation_errors: list` without element type | Type |
| core/config.py:190 | type-gap | `get_validation_errors() -> list` without element type | Type |
| core/exceptions.py:23,34,52,64 | type-gap | Exception `__init__` params untyped | Type |
| sessions.py:54-60 | state-mutation | `save_session()` mutates passed-in dict via .update() | Implicit Flow |
| core/config.py:145-182 | state-mutation | `validate()` creates directories as side effect | Implicit Flow |
| core/config.py:56-63 | implicit-flow | Config load order: file overrides env vars (counter-intuitive) | Implicit Flow |
| cli.py:134-137 | implicit-flow | Lambda callback ensures timezone is never None; `if timezone is not None:` at line 192 is dead code | Implicit Flow |
| cmd_calendar.py:211,241,304 | structural | Three commands call private `_make_request` directly (non-200 success codes) | Structure |
| cmd_events.py:24 | documentation | Stale TODO comment "will be moved to core module later" — already done | Structure |
| `__main__.py` | documentation | No module docstring for `python -m herds_cli` entry point | Structure |
| api.py:389-396 | documentation | `get_events_by_user` double-encodes params without explaining the split | Structure |

## Interventions

### 1. Define a `HerdsContext` TypedDict for `ctx.obj`

**What:** Create a `HerdsContext` TypedDict (in `core/types.py` or `core/config.py`):
```python
from typing import TypedDict

class HerdsContext(TypedDict):
    config: Config
    session_manager: SessionManager
    api_client: APIClient
    image_uploader: ImageUploader
    output_formatter: OutputFormatter
    timezone: str
    format: str
    base_url: str
```
Update `cli.py` to construct it explicitly. Update `CommandBase.__init__` signature to `ctx: click.Context`. Document the `_initialized` test bypass pattern.

**Resolves:**
- cli.py:204-231 (data-contract)
- core/base.py:24 (type-gap + documentation)
- cli.py:157-159 (implicit-flow documentation)

**Why highest leverage:** Every command depends on ctx.obj. One typed definition makes the entire DI mechanism AI-readable. Touches 3 dimensions.

**Effort:** low

### 2. Add type annotations to `core/base.py` public API

**What:** Annotate all public method signatures in CommandBase, EventCommandBase, ImageCommandBase, APIResponseHandler, and standalone helpers:
- `setup_session(self, email: Optional[str] = None, show_client_type: bool = False) -> str`
- `validate_session(self, email: str) -> Dict[str, Any]`
- `extract_user_id(self, email: str) -> str`
- `load_session_auth(self, email: str) -> bool`
- `execute_api_request(self, method: str, url: str, success_msg: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]`
- `handle_error_response(response: requests.Response, operation_name: str) -> None`
- `format_and_output(result: Any, output_format: str, skip_table: bool = False) -> None`
- `get_or_detect_session_email(session_manager: SessionManager, email: Optional[str], show_client_type: bool = False, config: Optional[Config] = None) -> str`
- `validate_session_exists(session_manager: SessionManager, email: str) -> Dict[str, Any]`
- `extract_user_id_from_session(session_manager: SessionManager, email: str) -> str`
- `display_events_summary(events: list[Dict[str, Any]]) -> None`

**Resolves:** core/base.py:31, :40, :47, :54, :66, :104, :135, :257, :319, :333, :351 (11 type-gap findings)

**Why highest leverage:** Most-consumed module — every command imports from it.

**Effort:** low

### 3. Define typed models for session data and event v2 schema

**What:** Create TypedDicts in a `core/types.py` module:
```python
from typing import TypedDict, Optional, Literal

ClientType = Literal["web", "mobile"]

class TokenData(TypedDict, total=False):
    access_token: str
    refresh_token: str
    expires_in: int

class SessionUserData(TypedDict, total=False):
    id: str
    user_id: str
    email: str
    created_at: str

class SessionData(TypedDict, total=False):
    client_type: ClientType
    cookies: Dict[str, str]
    tokens: TokenData
    user_data: SessionUserData
    base_url: str
    auth_provider: str
    email: str
    created_at: str
    session_filename: str

class SessionListEntry(TypedDict):
    filename: str
    email: str
    created_at: str

class DateInfoRaw(TypedDict, total=False):
    date: str

class DateInfoLocal(TypedDict, total=False):
    date_start: str
    date_end: str
    time_start: str
    time_end: str

class DateInfo(TypedDict, total=False):
    raw: DateInfoRaw
    local: DateInfoLocal

class LocationInfo(TypedDict, total=False):
    city: str
    state: str
    street_address: str

class ContactInfo(TypedDict, total=False):
    organizer: str
    email: str
    phone: str
    website: str

class EventUserData(TypedDict, total=False):
    apple_calendar_id: str
    google_calendar_id: str
    outlook_calendar_id: str

class EventV2(TypedDict, total=False):
    title: str
    category_level_1: str
    event_description: str
    date_info: DateInfo
    location: LocationInfo
    contact: ContactInfo
    user_data: EventUserData
```
Use `ClientType` in `api.py:login()` signature and session data. Use `SessionData` in `sessions.py`. Use `SessionListEntry` in `list_sessions()`. Use `EventV2` in display methods.

**Resolves:**
- sessions.py:74 (data-contract)
- sessions.py:103 (data-contract)
- core/base.py:156 (data-contract)
- core/base.py:351 (type-gap)
- api.py:46 (stringly-typed client_type)

**Why highest leverage:** Session data and event data are the two most-accessed schemas. Typing them makes the entire data layer AI-traceable.

**Effort:** medium

### 4. Remove dead-code duplicates and annotate `handle_api_error`

**What:**
- Delete cmd_events.py lines 416-591 (duplicate helpers + display function). The module already imports canonical versions from core.base (lines 11-15).
- Delete stale TODO comment at cmd_events.py:24 ("will be moved to core module later").
- Delete any similar stale comment in cmd_event_user_data.py if present.
- Add `-> NoReturn` return type to `api.py:524` `handle_api_error`.
- Add `from typing import NoReturn` import to api.py.

**Resolves:**
- cmd_events.py:417-591 (structural + implicit-flow — dead copies use sys.exit(1))
- cmd_events.py:24 (stale documentation)
- api.py:524 (type-gap affecting all 17 API methods)

**Why highest leverage:** Quick win eliminating the most confusing dead code and fixing a type gap that cascades through every API method.

**Effort:** low

### 5. Document implicit contracts on key classes

**What:** Update docstrings on 5 key classes:

**APIClient** (api.py:17): Explain web/mobile auth split, that every authenticated method calls `load_session_auth(email)` internally, that `handle_api_error` always raises, and that `_make_request` wraps requests.Session with debug logging.

**Config** (core/config.py:17-18): Explain loading precedence: dataclass defaults → `HERDS_*` env vars → JSON config file → CLI flags (applied in cli.py). Note that `_validation_errors` and `_loaded_config_file` are internal.

**SessionManager** (sessions.py:23): Explain filename convention (`herds_session_{sanitized_email}` where `@` → `_at_`, `+` → `_plus_`, `.` → `_`), 0600 permissions, and JSON storage format.

**HerdsError** (core/exceptions.py:9) or **HerdsGroup** (cli.py:33): Document the "print-then-raise" contract — all raise sites must print a user-friendly error message before raising because HerdsGroup swallows the exception and exits silently.

**GoogleOAuthFlow** (oauth.py:81-83): Document config protocol (`google_client_id`, `google_client_secret`, `google_redirect_uri` attributes), port 8080 constraint, and the callback flow architecture.

**Resolves:**
- api.py:17 (documentation)
- core/config.py:17-18 (documentation)
- sessions.py:23 (documentation)
- cli.py:33-45 (implicit-flow contract)
- oauth.py:81-83 (documentation + type-gap)

**Why highest leverage:** Five docstring updates give AI agents architectural context for the most important classes. Lowest effort, broad impact.

**Effort:** low

## Recommended Execution Order

1. ~~**Intervention #4** (remove dead code, add `-> NoReturn`)~~ — **DONE** (2026-04-06)
   - Deleted duplicate helpers from cmd_events.py (lines 416-591)
   - Deleted stale TODO comments from cmd_events.py and cmd_event_user_data.py
   - Added `-> NoReturn` to `api.py:handle_api_error`
2. ~~**Intervention #5** (document implicit contracts)~~ — **DONE** (2026-04-06)
   - Updated docstrings on APIClient, Config, SessionManager, HerdsError, GoogleOAuthFlow
3. ~~**Intervention #1** (HerdsContext TypedDict)~~ — **DONE** (2026-04-06)
   - Defined `HerdsContext(TypedDict)` in `core/base.py`
   - Typed `CommandBase.__init__(ctx: click.Context)` with attribute annotations
   - Updated `cli.py` to build ctx.obj via typed `herds_ctx: HerdsContext` dict
   - Exported `HerdsContext` from `core/__init__.py`
4. ~~**Intervention #2** (type annotations on core/base.py)~~ — **DONE** (2026-04-07)
   - Annotated all 13 public methods/functions: CommandBase (5), APIResponseHandler (2), EventCommandBase (1), ImageCommandBase (1), standalone helpers (4)
   - Added `requests`, `Optional`, `Any`, `Dict`, `List` imports
   - Updated docstrings to reference exceptions instead of "exits with error"
5. ~~**Intervention #3** (typed models for session/event data)~~ — **DONE** (2026-04-07)
   - Created `herds_cli/types.py` with `ClientType`, `SessionData`, `TokenData`, `SessionUserData`, `SessionListEntry`, `EventV2`, `DateInfo`, `LocationInfo`, `ContactInfo`, `EventUserData`
   - Updated `sessions.py`: `load_session() -> Optional[SessionData]`, `list_sessions() -> List[SessionListEntry]`
   - Updated `api.py`: `login(client_type: Literal["web", "mobile"])` (inline Literal to avoid circular import through `core/__init__.py`)
   - Updated `core/base.py`: `display_event_details(event_data: EventV2)`, `display_events_summary(events: List[EventV2])`, `validate_session -> SessionData`
   - Exported types from `core/__init__.py` for convenience
   - Note: types.py placed at `herds_cli/types.py` (not `core/types.py`) to avoid circular imports — `api.py` and `sessions.py` cannot import from `core/` because `core/__init__.py` eagerly imports `core/base.py` which imports them back

All 5 interventions complete. Overall AI reasoning gap score estimated to improve from 4.9/10 (C) to ~7-8/10 (B).
