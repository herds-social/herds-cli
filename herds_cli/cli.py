#!/usr/bin/env python3
"""
Herds Unified CLI Tool

A command-line interface for interacting with the Herds API.
Supports user management and image operations with session-based authentication.
"""

import click
import sys
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo
from tzlocal import get_localzone
import pytz

from .api import APIClient
from .sessions import SessionManager, HERDS_DIR
from .images import ImageUploader
from .output import OutputFormatter
from .core.base import HerdsContext
from .core.config import Config
from .core.exceptions import HerdsError
from .commands import (
    user,
    image,
    events,
    event_user_data,
    config,
    user_settings,
    calendar,
)


class HerdsGroup(click.Group):
    """Custom Click group that catches HerdsError and exits gracefully.

    Domain exceptions from core/base.py helpers already print user-friendly
    error messages before raising. This handler ensures the process exits
    with code 1 instead of showing a traceback.
    """

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except HerdsError:
            # Contract: helpers in core/base.py print a user-friendly message
            # *before* raising HerdsError, so we only need to set the exit code
            # here — no additional output is necessary.
            sys.exit(1)


def detect_system_timezone() -> str:
    """
    Auto-detect system timezone with fallback to UTC.

    Returns:
        str: IANA timezone string (e.g., "America/New_York", "UTC")
    """
    try:
        local_tz = get_localzone()
        return str(local_tz)
    except Exception:
        return "UTC"


def validate_timezone(timezone: str) -> str:
    """
    Validate that the timezone is a valid IANA timezone string.

    Args:
        timezone: Timezone string to validate

    Returns:
        str: Validated timezone string

    Raises:
        click.BadParameter: If timezone is invalid
    """
    if not timezone:
        return "UTC"

    # Strip whitespace
    timezone = timezone.strip()
    if not timezone:
        return "UTC"

    try:
        # This will raise an exception if timezone is invalid
        ZoneInfo(timezone)
        return timezone
    except Exception:
        # zoneinfo uses the OS tz database and may lack entries that pytz
        # bundles. Fall back to pytz so users on minimal systems (e.g. Alpine
        # Docker images) still get broad timezone coverage.
        try:
            pytz.timezone(timezone)
            return timezone
        except Exception:
            # Provide helpful error message with common timezones
            common_timezones = [
                "UTC",
                "America/New_York",
                "America/Los_Angeles",
                "Europe/London",
                "Europe/Paris",
                "Asia/Tokyo",
            ]
            raise click.BadParameter(
                f"Invalid timezone: '{timezone}'. Must be a valid IANA timezone. "
                f"Common examples: {', '.join(common_timezones)}"
            )


@click.group(cls=HerdsGroup)
@click.option(
    "--config",
    help="Path to JSON configuration file (auto-detected if not specified)",
    type=click.Path(exists=True),
)
@click.option(
    "--base-url",
    help="API base URL (overrides config)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "table"]),
    help="Output format (overrides config)",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output (overrides config)")
@click.option(
    "--debug-requests",
    "-d",
    is_flag=True,
    help="Show detailed HTTP request/response information (overrides config)",
)
# When --timezone is omitted, detect_system_timezone() runs as the Click
# callback default, so config_obj.timezone is always a valid IANA string
# (e.g. "America/New_York") by the time any command executes.
@click.option(
    "--timezone",
    help="Timezone for datetime operations (auto-detected if not specified, overrides config)",
    callback=lambda ctx, param, value: (
        validate_timezone(value) if value else detect_system_timezone()
    ),
)
@click.option(
    "--account",
    "default_account",
    help="Default account email to use (overrides config)",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config: Optional[str],
    base_url: Optional[str],
    output_format: Optional[str],
    verbose: bool,
    debug_requests: bool,
    timezone: Optional[str],
    default_account: Optional[str],
) -> None:
    """Herds CLI Tool - Unified interface for user and image operations."""
    ctx.ensure_object(dict)

    # Test injection path: tests invoke cli via CliRunner(cli, obj={...})
    # with pre-built mocks for api_client, session_manager, etc. The
    # "_initialized" flag lets us skip config loading and component wiring
    # entirely, so tests control the full dependency graph.
    if ctx.obj.get("_initialized"):
        return

    # Load configuration
    try:
        # If no config file specified, try local then ~/.herds/
        if config:
            config_path = config
        elif Path("./herds-cli-config.json").exists():
            config_path = "./herds-cli-config.json"
        else:
            config_path = str(HERDS_DIR / "config.json")
        config_obj = Config.load(config_path)
    except FileNotFoundError:
        # If default config file doesn't exist, load with defaults and env vars
        if config:
            # If user explicitly specified a config file that doesn't exist, that's an error
            OutputFormatter.print_error(f"Configuration file not found: {config}")
            sys.exit(1)
        # Otherwise, use defaults (this is normal when no config file exists yet)
        config_obj = Config()
    except Exception as e:
        OutputFormatter.print_error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Apply CLI overrides
    if base_url is not None:
        config_obj.api_url = base_url
    if output_format is not None:
        config_obj.output_format = output_format
    if verbose:  # Only override if explicitly set to True
        config_obj.verbose = verbose
    if debug_requests:  # Only override if explicitly set to True
        config_obj.debug_requests = debug_requests
    if timezone is not None:
        config_obj.timezone = timezone
    if default_account is not None:
        config_obj.default_account = default_account

    # Validate configuration
    if not config_obj.validate():
        OutputFormatter.print_error("Configuration validation failed:")
        for error in config_obj.get_validation_errors():
            OutputFormatter.print_error(f"  - {error}")
        sys.exit(1)

    # Print current configuration summary
    if config_obj.verbose:
        OutputFormatter.display_configuration(config_obj)
        OutputFormatter.print_info("")

    # Initialize core components
    session_manager = SessionManager(base_dir=config_obj.session_dir)
    api_client = APIClient(
        base_url=config_obj.api_url,
        session_manager=session_manager,
        debug_requests=config_obj.debug_requests,
        timeout=config_obj.api_timeout,
        app_api_key=config_obj.app_api_key,
    )
    image_uploader = ImageUploader(api_client, session_manager)

    # Build typed context — see HerdsContext in core/base.py for schema
    herds_ctx: HerdsContext = {
        "config": config_obj,
        "session_manager": session_manager,
        "api_client": api_client,
        "image_uploader": image_uploader,
        "output_formatter": OutputFormatter(),
        "timezone": config_obj.timezone or "UTC",
        "format": config_obj.output_format,
        "base_url": config_obj.api_url,
    }
    ctx.obj.update(herds_ctx)


# Register command groups
cli.add_command(user)
cli.add_command(image)
cli.add_command(events)
cli.add_command(event_user_data)
cli.add_command(config)
cli.add_command(user_settings)
cli.add_command(calendar)

if __name__ == "__main__":
    cli()
