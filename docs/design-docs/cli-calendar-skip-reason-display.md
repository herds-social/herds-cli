# CLI: Translate `calendar_add_error` into actionable display

## Status

Approved (not yet implemented)

## Context

When `herds image upload --poll` finishes, `display_event_details`
(`herds_cli/core/base.py:284-318`) prints one of three calendar-status
branches per extracted event:

1. A provider id is set → `Added to {provider} calendar...`
2. `user_data.calendar_add_error` is non-empty →
   `Calendar add failed: {raw_code}`
3. Neither → neutral fallback `Not added to a calendar`

Branch 2 has two problems:

- It treats every code as a "failure" and prints the raw enum string.
  `AUTO_ADD_DISABLED` is a deliberate skip (the user's setting is off
  or they passed `--no-add-to-calendar`); calling it a "failure" is
  misleading. `NO_CALENDAR_CONNECTION` is a configuration state, not
  a runtime error. Only `CALENDAR_PROVIDER_ERROR` and
  `CALENDAR_ADD_EXCEPTION` are genuine failures.
- It tells the user nothing about how to fix the situation. The CLI
  has the relevant remediation commands
  (`herds user-settings update --auto-add-to-calendar=True`,
  `herds calendar connect --provider <p>`,
  `herds calendar status`), but the display doesn't surface them.

