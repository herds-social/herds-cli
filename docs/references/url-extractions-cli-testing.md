# Testing URL submit and extractions from the CLI

Guide for manually exercising `herds url` and `herds extractions` (added in **4.2.0**).

## Prerequisites

### Use a 4.2.0+ build

The global `herds` install may still be 4.1.x and will not have `url` / `extractions`:

```bash
herds --help | grep url          # empty → old install
```

From the repo worktree:

```bash
cd /path/to/herds-cli
uv run herds --help | grep url   # should list url + extractions
```

Or install the branch locally:

```bash
uv pip install -e .
```

### Server must have URL ingestion enabled

`POST /api/url/submit` returns **403** with `URL ingestion is disabled` when the
server's `URL_FETCH_ENABLED` flag is off. Production (`https://api.herds.events`)
may have this disabled during rollout.

**Local dev** — start herds with the flag on:

```bash
cd ~/dev/herds
URL_FETCH_ENABLED=true uv run uvicorn app.main:app --reload
```

### CLI config and auth

```bash
# API target (local example)
herds config set api_url --local
# herds config set api_url --prod   # only works once URL_FETCH_ENABLED is on there

# Login (if no session yet)
herds user login --email you@example.com

# Optional: default account when multiple sessions exist
herds config set default_account you@example.com

# Sanity check
herds ping
herds config show
```

Config lives at `$XDG_CONFIG_HOME/herds/config.json` (default
`~/.config/herds/config.json`); override with `--config` or `HERDS_CONFIG_FILE`.
Sessions live at `$XDG_STATE_HOME/herds/` (default `~/.local/state/herds/`);
override the session directory with `HERDS_SESSION_DIR` or the `session_dir`
config key. Follows the XDG Base Directory spec.

---

## `herds url submit`

### Basic submit (fire-and-forget)

```bash
uv run herds url submit "https://example.com/events"
```

Expect stderr:

- `URL submitted for processing`
- `Event source ID: <id>`

Save the ID for extractions commands below.

### Submit with poll (wait + display events)

```bash
uv run herds url submit "https://example.com/events" --poll
```

Polls `GET /api/extractions/{id}` every 2s (180s timeout), then fetches events
and renders them like `herds image upload --poll`.

### Other flags

```bash
# Fast/cheap AI path (testing)
uv run herds url submit "https://example.com/events" --mock

# Calendar auto-add tri-state (omit = defer to user setting)
uv run herds url submit "https://example.com/events" --add-to-calendar
uv run herds url submit "https://example.com/events" --no-add-to-calendar

# Explicit account
uv run herds url submit "https://example.com/events" --email you@example.com

# JSON response on stdout (status lines on stderr)
uv run herds url submit "https://example.com/events" --format json
```

**Note:** `--poll` cannot be combined with an explicit `--format json`. Auto-resolved
json (piped stdout) still allows `--poll` and renders human-readable poll output,
matching `herds image upload --poll`.

### Real URL example

Quote URLs that contain `%` or special characters:

```bash
uv run herds url submit \
  "https://www.exploreboone.com/event/arttalk%3a-%e2%80%9c40-years-of-public-art-%e2%80%9d-hank-foreman/28861/"
```

### Expected errors

| Symptom                                               | Cause                                                                          |
| ----------------------------------------------------- | ------------------------------------------------------------------------------ |
| `No such command 'url'`                               | Old CLI install; use `uv run herds` from 4.2.0+ worktree                       |
| `URL ingestion is disabled`                           | Server `URL_FETCH_ENABLED=false`; use local server or wait for prod enablement |
| `URL blocked: ...`                                    | SSRF guard rejected the URL (400)                                              |
| `Rate limited` / usage message                        | Tier limit (429)                                                               |
| `URL was recently submitted; reusing extraction <id>` | Idempotent resubmit inside server window                                       |

---

## `herds extractions`

Use the `event_source_id` from submit, or an `image_id` from a prior image upload.

### List history

```bash
uv run herds extractions list

uv run herds extractions list --status completed --source-type url
uv run herds extractions list --unacked
uv run herds extractions list --limit 10 --offset 0
```

Unacknowledged terminal rows show a trailing `[unread]` marker in text mode.
List rows include the full 24-character extraction ID in brackets (copy it for
`get`, `events`, and `ack`).

### Get status

```bash
uv run herds extractions get <EXTRACTION_ID>
```

### Fetch events

```bash
uv run herds extractions events <EXTRACTION_ID>

# JSON array on stdout
uv run herds extractions events <EXTRACTION_ID> --format json
```

### Acknowledge

```bash
uv run herds extractions ack <ID1> <ID2>
uv run herds extractions ack --all
uv run herds extractions ack --before 2026-07-07
uv run herds extractions ack --before 2026-07-07T15:00:00Z
```

---

## End-to-end script

```bash
# 1. Local server (separate terminal)
cd ~/dev/herds && URL_FETCH_ENABLED=true uv run uvicorn app.main:app --reload

# 2. CLI
cd /path/to/herds-cli
herds config set api_url --local
uv run herds url submit "https://example.com/events" --poll

# 3. Inspect history
uv run herds extractions list --source-type url
```

Capture ID from submit output, then:

```bash
ID=<event_source_id>
uv run herds extractions get "$ID"
uv run herds extractions events "$ID"
```

---

## Automated tests (repo)

```bash
uv run pytest tests/cli/test_cli_url.py
uv run pytest tests/cli/test_cli_extractions.py
uv run pytest tests/unit/test_api_extractions.py
uv run pytest
```
