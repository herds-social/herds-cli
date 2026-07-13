# Adopt XDG Base Directory layout for config and session storage

## Status

Approved

## Context

The CLI stores everything under a single home-directory dotfile,
`HERDS_DIR = ~/.herds/` (`herds_cli/sessions.py`). That directory mixes two
categorically different kinds of file:

- **`config.json`** - user configuration.
- **`herds_session_<email>`** - auth cookies / bearer tokens written by the
  login flow. The user never hand-edits these; they are data / state, not
  configuration.

Current path behavior:

- Config **read** precedence (`herds_cli/cli.py`): `--config` flag ->
  `HERDS_CONFIG_FILE` env -> `./herds-cli-config.json` (cwd) ->
  `~/.herds/config.json`.
- Config **write** (`herds_cli/commands/cmd_config.py`): `save`, `set`, and
  `show` default to `./herds-cli-config.json` in the current working
  directory - inconsistent with the read fallback and surprising (a config
  edit drops a file wherever you happen to be standing).
- Sessions live in `~/.herds/`, overridable via the `session_dir` config
  field or `HERDS_SESSION_DIR`.

This layout predates any XDG support, clutters `$HOME` with a bespoke
dotfile, ignores `$XDG_CONFIG_HOME` / `$XDG_STATE_HOME` that dotfile-managed
setups rely on, and files credentials in the same place as config.

### Requirements

**Functional**

- Config lives at `$XDG_CONFIG_HOME/herds/config.json`, defaulting to
  `~/.config/herds/config.json`.
- Session / credential files live at `$XDG_STATE_HOME/herds/`, defaulting to
  `~/.local/state/herds/`.
- Honor the `XDG_CONFIG_HOME` and `XDG_STATE_HOME` environment variables;
  fall back to the spec defaults when a variable is unset or empty.

**Constraints / invariants to preserve**

- Existing override seams keep working: the `--config` flag,
  `HERDS_CONFIG_FILE`, `HERDS_SESSION_DIR`, and the `session_dir` config
  field.
- The `_initialized` guard in `cli.cli()` still short-circuits before any
  real-filesystem work, so tests never touch a real home directory.

**Non-goals**

- Automated migration of existing `~/.herds/` data. The CLI is currently
  single-user; the one existing install is moved by hand (see Decision).
  Shipping migration code for a population of one is not worth its startup
  logic and test surface.
- Windows-native conventions (`%APPDATA%`). On Windows without XDG vars the
  CLI falls back to `~/.config` / `~/.local/state`. Out of scope.
- `XDG_CACHE_HOME` / log relocation - the CLI has no cache or log files
  today.
- A backward-compatible read fallback to `~/.herds/`. Nothing consults the
  old directory once the files are moved.

## Decision

### What changes

1. **New module `herds_cli/paths.py`** becomes the single source of truth for
   every user-directory path. It is a pure stdlib leaf (no project imports),
   so it is unit-testable by monkeypatching environment variables and `HOME`:

   ```python
   def xdg_config_home() -> Path: ...   # $XDG_CONFIG_HOME or ~/.config
   def xdg_state_home() -> Path: ...     # $XDG_STATE_HOME  or ~/.local/state
   def config_dir() -> Path: ...         # <config_home>/herds
   def default_config_file() -> Path: ...# <config_home>/herds/config.json
   def state_dir() -> Path: ...          # <state_home>/herds   (session files)
   ```

   An unset **or empty** XDG variable falls back to the default, per the
   spec (an empty value is treated as unset). No `legacy_dir()` helper is
   needed: nothing in the code references `~/.herds/` after this change.

2. **`herds_cli/sessions.py`**: remove the `HERDS_DIR` constant; the
   `SessionManager` default `base_dir` becomes `paths.state_dir()`. The
   `base_dir` constructor param and the `HERDS_SESSION_DIR` / `session_dir`
   overrides are unchanged.

3. **`herds_cli/cli.py`**: resolve the config path using
   `paths.default_config_file()`. The cwd `./herds-cli-config.json` lookup is
   **removed**. New read precedence: `--config` flag -> `HERDS_CONFIG_FILE`
   env -> `paths.default_config_file()`.

4. **`herds_cli/commands/cmd_config.py`**: `save`, `set`, and `show` default
   their write / read target to `paths.default_config_file()` instead of
   `./herds-cli-config.json`, so `herds config set ...` persists to the
   standard XDG location. Update the affected `--config` help strings, the
   env-var help text, and the "defaults to ./herds-cli-config.json" hints.

