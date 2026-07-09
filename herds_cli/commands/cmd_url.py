"""
URL submission commands for the Herds CLI.

Submit URLs for server-side event extraction; optional --poll waits through
processing and renders extracted events via the shared extractions helpers.
"""

import click

from herds_cli.core.base import get_or_detect_session_email
from herds_cli.core.exceptions import HerdsError
from herds_cli.output import OutputFormatter
from herds_cli.commands.cmd_extractions import (
    display_extraction_events,
    poll_extraction_to_completion,
)


@click.group()
def url():
    """URL submission commands."""
    pass


@url.command("submit")
@click.argument("target_url")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--mock", is_flag=True, help="Enable mock AI processing for faster testing"
)
@click.option(
    "--add-to-calendar/--no-add-to-calendar",
    "add_to_calendar",
    default=None,
    help=(
        "Tri-state override for server-side calendar auto-add: "
        "--add-to-calendar forces an add, --no-add-to-calendar forces a skip, "
        "and omitting both defers to your auto_add_to_calendar_enabled user setting."
    ),
)
@click.option(
    "--poll",
    is_flag=True,
    help="Wait for processing to complete and display the extracted event(s)",
)
@click.pass_context
def submit(ctx, target_url, email, mock, add_to_calendar, poll):
    """Submit a URL for event extraction."""
    session_manager = ctx.obj["session_manager"]
    api_client = ctx.obj["api_client"]
    output_format = ctx.obj["format"]
    timezone = ctx.obj["timezone"]
    config = ctx.obj["config"]

    format_explicit = ctx.obj.get("_format_explicit", False)
    if poll and output_format == "json" and format_explicit:
        raise click.UsageError(
            "--poll cannot be combined with --format json (not yet supported)"
        )

    email = get_or_detect_session_email(
        session_manager, email, show_client_type=True, config=config
    )

    if not api_client.load_session_auth(email):
        OutputFormatter.print_error(
            f"No valid session found for {email}. Please login first."
        )
        raise HerdsError(f"no session for {email}")

    try:
        result = api_client.submit_url(
            email,
            target_url,
            timezone,
            mock_mode=mock,
            add_to_calendar=add_to_calendar,
        )
    except Exception as exc:
        OutputFormatter.print_error(f"URL submission failed: {exc}")
        raise HerdsError("url submission failed") from exc

    event_source_id = result.get("event_source_id")
    message = result.get("message", "")

    if message == "URL already submitted":
        OutputFormatter.print_warning(
            f"URL was recently submitted; reusing extraction {event_source_id}"
        )
    else:
        OutputFormatter.print_success("URL submitted for processing")
        if event_source_id:
            OutputFormatter.print_info(f"Event source ID: {event_source_id}")

    if poll:
        if not event_source_id:
            OutputFormatter.print_error(
                "Submit response missing event_source_id; cannot poll for status"
            )
            raise HerdsError("submit response missing event_source_id")
        poll_extraction_to_completion(api_client, email, event_source_id)
        display_extraction_events(ctx, email, event_source_id)
        return

    if output_format == "json":
        output = OutputFormatter.format_output(result, output_format)
        if output:
            click.echo(output)
