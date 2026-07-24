"""
Generic extraction-status commands for the Herds CLI.

Read-side facade over /api/extractions (URL and image jobs). Shared poll/display
helpers are exported for herds url submit --poll.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast
from zoneinfo import ZoneInfo

import click
from rich.markup import escape
from rich.status import Status

from herds_cli.api import APIClient
from herds_cli.calendar_status_display import ReconnectProviderResolver
from herds_cli.core.base import APIResponseHandler, CommandBase, EventCommandBase
from herds_cli.core.exceptions import HerdsError
from herds_cli.output import OutputFormatter, console
from herds_cli.types import EventV2, ExtractionResponse

POLL_INTERVAL_SECS = 2.0
POLL_TIMEOUT_SECS = 180.0

_TERMINAL_STATUSES = frozenset({"completed", "failed"})


@click.group()
def extractions():
    """Extraction history and status commands."""
    pass


def _source_label(extraction: ExtractionResponse) -> str:
    if extraction.get("source_type") == "url":
        url_detail = extraction.get("url") or {}
        return url_detail.get("submitted_url", "unknown")
    image_detail = extraction.get("image") or {}
    return image_detail.get("image_name", "unnamed")


def _event_count_display(extraction: ExtractionResponse) -> str:
    status = extraction.get("extraction_status", "")
    if status not in _TERMINAL_STATUSES:
        return "-"
    count = extraction.get("event_count", 0)
    return f"{count} events"


def _is_unacknowledged_terminal(extraction: ExtractionResponse) -> bool:
    status = extraction.get("extraction_status", "")
    if status not in _TERMINAL_STATUSES:
        return False
    return extraction.get("acknowledged_at") is None


def _format_list_row(index: int, extraction: ExtractionResponse) -> str:
    extraction_id = extraction.get("extraction_id", "unknown")
    source_type = extraction.get("source_type", "unknown")
    status = extraction.get("extraction_status", "unknown")
    source_label = _source_label(extraction)
    created_at = extraction.get("created_at", "unknown")
    row = (
        f"  {index}. [{extraction_id}] {source_type:<5} {status:<10} "
        f"{_event_count_display(extraction):<8} {source_label:<28} {created_at}"
    )
    if status == "failed":
        error_type = extraction.get("extraction_error_type")
        if error_type:
            row += f" ({error_type})"
    if _is_unacknowledged_terminal(extraction):
        row += " [unread]"
    return row


def _display_extraction_summary(extraction: ExtractionResponse) -> None:
    """Print a human-readable extraction status summary."""
    extraction_id = extraction.get("extraction_id", "unknown")
    OutputFormatter.print_info(f"Extraction ID: {extraction_id}")
    OutputFormatter.print_info(f"Source type: {extraction.get('source_type', 'unknown')}")
    OutputFormatter.print_info(
        f"Status: {extraction.get('extraction_status', 'unknown')}"
    )

    error_type = extraction.get("extraction_error_type")
    if error_type:
        OutputFormatter.print_info(f"Error type: {error_type}")

    OutputFormatter.print_info(f"Event count: {extraction.get('event_count', 0)}")

    if extraction.get("source_type") == "url":
        url_detail = extraction.get("url") or {}
        OutputFormatter.print_info(f"URL: {url_detail.get('submitted_url', 'unknown')}")
        OutputFormatter.print_info(
            f"Links: {url_detail.get('fetched_link_count', 0)}/"
            f"{url_detail.get('candidate_link_count', 0)} fetched"
        )
    elif extraction.get("source_type") == "image":
        image_detail = extraction.get("image") or {}
        OutputFormatter.print_info(f"Image: {image_detail.get('image_name', 'unknown')}")
        OutputFormatter.print_info(
            f"Media type: {image_detail.get('image_media_type', 'unknown')}"
        )

    ack_at = extraction.get("acknowledged_at")
    if ack_at:
        OutputFormatter.print_info(f"Acknowledged: {ack_at}")
    else:
        OutputFormatter.print_info("Acknowledged: no")

    OutputFormatter.print_info(f"Created: {extraction.get('created_at', 'unknown')}")
    updated_at = extraction.get("updated_at")
    if updated_at:
        OutputFormatter.print_info(f"Updated: {updated_at}")


def _poll_status_text(extraction: ExtractionResponse) -> str:
    status = extraction.get("extraction_status", "processing")
    if status == "pending":
        return "Waiting for extraction..."
    url_detail = extraction.get("url")
    if url_detail:
        fetched = url_detail.get("fetched_link_count", 0)
        candidate = url_detail.get("candidate_link_count", 0)
        if candidate > 0:
            return (
                f"Extracting events ({fetched}/{candidate} linked pages fetched)..."
            )
    return "Extracting events..."


def poll_extraction_to_completion(
    api_client: APIClient,
    email: str,
    extraction_id: str,
) -> ExtractionResponse:
    """Poll GET /api/extractions/{id} until terminal or timeout."""
    deadline = time.monotonic() + POLL_TIMEOUT_SECS
    last_status = "unknown"

    with Status("Waiting for extraction...", console=console, spinner="dots") as status:
        while True:
            extraction = api_client.get_extraction(email, extraction_id)
            last_status = extraction.get("extraction_status", "unknown")
            job_status = last_status

            if job_status == "failed":
                status.stop()
                OutputFormatter.print_error("Event extraction failed")
                error_type = extraction.get("extraction_error_type")
                if error_type:
                    OutputFormatter.print_error(f"  {error_type}")
                raise HerdsError("event extraction failed")

            if job_status == "completed":
                status.stop()
                OutputFormatter.print_success("Extraction completed")
                break

            status.update(_poll_status_text(extraction))

            if time.monotonic() >= deadline:
                status.stop()
                OutputFormatter.print_error(
                    f"Polling timed out after {POLL_TIMEOUT_SECS:.0f}s. "
                    f"Last status: {last_status}"
                )
                raise HerdsError("polling timed out")

            time.sleep(POLL_INTERVAL_SECS)

    return extraction


def _render_extraction_events(ctx: click.Context, events: List[EventV2]) -> None:
    """Render pre-fetched events with the standard event display."""
    OutputFormatter.print_success(f"Extracted {len(events)} event(s)")
    event_cmd = EventCommandBase(ctx)
    api_client: APIClient = ctx.obj["api_client"]
    resolver = ReconnectProviderResolver(api_client)
    for i, event in enumerate(events, 1):
        if len(events) > 1:
            OutputFormatter.print_info(f"--- Event {i} of {len(events)} ---")
        event_cmd.display_event_details(cast(EventV2, event), resolver=resolver)


def display_extraction_events(
    ctx: click.Context,
    email: str,
    extraction_id: str,
    *,
    empty_warning: str = "No events were extracted from this URL",
) -> None:
    """Fetch and render events for one extraction."""
    api_client: APIClient = ctx.obj["api_client"]
    timezone = ctx.obj["timezone"]

    OutputFormatter.print_info("Fetching extracted events...")
    events = api_client.get_extraction_events(
        email, extraction_id, timezone=timezone
    )

    if not events:
        OutputFormatter.print_warning(empty_warning)
        return

    _render_extraction_events(ctx, events)


def parse_before_timestamp(value: str, tz_name: str) -> str:
    """Parse --before into an aware UTC ISO 8601 string for the API."""
    local_tz = ZoneInfo(tz_name)
    try:
        if len(value) == 10 and value[4] == "-" and value[7] == "-":
            dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=local_tz)
        else:
            normalized = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=local_tz)
    except ValueError as exc:
        raise click.UsageError(
            f"Invalid --before value {value!r}: expected YYYY-MM-DD or ISO 8601"
        ) from exc

    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


@extractions.command("list")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--status",
    type=click.Choice(["pending", "processing", "completed", "failed"]),
    help="Filter by extraction status",
)
@click.option(
    "--source-type",
    type=click.Choice(["url", "image"]),
    help="Filter by source type",
)
@click.option(
    "--acked/--unacked",
    "acknowledged",
    default=None,
    help="Filter by acknowledgment state (omit for no filter)",
)
@click.option(
    "--limit",
    default=50,
    type=click.IntRange(min=1, max=200),
    show_default=True,
    help="Maximum number of extractions to return",
)
@click.option(
    "--offset",
    default=0,
    type=int,
    show_default=True,
    help="Pagination offset",
)
@click.pass_context
def list_extractions_cmd(
    ctx, email, status, source_type, acknowledged, limit, offset
):
    """List extraction history with optional filters."""
    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    OutputFormatter.print_info(
        f"Retrieving extractions (limit: {limit}, offset: {offset})..."
    )

    try:
        result = cmd.api_client.list_extractions(
            email,
            status=status,
            source_type=source_type,
            acknowledged=acknowledged,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError("failed to list extractions") from exc

    items = result.get("extractions", [])
    total_count = result.get("total_count", 0)
    next_offset = result.get("next_offset")

    if items:
        OutputFormatter.print_success(
            f"Found {total_count} extraction(s) (showing {len(items)})"
        )
        current_page = (offset // limit) + 1
        total_pages = (total_count + limit - 1) // limit
        if total_pages > 1:
            OutputFormatter.print_info(
                f"Page {current_page} of {total_pages} "
                f"(use --offset {next_offset or (offset + limit)} to see next page)"
            )
        OutputFormatter.print_info("Extractions:")
        for i, extraction in enumerate(items, 1):
            OutputFormatter.print_info(escape(_format_list_row(i, extraction)))
    else:
        OutputFormatter.print_warning("No extractions found")

    APIResponseHandler.format_and_output(result, cmd.output_format)


@extractions.command("get")
@click.argument("extraction_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def get_extraction_cmd(ctx, extraction_id, email):
    """Get one extraction's status by ID."""
    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    OutputFormatter.print_info(f"Retrieving extraction: {extraction_id}")

    try:
        result = cmd.api_client.get_extraction(email, extraction_id)
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError(f"failed to get extraction {extraction_id}") from exc

    _display_extraction_summary(result)
    APIResponseHandler.format_and_output(result, cmd.output_format)


