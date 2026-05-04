"""
Image management commands for the Herds CLI.

This module contains commands for image upload, processing, and management.
"""

import click
import sys
import time
from pathlib import Path
from typing import cast

from rich.status import Status

from herds_cli.api import APIClient
from herds_cli.calendar_status_display import ReconnectProviderResolver
from herds_cli.output import OutputFormatter, console
from herds_cli.core.base import (
    APIResponseHandler,
    EventCommandBase,
    ImageCommandBase,
    get_or_detect_session_email,
)
from herds_cli.core.exceptions import HerdsError
from herds_cli.types import EventV2, ImageV2Response

POLL_INTERVAL_SECS = 2.0
POLL_TIMEOUT_SECS = 180.0


@click.group()
def image():
    """Image management commands (upload, etc.)"""
    pass


@image.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--mock", is_flag=True, help="Enable mock AI processing for faster testing"
)
@click.option(
    "--endpoint",
    default="/api/images/v2/upload",
    help="API endpoint for upload",
    show_default=True,
)
@click.option(
    "--alg-version",
    type=click.Choice(["auto", "v2", "v3"]),
    default=None,
    help="Algorithm version to use for image processing ('auto' tries v3 first, fallback to v2)",
)
@click.option(
    "--ocr-text",
    help="OCR text to include with the upload",
)
@click.option(
    "--barcode",
    help="Barcode data to include with the upload",
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
def upload(ctx, file_path, email, mock, endpoint, alg_version, ocr_text, barcode, add_to_calendar, poll):
    """Upload an image file with optional algorithm version, mock mode, OCR text, and barcode selection."""
    session_manager = ctx.obj["session_manager"]
    image_uploader = ctx.obj["image_uploader"]
    output_format = ctx.obj["format"]
    timezone = ctx.obj["timezone"]

    # --poll streams human-readable progress to the console; mixing that with
    # JSON output would corrupt the JSON stream. Combined support can come
    # later (would emit one JSON blob containing image + extracted events).
    # We only reject when the user *explicitly* asked for JSON — letting the
    # config default flow through keeps `--poll` usable without forcing
    # every invocation to also pass `--format text`.
    format_explicit = ctx.obj.get("_format_explicit", False)
    if poll and output_format == "json" and format_explicit:
        raise click.UsageError(
            "--poll cannot be combined with --format json (not yet supported)"
        )

    # Get email from session
    config = ctx.obj["config"]
    email = get_or_detect_session_email(
        session_manager, email, show_client_type=True, config=config
    )

    try:
        result = image_uploader.upload_image(
            file_path,
            email,
            endpoint,
            timezone=timezone,
            alg_version=alg_version,
            mock_mode=mock,
            ocr_text=ocr_text,
            barcode=barcode,
            add_to_calendar=add_to_calendar,
        )

        OutputFormatter.print_success(f"Successfully uploaded {Path(file_path).name}")
        image_id = result.get("image_id")
        if image_id:
            OutputFormatter.print_info(f"Image ID: {image_id}")
        OutputFormatter.print_info(f"Media type: {result.get('media_type', 'unknown')}")

        if poll:
            if not image_id:
                OutputFormatter.print_error(
                    "Upload response missing image_id; cannot poll for status"
                )
                raise HerdsError("upload response missing image_id")
            api_client: APIClient = ctx.obj["api_client"]
            _poll_and_display_event(api_client, email, image_id, timezone, ctx)
            return

        # Output formatted response
        if output_format == "json":  # text mode already rendered via print_info above
            output = OutputFormatter.format_output(result, output_format)
            if output:  # Only print if there's content
                click.echo(output)

    except HerdsError:
        # Already printed by the raiser; let HerdsGroup convert to exit code.
        raise
    except Exception as e:
        OutputFormatter.print_error(f"Upload failed: {e}")
        raise HerdsError(f"upload failed: {e}") from e


def _fetch_image_status(api_client: "APIClient", image_id: str) -> ImageV2Response:
    """Fetch one snapshot of the image record (status fields included)."""
    url = f"{api_client.base_url}/api/images/v2/{image_id}"
    response = api_client._make_request("GET", url)
    if response.status_code != 200:
        error_msg = APIResponseHandler.format_error_message(response)
        raise RuntimeError(f"Failed to fetch image status: {error_msg}")
    return cast(ImageV2Response, response.json())


def _poll_and_display_event(
    api_client: "APIClient",
    email: str,
    image_id: str,
    timezone: str,
    ctx: click.Context,
) -> None:
    """Poll an in-flight upload through resize → extraction, then print events.

    Stages tracked separately because they happen in series server-side:
      1. resize_status + thumbnail_status (image variants written to S3)
      2. image_extraction_status (LLM extracts event metadata)

    Failures at either stage exit non-zero with the server's error details.
    """
    deadline = time.monotonic() + POLL_TIMEOUT_SECS
    stage1_announced_done = False

    with Status(
        "Waiting for image processing...", console=console, spinner="dots"
    ) as status:
        while True:
            image = _fetch_image_status(api_client, image_id)

            resize = image.get("resize_status", "processing")
            thumbnail = image.get("thumbnail_status", "processing")
            extraction = image.get("image_extraction_status", "processing")

            if resize == "failed" or thumbnail == "failed":
                status.stop()
                OutputFormatter.print_error(
                    f"Image resize failed (resize={resize}, thumbnail={thumbnail})"
                )
                raise HerdsError(
                    f"image resize failed (resize={resize}, thumbnail={thumbnail})"
                )

            if extraction == "failed":
                status.stop()
                OutputFormatter.print_error("Event extraction failed")
                exception = image.get("extraction_exception")
                if exception:
                    exc_type = exception.get("type", "Unknown")
                    exc_msg = exception.get("message", "")
                    OutputFormatter.print_error(f"  {exc_type}: {exc_msg}")
                raise HerdsError("event extraction failed")

            stage1_done = resize == "completed" and thumbnail == "completed"

            if extraction == "completed":
                status.stop()
                if not stage1_announced_done:
                    OutputFormatter.print_success("Image processed")
                OutputFormatter.print_success("Event extracted")
                break

            if stage1_done:
                if not stage1_announced_done:
                    # Print once when we transition out of stage 1 — gives the
                    # user a permanent record above the live spinner.
                    status.stop()
                    OutputFormatter.print_success("Image processed")
                    stage1_announced_done = True
                    status.start()
                status.update("Extracting event details...")
            else:
                status.update("Processing image...")

            if time.monotonic() >= deadline:
                status.stop()
                OutputFormatter.print_error(
                    f"Polling timed out after {POLL_TIMEOUT_SECS:.0f}s. "
                    f"Last status: extraction={extraction}, resize={resize}, "
                    f"thumbnail={thumbnail}"
                )
                raise HerdsError("polling timed out")

            time.sleep(POLL_INTERVAL_SECS)

    # Extraction complete — fetch and display the extracted events.
    OutputFormatter.print_info("Fetching extracted events...")
    events = api_client.get_events_by_image_id(email, image_id, timezone=timezone)

    if not events:
        OutputFormatter.print_warning("No events were extracted from this image")
        return

    OutputFormatter.print_success(f"Extracted {len(events)} event(s)")
    event_cmd = EventCommandBase(ctx)
    # One resolver per upload — caches /api/calendar/status across events so
    # multi-event images make at most one extra GET regardless of how many
    # events end up tagged calendar_needs_reconnect.
    resolver = ReconnectProviderResolver(api_client)
    for i, event in enumerate(events, 1):
        if len(events) > 1:
            OutputFormatter.print_info(f"--- Event {i} of {len(events)} ---")
        event_cmd.display_event_details(cast(EventV2, event), resolver=resolver)


@image.command()
@click.argument("image_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def get(ctx, image_id, email):
    """Get image metadata by ID from the API."""
    cmd = ImageCommandBase(ctx)

    # Get email and validate session exists
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)

    # Load session authentication
    cmd.load_session_auth(email)

    OutputFormatter.print_info(f"Retrieving image metadata for: {image_id}")

    # Execute API request and handle response
    url = f"{cmd.api_client.base_url}/api/images/v2/{image_id}"
    result = cmd.execute_api_request(
        "GET", url, "Successfully retrieved image metadata"
    )

    # Display image information using the base class method
    cmd.display_image_summary(cast(ImageV2Response, result))

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format)


