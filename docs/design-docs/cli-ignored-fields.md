# CLI: Surface `ignored_fields` from `PUT /api/user/setting`

## Status

Implemented

## Context

The Herds server (`PUT /api/user/setting`) silently drops premium-only fields
(`theme`, `auto_add_to_calendar_enabled`) when a free-tier client PUTs
them, returning 200 OK with the unchanged stored values. The CLI's current
`herds user-settings update` prints a green ✅ "Settings updated:" header
and the saved values, giving the user no signal that part of their request
was ignored.

A companion server change (commit `4b28d62` on `silent-premium-drop-1ss`)
made the silent drop observable by adding a new field to
`UserSettingsResponse`:

```json
{
  "settings": {...},
  "ignored_fields": [
    {"field": "theme", "reason": "requires_paid_subscription"},
    {"field": "auto_add_to_calendar_enabled", "reason": "requires_paid_subscription"}
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

`ignored_fields` is a list of `{field, reason}` objects. `reason` is a
string enum, currently only `requires_paid_subscription`, designed to grow
(e.g., a future `quota_exceeded` or `feature_flag_disabled`).

The original feedback note (`~/plans/silent-premium-drop-feedback.md`) called
for `dropped_premium_fields: list[str]`, but the server shipped the
generalized `ignored_fields: list[{field, reason}]` shape. This spec
consumes the actual server contract.

## Decision

### What changes

1. **Render a partial-success header in `update_settings`** when
   `ignored_fields` is non-empty. The current unconditional ✅ "Settings
   updated:" header is replaced with a yellow ⚠️ "Settings partially
   updated — N field(s) ignored:" header followed by a bulleted list of
   `{field}: {reason explanation}`, then a neutral "Saved values:"
   sub-header above the existing field listing.

   When `ignored_fields` is empty or absent, output is unchanged from
   today (preserves backward compatibility with older servers that don't
   return the field).

2. **Add a reason-rendering helper** in `cmd_user_settings.py`:

   ```python
   _IGNORED_FIELD_REASON_MESSAGES: dict[str, str] = {
       "requires_paid_subscription": "requires a paid subscription",
   }

   def _format_ignored_field_reason(reason: str) -> str:
       """Map an IgnoredField.reason enum value to a human-readable explanation.

       Unknown reasons fall through to the raw string so a server-side enum
       addition doesn't silently swallow the explanation in older CLI builds.
       """
       return _IGNORED_FIELD_REASON_MESSAGES.get(reason, reason)
   ```

   The fallback is the forward-compatibility hinge: if the server ships
   `quota_exceeded` next quarter, an old CLI prints the raw string rather
   than nothing.

3. **Type the response shape** in `herds_cli/types.py`:

   ```python
   IgnoredFieldReason = Literal["requires_paid_subscription"]

   class IgnoredField(TypedDict):
       field: str
       reason: IgnoredFieldReason

   class UserSettingsUpdateResponse(TypedDict, total=False):
       """Response from PUT /api/user/setting."""
       user_id: str
       settings: dict
       ignored_fields: List[IgnoredField]
       created_at: str
       updated_at: str
   ```

   The `Literal` stays narrow (only the currently-shipping reason). Both
   the literal and `_IGNORED_FIELD_REASON_MESSAGES` grow in lockstep when
   the server adds new reasons. Runtime fallback in
   `_format_ignored_field_reason` keeps older CLIs from breaking before
   that update lands.

4. **Add `tests/cli/test_cli_user_settings.py`** (new file — there are
   currently no CLI-layer tests for `cmd_user_settings`). Cover:
   - `test_update_succeeds_with_no_ignored_fields` — server returns
     `ignored_fields: []`; output contains "Settings updated:" and not
     "partially updated"; exit 0.
   - `test_update_renders_partial_success_when_ignored_fields_present` —
     one ignored field; output contains "partially updated", the field
     name, and "requires a paid subscription"; exit 0 (not 1, not 2).
   - `test_update_handles_multiple_ignored_fields` — two fields both
     appear in the bullet list with their reasons.
   - `test_update_falls_back_for_unknown_reason_code` — `reason: "quota_exceeded"` (hypothetical future reason); output contains the raw string and doesn't crash.
   - `test_update_json_format_passes_through_ignored_fields` —
     `--format json` output contains the `ignored_fields` array verbatim.
   - `test_update_treats_missing_ignored_fields_as_empty` — response
     without the field; behaves like empty list, no warning. Defensive
     against older servers.

5. **Bump version** `1.1.0` → `1.2.0` in `pyproject.toml` and
   `herds_cli/__init__.py` (minor — additive feature, no schema break).

### Files touched

| File                                      | Change                                                                             |
| ----------------------------------------- | ---------------------------------------------------------------------------------- |
| `herds_cli/types.py`                      | Add `IgnoredFieldReason`, `IgnoredField`, `UserSettingsUpdateResponse`             |
| `herds_cli/commands/cmd_user_settings.py` | `_format_ignored_field_reason` helper; partial-success branch in `update_settings` |
| `tests/cli/test_cli_user_settings.py`     | New file; six test cases above                                                     |
| `pyproject.toml`                          | Version bump                                                                       |
| `herds_cli/__init__.py`                   | Version bump                                                                       |

### What does NOT change

- **`get_settings` is untouched.** The shared `UserSettingsResponse`
  schema technically permits `ignored_fields` on GET, but the server's
  `get_settings()` always returns `[]` because reading doesn't drop
  anything. If the server's intent ever changes, the CLI follows then.
- **Exit code stays 0** when `ignored_fields` is non-empty. The HTTP
  request succeeded (partial-success); the warning is loud enough for
  human users; scripted users can detect drops via `--format json`.
  Adding a non-zero exit would break any script that batches settings
  calls and expects 0 on partial success.
- **No client-side tier check.** The CLI doesn't pre-validate against
  tier; it reports what the server says. Adding a `tier` lookup would
  invite drift between two sources of truth (this is the explicit "Out
  of Scope" guidance from the upstream feedback note).
- **No `--upgrade` CTA URL.** The existing `--help` text for `--theme`
  and `--auto-add-to-calendar` already says "(paid plan only)". A CTA
  is a separate UX decision.
- **No change to silent-drop behavior.** Server still applies
  partial-success rather than 403. CLI just makes the drop observable.

## Consequences

### Wins

- **Free-tier users see the drop.** Today: green ✅ + a baffling
  "wait, why is theme still light?". After: yellow ⚠️ + an explicit
  reason for each ignored field.
- **Forward-compatible with new server reasons.** The
  `dict.get(reason, reason)` fallback means a server that adds
  `quota_exceeded` won't crash an old CLI; it'll print the raw enum
  string.
- **Backward-compatible with older servers.** `result.get("ignored_fields", [])`
  treats a missing field as an empty list, so a CLI built against the
  new server still works against an older one.
- **First test coverage for `cmd_user_settings`.** The new test file
  doubles as regression coverage for the existing happy-path output.

### Trade-offs

- **The `IgnoredFieldReason` literal will need updating** every time the
  server adds a reason. Failure mode is mild (mypy warning if a test
  hard-codes a new reason; runtime is unaffected via fallback), but it
  is real maintenance.
- **The "Saved values:" sub-header is a visual change** in the
  partial-success branch. Users scraping the output for "Settings
  updated:" lose that match — but anyone scraping CLI output should
  use `--format json`, and the JSON shape is unchanged.

### Cross-references

- Upstream server change: commit `4b28d62` on branch
  `emdash/silent-premium-drop-1ss` (server worktree at
  `~/dev/worktrees/silent-premium-drop-1ss`).
- Server schema: `app/schemas/user_settings_schemas.py`
  (`IgnoredField`, `IgnoredFieldReasonEnum`,
  `UserSettingsResponse.ignored_fields`).
- Original feedback note: `~/plans/silent-premium-drop-feedback.md`
  (proposed `dropped_premium_fields: list[str]`; server shipped the
  more general `ignored_fields: list[{field, reason}]`).
- Calendar-status companion: `docs/exec-plans/completed/2026-04-28-calendar-status-readiness.md`
  (analog `blockers` field on `/api/calendar/status`).
