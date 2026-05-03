"""
Configuration management commands for the Herds CLI.

This module contains commands for viewing, validating, and managing
CLI configuration.
"""

import click
import sys
from pathlib import Path
from typing import NotRequired, Optional, TypedDict

from herds_cli.output import OutputFormatter
from herds_cli.core.config import Config

_LOCAL_API_URL = "http://localhost:8000"
_PROD_API_URL = "https://api.herds.events"


class ConfigKeyInfo(TypedDict):
    """Metadata for a single configurable key: its type, description, and optional choices."""

    type: str
    description: str
    current: str | int | bool | None
    choices: NotRequired[list[str]]
    secret: NotRequired[bool]


# Static config key metadata — 'current' is populated at runtime from Config.to_dict().
# Keep in sync with Config dataclass fields and _CONFIGURABLE_KEYS in core/config.py.
CONFIG_KEYS: dict[str, ConfigKeyInfo] = {
    "api_url": {
        "type": "url",
        "description": "API base URL (e.g., https://api.example.com)",
        "current": None,
    },
    "api_timeout": {
        "type": "int",
        "description": "API timeout in seconds (positive integer)",
        "current": None,
    },
    "output_format": {
        "type": "choice",
        "choices": ["json", "text", "auto"],
        "description": "Output format (json, text, or auto — auto picks text on a TTY, json when piped)",
        "current": None,
    },
    "verbose": {
        "type": "bool",
        "description": "Enable verbose output (true/false)",
        "current": None,
    },
    "debug_requests": {
        "type": "bool",
        "description": "Enable request debugging (true/false)",
        "current": None,
    },
    "timezone": {
        "type": "timezone",
        "description": "Timezone for operations (e.g., America/New_York, UTC)",
        "current": None,
    },
    "default_account": {
        "type": "email",
        "description": "Default account email to use when multiple sessions exist",
        "current": None,
    },
    "app_api_key": {
        "type": "string",
        "description": "Application API key (sent as X-API-Key on account creation)",
        "current": None,
        "secret": True,
    },
    "config_file": {
        "type": "path",
        "description": "Path to CLI configuration JSON file",
        "current": None,
    },
    "session_dir": {
        "type": "path",
        "description": "Directory path for storing session files",
        "current": None,
    },
}


def _display_value(
    value: str | int | bool | None,
    key_info: ConfigKeyInfo,
) -> str:
    """Format a config value for user-facing output, masking secrets."""
    if value is None:
        return "(not set)"
    if key_info.get("secret") and isinstance(value, str) and value:
        return value[:4] + "****" if len(value) > 4 else "****"
    return str(value)


def _resolve_api_url_shortcut(
    local: bool,
    prod: bool,
    key: Optional[str],
    value: Optional[str],
) -> str:
    """Validate --local/--prod flag combinations and return the resolved URL.

    Exits with an error message if the flags are used incorrectly (both set,
    wrong key, or a value also supplied).

    Returns:
        The resolved API URL string.
    """
    if local and prod:
        OutputFormatter.print_error(
            "Cannot use both --local and --prod flags simultaneously"
        )
        sys.exit(1)

    if not key:
        OutputFormatter.print_error(
            "Environment shortcuts (--local, --prod) require specifying 'api_url' as the key"
        )
        OutputFormatter.print_info("Usage: herds config set api_url --local")
        OutputFormatter.print_info("       herds config set api_url --prod")
        sys.exit(1)

    if key != "api_url":
        OutputFormatter.print_error(
            f"Environment shortcuts (--local, --prod) can only be used with 'api_url', not '{key}'"
        )
        sys.exit(1)

    if value:
        OutputFormatter.print_error(
            "Cannot provide both an environment shortcut flag and a direct value"
        )
        OutputFormatter.print_info(
            "Use either: herds config set api_url --local"
        )
        OutputFormatter.print_info(
            "        or: herds config set api_url https://custom.com"
        )
        sys.exit(1)

    return _LOCAL_API_URL if local else _PROD_API_URL


@click.group()
def config():
    """Configuration management commands"""
    pass