@extractions.command("events")
@click.argument("extraction_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def events_cmd(ctx, extraction_id, email):
    """Fetch and display an extraction's events."""
    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    output_format = cmd.output_format
    timezone = ctx.obj["timezone"]

    try:
        events = cmd.api_client.get_extraction_events(
            email, extraction_id, timezone=timezone
        )
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError(f"failed to get events for extraction {extraction_id}") from exc

    if output_format == "json":
        APIResponseHandler.format_and_output(events, output_format)
        return

    if not events:
        OutputFormatter.print_warning("No events were extracted")
        return

    _render_extraction_events(ctx, events)


@extractions.command("ack")
@click.argument("extraction_ids", nargs=-1)
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--before",
    help="Acknowledge extractions updated before this timestamp (ISO 8601 or YYYY-MM-DD)",
)
@click.option(
    "--all",
    "ack_all",
    is_flag=True,
    help="Acknowledge every terminal extraction",
)
@click.pass_context
def ack_cmd(ctx, extraction_ids, email, before, ack_all):
    """Acknowledge terminal extractions."""
    ids: List[str] = list(extraction_ids)

    if ack_all and (ids or before):
        raise click.UsageError("--all cannot be combined with extraction IDs or --before")
    if not ack_all and not before and not ids:
        raise click.UsageError(
            "Provide extraction ID(s), --before, or --all"
        )

    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    before_utc: Optional[str] = None
    if before:
        before_utc = parse_before_timestamp(before, ctx.obj["timezone"])

    try:
        result = cmd.api_client.acknowledge_extractions(
            email,
            before=before_utc,
            extraction_ids=ids if ids else None,
        )
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError("failed to acknowledge extractions") from exc

    count = result.get("acknowledged_count", 0)
    OutputFormatter.print_success(f"Acknowledged {count} extraction(s)")
    APIResponseHandler.format_and_output(result, cmd.output_format)


