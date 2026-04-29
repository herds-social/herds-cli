# CLI: Surface `ignored_fields` from `PUT /api/user/setting` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the silent partial-success on `PUT /api/user/setting` observable in `herds user-settings update` by rendering a yellow ⚠️ partial-success header with per-field reasons whenever the server returns a non-empty `ignored_fields` array.

**Architecture:** Localized to two production files (`herds_cli/types.py`, `herds_cli/commands/cmd_user_settings.py`) plus tests. A small `_format_ignored_field_reason` helper maps reason codes (currently only `requires_paid_subscription`) to human-readable strings, with a fallback that prints the raw enum string if the server adds an unknown reason. The existing JSON output passes through unchanged.

**Tech Stack:** Python 3.11+, Click, Rich, pytest, Click CliRunner. Runtime under `uv`.

**Companion design doc:** `docs/design-docs/cli-ignored-fields.md`.

**Upstream server change:** commit `4b28d62` on branch `emdash/silent-premium-drop-1ss` (already merged).

---

## File Structure

| File                                      | Role                                                                                 |
| ----------------------------------------- | ------------------------------------------------------------------------------------ |
| `herds_cli/types.py`                      | TypedDicts and Literals — pure leaf, no imports from project. Add 3 new symbols.     |
| `herds_cli/commands/cmd_user_settings.py` | Click command group. Adds `_format_ignored_field_reason` and partial-success branch. |
| `tests/unit/test_helpers.py`              | Existing unit-test home for cmd\_\*.py helpers. Adds `TestFormatIgnoredFieldReason`. |
| `tests/cli/test_cli_user_settings.py`     | NEW. CliRunner integration tests for `user-settings update` rendering paths.         |
| `pyproject.toml`                          | Version bump 1.1.0 → 1.2.0 (line 7).                                                 |
| `herds_cli/__init__.py`                   | Version bump 1.1.0 → 1.2.0 (line 8).                                                 |

---

## Task 1: Add types to `herds_cli/types.py`

**Why first:** Pure additive type symbols. No behavior change, no tests needed (TypedDicts and Literals are static-analysis surface only). Both Task 2 and Task 4 will import these.

**Files:**

- Modify: `herds_cli/types.py:9` (imports), `herds_cli/types.py:200` (after existing `UserSettings`)

- [ ] **Step 1: Read the existing types module to find insertion points**

Run: `head -15 herds_cli/types.py && grep -n "class UserSettings" herds_cli/types.py`

Expected: confirms imports list at line 9 and locates `class UserSettings(TypedDict, total=False):` so the new symbols land logically next to the related schema.

- [ ] **Step 2: Add the new symbols**

Add `Literal` and `List` to the existing typing import (they may already be there — confirm before editing). Then append three new symbols immediately after the existing `class UserSettings(TypedDict, total=False):` block.

In `herds_cli/types.py`, locate this existing block:

```python
class UserSettings(TypedDict, total=False):
    """User preference settings from GET /api/users/me."""

    default_calendar: Optional[str]
    sort_by: Optional[str]
    filter_by: Optional[str]
```

Insert immediately after it:

```python
IgnoredFieldReason = Literal["requires_paid_subscription"]
"""Reason codes the server returns in UserSettingsUpdateResponse.ignored_fields.

Today the only reason is requires_paid_subscription; the literal grows in
lockstep with the server's IgnoredFieldReasonEnum. The runtime mapping in
cmd_user_settings._format_ignored_field_reason falls back to the raw string
for unknown reasons so older CLIs keep working when the server adds new ones.
"""


class IgnoredField(TypedDict):
    """One entry in UserSettingsUpdateResponse.ignored_fields.

    Mirrors the server's app.schemas.user_settings_schemas.IgnoredField.
    """

    field: str
    reason: IgnoredFieldReason


class UserSettingsUpdateResponse(TypedDict, total=False):
    """Response from PUT /api/user/setting.

    The settings dict is left loose because the existing command code accesses
    it via .get() on a handful of fields — tightening it isn't part of this
    change. ignored_fields lists fields the request set but the server did
    not apply (e.g., free-tier user PATCHing premium-only fields). Empty list
    or absent field means every requested change was applied.
    """

    user_id: str
    settings: dict
    ignored_fields: List[IgnoredField]
    created_at: str
    updated_at: str
```