@config.command()
@click.option(
    "--config-file",
    help="Path to save configuration file (optional, defaults to ./herds-cli-config.json)",
    default="./herds-cli-config.json",
)
@click.pass_context
def show(ctx, config_file):
    """Show current configuration.

    Displays all current configuration settings and their sources.

    CONFIGURABLE VARIABLES:
        api_url          - API base URL (default: http://localhost:8000)
        api_timeout      - API timeout in seconds (default: 30)
        output_format    - Output format: json or table (default: json)
        verbose          - Enable verbose output: true/false (default: false)
        debug_requests   - Enable request debugging: true/false (default: false)
        timezone         - Timezone for operations (auto-detected if not set)
        default_account  - Default account email for multiple sessions
        session_dir      - Directory for storing session files

    ENVIRONMENT VARIABLES:
        HERDS_API_URL              - Set api_url
        HERDS_API_TIMEOUT          - Set api_timeout
        HERDS_OUTPUT_FORMAT        - Set output_format
        HERDS_VERBOSE              - Set verbose
        HERDS_DEBUG_REQUESTS       - Set debug_requests
        HERDS_TIMEZONE             - Set timezone
        HERDS_DEFAULT_ACCOUNT      - Set default_account
        HERDS_SESSION_DIR          - Set session_dir

    EXAMPLES:
        herds config show
        herds config show --config my-config.json
    """
    # Try to load from config file if it exists, otherwise use current config
    try:
        config_obj = Config.load(config_file)
    except FileNotFoundError:
        # If config file doesn't exist, use the current loaded config
        config_obj = ctx.obj.get("config")
        if not config_obj:
            OutputFormatter.print_error("Configuration not loaded")
            sys.exit(1)

    # Show config file source
    if config_obj._loaded_config_file:
        OutputFormatter.print_info(
            f"Configuration loaded from: {config_obj._loaded_config_file}"
        )
    else:
        OutputFormatter.print_info(
            "Configuration: Using defaults and environment variables"
        )

    # Show detailed configuration (skip if already shown during verbose startup)
    if not config_obj.verbose:
        OutputFormatter.print_info("")
        OutputFormatter.display_configuration(config_obj)

    # Validate configuration
    if config_obj.validate():
        OutputFormatter.print_success("Configuration is valid")
    else:
        OutputFormatter.print_warning("Configuration has validation errors:")
        for error in config_obj.get_validation_errors():
            OutputFormatter.print_warning(f"  - {error}")


@config.command()
@click.pass_context
def validate(ctx):
    """Validate current configuration."""
    config_obj = ctx.obj.get("config")
    if not config_obj:
        OutputFormatter.print_error("Configuration not loaded")
        sys.exit(1)

    if config_obj.validate():
        OutputFormatter.print_success("Configuration is valid")
        sys.exit(0)
    else:
        OutputFormatter.print_error("Configuration validation failed:")
        for error in config_obj.get_validation_errors():
            OutputFormatter.print_error(f"  - {error}")
        sys.exit(1)


@config.command()
@click.argument("config_file", type=click.Path())
@click.option(
    "--force", "-f", is_flag=True, help="Overwrite existing configuration file"
)
@click.pass_context
def save(ctx, config_file, force):
    """Save current configuration to a JSON file."""
    config_obj = ctx.obj.get("config")
    if not config_obj:
        OutputFormatter.print_error("Configuration not loaded")
        sys.exit(1)

    path = Path(config_file)
    if path.exists() and not force:
        OutputFormatter.print_error(f"Configuration file already exists: {config_file}")
        OutputFormatter.print_info("Use --force to overwrite")
        sys.exit(1)

    try:
        config_obj.save(config_file)
        OutputFormatter.print_success(f"Configuration saved to: {config_file}")
    except Exception as e:
        OutputFormatter.print_error(f"Failed to save configuration: {e}")
        sys.exit(1)


