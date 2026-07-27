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

# Run the test suite
uv run pytest

# Run a single test file
uv run pytest tests/cli/test_cli_image.py
```

Tests live under `tests/`:

- `tests/unit/` — unit tests for individual modules (api, config, images, helpers, types/oauth)
- `tests/cli/` — Click CliRunner tests that invoke commands end-to-end with mocked HTTP
- `tests/scripts/` - tests for the release/CI tooling under `scripts/` (version guard, formula generator)

CLI tests inject a fully-built `ctx.obj` via `CliRunner.invoke(..., obj=cli_obj)` and rely on the `_initialized` guard in `cli.cli()` to skip config loading. Shared fixtures (`mock_api_client`, `mock_session_manager`, `cli_obj`) are in `tests/cli/conftest.py` and `tests/unit/conftest.py`.

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
- **Output**: All commands respect `--format json|text|auto`. The default is `auto` — `text` when stdout is a TTY, `json` when piped/redirected. Status messages always go to stderr (via `OutputFormatter.print_*`); `json` mode also writes a JSON dump on stdout, while `text` mode leaves stdout empty. Documented exception: `extractions share` prints the bare share URL on stdout in text mode and resolves a default `auto` to text even when piped, so `herds extractions share <id> | pbcopy` yields the URL.

## Debugging Cross-Stack Issues

When a bug appears to be caused by the server (wrong status code, missing fields, unhelpful error shape, conflated error types, etc.), **recommend fixing the server first, then update the CLI to match**. The server lives in `~/dev/herds`. Adapting the CLI to paper over a server-side defect locks in the bug — a correct server contract is easier to consume cleanly. Only change the CLI-first if the server behavior is intentional or the fix is genuinely CLI-local.

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Module map, dependency flow, layer diagram, key interfaces
- **[docs/design-docs/](docs/design-docs/)** — Architecture Decision Records (ADRs)
- **[docs/exec-plans/active/](docs/exec-plans/active/)** — Current execution plans
- **[docs/exec-plans/completed/](docs/exec-plans/completed/)** — Finished plans for reference
- **[docs/references/](docs/references/)** — External docs (Google Auth setup, Homebrew distribution)

## Versioning

**Bump the version once per branch.** When a branch touches source under `herds_cli/`, increment the version one time on that branch — not on every commit during iterative development. Three files must stay in sync and move together in a single commit:

- `pyproject.toml` (the `version = "..."` field, currently line 7)
- `herds_cli/__init__.py` (the `__version__ = "..."` constant, currently line 8)
- `uv.lock` — regenerate by running `uv lock` after bumping the two source files; uv reads the new version from `pyproject.toml` and updates the lockfile's `herds-cli` entry. Skipping this step leaves `uv.lock` perpetually "modified" on subsequent `uv run` invocations and produces a stale lockfile in the commit history.

Follow semver:

- **Patch** (`1.0.0` → `1.0.1`) — bug fixes, internal refactors, no user-visible behavior change
- **Minor** (`1.0.0` → `1.1.0`) — new commands, new flags, additive features
- **Major** (`1.0.0` → `2.0.0`) — breaking CLI changes (removed/renamed flags or commands, changed output schema)

Documentation-only and test-only branches do not require a bump.

## Release

Releases are automated. Merging a PR to `main` whose branch bumped the version triggers `.github/workflows/release-cli.yml`: it builds with `python -m build`, creates tag `cli-vX.Y.Z` plus a GitHub Release, and regenerates and pushes `Formula/herds.rb` in the `homebrew-herds-cli` tap (`scripts/generate_formula.py`). Merges without a version bump release nothing. CI runs `scripts/version_guard.py` on every PR and fails it when `herds_cli/` source or dependencies changed without a bump. Manually pushed `cli-v*` tags and `workflow_dispatch` run the same pipeline as a fallback.