@image.command()
@click.argument("image_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def detections(ctx, image_id, email):
    """Get all detection/response data for an image by ID."""
    cmd = ImageCommandBase(ctx)

    # Get email and validate session exists
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)

    # Load session authentication
    cmd.load_session_auth(email)

    OutputFormatter.print_info(f"Retrieving detection data for image: {image_id}")

    # Execute API request
    url = f"{cmd.api_client.base_url}/api/images/v2/{image_id}/detections"
    result = cmd.execute_api_request("GET", url)

    detections = result.get("responses", [])
    OutputFormatter.print_success(
        f"Successfully retrieved {len(detections)} detections"
    )

    if detections:
        OutputFormatter.print_info("Detection Summary:")
        total_cost = 0.0

        for i, detection in enumerate(detections, 1):
            cost = detection.get("cost", 0)
            total_cost += cost
            provider = detection.get("provider", "unknown")
            model = detection.get("model", "unknown")
            created = detection.get("created_at", "unknown")

            OutputFormatter.print_info(
                f"  {i}. {provider}/{model} - Cost: ${cost:.4f} - Created: {created}"
            )

        OutputFormatter.print_info(f"Total Cost: ${total_cost:.4f}")

        # Display event data summary if available
        event_data = detections[0].get("event_data", {})
        if event_data.get("has_event_data"):
            OutputFormatter.print_info("Event Information:")
            OutputFormatter.print_info(f"  Title: {event_data.get('title', 'N/A')}")
            OutputFormatter.print_info(
                f"  Organizer: {event_data.get('organizer', 'N/A')}"
            )
            OutputFormatter.print_info(
                f"  Category: {event_data.get('category_level_1', 'N/A')}"
            )
            if event_data.get("event_date"):
                OutputFormatter.print_info(f"  Date: {event_data.get('event_date')}")
    else:
        OutputFormatter.print_warning("No detections found for this image")

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format)