Branch 3 is a separate problem (the field can be empty when it
shouldn't be) and is being fixed server-side. This spec assumes that
fix lands and focuses on branch 2.

The five codes the server can emit
(`app/schemas/calendar_schemas.py:40-56` in `~/dev/herds`) are:

- `AUTO_ADD_DISABLED` — per-upload flag off + user setting off
- `NO_CALENDAR_CONNECTION` — no Google/Outlook/Apple provider connected
- `CALENDAR_NEEDS_RECONNECT` — provider revoked our refresh token
- `CALENDAR_PROVIDER_ERROR` — provider rejected the event
- `CALENDAR_ADD_EXCEPTION` — generic crash inside the auto-add pipeline

## Decision

### What changes

1. **New module `herds_cli/calendar_status_display.py`** owning the
   code → message mapping. Pure functions; no Click context, no
   networking. Returns rendered output as a list of
   `(severity, line)` tuples that the caller dispatches through
   `OutputFormatter`. Keeping rendering data-driven means tests don't
   have to capture stdout.

2. **`display_event_details` in `core/base.py:284-318`** is replaced
   by a call into the new module. The success branch
   (`Added to {provider} calendar...`) stays where it is — only the
   `calendar_add_error` and fallback branches are reworked.

3. **A `ReconnectProviderResolver` helper** lazily fetches
   `GET /api/calendar/status` once per upload to learn which provider
   the user previously connected, but only when at least one event in
   the batch carries `calendar_needs_reconnect`. Result is cached on
   the resolver instance. Network failure or `connected: false` falls
   back to a `<google|outlook>` placeholder rather than raising.

4. **`_poll_and_display_event`
   (`herds_cli/commands/cmd_image.py:156`)** constructs one resolver
   and threads it into each `display_event_details` call so a
   multi-event image makes at most one extra status call regardless of
   how many events triggered reconnect.

### Output by code

```
AUTO_ADD_DISABLED
ℹ️  Not added to calendar: auto-add is disabled in your settings
   Enable with: herds user-settings update --auto-add-to-calendar=True

NO_CALENDAR_CONNECTION
ℹ️  Not added to calendar: no calendar provider connected
   Connect with: herds calendar connect --provider google  (or --provider outlook)

CALENDAR_NEEDS_RECONNECT      (provider resolved from /api/calendar/status)
⚠️  Not added to calendar: connection has expired and needs to be reconnected
   Reconnect with: herds calendar connect --provider google

CALENDAR_NEEDS_RECONNECT      (resolver returned None — fallback)
⚠️  Not added to calendar: connection has expired and needs to be reconnected
   Reconnect with: herds calendar connect --provider <google|outlook>

CALENDAR_PROVIDER_ERROR
⚠️  Not added to calendar: your calendar provider rejected the event
   Run: herds calendar status   for connection diagnostics

CALENDAR_ADD_EXCEPTION
⚠️  Not added to calendar: an unexpected error occurred during auto-add
   Run: herds calendar status   for connection diagnostics

(unknown future code — defensive fallback)
⚠️  Not added to calendar: {raw_code}
```

Severity convention: `ℹ️` for user-actionable configuration states,
`⚠️` for runtime/auth failures. The unknown-code fallback uses `⚠️`
because we genuinely don't know what happened.

### Why a lazy `/api/calendar/status` lookup for `NEEDS_RECONNECT`

Three alternatives were considered (full design space in
`~/plans/deferred/server-calendar-needs-reconnect-provider-hint.md`):

- **Server adds `calendar_add_error_provider` sibling field** —
  cleanest long-term, but requires schema + transformer + persistence
  changes server-side. Deferred.
- **Encode provider into the error code** (e.g.
  `calendar_needs_reconnect_google`) — explodes the enum and
  conflates kind with parameter. Rejected.
- **Lazy CLI lookup of `/api/calendar/status`** — chosen.

The cost of the chosen approach is bounded: at most one extra `GET`
per upload, and only when an event in that upload carries
`calendar_needs_reconnect`. That code is rare in practice (it requires
an active connection whose token has been revoked), so the steady-state
overhead is essentially zero. If it ever becomes common, the deferred
plan exists.

### Edge cases

- **`/api/calendar/status` returns `connected: false`** while an event
  carries `calendar_needs_reconnect`. Shouldn't happen but harmless —
  fall back to the `<google|outlook>` placeholder.
- **Network error fetching status.** Same fallback; the resolver
  swallows the exception and logs at debug. We don't want a status
  blip to mask the calendar message itself.
- **Unknown error code from the server.** Hit when the server adds a
  new code we haven't taught the CLI yet. We render
  `Not added to calendar: {raw_code}` so we never silently lose
  information.
- **Multiple distinct error codes across events in one image.** Each
  event renders its own message. The resolver is shared but only used
  for `NEEDS_RECONNECT`-flagged events.
- **Both fields empty (no provider id, no `calendar_add_error`).**
  Should not happen once the server-side persistence fix has shipped,
  but kept as a defensive last resort: print today's neutral
  `Not added to a calendar` so we never produce no calendar line at
  all.

### Tests

- Unit tests in `tests/unit/test_calendar_status_display.py`:
  one parametrized case per code asserting the rendered tuple list.
- Unit test for `ReconnectProviderResolver`: caches one HTTP call
  across N invocations; falls back on HTTP error; falls back when
  `connected` is False.
- CLI test in `tests/cli/test_cli_image.py` extending the existing
  `--poll` fixtures: mock an upload that returns each error code and
  assert the new lines appear in the captured output. Use the
  existing `mock_api_client` fixture for the `/api/calendar/status`
  stub.

## Consequences

### Trade-offs

- One extra HTTP call on the rare `NEEDS_RECONNECT` path. Acceptable
  given the code's rarity.
- Two display surfaces (`events get`, `events list`) inherit the
  improved behavior because they share `display_event_details`. Minor
  scope creep, but the alternative (special-casing) is worse.
- No server change in this branch; the deferred sibling-field plan
  remains available if reconnect frequency changes.

### What changes for users

- Every "not added to calendar" outcome now produces one of five
  named messages with a concrete next-step command, instead of a raw
  enum or silent fallback.
- `--format json` output is unchanged — the new strings live only in
  the human-readable display path.

### What does NOT change

- The success branch (`Added to {provider} calendar...`) is
  untouched.
- The server-side bug that's leaving `calendar_add_error` empty in
  some uploads is out of scope; it's tracked separately
  (`~/plans/completed/server-fix-auto-add-disabled-persistence.md`).
- No changes to `events get` / `events list` commands beyond what
  they inherit from `display_event_details`.