@config.command()
def reset():
    """Show default configuration values."""
    default_config = Config()

    OutputFormatter.print_info("Default Configuration:")
    OutputFormatter.print_info(f"  API URL: {default_config.api_url}")
    OutputFormatter.print_info(f"  API Timeout: {default_config.api_timeout}s")
    OutputFormatter.print_info(f"  Output Format: {default_config.output_format}")
    OutputFormatter.print_info(f"  Verbose: {default_config.verbose}")
    OutputFormatter.print_info(f"  Debug Requests: {default_config.debug_requests}")
    OutputFormatter.print_info(f"  Timezone: {default_config.timezone}")

    # Show environment variables that can be set
    OutputFormatter.print_info("\nEnvironment Variables:")
    OutputFormatter.print_info("  HERDS_API_URL - API base URL")
    OutputFormatter.print_info("  HERDS_API_TIMEOUT - API timeout in seconds")
    OutputFormatter.print_info("  HERDS_OUTPUT_FORMAT - Output format (json/table)")
    OutputFormatter.print_info("  HERDS_VERBOSE - Enable verbose output (true/1/yes)")
    OutputFormatter.print_info("  HERDS_DEBUG_REQUESTS - Enable request debugging")
    OutputFormatter.print_info("  HERDS_TIMEZONE - Timezone for operations")
    OutputFormatter.print_info("  HERDS_DEFAULT_ACCOUNT - Default account email to use")
    OutputFormatter.print_info("  HERDS_SESSION_DIR - Directory for session files")


@config.command()
@click.option(
    "--config-file",
    help="Path to save configuration file (optional, defaults to ./herds-cli-config.json)",
    default="./herds-cli-config.json",
)
@click.option(
    "--local",
    is_flag=True,
    help="Set api_url to local development (http://localhost:8000)",
)
@click.option(
    "--prod",
    is_flag=True,
    help="Set api_url to production (https://api.herds.events)",
)
@click.argument("key", required=False)
@click.argument("value", required=False)
@click.pass_context
def set(ctx, config_file, local, prod, key, value):
    """
    Set configuration values interactively or programmatically.

    USAGE MODES:
      config set KEY VALUE    - Set specific value programmatically
      config set KEY          - Interactive prompt for specific key
      config set              - Interactive wizard for all settings

    \b
    API URL SHORTCUTS:
    \b
      config set api_url --local    - Set to http://localhost:8000
      config set api_url --prod     - Set to https://api.herds.events

    \b
    CONFIGURABLE VARIABLES:
    \b
      api_url          - API base URL (default: http://localhost:8000)
      api_timeout      - API timeout in seconds (default: 30)
      output_format    - Output format: json or table (default: json)
      verbose          - Enable verbose output: true/false (default: false)
      debug_requests   - Enable request debugging: true/false (default: false)
      timezone         - Timezone for operations (auto-detected if not set)
      default_account  - Default account email for multiple sessions
      session_dir      - Directory for storing session files

    \b
    ENVIRONMENT VARIABLES:
    \b
      HERDS_API_URL              - Set api_url
      HERDS_API_TIMEOUT          - Set api_timeout
      HERDS_OUTPUT_FORMAT        - Set output_format
      HERDS_VERBOSE              - Set verbose
      HERDS_DEBUG_REQUESTS       - Set debug_requests
      HERDS_TIMEZONE             - Set timezone
      HERDS_DEFAULT_ACCOUNT      - Set default_account
      HERDS_SESSION_DIR          - Set session_dir

    \b
    EXAMPLES:
    \b
      # Set API URL using shortcuts
      herds config set api_url --local
      herds config set api_url --prod

      # Set specific value programmatically
      herds config set api_url https://api.example.com

      # Interactive mode for specific key
      herds config set api_url

      # Interactive wizard for all settings
      herds config set

      # Save to specific config file
      herds config set --config my-config.json api_url https://api.example.com
    """
    # Handle environment shortcuts (--local and --prod)
    if local or prod:
        value = _resolve_api_url_shortcut(local, prod, key, value)

    # Load existing configuration from file if it exists, otherwise use current config
    try:
        config_obj = Config.load(config_file)
    except FileNotFoundError:
        # If config file doesn't exist, use the current loaded config
        config_obj = ctx.obj.get("config")
        if not config_obj:
            # Create a new config with defaults
            config_obj = Config()

    # Build config keys with current values from runtime config
    current_config = config_obj.to_dict()
    config_keys: dict[str, ConfigKeyInfo] = {
        k: {**info, "current": current_config.get(k)}
        for k, info in CONFIG_KEYS.items()
    }

    # Handle different command modes
    if key and value:
        # Programmatic mode: herds config set key value
        _set_single_value(config_obj, config_keys, key, value, config_file)
    elif key:
        # Interactive mode for specific key: herds config set key
        _set_single_value_interactive(config_obj, config_keys, key, config_file)
    else:
        # Interactive wizard mode: herds config set
        _set_interactive_wizard(config_obj, config_keys, config_file)


