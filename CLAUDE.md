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

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full domain map: module descriptions, dependency flow, layer diagram, and key interfaces.

**Quick orientation:**
- Entry point: `herds_cli/cli.py` (Click root group, context setup)
- Commands: `herds_cli/commands/cmd_*.py` (one file per command group)
- Core: `core/base.py` (command base classes), `core/config.py` (Config), `core/exceptions.py` (HerdsError hierarchy)
- Clients: `api.py` (HTTP), `sessions.py` (persistence), `images.py` (uploads), `oauth.py` (Google OAuth)
- Types: `types.py` (TypedDicts — pure leaf, no project imports)

### Key Patterns

- **Auth**: Two client types — `web` (cookies) and `mobile` (Bearer token). Resolved via `CommandBase.setup_session()` → `APIClient.load_session_auth()`.
- **Errors**: Helpers print a message then raise `HerdsError`. `HerdsGroup` at CLI boundary catches and exits.
- **Output**: All commands respect `--format json|table`. JSON is default.

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Module map, dependency flow, layer diagram, key interfaces
- **[docs/design-docs/](docs/design-docs/)** — Architecture Decision Records (ADRs)
- **[docs/exec-plans/active/](docs/exec-plans/active/)** — Current execution plans
- **[docs/exec-plans/completed/](docs/exec-plans/completed/)** — Finished plans for reference
- **[docs/references/](docs/references/)** — External docs (Google Auth setup, Homebrew distribution)

## Release

Tags matching `cli-v*` trigger the GitHub Actions release workflow (`.github/workflows/release-cli.yml`), which builds with `python -m build` and creates a GitHub Release.
