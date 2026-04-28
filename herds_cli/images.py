"""
Herds CLI Image Management Module

Handles image upload functionality with session-based authentication.

Note: imports APIResponseHandler lazily inside upload_image() to avoid a
circular dependency (core/base.py imports ImageUploader from this module).
"""

import os
import mimetypes
from pathlib import Path
from typing import Dict, Any, Optional, cast

from .api import APIClient
from .output import OutputFormatter
from .sessions import SessionManager
from .types import UploadResult


class ImageUploader:
    """Handles image upload operations with authentication."""

    def __init__(
        self,
        api_client: Optional[APIClient] = None,
        session_manager: Optional[SessionManager] = None,
    ):
        self.api_client = api_client or APIClient()
        self.session_manager = session_manager or SessionManager()

    def detect_media_type(self, file_path: Path) -> str:
        """
        Detect the media type of an image file.

        Args:
            file_path: Path to the image file

        Returns:
            str: MIME type string (e.g., 'image/jpeg', 'image/png')

        Raises:
            ValueError: If the file type cannot be determined or is not a supported image type
        """
        # Use mimetypes to guess the media type
        media_type, _ = mimetypes.guess_type(str(file_path))

        if not media_type:
            # Fallback: try to determine from file extension
            extension = file_path.suffix.lower()
            extension_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }
            media_type = extension_map.get(extension)

        if not media_type or not media_type.startswith("image/"):
            raise ValueError(
                f"Unsupported or unrecognized image type for file: {file_path}"
            )

        # Validate against supported types
        supported_types = [
            "image/jpeg",
            "image/jpg",
            "image/png",
            "image/webp",
            "image/gif",
        ]
        if media_type not in supported_types:
            raise ValueError(
                f"Unsupported media type: {media_type}. Supported types: {supported_types}"
            )

        return media_type

    def validate_image_file(self, file_path: str) -> Path:
        """Validate that the file exists and is an image."""
        path = Path(file_path)

        if not path.exists():
            raise ValueError(f"File {file_path} does not exist")

        if not path.is_file():
            raise ValueError(f"Path {file_path} is not a file")

        # Try to detect media type to validate it's an image
        try:
            self.detect_media_type(path)
        except ValueError as e:
            raise ValueError(f"Invalid image file: {e}")

        return path

    def upload_image(
        self,
        file_path: str,
        email: str,
        endpoint: str = "/api/images/v2/upload",
        timezone: Optional[str] = None,
        alg_version: Optional[str] = None,
        mock_mode: bool = False,
        ocr_text: Optional[str] = None,
        barcode: Optional[str] = None,
        add_to_calendar: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Upload an image file using authenticated session.

        Pre-action info lines (Uploading…, Using timezone…, etc.) are
        emitted here — after load_session_auth confirms credentials are
        loadable, before the multipart POST. This guarantees nothing is
        printed when the upload won't actually happen.

        Args:
            file_path: Path to the image file
            email: Email address for session lookup
            endpoint: API endpoint for upload
            timezone: IANA timezone string for event processing
            alg_version: Algorithm version to use ('auto', 'v2', or 'v3'). If None, uses server default.
            mock_mode: Enable mock AI processing for testing (bypasses real LLM calls). Defaults to False.
            ocr_text: OCR text to include with the upload (optional)
            barcode: Barcode data to include with the upload (optional)
            add_to_calendar: Tri-state override for server-side auto-add.
                True/False force the server's behavior; None omits the field
                so the server defers to the user's auto_add_to_calendar_enabled
                setting.

        Returns:
            Dict containing upload response

        Raises:
            Exception: If upload fails or authentication is invalid
        """
        # Validate file
        image_path = self.validate_image_file(file_path)

        # Load session authentication
        if not self.api_client.load_session_auth(email):
            raise Exception(
                f"No valid session found for {email}. Please login first using: "
                "herds user login"
            )

        # Pre-action info — only after auth has been loaded successfully.
        OutputFormatter.print_info(f"Uploading {file_path}...")
        if timezone:
            OutputFormatter.print_info(f"Using timezone: {timezone}")
        if alg_version:
            OutputFormatter.print_info(f"Using algorithm version: {alg_version}")
        if mock_mode:
            OutputFormatter.print_info("Using mock AI processing mode")
        if add_to_calendar is True:
            OutputFormatter.print_info("Requesting auto-add to calendar")
        elif add_to_calendar is False:
            OutputFormatter.print_info(
                "Skipping calendar auto-add (overrides user setting)"
            )

        # Detect media type
        media_type = self.detect_media_type(image_path)

        # Prepare file for upload
        with open(image_path, "rb") as f:
            files = {"image": (image_path.name, f, media_type)}

            # Prepare form data including timezone, algorithm version, mock mode, OCR text, and barcode
            data = {}
            if timezone:
                data["timezone"] = timezone
            if alg_version:
                data["alg_version"] = alg_version
            if mock_mode:
                data["mock_mode"] = "true"
            if ocr_text:
                data["ocr_text"] = ocr_text
            if barcode:
                data["barcode"] = barcode
            # Tri-state forwarding to match the server's UploadRequest contract:
            # True/False are explicit overrides; None omits the field so the
            # server defers to the user's auto_add_to_calendar_enabled setting.
            if add_to_calendar is not None:
                data["add_to_calendar"] = "true" if add_to_calendar else "false"

            # Make authenticated request
            url = f"{self.api_client.base_url}{endpoint}"
            response = self.api_client._make_request(
                "POST", url, files=files, data=data
            )

            if response.status_code == 200:
                result = response.json()
                result["file_path"] = str(image_path)
                result["media_type"] = media_type
                return result
            else:
                # Lazy import to avoid circular dependency (core/base imports ImageUploader)
                from herds_cli.core.base import APIResponseHandler

                error_msg = APIResponseHandler.format_error_message(response)
                raise Exception(f"Upload failed: {error_msg}")

    def upload_multiple_images(
        self,
        file_paths: list[str],
        email: str,
        endpoint: str = "/api/images/v2/upload",
        timezone: Optional[str] = None,
        alg_version: Optional[str] = None,
    ) -> list[UploadResult]:
        """
        Upload multiple image files.

        Args:
            file_paths: List of paths to image files
            email: Email address for session lookup
            endpoint: API endpoint for upload
            timezone: IANA timezone string for event processing
            alg_version: Algorithm version to use ('auto', 'v2', or 'v3'). If None, uses server default.

        Returns:
            List of upload results (dicts with success/error info)
        """
        results: list[UploadResult] = []

        for file_path in file_paths:
            try:
                result = self.upload_image(
                    file_path,
                    email,
                    endpoint,
                    timezone=timezone,
                    alg_version=alg_version,
                )
                result["status"] = "success"
                results.append(cast(UploadResult, result))
            except Exception as e:
                results.append(
                    {"status": "error", "file_path": file_path, "error": str(e)}
                )

        return results
