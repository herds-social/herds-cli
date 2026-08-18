"""
Source commands for the Herds CLI.

Read-side facade over /api/sources (URL, image, and bookmark). Shared
poll/display helpers are exported for herds url submit --poll.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List, Optional, cast
from zoneinfo import ZoneInfo

import click
from rich.markup import escape
from rich.status import Status

from herds_cli.api import APIClient
from herds_cli.calendar_status_display import ReconnectProviderResolver
from herds_cli.core.base import APIResponseHandler, CommandBase, EventCommandBase
from herds_cli.core.exceptions import HerdsError
from herds_cli.output import OutputFormatter, console
from herds_cli.types import EventV2, ShareCommandOutput, SourceResponse

POLL_INTERVAL_SECS = 2.0
POLL_TIMEOUT_SECS = 180.0

_TERMINAL_STATUSES = frozenset({"completed", "failed"})


@click.group()
def sources():
    """Source inbox, status, share, and reprocess commands."""
    pass


def _source_label(source: SourceResponse) -> str:
    source_type = source.get("source_type")
    if source_type == "url":
        url_detail = source.get("url") or {}
        return url_detail.get("submitted_url", "unknown")
    if source_type == "image":
        image_detail = source.get("image") or {}
        return image_detail.get("image_name", "unnamed")
    if source_type == "bookmark":
        return source.get("bookmark_source_id") or "unknown"
    return "unknown"


def _event_count_display(source: SourceResponse) -> str:
    status = source.get("extraction_status", "")
    if status not in _TERMINAL_STATUSES:
        return "-"
    count = source.get("event_count", 0)
    return f"{count} events"


def _is_unacknowledged_terminal(source: SourceResponse) -> bool:
    status = source.get("extraction_status", "")
    if status not in _TERMINAL_STATUSES:
        return False
    return source.get("acknowledged_at") is None


def _format_list_row(index: int, source: SourceResponse) -> str:
    source_id = source.get("source_id", "unknown")
    source_type = source.get("source_type", "unknown")
    status = source.get("extraction_status", "unknown")
    source_label = _source_label(source)
    created_at = source.get("created_at", "unknown")
    row = (
        f"  {index}. [{source_id}] {source_type:<8} {status:<10} "
        f"{_event_count_display(source):<8} {source_label:<28} {created_at}"
    )
    if status == "failed":
        error_type = source.get("extraction_error_type")
        if error_type:
            row += f" ({error_type})"
    if _is_unacknowledged_terminal(source):
        row += " [unread]"
    return row


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _display_source_summary(source: SourceResponse) -> None:
    """Print a human-readable source status summary."""
    source_id = source.get("source_id", "unknown")
    OutputFormatter.print_info(f"Source ID: {source_id}")
    OutputFormatter.print_info(f"Source type: {source.get('source_type', 'unknown')}")
    OutputFormatter.print_info(
        f"Status: {source.get('extraction_status', 'unknown')}"
    )

    error_type = source.get("extraction_error_type")
    if error_type:
        OutputFormatter.print_info(f"Error type: {error_type}")

    OutputFormatter.print_info(f"Event count: {source.get('event_count', 0)}")
    OutputFormatter.print_info(
        f"Can reprocess: {_yes_no(bool(source.get('can_reprocess')))}"
    )

    share_url = source.get("share_url")
    if share_url:
        OutputFormatter.print_info(f"Share URL: {share_url}")

    source_type = source.get("source_type")
    if source_type == "url":
        url_detail = source.get("url") or {}
        OutputFormatter.print_info(f"URL: {url_detail.get('submitted_url', 'unknown')}")
        OutputFormatter.print_info(
            f"Links: {url_detail.get('fetched_link_count', 0)}/"
            f"{url_detail.get('candidate_link_count', 0)} fetched"
        )
    elif source_type == "image":
        image_detail = source.get("image") or {}
        OutputFormatter.print_info(f"Image: {image_detail.get('image_name', 'unknown')}")
        OutputFormatter.print_info(
            f"Media type: {image_detail.get('image_media_type', 'unknown')}"
        )
    elif source_type == "bookmark":
        OutputFormatter.print_info(
            f"Bookmark source: {source.get('bookmark_source_id', 'unknown')}"
        )

    ack_at = source.get("acknowledged_at")
    if ack_at:
        OutputFormatter.print_info(f"Acknowledged: {ack_at}")
    else:
        OutputFormatter.print_info("Acknowledged: no")

    OutputFormatter.print_info(f"Created: {source.get('created_at', 'unknown')}")
    updated_at = source.get("updated_at")
    if updated_at:
        OutputFormatter.print_info(f"Updated: {updated_at}")


def _poll_status_text(source: SourceResponse) -> str:
    status = source.get("extraction_status", "processing")
    if status == "pending":
        return "Waiting for extraction..."
    url_detail = source.get("url")
    if url_detail:
        fetched = url_detail.get("fetched_link_count", 0)
        candidate = url_detail.get("candidate_link_count", 0)
        if candidate > 0:
            return (
                f"Extracting events ({fetched}/{candidate} linked pages fetched)..."
            )
    return "Extracting events..."


def poll_source_to_completion(
    api_client: APIClient,
    email: str,
    source_id: str,
) -> SourceResponse:
    """Poll GET /api/sources/{id} until terminal or timeout."""
    deadline = time.monotonic() + POLL_TIMEOUT_SECS
    last_status = "unknown"

    with Status("Waiting for extraction...", console=console, spinner="dots") as status:
        while True:
            source = api_client.get_source(email, source_id)
            last_status = source.get("extraction_status", "unknown")

            if last_status == "failed":
                status.stop()
                OutputFormatter.print_error("Event extraction failed")
                error_type = source.get("extraction_error_type")
                if error_type:
                    OutputFormatter.print_error(f"  {error_type}")
                raise HerdsError("event extraction failed")

            if last_status == "completed":
                status.stop()
                OutputFormatter.print_success("Extraction completed")
                break

            status.update(_poll_status_text(source))

            if time.monotonic() >= deadline:
                status.stop()
                OutputFormatter.print_error(
                    f"Polling timed out after {POLL_TIMEOUT_SECS:.0f}s. "
                    f"Last status: {last_status}"
                )
                raise HerdsError("polling timed out")

            time.sleep(POLL_INTERVAL_SECS)

    return source


def _render_source_events(ctx: click.Context, events: List[EventV2]) -> None:
    """Render pre-fetched events with the standard event display."""
    OutputFormatter.print_success(f"Extracted {len(events)} event(s)")
    event_cmd = EventCommandBase(ctx)
    api_client: APIClient = ctx.obj["api_client"]
    resolver = ReconnectProviderResolver(api_client)
    for i, event in enumerate(events, 1):
        if len(events) > 1:
            OutputFormatter.print_info(f"--- Event {i} of {len(events)} ---")
        event_cmd.display_event_details(event, resolver=resolver)


def display_source_events(
    ctx: click.Context,
    email: str,
    source_id: str,
    *,
    empty_warning: str = "No events were extracted",
) -> None:
    """Fetch and render events for one source."""
    api_client: APIClient = ctx.obj["api_client"]
    timezone = ctx.obj["timezone"]

    OutputFormatter.print_info("Fetching extracted events...")
    events = api_client.get_source_events(email, source_id, timezone=timezone)

    if not events:
        OutputFormatter.print_warning(empty_warning)
        return

    _render_source_events(ctx, events)


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


@sources.command("list")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--status",
    type=click.Choice(["pending", "processing", "completed", "failed"]),
    help="Filter by extraction status",
)
@click.option(
    "--source-type",
    type=click.Choice(["url", "image", "bookmark"]),
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
    help="Maximum number of sources to return",
)
@click.option(
    "--offset",
    default=0,
    type=int,
    show_default=True,
    help="Pagination offset",
)
@click.pass_context
def list_sources_cmd(ctx, email, status, source_type, acknowledged, limit, offset):
    """List sources with optional filters."""
    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    OutputFormatter.print_info(
        f"Retrieving sources (limit: {limit}, offset: {offset})..."
    )

    try:
        result = cmd.api_client.list_sources(
            email,
            extraction_status=status,
            source_type=source_type,
            acknowledged=acknowledged,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError("failed to list sources") from exc

    items = result.get("sources", [])
    total_count = result.get("total_count", 0)
    next_offset = result.get("next_offset")

    if items:
        OutputFormatter.print_success(
            f"Found {total_count} source(s) (showing {len(items)})"
        )
        current_page = (offset // limit) + 1
        total_pages = (total_count + limit - 1) // limit
        if total_pages > 1:
            OutputFormatter.print_info(
                f"Page {current_page} of {total_pages} "
                f"(use --offset {next_offset or (offset + limit)} to see next page)"
            )
        OutputFormatter.print_info("Sources:")
        for i, source in enumerate(items, 1):
            OutputFormatter.print_info(escape(_format_list_row(i, source)))
    else:
        OutputFormatter.print_warning("No sources found")

    APIResponseHandler.format_and_output(result, cmd.output_format)


@sources.command("get")
@click.argument("source_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def get_source_cmd(ctx, source_id, email):
    """Get one source's status by ID."""
    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    OutputFormatter.print_info(f"Retrieving source: {source_id}")

    try:
        result = cmd.api_client.get_source(email, source_id)
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError(f"failed to get source {source_id}") from exc

    _display_source_summary(result)
    APIResponseHandler.format_and_output(result, cmd.output_format)


