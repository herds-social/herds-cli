"""
Configuration management for the Herds CLI.

This module provides configuration loading from files, environment variables,
and command-line options.
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict, field
from urllib.parse import urlparse


# Fields that may be set from a JSON config file. This allowlist prevents
# config files from overwriting internal state (_validation_errors, etc.)
# or injecting unexpected attributes via hasattr-based dynamic dispatch.
_CONFIGURABLE_KEYS: frozenset[str] = frozenset({
    "api_url",
    "api_timeout",
    "output_format",
    "verbose",
    "debug_requests",
    "timezone",
    "default_account",
    "app_api_key",
    "config_file",
    "session_dir",
})


@dataclass
class Config:
    """Layered configuration for the Herds CLI.

    Loading precedence (last wins):
        dataclass defaults → HERDS_* env vars → JSON config file → CLI flags

    The first three layers are applied by Config.load(). CLI flag overrides
    are applied separately in cli.py after load() returns.

    Internal fields (_validation_errors, _loaded_config_file) are excluded
    from serialization by save() but ARE included by to_dict()/asdict().

    Adding a new configurable field requires updates in three locations:
        1. Add a field to this dataclass.
        2. Add the field name to _CONFIGURABLE_KEYS (above).
        3. Add a corresponding entry to CONFIG_KEYS in commands/cmd_config.py.
    """

    # API settings
    api_url: str = "http://localhost:8000"
    api_timeout: int = 30

    # Output settings
    output_format: str = "json"
    verbose: bool = False
    debug_requests: bool = False

    # Session settings
    timezone: Optional[str] = None
    default_account: Optional[str] = None  # Default account email to use

    # App API key (sent as X-API-Key header on account creation)
    app_api_key: Optional[str] = None

    # File paths
    config_file: Optional[str] = None
    session_dir: Optional[str] = None

    # Internal fields (not serialized)
    _validation_errors: list[str] = field(default_factory=list, init=False)
    _loaded_config_file: Optional[str] = field(default=None, init=False)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from file and environment variables.

        Args:
            config_path: Path to configuration file (optional)

        Returns:
            Config instance with loaded values
        """
        config = cls()

        # Load from environment variables
        config._load_from_env()

        # Load from config file if specified
        if config_path:
            config._load_from_file(config_path)
            config._loaded_config_file = config_path

        return config

    def _load_from_env(self) -> None:
        """Load configuration from environment variables."""
        # API settings
        if "HERDS_API_URL" in os.environ:
            self.api_url = os.environ["HERDS_API_URL"]
        if "HERDS_API_TIMEOUT" in os.environ:
            try:
                self.api_timeout = int(os.environ["HERDS_API_TIMEOUT"])
            except ValueError:
                pass  # Keep default

        # Output settings
        if "HERDS_OUTPUT_FORMAT" in os.environ:
            self.output_format = os.environ["HERDS_OUTPUT_FORMAT"]
        if "HERDS_VERBOSE" in os.environ:
            self.verbose = os.environ["HERDS_VERBOSE"].lower() in ("true", "1", "yes")
        if "HERDS_DEBUG_REQUESTS" in os.environ:
            self.debug_requests = os.environ["HERDS_DEBUG_REQUESTS"].lower() in (
                "true",
                "1",
                "yes",
            )

        # Session settings
        if "HERDS_TIMEZONE" in os.environ:
            self.timezone = os.environ["HERDS_TIMEZONE"]
        if "HERDS_DEFAULT_ACCOUNT" in os.environ:
            self.default_account = os.environ["HERDS_DEFAULT_ACCOUNT"]

        # App API key
        if "HERDS_APP_API_KEY" in os.environ:
            self.app_api_key = os.environ["HERDS_APP_API_KEY"]

        # File paths
        if "HERDS_CONFIG_FILE" in os.environ:
            self.config_file = os.environ["HERDS_CONFIG_FILE"]
        if "HERDS_SESSION_DIR" in os.environ:
            self.session_dir = os.environ["HERDS_SESSION_DIR"]

    def _load_from_file(self, config_path: str) -> None:
        """Load configuration from a JSON file.

        Args:
            config_path: Path to the JSON configuration file
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        if path.suffix.lower() != ".json":
            raise ValueError(
                f"Configuration file must be JSON format, got: {path.suffix}"
            )

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for key, value in data.items():
            if key in _CONFIGURABLE_KEYS:
                setattr(self, key, value)

    def save(self, config_path: str) -> None:
        """Save configuration to a JSON file.

        Args:
            config_path: Path to save the configuration
        """
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Get serializable data (exclude internal fields)
        data = self.to_dict()
        data.pop("_validation_errors", None)
        data.pop("_loaded_config_file", None)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def validate(self) -> bool:
        """Validate configuration values.

        Returns:
            True if valid, False if invalid (check validation_errors for details)
        """
        self._validation_errors = []

        # Validate API URL
        if not self._is_valid_url(self.api_url):
            self._validation_errors.append(f"Invalid API URL: {self.api_url}")

        # Validate API timeout
        if not isinstance(self.api_timeout, int) or self.api_timeout <= 0:
            self._validation_errors.append(
                f"API timeout must be a positive integer, got: {self.api_timeout}"
            )

        # Validate output format
        if self.output_format not in ["json", "table"]:
            self._validation_errors.append(
                f"Output format must be 'json' or 'table', got: {self.output_format}"
            )

        # Validate timezone if provided
        if self.timezone and not self._is_valid_timezone(self.timezone):
            self._validation_errors.append(f"Invalid timezone: {self.timezone}")

        # Validate default account if provided (basic email format check)
        if self.default_account and not self._is_valid_email(self.default_account):
            self._validation_errors.append(
                f"Invalid default account email: {self.default_account}"
            )

        # Validate session directory if provided
        if self.session_dir and not Path(self.session_dir).is_dir():
            try:
                Path(self.session_dir).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self._validation_errors.append(
                    f"Invalid session directory: {self.session_dir} ({e})"
                )

        return len(self._validation_errors) == 0

    def get_validation_errors(self) -> list[str]:
        """Get list of validation errors."""
        return self._validation_errors.copy()

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to a dictionary."""
        return asdict(self)

    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is valid."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False

    def _is_valid_timezone(self, timezone: str) -> bool:
        """Check if timezone is valid."""
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(timezone)
            return True
        except:
            try:
                import pytz

                pytz.timezone(timezone)
                return True
            except:
                return False

    def _is_valid_email(self, email: str) -> bool:
        """Check if email format is valid (basic validation)."""
        import re

        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.match(email_pattern, email))

    def __repr__(self) -> str:
        """String representation of the configuration."""
        return f"Config(api_url='{self.api_url}', output_format='{self.output_format}', verbose={self.verbose})"
