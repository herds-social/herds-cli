"""
Herds CLI Output Formatting Module

Handles different output formats for CLI responses using Rich.

OutputFormatter is a stateless namespace of static methods:
- print_success/error/warning/info output status messages via Rich Console
  (stderr — keeps stdout clean for JSON and other data output).
- format_output serializes data to a string (JSON only; text mode emits
  nothing on stdout, since the print_* helpers above already render the
  human-readable summary on stderr).

For command output that respects the --format flag, prefer
APIResponseHandler.format_and_output (core/base.py) instead of calling
these methods directly.
"""

import json
from typing import TYPE_CHECKING, Any

from rich.console import Console

if TYPE_CHECKING:
    from .core.config import Config

# Diagnostic/status output goes to stderr so stdout stays clean for JSON
# (or other future structured formats). Pipes like `herds X | jq` get only
# the JSON; the user still sees status messages on their terminal.
console = Console(stderr=True)


class OutputFormatter:
    """Handles different output formats for API responses."""

    @staticmethod
    def format_output(data: dict[str, Any] | list[Any], format_type: str = "json") -> str:
        """Format data for the data channel (stdout).

        Returns a JSON string for ``"json"``; returns ``""`` for ``"text"``
        because human-readable output is emitted via the print_* helpers
        on stderr — the data channel stays empty so redirects (`> file.txt`)
        and pipes don't capture status noise.
        """
        if format_type == "json":
            return json.dumps(data, indent=2)
        return ""

    @staticmethod
    def print_success(message: str) -> None:
        """Print a success message."""
        console.print(f"[green]✅ {message}[/green]")

    @staticmethod
    def print_error(message: str) -> None:
        """Print an error message."""
        console.print(f"[red]❌ {message}[/red]")

    @staticmethod
    def print_warning(message: str) -> None:
        """Print a warning message."""
        console.print(f"[yellow]⚠️  {message}[/yellow]")

    @staticmethod
    def print_info(message: str) -> None:
        """Print an info message."""
        console.print(f"[bright_blue]ℹ️  {message}[/bright_blue]")

    @staticmethod
    def display_configuration(config_obj: "Config") -> None:
        """Display the current configuration settings."""
        OutputFormatter.print_info("Current Configuration:")
        OutputFormatter.print_info(f"  API URL: {config_obj.api_url}")
        OutputFormatter.print_info(f"  API Timeout: {config_obj.api_timeout}s")
        OutputFormatter.print_info(f"  Output Format: {config_obj.output_format}")
        OutputFormatter.print_info(f"  Verbose: {config_obj.verbose}")
        OutputFormatter.print_info(f"  Debug Requests: {config_obj.debug_requests}")
        OutputFormatter.print_info(f"  Timezone: {config_obj.timezone}")

        # Account information
        if config_obj.default_account:
            OutputFormatter.print_info(
                f"  Default Account: {config_obj.default_account}"
            )
        else:
            OutputFormatter.print_info("  Default Account: not set")

        if config_obj.session_dir:
            OutputFormatter.print_info(f"  Session Directory: {config_obj.session_dir}")