@sources.command("events")
@click.argument("source_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def events_cmd(ctx, source_id, email):
    """Fetch and display a source's events."""
    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    output_format = cmd.output_format
    timezone = ctx.obj["timezone"]

    try:
        events = cmd.api_client.get_source_events(
            email, source_id, timezone=timezone
        )
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError(f"failed to get events for source {source_id}") from exc

    if output_format == "json":
        APIResponseHandler.format_and_output(events, output_format)
        return

    if not events:
        OutputFormatter.print_warning("No events were extracted")
        return

    _render_source_events(ctx, events)


@sources.command("ack")
@click.argument("source_ids", nargs=-1)
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--before",
    help="Acknowledge sources updated before this timestamp (ISO 8601 or YYYY-MM-DD)",
)
@click.option(
    "--all",
    "ack_all",
    is_flag=True,
    help="Acknowledge every terminal source",
)
@click.pass_context
def ack_cmd(ctx, source_ids, email, before, ack_all):
    """Acknowledge terminal sources."""
    ids: List[str] = list(source_ids)

    if ack_all and (ids or before):
        raise click.UsageError("--all cannot be combined with source IDs or --before")
    if not ack_all and not before and not ids:
        raise click.UsageError("Provide source ID(s), --before, or --all")

    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    before_utc: Optional[str] = None
    if before:
        before_utc = parse_before_timestamp(before, ctx.obj["timezone"])

    try:
        result = cmd.api_client.acknowledge_sources(
            email,
            before=before_utc,
            source_ids=ids if ids else None,
        )
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError("failed to acknowledge sources") from exc

    count = result.get("acknowledged_count", 0)
    OutputFormatter.print_success(f"Acknowledged {count} source(s)")
    APIResponseHandler.format_and_output(result, cmd.output_format)


