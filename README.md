# Herds CLI

A command-line interface for the [Herds](https://herds.events) event platform. Upload event flyers, manage extracted events, and integrate with calendars — all from your terminal.

## Install

### Homebrew (macOS)

```bash
brew tap herds-social/herds-cli-homebrew
brew install herds
```

### pip / pipx

```bash
pipx install herds-cli      # isolated install (recommended)
# or
pip install herds-cli
```

### From source

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/herds-social/herds-cli.git
cd herds-cli
uv sync
uv run herds --help   # run inside the repo only
```

#### Install globally for your user with `uv tool`

To make `herds` available from any directory (not just the repo), install it as a uv tool:

```bash
# from the repo root
uv tool install .

# one-time: ensure ~/.local/bin is on your PATH
uv tool update-shell
```

This creates an isolated environment for the CLI under `~/.local/share/uv/tools/herds-cli/` and drops a `herds` shim into `~/.local/bin/`. Verify with:

```bash
which herds
herds --help
```

For active development, install in editable mode so source edits are picked up without reinstalling:

```bash
uv tool install --editable .
```

To upgrade or reinstall after pulling new changes:

```bash
uv tool upgrade herds-cli
# or, to force a clean reinstall
uv tool install --reinstall .
```

To remove it:

```bash
uv tool uninstall herds-cli
```

## Quick start

```bash
# 1. Log in
herds user login --email you@example.com

# 2. Upload an event flyer
herds image upload flyer.jpg

# 3. Check processing status
herds image in-progress

# 4. View your extracted events
herds events list
```

## Commands

### User management

| Command                      | Description                      |
| ---------------------------- | -------------------------------- |
| `herds user login`           | Authenticate with email/password |
| `herds user login-google`    | Authenticate via Google OAuth    |
| `herds user create-user`     | Create a new account             |
| `herds user change-password` | Change your password             |
| `herds user whoami`          | Show current user info           |
| `herds user sessions`        | List all stored sessions         |
| `herds user logout`          | Clear stored session             |

### Images

| Command                       | Description                           |
| ----------------------------- | ------------------------------------- |
| `herds image upload <file>`   | Upload an image for event extraction  |
| `herds image get <id>`        | Get image metadata                    |
| `herds image detections <id>` | Get AI detection results for an image |
| `herds image in-progress`     | List images currently processing      |
| `herds image delete <id>`     | Delete an image                       |

### Events

| Command                            | Description                                          |
| ---------------------------------- | ---------------------------------------------------- |
| `herds events list`                | List your events (supports date filters and sorting) |
| `herds events get <id>`            | Get event details                                    |
| `herds events update <id>`         | Update event fields (title, date, location, etc.)    |
| `herds events delete <id>`         | Delete an event                                      |
| `herds events by-image <image-id>` | Get events extracted from a specific image           |

### Event user data

| Command                                       | Description                       |
| --------------------------------------------- | --------------------------------- |
| `herds event-user-data get <event-id>`        | Get your data for an event        |
| `herds event-user-data update`                | Set calendar integration IDs      |
| `herds event-user-data delete-all <event-id>` | Remove all your data for an event |

### User settings

| Command                      | Description                                      |
| ---------------------------- | ------------------------------------------------ |
| `herds user-settings get`    | Show your preferences                            |
| `herds user-settings update` | Update preferences (calendar, sort, theme, etc.) |

### Calendar

| Command                    | Description                         |
| -------------------------- | ----------------------------------- |
| `herds calendar connect`   | Start OAuth flow for Google/Outlook |
| `herds calendar status`    | Check connection status             |
| `herds calendar calendars` | List connected calendars            |

### Configuration

| Command                    | Description                                     |
| -------------------------- | ----------------------------------------------- |
| `herds config show`        | Display current config                          |
| `herds config validate`    | Validate config                                 |
| `herds config set`         | Set config values (interactive or programmatic) |
| `herds config save <file>` | Save config to a JSON file                      |
| `herds config reset`       | Show defaults                                   |

## Global options

```
--config PATH          Path to JSON config file
--base-url TEXT        API base URL (overrides config)
--format [json|table]  Output format [default: json]
-v, --verbose          Verbose output
-d, --debug-requests   Show HTTP request/response details
--timezone TEXT        Timezone override (auto-detected by default)
--account TEXT         Account email to use
--help                 Show help
```

## Configuration

The CLI loads settings in this order (last wins):

1. Built-in defaults
2. `herds-cli-config.json` in the current directory
3. Environment variables (`HERDS_API_URL`, `HERDS_OUTPUT_FORMAT`, etc.)
4. CLI flags (`--base-url`, `--format`, etc.)

```bash
# Set the API URL to local dev server
herds config set api_url --local

# Switch to table output
herds config set output_format table

# Save your config for reuse
herds config save my-config.json
herds --config my-config.json events list
```

## Session management

Sessions are stored as JSON files in `~/.herds/` with one file per account:

```
~/.herds/herds_session_you_at_example_com
~/.herds/herds_session_admin_at_herds_events
```

- Files are created with `0600` permissions (owner-only read/write).
- Multiple sessions can coexist — use `--account` or `--email` to target a specific one.
- `herds user sessions` lists all active sessions.

The CLI supports two auth modes:

| Mode          | Flag                   | Auth mechanism |
| ------------- | ---------------------- | -------------- |
| Web (default) | `--client-type web`    | HTTP cookies   |
| Mobile        | `--client-type mobile` | Bearer token   |

## Examples

### End-to-end image processing

```bash
herds user login --email you@example.com
herds image upload concert-poster.jpg
herds image in-progress
herds events list
herds events update 680a1b... --title "Summer Jazz Festival"
```

### Filter and sort events

```bash
herds events list --date-filter upcoming --sort-by date_start
herds events list --date-filter past-7-days
herds events list --all --sort-by date_added
```

### Multiple accounts

```bash
herds user login --email personal@gmail.com
herds user login --email work@company.com
herds user sessions                          # see both
herds events list --account work@company.com # target one
```

### Debugging

```bash
herds --verbose --debug-requests image upload flyer.jpg
```

## Troubleshooting

| Problem                            | Fix                                                                     |
| ---------------------------------- | ----------------------------------------------------------------------- |
| "No active sessions found"         | Run `herds user login` first                                            |
| "Multiple sessions found"          | Add `--account you@example.com` to pick one                             |
| API connection errors              | Check `herds config show` for the API URL; ensure the server is running |
| Permission errors on session files | Check directory permissions on `~/.herds/`                              |
| Command not found                  | Verify installation: `which herds` or `pipx list`                       |

Use `herds config validate` to check your configuration is complete.

## Development

```bash
# Run from the repo root
./scripts/herds_cli --help

# Run tests
uv run pytest tests/scripts/ -v

# Build the package
cd cli && python -m build
```

## License

Apache-2.0