- [ ] **Step 3: Verify the types module still imports**

Run: `uv run python -c "from herds_cli.types import IgnoredField, IgnoredFieldReason, UserSettingsUpdateResponse; print('ok')"`

Expected: prints `ok` with no traceback.

- [ ] **Step 4: Commit**

```bash
git add herds_cli/types.py
git commit -m "feat(types): add IgnoredField + UserSettingsUpdateResponse for PUT /api/user/setting

Mirrors the server-side IgnoredField/IgnoredFieldReasonEnum schema added in
emdash/silent-premium-drop-1ss. The Literal stays narrow today (only
requires_paid_subscription) and grows alongside the server enum; runtime
fallback in cmd_user_settings keeps older CLIs working when the server
adds new reason codes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add `_format_ignored_field_reason` helper (TDD)

**Why next:** Pure-function helper with no I/O. Easy to TDD. Task 4 will call it.

**Files:**

- Modify: `herds_cli/commands/cmd_user_settings.py` (top of file, near other module-level helpers)
- Test: `tests/unit/test_helpers.py` (add a new `TestFormatIgnoredFieldReason` class)

- [ ] **Step 1: Write the failing tests**

Open `tests/unit/test_helpers.py`. Add this import next to the existing `from herds_cli.commands.cmd_*` imports near the top of the file:

```python
from herds_cli.commands.cmd_user_settings import _format_ignored_field_reason
```

Append this test class to the end of the file:

```python
# ---------------------------------------------------------------------------
# _format_ignored_field_reason
# ---------------------------------------------------------------------------


class TestFormatIgnoredFieldReason:
    def test_known_reason_returns_human_string(self):
        assert (
            _format_ignored_field_reason("requires_paid_subscription")
            == "requires a paid subscription"
        )

    def test_unknown_reason_falls_back_to_raw_string(self):
        # Forward-compatibility: a future server reason like quota_exceeded
        # should print as-is rather than disappear, so the user still gets
        # *some* explanation even on an outdated CLI.
        assert _format_ignored_field_reason("quota_exceeded") == "quota_exceeded"

    def test_empty_string_returns_empty_string(self):
        assert _format_ignored_field_reason("") == ""
```

- [ ] **Step 2: Run the test and confirm it fails with ImportError**

Run: `uv run pytest tests/unit/test_helpers.py::TestFormatIgnoredFieldReason -v`

Expected: FAILS at collection time with `ImportError: cannot import name '_format_ignored_field_reason' from 'herds_cli.commands.cmd_user_settings'`. This is the red bar.

- [ ] **Step 3: Add the helper to `cmd_user_settings.py`**

In `herds_cli/commands/cmd_user_settings.py`, immediately after the existing import block (currently ending around line 14 with `from herds_cli.core.base import CommandBase, APIResponseHandler`), add:

```python


# Maps server-side IgnoredField.reason enum values to human-readable
# explanations rendered in the partial-success warning. Unknown reasons fall
# through to their raw string via _format_ignored_field_reason — that is the
# forward-compatibility hinge for new server enum values.
_IGNORED_FIELD_REASON_MESSAGES: dict[str, str] = {
    "requires_paid_subscription": "requires a paid subscription",
}


def _format_ignored_field_reason(reason: str) -> str:
    """Map an IgnoredField.reason enum value to a human-readable explanation.

    Unknown reasons fall through to the raw string so a server-side enum
    addition (e.g., a future quota_exceeded) doesn't silently swallow the
    explanation in older CLI builds — the user still sees *something*.
    """
    return _IGNORED_FIELD_REASON_MESSAGES.get(reason, reason)
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `uv run pytest tests/unit/test_helpers.py::TestFormatIgnoredFieldReason -v`

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add herds_cli/commands/cmd_user_settings.py tests/unit/test_helpers.py
git commit -m "feat(user-settings): add _format_ignored_field_reason helper

