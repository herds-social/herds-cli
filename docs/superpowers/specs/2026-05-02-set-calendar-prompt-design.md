# `herds calendar set-calendar` — Interactive Picker Design

**Date:** 2026-05-02
**Status:** Approved (pending user review of this written spec)
**Target version:** `2.0.0` (major bump — removes `--calendar-name` flag)

## Goal

Replace the current `set-calendar --calendar-id <ID>` flow, which forces users to copy/paste opaque calendar IDs from `calendar list`, with an interactive numbered picker. Preserve a non-interactive escape hatch for scripts and CI.

## Background

Today, `herds calendar set-calendar` requires `--calendar-id`. To use it, a user must:

1. Run `herds calendar list` to see calendars and their IDs.
2. Manually copy a calendar ID — frequently a long opaque string like `c_abc123def@group.calendar.google.com` for non-primary Google calendars.
3. Re-run `set-calendar --calendar-id <pasted-id>`.
4. Optionally pass `--calendar-name "<label>"` so `calendar status` shows a friendly name instead of `"Not set"`.

The two-step copy-paste is the main UX problem. The optional `--calendar-name` flag is itself a workaround for the server not auto-resolving the display name from the calendar provider — fixing that lives in a separate plan (`~/dev/herds/docs/exec-plans/active/2026-05-02-calendar-name-auto-resolve.md`).

## Decisions

| #   | Decision                                                                                                                                                         | Rationale                                                                                    |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 1   | `--calendar-id` becomes **optional**. When omitted on a TTY, an interactive picker fires. When passed, the command behaves as today (no prompt).                 | Preserves scripting/CI use; layers interactivity on top.                                     |
| 2   | `--calendar-name` is **removed**. The server resolves the display name from the calendar provider on write.                                                      | Eliminates a CLI workaround for a server-side concern. Breaking change → major version bump. |
| 3   | Picker default is **smart**: current selection if it appears in the list, else the primary calendar, else the only calendar (when length is 1), else no default. | Pressing Enter does the obvious thing in both first-run and re-run scenarios.                |
| 4   | Picker tags entries with `(primary)` and `(current)`. A calendar that is both displays both, comma-separated: `(primary, current)`.                              | Answers "which one is set right now?" without a separate command.                            |
| 5   | `--format json` always forces non-interactive (even on a TTY). No-flag + JSON = error.                                                                           | Keeps stdout JSON parseable in pipes; matches existing format conventions.                   |
| 6   | Prompt output (list, "Calendar [N]:" prompt, errors) goes to **stderr**. Success output and JSON go to **stdout**.                                               | Click's default; we just don't break it.                                                     |
| 7   | If `GET /api/calendar/status` fails, picker still works — degrades to no `(current)` tag and falls back to primary as default.                                   | Picker should be robust. A status-read failure shouldn't block selection.                    |
| 8   | Single-calendar lists still show the picker (default `[1]`, one Enter).                                                                                          | Avoids "did it actually do something?" silent-action ambiguity.                              |

## Command signature

```
herds calendar set-calendar [--email EMAIL] [--calendar-id ID] [--format json|table]
```

Removed: `--calendar-name`.

## Behavior

### Interactive flow (TTY + no flag + format != json)

```
$ herds calendar set-calendar
Select a calendar:
  1. Personal (primary)
  2. Work (current)
  3. Family
  4. Holidays in United States
Calendar [2]: 1
Calendar selection updated.
  Calendar ID:   primary
  Calendar Name: Personal
```

The trailing `Calendar Name: Personal` line is read from the `PUT` response; the server resolves and returns it.

### Non-interactive flow

| Condition                | Behavior                                                                                                                  |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| `--calendar-id` passed   | No prompt. Single `PUT /api/calendar/settings` with `{calendar_id}`.                                                      |
| No flag, no TTY          | Exit 1: `--calendar-id is required when running non-interactively. Run 'herds calendar list' to see available calendars.` |
| No flag, `--format json` | Same error as above (JSON forces non-interactive even on a TTY).                                                          |

### Edge cases

- **Zero calendars** returned by `list` → exit 1: `No calendars found. Verify your provider connection.`
- **Single calendar** → picker still shown with default `[1]`.
- **Ctrl-C** at prompt → Click `Abort`, exit 1, no `PUT` sent.
- **Invalid input** at prompt → Click `IntRange` re-prompts automatically.

## Architecture

**File touched:** `herds_cli/commands/cmd_calendar.py` only.

### `set_calendar` control flow

```
set_calendar(ctx, email, calendar_id, format)
  ├── setup_session + load_session_auth                       (existing pattern)
  ├── if calendar_id is None:                                  (interactive branch)
  │     ├── if not stdin.isatty() or format == "json":
  │     │     → error: "--calendar-id required non-interactively"
  │     ├── calendars = GET /api/calendar/list
  │     ├── status   = GET /api/calendar/status      (tolerated if it fails)
  │     └── calendar_id = _prompt_for_calendar(calendars, status)
  ├── PUT /api/calendar/settings  body={calendar_id}
  └── print success + format JSON output (skip_table)
```

