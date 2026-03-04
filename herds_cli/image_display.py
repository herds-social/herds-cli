"""
Image Display Module for Herds CLI

Handles displaying images inline in iTerm2 terminal using the iTerm2 inline image protocol.
"""

import base64
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional


class ImageDisplay:
    """Handles displaying images in the terminal."""

    @staticmethod
    def is_iterm2() -> bool:
        """Check if the terminal is iTerm2.

        Returns:
            bool: True if running in iTerm2, False otherwise
        """
        term_program = os.environ.get("TERM_PROGRAM", "")
        return term_program == "iTerm.app"

    @staticmethod
    def display_in_iterm(image_bytes: bytes, width: str = "auto") -> None:
        """Display an image inline in iTerm2 terminal.

        Uses the iTerm2 inline image protocol to display images directly in the terminal.
        If not running in iTerm2, saves the image to a temporary file and prints the path.

        Args:
            image_bytes: The raw image data as bytes
            width: Display width specification (e.g., '800px', '50%', 'auto')

        Raises:
            ValueError: If image_bytes is empty
        """
        if not image_bytes:
            raise ValueError("Image bytes cannot be empty")

        if not ImageDisplay.is_iterm2():
            # Fallback: save to temp file and print path
            ImageDisplay._save_to_temp_file(image_bytes)
            return

        # Encode image to base64
        encoded = base64.b64encode(image_bytes).decode("ascii")

        # Build iTerm2 inline image escape sequence
        # Format: \033]1337;File=inline=1;width=<width>;height=auto:<base64_data>\007
        escape_sequence = (
            f"\033]1337;File=inline=1;width={width};height=auto:{encoded}\007"
        )

        # Write to stdout
        sys.stdout.write(escape_sequence)
        sys.stdout.write("\n")
        sys.stdout.flush()

    @staticmethod
    def _save_to_temp_file(image_bytes: bytes) -> None:
        """Save image to a temporary file as a fallback when not in iTerm2.

        Args:
            image_bytes: The raw image data as bytes
        """
        # Create a temporary file that won't be auto-deleted
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            tmp_file.write(image_bytes)
            tmp_path = tmp_file.name

        print(f"Not running in iTerm2. Image saved to: {tmp_path}")
        print(f"To view: open {tmp_path}")

    @staticmethod
    def save_image(image_bytes: bytes, output_path: str) -> None:
        """Save image bytes to a file.

        Args:
            image_bytes: The raw image data as bytes
            output_path: Path where the image should be saved

        Raises:
            ValueError: If image_bytes is empty
            IOError: If the file cannot be written
        """
        if not image_bytes:
            raise ValueError("Image bytes cannot be empty")

        output_file = Path(output_path)

        # Create parent directories if they don't exist
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Write the image file
        with open(output_file, "wb") as f:
            f.write(image_bytes)

        print(f"Image saved to: {output_path}")