@image.command("in-progress")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--limit",
    default=50,
    type=int,
    help="Maximum number of images to return",
    show_default=True,
)
@click.option(
    "--offset", default=0, type=int, help="Number of images to skip", show_default=True
)
@click.option(
    "--sort-by",
    default="created_at",
    type=click.Choice(["created_at", "updated_at", "name"]),
    help="Field to sort images by",
    show_default=True,
)
@click.option(
    "--sort-order",
    default="desc",
    type=click.Choice(["asc", "desc"]),
    help="Sort order (ascending or descending)",
    show_default=True,
)
@click.pass_context
def in_progress(ctx, email, limit, offset, sort_by, sort_order):
    """List images currently in progress (pending or processing status).

    Shows all images that are currently being processed by the AI system.
    Images with extraction_status of 'pending' or 'processing' are included.

    The results are paginated - use --offset to see more images.

    Examples:
        herds image in-progress
        herds image in-progress --limit 20 --offset 40
        herds image in-progress --sort-by name --sort-order asc
        herds image in-progress --email user@example.com
    """
    cmd = ImageCommandBase(ctx)

    # Get email and validate session exists
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)

    # Load session authentication
    cmd.load_session_auth(email)

    # Build query parameters
    params = {
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }

    OutputFormatter.print_info(
        f"Retrieving in-progress images (limit: {limit}, offset: {offset})..."
    )

    # Execute API request
    url = f"{cmd.api_client.base_url}/api/images/v2/images/in-progress"
    result = cmd.execute_api_request("GET", url, params=params)

    images = result.get("images", [])
    total_count = result.get("total_count", 0)
    has_more = result.get("has_more", False)
    next_offset = result.get("next_offset")

    # Display summary
    if images:
        OutputFormatter.print_success(
            f"Found {total_count} images in progress (showing {len(images)})"
        )

        # Calculate page info
        current_page = (offset // limit) + 1
        total_pages = (total_count + limit - 1) // limit  # Ceiling division

        if total_pages > 1:
            OutputFormatter.print_info(
                f"Page {current_page} of {total_pages} "
                f"(use --offset {next_offset or (offset + limit)} to see next page)"
            )

        # Display images
        OutputFormatter.print_info("Images in progress:")
        for i, image in enumerate(images, 1):
            image_id = image.get("image_id", "unknown")
            image_name = image.get("image_name", "unnamed")
            status = image.get("image_extraction_status", "unknown")
            created_at = image.get("image_created_at", "unknown")
            size_mb = image.get("original_size_mb")

            # Format size display
            size_display = f" ({size_mb:.1f}MB)" if size_mb else ""

            # Format ID for display (show first 8 chars)
            short_id = image_id[:8] if len(image_id) > 8 else image_id

            OutputFormatter.print_info(
                f"  {i}. [{short_id}] {image_name} - {status}{size_display}"
            )
            OutputFormatter.print_info(f"     Created: {created_at}")
    else:
        OutputFormatter.print_warning("No images currently in progress")

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format)