@sources.command("reprocess")
@click.argument("source_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def reprocess_cmd(ctx, source_id, email):
    """Retry a failed URL or image source."""
    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    try:
        result = cmd.api_client.reprocess_source(email, source_id)
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError(f"failed to reprocess source {source_id}") from exc

    OutputFormatter.print_success(f"Reprocessing source {source_id}")
    APIResponseHandler.format_and_output(result, cmd.output_format)


@sources.command("share")
@click.argument("source_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--web-url",
    help=(
        "Also report the share URL rebuilt on this base "
        "(e.g. http://localhost:5173) for testing a local web app"
    ),
)
@click.pass_context
def share_cmd(ctx, source_id, email, web_url):
    """Mint (or return the existing) share link for a source.

    The share URL (and nothing else) is printed on stdout - a deliberate
    exception, scoped to this command, to the usual empty-stdout text
    convention - so `herds sources share <id> | pbcopy` works
    directly. To keep that pipe working, a default `auto` format resolves
    to text here even when piped (every other command resolves a piped
    `auto` to json). Status messages stay on stderr. With --web-url, the
    stdout line is the rebuilt local URL instead.

    Scripts that want the token or the server URL explicitly can use:
    `herds sources share <id> --format json | jq -r .share_url`
    """
    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    output_format = cmd.output_format
    if ctx.obj.get("_raw_format") == "auto":
        output_format = "text"

    try:
        result = cmd.api_client.create_share(email, source_id)
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError(f"failed to share source {source_id}") from exc

    share_url = result["share_url"]
    local_share_url: Optional[str] = None
    if web_url:
        local_share_url = f"{web_url.rstrip('/')}/s/{result['share_token']}"

    payload = cast(ShareCommandOutput, result)
    if local_share_url is not None:
        payload["local_share_url"] = local_share_url
    APIResponseHandler.format_and_output(payload, output_format)

    OutputFormatter.print_success(f"Share link: {share_url}")
    if local_share_url is not None:
        OutputFormatter.print_info(f"Local share link: {local_share_url}")
    if output_format != "json":
        click.echo(local_share_url if local_share_url is not None else share_url)


@sources.command("unshare")
@click.argument("source_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def unshare_cmd(ctx, source_id, email):
    """Revoke a source's share link.

    After revocation the public share page renders its
    "link no longer active" state. Re-running `share` afterwards restores
    the same URL. Bookmark revoke is rejected by the server.
    """
    cmd = CommandBase(ctx)
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)
    cmd.load_session_auth(email)

    try:
        result = cmd.api_client.revoke_share(email, source_id)
    except Exception as exc:
        OutputFormatter.print_error(str(exc))
        raise HerdsError(f"failed to unshare source {source_id}") from exc

    OutputFormatter.print_success("Share link revoked.")
    APIResponseHandler.format_and_output(result, cmd.output_format)