def _set_single_value(
    config_obj: Config,
    config_keys: dict[str, ConfigKeyInfo],
    key: str,
    value: str,
    config_file: str,
) -> None:
    """Set a single configuration value programmatically."""
    if key not in config_keys:
        OutputFormatter.print_error(f"Unknown configuration key: {key}")
        OutputFormatter.print_info(f"Available keys: {', '.join(config_keys.keys())}")
        sys.exit(1)

    key_info = config_keys[key]

    # Validate and convert the value
    try:
        validated_value = _validate_and_convert_value(key, value, key_info)
    except ValueError as e:
        OutputFormatter.print_error(f"Invalid value for {key}: {e}")
        sys.exit(1)

    # Set the value
    setattr(config_obj, key, validated_value)

    # Validate the full configuration
    if not config_obj.validate():
        OutputFormatter.print_error("Configuration validation failed:")
        for error in config_obj.get_validation_errors():
            OutputFormatter.print_error(f"  - {error}")
        sys.exit(1)

    # Save the configuration
    try:
        config_obj.save(config_file)
        OutputFormatter.print_success(
            f"Set {key} = {_display_value(validated_value, key_info)}"
        )
        OutputFormatter.print_info(f"Configuration saved to: {config_file}")
    except Exception as e:
        OutputFormatter.print_error(f"Failed to save configuration: {e}")
        sys.exit(1)


def _set_single_value_interactive(
    config_obj: Config,
    config_keys: dict[str, ConfigKeyInfo],
    key: str,
    config_file: str,
) -> None:
    """Set a single configuration value interactively."""
    if key not in config_keys:
        OutputFormatter.print_error(f"Unknown configuration key: {key}")
        OutputFormatter.print_info(f"Available keys: {', '.join(config_keys.keys())}")
        sys.exit(1)

    key_info = config_keys[key]
    current_value = key_info["current"]

    # Show current value and prompt for new value
    OutputFormatter.print_info(f"Setting: {key}")
    OutputFormatter.print_info(f"Description: {key_info['description']}")
    OutputFormatter.print_info(f"Current value: {_display_value(current_value, key_info)}")

    # Get user input (don't echo default for secrets; mask typed input)
    is_secret = bool(key_info.get("secret"))
    prompt_default = None if is_secret else current_value
    value = click.prompt(
        f"Enter new value for {key}",
        default=prompt_default,
        hide_input=is_secret,
    )

    # Validate and set
    try:
        validated_value = _validate_and_convert_value(key, value, key_info)
    except ValueError as e:
        OutputFormatter.print_error(f"Invalid value: {e}")
        sys.exit(1)

    # Set the value
    setattr(config_obj, key, validated_value)

    # Validate the full configuration
    if not config_obj.validate():
        OutputFormatter.print_error("Configuration validation failed:")
        for error in config_obj.get_validation_errors():
            OutputFormatter.print_error(f"  - {error}")
        sys.exit(1)

    # Save the configuration
    try:
        config_obj.save(config_file)
        OutputFormatter.print_success(
            f"Set {key} = {_display_value(validated_value, key_info)}"
        )
        OutputFormatter.print_info(f"Configuration saved to: {config_file}")
    except Exception as e:
        OutputFormatter.print_error(f"Failed to save configuration: {e}")
        sys.exit(1)