Pure mapping from server reason codes to human-readable strings, with a
fallback to the raw string for forward compatibility. Used by the
partial-success rendering path added in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Write CliRunner test file with all 6 integration tests

**Why all six at once:** TDD with CliRunner is most natural at the file level — write the test file, run it, see which cases the existing implementation already covers (the happy path) vs. fails (the new partial-success path). Then Task 4 makes the failing ones pass.

**Files:**

- Create: `tests/cli/test_cli_user_settings.py`

- [ ] **Step 1: Create the test file**

Create `tests/cli/test_cli_user_settings.py` with this content:

```python
"""User settings command tests via Click's CliRunner.

Exercises the rendering branches of `herds user-settings update`,
particularly the partial-success path triggered by ignored_fields in
the server response.
"""

import json
from unittest.mock import MagicMock

from tests.cli.conftest import strip_ansi
from herds_cli.cli import cli


def _make_settings_response(ignored_fields=None, **settings_overrides):
    """Build a UserSettingsUpdateResponse-shaped dict for mocking the PUT.

    Defaults match a free-tier user: theme=light, auto_add=False. Override
    any field via kwargs. ignored_fields defaults to an empty list; pass a
    list of {field, reason} dicts to simulate a partial-success response.
    Pass ignored_fields=False (the boolean) to omit the key entirely,
    simulating an older server that doesn't return the field.
    """
    settings = {
        "default_calendar": "Family",
        "sort_by": "utc_start",
        "sort_order": "asc",
        "filter_by": "all",
        "theme": "light",
        "auto_add_to_calendar_enabled": False,
        "date_filter": "all",
    }
    settings.update(settings_overrides)
    body = {
        "user_id": "u-123",
        "settings": settings,
        "created_at": "2026-04-29T00:00:00Z",
        "updated_at": "2026-04-29T00:00:00Z",
    }
    if ignored_fields is not False:
        body["ignored_fields"] = ignored_fields or []
    return body


def _save_test_session(session_manager, email="test@example.com"):
    """Persist a minimal mobile session so cmd.setup_session/load_session_auth pass."""
    session_manager.save_session(email, {
        "client_type": "mobile",
        "tokens": {"access_token": "tok"},
        "user_data": {"id": "u-123", "email": email},
    })


def _mock_put_response(cli_obj, body):
    """Wire the mocked HTTP session to return `body` from the next request."""
    response = MagicMock(status_code=200)
    response.json.return_value = body
    response.cookies = {}
    cli_obj["api_client"].session.request.return_value = response
    return response


class TestUpdateSettings:
    def test_no_ignored_fields_renders_success_header(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """Empty ignored_fields → existing green ✅ Settings updated: header."""
        _save_test_session(mock_session_manager)
        _mock_put_response(cli_obj, _make_settings_response(ignored_fields=[]))

        result = cli_runner.invoke(
            cli,
            ["user-settings", "update", "--default-calendar", "Family"],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "Settings updated:" in out
        assert "partially updated" not in out.lower()

    def test_ignored_fields_renders_partial_success_header(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """Non-empty ignored_fields → ⚠️ partial-success header + reason bullets."""
        _save_test_session(mock_session_manager)
        _mock_put_response(
            cli_obj,
            _make_settings_response(
                ignored_fields=[
                    {"field": "theme", "reason": "requires_paid_subscription"}
                ]
            ),
        )

        result = cli_runner.invoke(
            cli,
            ["user-settings", "update", "--theme", "dark"],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "partially updated" in out.lower()
        assert "1 field" in out  # singular: "1 field ignored"
        assert "theme" in out
        assert "requires a paid subscription" in out
        # The success header MUST NOT appear when partial.
        assert "Settings updated:" not in out
        # Saved values should still be displayed under a neutral header.
        assert "Saved values:" in out

    def test_multiple_ignored_fields_listed(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """Two ignored fields → both appear in the bullet list."""
        _save_test_session(mock_session_manager)
        _mock_put_response(
            cli_obj,
            _make_settings_response(
                ignored_fields=[
                    {"field": "theme", "reason": "requires_paid_subscription"},
                    {
                        "field": "auto_add_to_calendar_enabled",
                        "reason": "requires_paid_subscription",
                    },
                ]
            ),
        )

        result = cli_runner.invoke(
            cli,
            [
                "user-settings",
                "update",
                "--theme",
                "dark",
                "--auto-add-to-calendar=True",
            ],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "2 field" in out  # plural: "2 fields ignored"
        assert "theme" in out
        assert "auto_add_to_calendar_enabled" in out
        # Both reasons rendered.
        assert out.count("requires a paid subscription") == 2

    def test_unknown_reason_code_falls_back_to_raw_string(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """A future reason code unknown to this CLI prints raw, doesn't crash."""
        _save_test_session(mock_session_manager)
        _mock_put_response(
            cli_obj,
            _make_settings_response(
                ignored_fields=[
                    {"field": "theme", "reason": "quota_exceeded"}
                ]
            ),
        )

        result = cli_runner.invoke(
            cli,
            ["user-settings", "update", "--theme", "dark"],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "theme" in out
        # Falls back to raw enum string rather than swallowing or crashing.
        assert "quota_exceeded" in out

    def test_json_format_passes_through_ignored_fields(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """--format json includes the ignored_fields array verbatim."""
        _save_test_session(mock_session_manager)
        ignored = [{"field": "theme", "reason": "requires_paid_subscription"}]
        _mock_put_response(
            cli_obj, _make_settings_response(ignored_fields=ignored)
        )

        # Override format on the injected obj — cmd code reads cmd.output_format.
        cli_obj["format"] = "json"
        cli_obj["config"].output_format = "json"

        result = cli_runner.invoke(
            cli,
            ["user-settings", "update", "--theme", "dark"],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        # Locate the JSON object embedded in the output and confirm it carries
        # the ignored_fields array unmodified.
        start = out.find("{")
        end = out.rfind("}")
        assert start != -1 and end != -1, f"no JSON found in output: {out!r}"
        parsed = json.loads(out[start : end + 1])
        assert parsed["ignored_fields"] == ignored

    def test_missing_ignored_fields_treated_as_empty(
        self, cli_runner, cli_obj, mock_session_manager
    ):
        """Older server without the field → no warning, success header renders."""
        _save_test_session(mock_session_manager)
        # ignored_fields=False (sentinel) tells the helper to OMIT the key.
        _mock_put_response(
            cli_obj, _make_settings_response(ignored_fields=False)
        )

        result = cli_runner.invoke(
            cli,
            ["user-settings", "update", "--default-calendar", "Family"],
            obj=cli_obj,
        )

        out = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "Settings updated:" in out
        assert "partially updated" not in out.lower()
```