### One-time manual migration

The single existing install is moved by hand, once, alongside the upgrade
(no code ships for this):

```bash
mkdir -p ~/.config/herds ~/.local/state/herds
mv ~/.herds/config.json ~/.config/herds/config.json   # if present
mv ~/.herds/herds_session_* ~/.local/state/herds/
rmdir ~/.herds 2>/dev/null || true
```

Respect `$XDG_CONFIG_HOME` / `$XDG_STATE_HOME` if either is set. This is
documented in the PR description, not in the shipped CLI.

### Files touched

| File                                                                               | Change                                                                                                       |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `herds_cli/paths.py`                                                               | New. XDG path resolution helpers                                                                             |
| `herds_cli/sessions.py`                                                            | Drop `HERDS_DIR`; default `base_dir` -> `paths.state_dir()`                                                  |
| `herds_cli/cli.py`                                                                 | Config path -> `paths.default_config_file()`; read `HERDS_CONFIG_FILE`; drop cwd lookup                      |
| `herds_cli/commands/cmd_config.py`                                                 | `save`/`set`/`show` resolve via `_resolve_config_file` (arg -> `HERDS_CONFIG_FILE` -> XDG); update help text |
| `herds_cli/types.py`                                                               | Update session-path comment                                                                                  |
| `tests/unit/test_paths.py`                                                         | New. Path resolution tests (env honored, empty/relative fallback, subdirs)                                   |
| `tests/cli/test_cli_config.py`                                                     | New. XDG default, `HERDS_CONFIG_FILE` precedence, cwd-ignored, no-brick                                      |
| `tests/cli/test_sessions.py`                                                       | Add `SessionManager()` -> `state_dir()` default test                                                         |
| `README.md`, `ARCHITECTURE.md`                                                     | Document XDG paths in place of `~/.herds/`                                                                   |
| `docs/references/google-auth.md`, `docs/references/url-extractions-cli-testing.md` | Update `~/.herds/` / cwd-config references                                                                   |
| `pyproject.toml` / `__init__.py` / `uv.lock`                                       | Minor version bump                                                                                           |

### What does NOT change

- **Override seams are untouched.** `--config`, `HERDS_CONFIG_FILE`,
  `HERDS_SESSION_DIR`, and the `session_dir` config field all behave as
  before and continue to win over the XDG defaults.
- **Config layering order is preserved**: dataclass defaults -> `HERDS_*`
  env vars -> JSON config file -> CLI flags. Only the file's _default
  location_ moves.
- **No `~/.herds/` read fallback.** The old directory is not consulted once
  the files are moved. This keeps path resolution simple and avoids a
  lingering split-brain state.
- **The `_initialized` test guard still gates all filesystem work**, so the
  test suite never touches a real home directory.

## Consequences

### Wins

- **Standards-compliant layout.** Config in `~/.config/herds/`, credentials
  in `~/.local/state/herds/`, honoring `$XDG_CONFIG_HOME` / `$XDG_STATE_HOME`
  as dotfile-managed environments expect.
- **Config and credentials no longer share a directory**, matching the XDG
  config-vs-state distinction.
- **`herds config set` becomes predictable.** It writes to the standard
  config file rather than dropping `./herds-cli-config.json` into the current
  directory.
- **No forced re-login.** The one existing install keeps its sessions and
  config via the manual move; nothing has to be re-authenticated.
- **Path logic is centralized and testable.** `paths.py` replaces
  string-literal paths scattered across `sessions.py` and `cli.py`.
- **No migration code to carry.** No startup logic and no migration test
  surface to maintain for a single user.

### Trade-offs

- **`herds config set` changes its default write location.** A user who
  relied on the cwd `./herds-cli-config.json` behavior (dropping decision #3)
  must now pass `--config ./herds-cli-config.json` explicitly. This is the
  intended cleanup, not an accident.
- **Upgrade requires a manual file move.** Acceptable because there is
  exactly one install. If the user base grows before this ships, revisit and
  add automated migration.
- **Cross-platform edge.** On Windows without XDG variables the CLI uses
  `~/.config` / `~/.local/state`, which is not the native Windows
  convention. Accepted as a non-goal.

### Cross-references

- Current layout: `herds_cli/sessions.py` (`HERDS_DIR`),
  `herds_cli/cli.py` (config path resolution),
  `herds_cli/commands/cmd_config.py` (`save` / `set` / `show` defaults).
- XDG Base Directory Specification:
  <https://specifications.freedesktop.org/basedir-spec/latest/>