@extractions.command("share")
@click.argument("extraction_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--web-url",
    help=(
        "Also report the share URL rebuilt on this base "
        "(e.g. http://localhost:5173) for testing a local web app"
    ),
)
@click.pass_context
def share_cmd(ctx, extraction_id, email, web_url):
    """Mint (or return the existing) share link for an extraction.

    Unlike other text-mode commands, this one also prints the share URL
    (and nothing else) on stdout, so `herds extractions share <id> | pbcopy`
    works directly; status messages stay on stderr. When --web-url is
    passed, the stdout line is the rebuilt local URL instead. This is a
    deliberate, scoped deviation from the stdout-empty text convention.

    Scripts that want the token or the server URL explicitly should use:
    `herds extractions share <id> --format json | jq -r .share_url`
    """
    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    try:
        result = cmd.api_client.create_share(email, extraction_id)
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError(f"failed to share extraction {extraction_id}") from exc

    share_url = result.get("share_url", "")
    local_share_url: Optional[str] = None
    if web_url:
        local_share_url = f"{web_url.rstrip('/')}/s/{result.get('share_token', '')}"

    if cmd.output_format == "json":
        payload: Dict[str, Any] = dict(result)
        if local_share_url is not None:
            payload["local_share_url"] = local_share_url
        APIResponseHandler.format_and_output(payload, "json")
        return

    OutputFormatter.print_success(f"Share link: {share_url}")
    if local_share_url is not None:
        OutputFormatter.print_info(f"Local share link: {local_share_url}")
    # Pipeable data channel: the one URL the caller came for (see docstring).
    click.echo(local_share_url if local_share_url is not None else share_url)


@extractions.command("unshare")
@click.argument("extraction_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def unshare_cmd(ctx, extraction_id, email):
    """Revoke an extraction's share link.

    After revocation the public share page renders its
    "link no longer active" state. Re-running `share` afterwards mints
    a fresh token.
    """
    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    try:
        result = cmd.api_client.revoke_share(email, extraction_id)
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError(f"failed to unshare extraction {extraction_id}") from exc

    OutputFormatter.print_success("Share link revoked.")
    APIResponseHandler.format_and_output(result, cmd.output_format)