- [ ] **Step 2: Run the test file and observe red/green split**

Run: `uv run pytest tests/cli/test_cli_user_settings.py -v`

Expected: 2 PASS (the no-ignored-fields and missing-ignored-fields cases — current code already prints "Settings updated:" unconditionally), 4 FAIL (partial-success, multiple, unknown-reason, JSON-passthrough — current code never renders the warning). Pin the failing test names; Task 4 will turn them green.

- [ ] **Step 3: Commit the (still-red) test file**

```bash
git add tests/cli/test_cli_user_settings.py
git commit -m "test(user-settings): add CliRunner suite for update_settings rendering

Six tests covering: empty ignored_fields (success header preserved),
single/multiple partial-success, unknown reason fallback, JSON-format
passthrough, and older-server compat (missing field treated as empty).
Four currently fail; the implementation in the next commit makes them
green.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Implement the partial-success rendering

**Why:** Make the four failing tests from Task 3 pass.

**Files:**

- Modify: `herds_cli/commands/cmd_user_settings.py:268-291` (the `update_settings` post-PUT rendering block)

- [ ] **Step 1: Read the current rendering block to confirm the line range**

Run: `sed -n '260,295p' herds_cli/commands/cmd_user_settings.py`

Expected output ends with the `APIResponseHandler.format_and_output(result, ...)` call. Confirm the block currently does an unconditional `OutputFormatter.print_success("Settings updated:")` followed by 6 `print_info` calls and the final `format_and_output`.

- [ ] **Step 2: Replace the rendering block with the branched version**

In `herds_cli/commands/cmd_user_settings.py`, locate this existing code (currently around lines 270-291):

```python
    # Display updated settings
    updated_settings = result.get("settings", {})
    OutputFormatter.print_success("Settings updated:")
    OutputFormatter.print_info(
        f"  Default Calendar: {updated_settings.get('default_calendar', 'Not set')}"
    )
    OutputFormatter.print_info(
        f"  Sort By: {updated_settings.get('sort_by', 'Not set')}"
    )
    OutputFormatter.print_info(
        f"  Filter By: {updated_settings.get('filter_by', 'Not set')}"
    )
    OutputFormatter.print_info(f"  Theme: {updated_settings.get('theme', 'Not set')}")
    OutputFormatter.print_info(
        f"  Auto Add to Calendar: {updated_settings.get('auto_add_to_calendar_enabled', 'Not set')}"
    )
    date_filter_val = updated_settings.get("date_filter")
    date_filter = date_filter_val if isinstance(date_filter_val, str) else None
    OutputFormatter.print_info(f"  Date Filter: {_format_date_filter(date_filter)}")

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format, skip_table=True)
```

Replace with:

```python
    # Display updated settings — branch on ignored_fields to honor partial
    # success. The server returns a non-empty ignored_fields when free-tier
    # users PATCH premium-only fields (the silent-drop behavior). Older
    # servers omit the field entirely, which we treat as an empty list.
    updated_settings = result.get("settings", {})
    ignored_fields = result.get("ignored_fields", [])

    if ignored_fields:
        count = len(ignored_fields)
        plural = "field" if count == 1 else "fields"
        OutputFormatter.print_warning(
            f"Settings partially updated — {count} {plural} ignored:"
        )
        for entry in ignored_fields:
            field_name = entry.get("field", "<unknown>")
            reason = _format_ignored_field_reason(entry.get("reason", ""))
            OutputFormatter.print_info(f"  • {field_name} — {reason}")
        OutputFormatter.print_info("Saved values:")
    else:
        OutputFormatter.print_success("Settings updated:")

    OutputFormatter.print_info(
        f"  Default Calendar: {updated_settings.get('default_calendar', 'Not set')}"
    )
    OutputFormatter.print_info(
        f"  Sort By: {updated_settings.get('sort_by', 'Not set')}"
    )
    OutputFormatter.print_info(
        f"  Filter By: {updated_settings.get('filter_by', 'Not set')}"
    )
    OutputFormatter.print_info(f"  Theme: {updated_settings.get('theme', 'Not set')}")
    OutputFormatter.print_info(
        f"  Auto Add to Calendar: {updated_settings.get('auto_add_to_calendar_enabled', 'Not set')}"
    )
    date_filter_val = updated_settings.get("date_filter")
    date_filter = date_filter_val if isinstance(date_filter_val, str) else None
    OutputFormatter.print_info(f"  Date Filter: {_format_date_filter(date_filter)}")

    # Output formatted response (JSON path includes ignored_fields verbatim)
    APIResponseHandler.format_and_output(result, cmd.output_format, skip_table=True)
