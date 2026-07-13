"""
XDG Base Directory path resolution for Herds CLI.

Single source of truth for where the CLI reads and writes user files,
following the XDG Base Directory Specification: configuration under
$XDG_CONFIG_HOME/herds and session/credential state under
$XDG_STATE_HOME/herds. Nothing else in the codebase should hard-code a
home-directory path.
"""

import os
from pathlib import Path

# Application subdirectory created under each XDG base directory.
_APP_DIR = "herds"


def _xdg_base(env_var: str, default_relative: str) -> Path:
    """Resolve an XDG base directory from its environment variable.

    Per the XDG spec, the variable's value is used only when it is a
    non-empty absolute path. An unset value, an empty string, or a relative
    path all fall back to ``$HOME/<default_relative>``.
    """
    value = os.environ.get(env_var, "")
    if value:
        path = Path(value)
        if path.is_absolute():
            return path
    return Path.home() / default_relative


def xdg_config_home() -> Path:
    """User config base directory: ``$XDG_CONFIG_HOME`` or ``~/.config``."""
    return _xdg_base("XDG_CONFIG_HOME", ".config")


def xdg_state_home() -> Path:
    """User state base directory: ``$XDG_STATE_HOME`` or ``~/.local/state``."""
    return _xdg_base("XDG_STATE_HOME", ".local/state")


def config_dir() -> Path:
    """Herds config directory: ``<config-home>/herds``."""
    return xdg_config_home() / _APP_DIR


def default_config_file() -> Path:
    """Default config file: ``<config-home>/herds/config.json``."""
    return config_dir() / "config.json"


def state_dir() -> Path:
    """Herds state directory holding session files: ``<state-home>/herds``."""
    return xdg_state_home() / _APP_DIR
