# Architecture

Herds CLI is a Python CLI for the [Herds](https://herds.events) event platform. It lets users upload event flyers, manage extracted events, and integrate with calendars. Built with Click, Rich, and requests.

## Module Map

```
herds_cli/
├── cli.py              Entry point — Click root group, context setup, HerdsGroup error handler
├── api.py              APIClient — wraps requests.Session with auth, debug logging, all endpoints
├── sessions.py         SessionManager — JSON session files in ~/.local/state/herds/ with 0600 permissions
├── images.py           ImageUploader — file validation, MIME detection, multipart upload
├── output.py           OutputFormatter — JSON on stdout (json mode); print_* status messages on stderr (both modes)
├── oauth.py            GoogleOAuthFlow — local HTTP server + browser OAuth for Google login
├── image_display.py    Terminal image rendering helpers
├── types.py            TypedDicts for SessionData, EventV2, etc. (pure leaf, no project imports)
├── core/
│   ├── config.py       Config dataclass — layered loading: defaults → env → file → CLI flags
│   ├── base.py         CommandBase / EventCommandBase / ImageCommandBase + standalone helpers
│   └── exceptions.py   Domain exceptions (HerdsError hierarchy)
└── commands/
    ├── cmd_user.py           login, logout, create-user, whoami, sessions, Google OAuth
    ├── cmd_image.py          upload, get, detections, in-progress, delete
    ├── cmd_url.py            submit (URL event extraction, optional polling)
    ├── cmd_events.py         list (date filters/sorting), get, update, delete, by-image
    ├── cmd_extractions.py    list, get, events, ack (extraction jobs; joined from events via EventV2.extraction_id)
    ├── cmd_event_user_data.py  get/update/delete calendar integration data per event
    ├── cmd_config.py         show, validate, set, save, reset
    ├── cmd_user_settings.py  get/update user preferences
    ├── cmd_calendar.py       connect (Google/Outlook OAuth), status, list calendars
    └── cmd_ping.py           API health check
```

## Dependency Flow

```
commands/cmd_*.py
    │
    ├──→ core/base.py          (CommandBase, helpers)
    │       ├──→ api.py         (APIClient)
    │       ├──→ sessions.py    (SessionManager)
    │       ├──→ output.py      (OutputFormatter)
    │       └──→ core/exceptions.py
    │
    ├──→ core/config.py        (Config)
    ├──→ images.py             (ImageUploader, from cmd_image only)
    └──→ oauth.py              (GoogleOAuthFlow, from cmd_user + cmd_calendar only)

types.py                       (pure leaf — imported by api.py, sessions.py, core/base.py)

cli.py                         (top-level wiring — creates all components, populates ctx.obj)
    ├──→ all of the above
    └──→ core/exceptions.py    (HerdsGroup catches HerdsError → sys.exit(1))
```

## Layer Diagram

```
┌─────────────────────────────────────────────┐
│  CLI Layer (cli.py, commands/cmd_*.py)      │  Click commands, argument parsing, output
├─────────────────────────────────────────────┤
│  Service Layer (core/base.py)               │  Session resolution, API request orchestration
├─────────────────────────────────────────────┤
│  Client Layer (api.py, sessions.py,         │  HTTP requests, session persistence,
│                images.py, oauth.py)         │  file uploads, OAuth flows
├─────────────────────────────────────────────┤
│  Foundation (core/config.py, types.py,      │  Configuration, type definitions,
│              core/exceptions.py, output.py) │  error hierarchy, display formatting
└─────────────────────────────────────────────┘
```

## Key Interfaces and Boundaries

### Context / Dependency Injection

`cli.py` builds a `HerdsContext` TypedDict and stores it in `ctx.obj`. Every command receives its dependencies (APIClient, SessionManager, Config, etc.) through this dict. `CommandBase.__init__` unpacks it.

### Auth Boundary

Two auth modes determined at login time:

- **Web** (`client_type: "web"`) — cookie-based auth via `requests.Session.cookies`
- **Mobile** (`client_type: "mobile"`) — Bearer token via `Authorization` header

`APIClient.load_session_auth(email)` reads the session file and configures the HTTP session accordingly. All authenticated API methods call this internally.

### Error Boundary

Domain errors use the `HerdsError` hierarchy (`core/exceptions.py`). Helpers in `core/base.py` print a user-friendly message then raise. `HerdsGroup` at the CLI boundary catches `HerdsError` and calls `sys.exit(1)` — no traceback shown to users.

### Session Storage

`SessionManager` persists sessions as JSON files in the XDG state directory (`$XDG_STATE_HOME/herds/`, default `~/.local/state/herds/`) with filename convention `herds_session_{sanitized_email}` (where `@` → `_at_`, `.` → `_`). Files use `0600` permissions. Override the directory with `HERDS_SESSION_DIR` or the `session_dir` config key. See `herds_cli/paths.py` for path resolution.

### Configuration Precedence

Config values are resolved in this order (last wins):

1. Dataclass defaults
2. `HERDS_*` environment variables
3. JSON config file (`$XDG_CONFIG_HOME/herds/config.json`, default `~/.config/herds/config.json`; override with `--config` or `HERDS_CONFIG_FILE`)
4. CLI flags (`--base-url`, `--format`, etc.)