### New helper: `_prompt_for_calendar(calendars, status) -> str`

Module-level function in `cmd_calendar.py`. Pure function of its inputs apart from the Click prompt — does no I/O.

- Print numbered list to stderr with `(primary)` / `(current)` tags computed from the inputs.
- Compute default index: the index of the calendar matching `status.calendar_id` if found, else the index of the calendar with `primary == True`, else `1` if `len(calendars) == 1`, else `None`.
- Call `click.prompt("Calendar", type=click.IntRange(1, len(calendars)), default=default_idx)`.
- Return the chosen calendar's `id` field.

### Wire format change

CLI `PUT /api/calendar/settings` body:

- **Before:** `{"calendar_id": "...", "calendar_name": "..."}` (name optional)
- **After:** `{"calendar_id": "..."}`

The server is the single source of truth for the display name.

## Error handling

All paths preserve existing CLI conventions: `OutputFormatter.print_error`, `sys.exit(1)`, `HerdsError` boundary at `cli.cli()`.

| Trigger                                                       | Behavior                                                                                                                   |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| No TTY + no flag                                              | Exit 1 with explicit message (see "Non-interactive flow" above).                                                           |
| `--format json` + no flag                                     | Same as above.                                                                                                             |
| `GET /api/calendar/list` returns 400 `no_calendar_connection` | Reuse the existing message from `list_calendars`: `No calendar connected. Run 'herds calendar connect ...'`. Exit 1.       |
| `GET /api/calendar/list` returns empty list                   | Exit 1: `No calendars found. Verify your provider connection.`                                                             |
| `GET /api/calendar/status` fails or returns `connected=False` | Tolerate it. Skip the `(current)` tag and the smart default — degrade to "primary or no default." Do not fail the command. |
| Ctrl-C at prompt                                              | Click raises `Abort`; exit 1, no `PUT` sent.                                                                               |
| Invalid input at prompt                                       | Click `IntRange` re-prompts automatically; no custom code.                                                                 |
| `PUT /api/calendar/settings` fails                            | Existing `execute_api_request` error path.                                                                                 |

## Testing

New file: `tests/cli/test_cli_calendar.py` — first calendar tests in the repo. Follow patterns in `tests/cli/conftest.py` (`mock_api_client`, `cli_obj`).

| #   | Test                      | Setup                                                                 | Expectation                                           |
| --- | ------------------------- | --------------------------------------------------------------------- | ----------------------------------------------------- |
| 1   | Flag passed               | `--calendar-id abc123`                                                | No GETs. Single `PUT` with `{calendar_id: "abc123"}`. |
| 2   | Interactive happy path    | TTY, `input="1\n"`, list returns 3, status's `calendar_id` matches #2 | Default is `[2]`, user picks 1, `PUT` with id of #1.  |
| 3   | Default acceptance        | TTY, `input="\n"`                                                     | Picks the smart default (current).                    |
| 4   | No current selection      | `status` returns `connected=False`                                    | Default falls back to primary.                        |
| 5   | No primary either         | Neither current nor primary                                           | No default; explicit input required.                  |
| 6   | Non-TTY + no flag         | `isatty=False`, no `--calendar-id`                                    | Exit 1 with expected message. No GETs, no `PUT`.      |
| 7   | `--format json` + no flag | TTY, `--format json`, no `--calendar-id`                              | Exit 1 with expected message.                         |
| 8   | Empty calendar list       | `list` returns `[]`                                                   | Exit 1: "No calendars found."                         |
| 9   | No connection             | `list` returns 400 `no_calendar_connection`                           | Exit 1 with reused error message.                     |
| 10  | Status fetch fails        | `status` raises; `list` succeeds                                      | Picker works, no `(current)` tag, default → primary.  |
| 11  | Single calendar           | `list` returns 1 calendar                                             | Picker shown, default `[1]`.                          |
| 12  | Ctrl-C at prompt          | Simulate `Abort`                                                      | Exit 1, no `PUT`.                                     |

**TTY simulation:** mock `sys.stdin.isatty()` for #6; `CliRunner.invoke(..., input="...")` provides stdin for the rest.

## Rollout

The server's auto-resolve change must ship **before** this CLI 2.0 release. If CLI 2.0 ships first, users running the new CLI will see `Calendar Name: Not set` (or null) in `calendar status` because the CLI no longer sends a name and the server doesn't yet resolve one.

The backend plan at `~/dev/herds/docs/exec-plans/active/2026-05-02-calendar-name-auto-resolve.md` is a hard prerequisite for this CLI release.

Version bump: `1.2.x` → `2.0.0`. Per the project's versioning policy, three files move together in one commit: `pyproject.toml`, `herds_cli/__init__.py`, `uv.lock` (regenerated via `uv lock`).

## Out of scope

- Renaming `set-calendar` to anything else.
- Adding a `--non-interactive` flag (TTY detection + `--format json` already cover this).
- Search/filter inside the picker (4–10 entries is the typical case; not worth the dependency).
- Replacing Click's prompt with `questionary` or Rich's `Prompt.ask`.
