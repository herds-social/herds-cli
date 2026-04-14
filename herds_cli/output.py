"""
Herds CLI Output Formatting Module

Handles different output formats for CLI responses using Rich.
"""

import json
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from .core.config import Config

# Initialize rich console for beautiful output
console = Console()


class OutputFormatter:
    """Handles different output formats for API responses."""

    @staticmethod
    def format_output(data: Any, format_type: str = "json") -> str:
        """Format data according to the specified format."""
        if format_type == "json":
            return json.dumps(data, indent=2)
        elif format_type == "table":
            return OutputFormatter.format_table(data)
        else:
            return str(data)

    @staticmethod
    def format_table(data: Any) -> str:
        """Format data as a rich table."""
        if isinstance(data, dict):
            table = Table(title="API Response")
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="green")

            for key, value in data.items():
                if isinstance(value, dict):
                    value = json.dumps(value, indent=2)
                table.add_row(str(key), str(value))

            console.print(table)
            return ""  # Table is already printed
        else:
            return json.dumps(data, indent=2)

    @staticmethod
    def print_success(message: str):
        """Print a success message."""
        console.print(f"[green]✅ {message}[/green]")

    @staticmethod
    def print_error(message: str):
        """Print an error message."""
        console.print(f"[red]❌ {message}[/red]")

    @staticmethod
    def print_warning(message: str):
        """Print a warning message."""
        console.print(f"[yellow]⚠️  {message}[/yellow]")

    @staticmethod
    def print_info(message: str):
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
