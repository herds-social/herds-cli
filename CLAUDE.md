# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Herds CLI (`herds-cli`) is a Python CLI for the [Herds](https://herds.events) event platform. It lets users upload event flyers, manage extracted events, and integrate with calendars. Built with Click, Rich, and requests.

## Development Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run herds --help

# Build the package
python -m build
```

There are no tests in this repo currently.

## Architecture

### Entry Point

`herds_cli/cli.py` — The Click root group. Sets up the shared context (`ctx.obj`) that every subcommand depends on:
- Loads `Config` (file → env vars → CLI flags, last wins)
- Creates `SessionManager`, `APIClient`, `ImageUploader`, `OutputFormatter`
- Stores them in `ctx.obj` for subcommands to consume

### Core Components

- **`core/config.py`** — `Config` dataclass. Layered loading: defaults → env vars (`HERDS_*`) → JSON file → CLI flags. Validates URL, timeout, timezone, email format.
- **`core/base.py`** — `CommandBase` / `EventCommandBase` / `ImageCommandBase` — base classes that commands inherit from. Provides `setup_session()` (auto-detect email from `~/.herds/` sessions), `extract_user_id()`, `execute_api_request()`, and standardized display methods. Also has standalone helpers: `get_or_detect_session_email()`, `validate_session_exists()`.
- **`api.py`** — `APIClient`. Wraps `requests.Session` with auth loading (cookies for web, Bearer token for mobile), debug logging, and all API endpoint methods. Every authenticated method calls `load_session_auth(email)` first.
- **`sessions.py`** — `SessionManager`. Stores sessions as JSON files in `~/.herds/` with `0600` permissions. Email-based filenames (`herds_session_user_at_example_com`).
- **`images.py`** — `ImageUploader`. File validation, MIME type detection, multipart upload to `/api/images/v2/upload`.
- **`output.py`** — `OutputFormatter`. JSON or Rich table output. Static methods for success/error/warning/info messages.
- **`oauth.py`** — `GoogleOAuthFlow`. Spins up a local HTTP server on port 8080, opens the browser for Google OAuth, exchanges the code for an ID token.

### Command Modules (`commands/`)

Each file is a Click command group registered in `cli.py`:
- `cmd_user.py` — login, logout, create-user, whoami, sessions, Google OAuth login
- `cmd_image.py` — upload, get, detections, in-progress, delete
- `cmd_events.py` — list (with date filters/sorting), get, update, delete, by-image
- `cmd_event_user_data.py` — get/update/delete calendar integration data per event
- `cmd_config.py` — show, validate, set, save, reset
- `cmd_user_settings.py` — get/update user preferences
- `cmd_calendar.py` — connect (Google/Outlook OAuth), status, list calendars

### Key Patterns

- **Auth flow**: Commands call `CommandBase.setup_session(email)` to resolve which account to use (explicit `--email`, single session auto-detect, or `--account`/`HERDS_DEFAULT_ACCOUNT`). Then `APIClient.load_session_auth(email)` loads cookies or Bearer token.
- **Two client types**: `web` (cookie-based) and `mobile` (Bearer token). Determined at login time via `--client-type`.
- **Output**: All commands respect `--format json|table`. JSON is default.

## Release

Tags matching `cli-v*` trigger the GitHub Actions release workflow (`.github/workflows/release-cli.yml`), which builds with `python -m build` and creates a GitHub Release.
