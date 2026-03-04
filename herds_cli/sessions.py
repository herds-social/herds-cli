"""
Herds CLI Session Management Module

Manages user sessions with email-based filenames for secure local storage.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from rich.console import Console

# Initialize rich console for beautiful output
console = Console()


HERDS_DIR = Path.home() / ".herds"


class SessionManager:
    """Manages user sessions with email-based filenames."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir) if base_dir else HERDS_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def sanitize_email(self, email: str) -> str:
        """Convert email to filesystem-safe filename.

        user@example.com → user_at_example_com
        john.doe+test@domain.co.uk → john_doe_plus_test_at_domain_co_uk
        """
        # Replace @ with _at_
        sanitized = email.replace("@", "_at_")
        # Replace + with _plus_
        sanitized = sanitized.replace("+", "_plus_")
        # Replace dots with underscores
        sanitized = sanitized.replace(".", "_")
        # Replace any remaining special characters with underscores
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", sanitized)
        return sanitized

    def get_session_filename(self, email: str) -> Path:
        """Get the session filename for a given email."""
        sanitized = self.sanitize_email(email)
        return self.base_dir / f"herds_session_{sanitized}"

    def save_session(self, email: str, session_data: Dict[str, Any]) -> str:
        """Save session data to file."""
        filename = self.get_session_filename(email)

        session_data.update(
            {
                "email": email,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "session_filename": filename.name,
            }
        )

        try:
            with open(filename, "w") as f:
                json.dump(session_data, f, indent=2)

            # Set restrictive permissions (owner read/write only)
            os.chmod(filename, 0o600)

            return filename.name
        except Exception as e:
            raise Exception(f"Failed to save session: {e}")

    def load_session(self, email: str) -> Optional[Dict[str, Any]]:
        """Load session data for a specific email."""
        filename = self.get_session_filename(email)

        if not filename.exists():
            return None

        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception as e:
            console.print(
                f"[yellow]Warning: Failed to load session {filename}: {e}[/yellow]"
            )
            return None

    def delete_session(self, email: str) -> bool:
        """Delete session file for a specific email."""
        filename = self.get_session_filename(email)

        if filename.exists():
            try:
                filename.unlink()
                return True
            except Exception as e:
                console.print(f"[red]Error deleting session {filename}: {e}[/red]")
                return False
        return False

    def list_sessions(self) -> list:
        """List all available session files."""
        sessions = []
        for file_path in self.base_dir.glob("herds_session_*"):
            try:
                with open(file_path, "r") as f:
                    session_data = json.load(f)
                    sessions.append(
                        {
                            "filename": file_path.name,
                            "email": session_data.get("email", "unknown"),
                            "created_at": session_data.get("created_at", "unknown"),
                        }
                    )
            except Exception:
                # Skip corrupted session files
                continue

        return sessions