```

- [ ] **Step 3: Run the new test file and confirm all 6 pass**

Run: `uv run pytest tests/cli/test_cli_user_settings.py -v`

Expected: 6 PASSED.

- [ ] **Step 4: Run the full unit-helper test for the helper-fallback branch**

Run: `uv run pytest tests/unit/test_helpers.py::TestFormatIgnoredFieldReason -v`

Expected: 3 PASSED. (Sanity check — Task 2's tests should still pass.)

- [ ] **Step 5: Commit**

```bash
git add herds_cli/commands/cmd_user_settings.py
git commit -m "feat(user-settings): render partial-success header on ignored_fields

Free-tier users PATCHing premium-only fields (theme, auto_add) used to
get a green ✅ Settings updated: header even though the server silently
dropped their request. With the server-side ignored_fields contract now
in place (commit 4b28d62 on emdash/silent-premium-drop-1ss), branch the
rendering: yellow ⚠️ partial-success header with per-field bullets when
ignored_fields is non-empty, neutral 'Saved values:' sub-header above
the field listing.

Empty/missing ignored_fields preserves the existing success header so
the CLI stays compatible with older servers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Verify full suite and bump version

**Why last:** Confirm nothing else regressed before locking in the version bump.

**Files:**

- Modify: `pyproject.toml:7`
- Modify: `herds_cli/__init__.py:8`

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`

Expected: ALL pass (existing + new). If anything unrelated regressed, stop and diagnose before proceeding.

- [ ] **Step 2: Bump version in `pyproject.toml`**

Edit `pyproject.toml` line 7:

```toml
version = "1.2.0"
```

(Was `version = "1.1.0"`.)

- [ ] **Step 3: Bump version in `herds_cli/__init__.py`**

Edit `herds_cli/__init__.py` line 8:

```python
__version__ = "1.2.0"
```

(Was `__version__ = "1.1.0"`.)

- [ ] **Step 4: Verify both files are in sync**

Run: `grep -E '^version' pyproject.toml && grep __version__ herds_cli/__init__.py`

Expected:

```
version = "1.2.0"
__version__ = "1.2.0"
```

- [ ] **Step 5: Manual smoke (optional but recommended)**

If you have a free-tier dev session available, smoke-test the partial-success path:

```bash
uv run herds user-settings update --theme dark
```

Expected: Yellow ⚠️ "Settings partially updated — 1 field ignored:" header, bullet `• theme — requires a paid subscription`, then "Saved values:" + the field listing showing `Theme: light` (unchanged). Exit code 0.

If you don't have a free-tier session handy, skip this step — the CliRunner tests cover the same paths.

- [ ] **Step 6: Commit the version bump**

```bash
git add pyproject.toml herds_cli/__init__.py
git commit -m "chore(version): bump 1.1.0 -> 1.2.0 for ignored_fields surfacing

Additive feature — new partial-success rendering branch in
\`herds user-settings update\`, no flag removals or schema breaks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Verification

The implementation is complete when:

1. `uv run pytest tests/cli/test_cli_user_settings.py tests/unit/test_helpers.py::TestFormatIgnoredFieldReason -v` shows 9 PASSED (6 CLI + 3 helper).
2. `uv run pytest -v` shows the full suite passing — no unrelated regressions.
3. `grep -E '^version' pyproject.toml` and `grep __version__ herds_cli/__init__.py` both show `1.2.0`.
4. `git log --oneline main..HEAD` shows 5 commits in the order: types → helper → tests → impl → version.
5. Manual smoke (if performed): a free-tier `--theme dark` PATCH renders the yellow ⚠️ header with the correct field name and reason.

## Out of Scope (carried from spec)

- `get_settings` is not modified (server's `get_settings()` always returns `[]` for `ignored_fields`).
- No exit-code change — partial success still exits 0.
- No client-side tier check before PATCH.
- No upgrade-CTA URL in the warning (the `--help` text already labels the flags "(paid plan only)").
- No change to the silent-drop behavior on the server.