@image.command()
@click.argument("image_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def delete(ctx, image_id, email, yes):
    """Delete an image by ID.

    This action cannot be undone. The image and all associated data (S3 files, responses) will be permanently deleted.
    """
    cmd = ImageCommandBase(ctx)

    # Get email and validate session exists
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)

    # Confirm deletion unless --yes flag is used
    if not yes:
        OutputFormatter.print_warning(f"You are about to delete image: {image_id}")
        OutputFormatter.print_warning("This action cannot be undone!")
        if not click.confirm("Are you sure you want to continue?"):
            OutputFormatter.print_info("Deletion cancelled.")
            return

    OutputFormatter.print_info(f"Deleting image: {image_id}")

    # Use the API client method
    result = cmd.api_client.delete_image(email, image_id)

    OutputFormatter.print_success(f"Successfully deleted image {image_id}")

    # Output formatted response
    APIResponseHandler.format_and_output(result, cmd.output_format)


@image.command()
@click.argument("image_id")
@click.option("--email", help="Email address (autodetect if only one session)")
@click.option(
    "--type",
    "image_type",
    type=click.Choice(["original", "resized", "thumbnail"]),
    default="resized",
    help="Which image version to display",
    show_default=True,
)
@click.option(
    "--width",
    default="auto",
    help="Display width for iTerm2 (e.g., '800px', '50%', 'auto')",
    show_default=True,
)
@click.option(
    "--save", type=click.Path(), help="Save image to file instead of displaying"
)
@click.pass_context
def show(ctx, image_id, email, image_type, width, save):
    """Display an image by ID in the terminal.

    Fetches the image metadata and displays the specified image version inline
    in iTerm2. If not in iTerm2, saves to a temporary file instead.

    Examples:
        herds image show abc123def456
        herds image show abc123def456 --type original
        herds image show abc123def456 --type thumbnail --width 400px
        herds image show abc123def456 --save my_image.jpg
    """
    from herds_cli.image_display import ImageDisplay

    cmd = ImageCommandBase(ctx)

    # Get email and validate session exists
    email = cmd.setup_session(email, show_client_type=True)
    cmd.validate_session(email)

    # Load session authentication
    cmd.load_session_auth(email)

    OutputFormatter.print_info(f"Retrieving image metadata for: {image_id}")

    # Fetch image metadata
    url = f"{cmd.api_client.base_url}/api/images/v2/{image_id}"
    result = cmd.execute_api_request("GET", url)

    # Map image_type to the correct field name in the response
    type_to_field = {
        "original": "image_path",
        "resized": "resized_path",
        "thumbnail": "thumbnail_path",
    }

    field_name = type_to_field[image_type]
    image_url = result.get(field_name)

    # Check if the requested image path exists
    if not image_url:
        OutputFormatter.print_error(
            f"The {image_type} image is not available for this image."
        )

        # Provide helpful information about available versions
        available_types = []
        if result.get("image_path"):
            available_types.append("original")
        if result.get("resized_path"):
            available_types.append("resized")
        if result.get("thumbnail_path"):
            available_types.append("thumbnail")

        if available_types:
            OutputFormatter.print_info(f"Available types: {', '.join(available_types)}")

        sys.exit(1)

    # Display status information
    if image_type == "resized":
        status = result.get("resize_status", "unknown")
        OutputFormatter.print_info(f"Resize status: {status}")
    elif image_type == "thumbnail":
        status = result.get("thumbnail_status", "unknown")
        OutputFormatter.print_info(f"Thumbnail status: {status}")

    OutputFormatter.print_info(f"Fetching {image_type} image...")

    # Download the image bytes
    try:
        image_bytes = cmd.api_client.fetch_authenticated_image(image_url)
    except Exception as e:
        OutputFormatter.print_error(f"Failed to fetch image: {e}")
        sys.exit(1)

    # Either save to file or display in terminal
    if save:
        try:
            ImageDisplay.save_image(image_bytes, save)
            OutputFormatter.print_success(f"Image saved successfully")
        except Exception as e:
            OutputFormatter.print_error(f"Failed to save image: {e}")
            sys.exit(1)
    else:
        try:
            OutputFormatter.print_info(f"Displaying {image_type} image...")
            ImageDisplay.display_in_iterm(image_bytes, width)

            # Show helpful info
            image_size_mb = len(image_bytes) / (1024 * 1024)
            OutputFormatter.print_info(f"Image size: {image_size_mb:.2f} MB")

        except Exception as e:
            OutputFormatter.print_error(f"Failed to display image: {e}")
            sys.exit(1)