def _set_interactive_wizard(
    config_obj: Config,
    config_keys: dict[str, ConfigKeyInfo],
    config_file: str,
) -> None:
    """Run interactive wizard to set multiple configuration values."""
    OutputFormatter.print_info("Interactive Configuration Wizard")
    OutputFormatter.print_info("=================================")
    OutputFormatter.print_info(
        "Configure your Herds CLI settings. Press Enter to keep current values."
    )
    OutputFormatter.print_info("")

    changes_made = False

    for key, key_info in config_keys.items():
        current_value = key_info["current"]

        # Show current value and prompt for new value
        OutputFormatter.print_info(f"Setting: {key}")
        OutputFormatter.print_info(f"Description: {key_info['description']}")
        OutputFormatter.print_info(f"Current value: {_display_value(current_value, key_info)}")

        # Get user input (allow empty to skip; mask typed input for secrets)
        value = click.prompt(
            f"Enter new value for {key} (or press Enter to skip)",
            default="",
            show_default=False,
            hide_input=bool(key_info.get("secret")),
        )

        if value.strip():  # Only process non-empty values
            try:
                validated_value = _validate_and_convert_value(key, value, key_info)
                setattr(config_obj, key, validated_value)
                changes_made = True
                OutputFormatter.print_success(
                    f"Set {key} = {_display_value(validated_value, key_info)}"
                )
            except ValueError as e:
                OutputFormatter.print_warning(f"Skipped {key}: {e}")
        else:
            OutputFormatter.print_info(f"Skipped {key} (keeping current value)")

        OutputFormatter.print_info("")

    if not changes_made:
        OutputFormatter.print_info("No changes made.")
        return

    # Validate the full configuration
    if not config_obj.validate():
        OutputFormatter.print_error("Configuration validation failed:")
        for error in config_obj.get_validation_errors():
            OutputFormatter.print_error(f"  - {error}")
        sys.exit(1)

    # Save the configuration
    try:
        config_obj.save(config_file)
        OutputFormatter.print_success("Configuration updated successfully!")
        OutputFormatter.print_info(f"Saved to: {config_file}")
    except Exception as e:
        OutputFormatter.print_error(f"Failed to save configuration: {e}")
        sys.exit(1)


def _validate_and_convert_value(
    key: str,
    value: str | int | bool | None,
    key_info: ConfigKeyInfo,
) -> str | int | bool | None:
    """Validate and convert a configuration value based on its type."""
    value_type = key_info["type"]

    # Handle None/empty values
    if value is None or str(value).strip() == "":
        return None

    value_str = str(value).strip()

    if value_type == "url":
        # Basic URL validation
        if not (value_str.startswith("http://") or value_str.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        # Additional URL validation could be added here
        return value_str

    elif value_type == "int":
        try:
            int_value = int(value_str)
        except ValueError:
            raise ValueError("Must be a valid integer")
        if int_value <= 0:
            raise ValueError("Must be a positive integer")
        return int_value

    elif value_type == "bool":
        lower_value = value_str.lower()
        if lower_value in ("true", "1", "yes", "on", "enable"):
            return True
        elif lower_value in ("false", "0", "no", "off", "disable"):
            return False
        else:
            raise ValueError(
                "Must be true/false, yes/no, 1/0, on/off, or enable/disable"
            )

    elif value_type == "choice":
        choices = key_info.get("choices", [])
        if value_str not in choices:
            raise ValueError(f"Must be one of: {', '.join(choices)}")
        return value_str

    elif value_type == "email":
        # Basic email validation
        import re

        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, value_str):
            raise ValueError("Must be a valid email address")
        return value_str

    elif value_type == "timezone":
        # Basic timezone validation (could be enhanced)
        # For now, just accept common formats
        if "/" not in value_str and value_str != "UTC":
            raise ValueError(
                "Timezone should be in format like 'America/New_York' or 'UTC'"
            )
        return value_str

    elif value_type == "path":
        # Path validation (Path is imported at module level)
        path = Path(value_str)
        # Don't create directories automatically, just validate the path format
        return str(path)

    else:
        # Default to string
        return value_str
