"""
Configuration management commands for the Herds CLI.

This module contains commands for viewing, validating, and managing
CLI configuration.
"""

import click
import sys
from pathlib import Path

from herds_cli.output import OutputFormatter
from herds_cli.core.config import Config


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
        herds_cli config show
        herds_cli config show --config my-config.json
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
    help="Set api_url to production (https://herds.onrender.com)",
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
      config set api_url --prod     - Set to https://herds.onrender.com

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
      herds_cli config set api_url --local
      herds_cli config set api_url --prod

      # Set specific value programmatically
      herds_cli config set api_url https://api.example.com

      # Interactive mode for specific key
      herds_cli config set api_url

      # Interactive wizard for all settings
      herds_cli config set

      # Save to specific config file
      herds_cli config set --config my-config.json api_url https://api.example.com
    """
    # Handle environment shortcuts (--local and --prod)
    if local or prod:
        # Validate usage of environment shortcuts
        if local and prod:
            OutputFormatter.print_error(
                "Cannot use both --local and --prod flags simultaneously"
            )
            sys.exit(1)

        if not key:
            OutputFormatter.print_error(
                "Environment shortcuts (--local, --prod) require specifying 'api_url' as the key"
            )
            OutputFormatter.print_info("Usage: herds_cli config set api_url --local")
            OutputFormatter.print_info("       herds_cli config set api_url --prod")
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
                "Use either: herds_cli config set api_url --local"
            )
            OutputFormatter.print_info(
                "        or: herds_cli config set api_url https://custom.com"
            )
            sys.exit(1)

        # Set the appropriate URL based on the flag
        if local:
            value = "http://localhost:8000"
        elif prod:
            value = "https://herds.onrender.com"

    # Load existing configuration from file if it exists, otherwise use current config
    try:
        config_obj = Config.load(config_file)
    except FileNotFoundError:
        # If config file doesn't exist, use the current loaded config
        config_obj = ctx.obj.get("config")
        if not config_obj:
            # Create a new config with defaults
            config_obj = Config()

    # Get the current config values for reference
    current_config = config_obj.to_dict()

    # Define available config keys with their types and descriptions
    config_keys = {
        "api_url": {
            "type": "url",
            "description": "API base URL (e.g., https://api.example.com)",
            "current": current_config.get("api_url", "http://localhost:8000"),
        },
        "api_timeout": {
            "type": "int",
            "description": "API timeout in seconds (positive integer)",
            "current": current_config.get("api_timeout", 30),
        },
        "output_format": {
            "type": "choice",
            "choices": ["json", "table"],
            "description": "Output format (json or table)",
            "current": current_config.get("output_format", "json"),
        },
        "verbose": {
            "type": "bool",
            "description": "Enable verbose output (true/false)",
            "current": current_config.get("verbose", False),
        },
        "debug_requests": {
            "type": "bool",
            "description": "Enable request debugging (true/false)",
            "current": current_config.get("debug_requests", False),
        },
        "timezone": {
            "type": "timezone",
            "description": "Timezone for operations (e.g., America/New_York, UTC)",
            "current": current_config.get("timezone", None),
        },
        "default_account": {
            "type": "email",
            "description": "Default account email to use when multiple sessions exist",
            "current": current_config.get("default_account", None),
        },
        "session_dir": {
            "type": "path",
            "description": "Directory path for storing session files",
            "current": current_config.get("session_dir", None),
        },
    }

    # Handle different command modes
    if key and value:
        # Programmatic mode: herds_cli config set key value
        _set_single_value(config_obj, config_keys, key, value, config_file)
    elif key:
        # Interactive mode for specific key: herds_cli config set key
        _set_single_value_interactive(config_obj, config_keys, key, config_file)
    else:
        # Interactive wizard mode: herds_cli config set
        _set_interactive_wizard(config_obj, config_keys, config_file)


def _set_single_value(config_obj, config_keys, key, value, config_file):
    """Set a single configuration value programmatically.

    Args:
        config_obj: Configuration object to update
        config_keys: Dictionary of available configuration keys
        key: Configuration key to set
        value: Value to set
        config_file: Path to configuration file
    """
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
        OutputFormatter.print_success(f"Set {key} = {validated_value}")
        OutputFormatter.print_info(f"Configuration saved to: {config_file}")
    except Exception as e:
        OutputFormatter.print_error(f"Failed to save configuration: {e}")
        sys.exit(1)


def _set_single_value_interactive(config_obj, config_keys, key, config_file):
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
    if current_value is not None:
        OutputFormatter.print_info(f"Current value: {current_value}")
    else:
        OutputFormatter.print_info("Current value: (not set)")

    # Get user input
    value = click.prompt(f"Enter new value for {key}", default=current_value)

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
        OutputFormatter.print_success(f"Set {key} = {validated_value}")
        OutputFormatter.print_info(f"Configuration saved to: {config_file}")
    except Exception as e:
        OutputFormatter.print_error(f"Failed to save configuration: {e}")
        sys.exit(1)


def _set_interactive_wizard(config_obj, config_keys, config_file):
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
        if current_value is not None:
            OutputFormatter.print_info(f"Current value: {current_value}")
        else:
            OutputFormatter.print_info("Current value: (not set)")

        # Get user input (allow empty to skip)
        value = click.prompt(
            f"Enter new value for {key} (or press Enter to skip)",
            default="",
            show_default=False,
        )

        if value.strip():  # Only process non-empty values
            try:
                validated_value = _validate_and_convert_value(key, value, key_info)
                setattr(config_obj, key, validated_value)
                changes_made = True
                OutputFormatter.print_success(f"Set {key} = {validated_value}")
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


def _validate_and_convert_value(key, value, key_info):
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
            if int_value <= 0:
                raise ValueError("Must be a positive integer")
            return int_value
        except ValueError:
            raise ValueError("Must be a valid integer")

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
        # Path validation
        from pathlib import Path

        path = Path(value_str)
        # Don't create directories automatically, just validate the path format
        return str(path)

    else:
        # Default to string
        return value_str
