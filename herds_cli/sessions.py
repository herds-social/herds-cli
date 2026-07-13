"""
Herds CLI Session Management Module

Manages user sessions with email-based filenames for secure local storage.

Session files live in the XDG state directory (``~/.local/state/herds/`` by
default); see herds_cli.paths.state_dir.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from herds_cli import paths
from herds_cli.types import SessionData, SessionListEntry

from rich.console import Console

# Diagnostic output goes to stderr so stdout stays clean for command data.
console = Console(stderr=True)


class SessionManager:
    """Manages user sessions as JSON files in the XDG state dir (or custom base_dir).

    Files are named herds_session_{sanitized_email} where:
        @ → _at_,  + → _plus_,  . → _

    Permissions are set to 0600 (owner read/write only) for security.

    Each session file contains auth credentials (cookies or Bearer tokens),
    user data, base_url, client_type ("web" or "mobile"), and metadata
    (email, created_at, session_filename).
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir) if base_dir else paths.state_dir()
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

    def save_session(self, email: str, session_data: SessionData) -> str:
        """Save session data to file.

        Creates a copy of session_data before adding metadata fields,
        so the caller's dict is never mutated.
        """
        filename = self.get_session_filename(email)

        enriched: SessionData = {
            **session_data,
            "email": email,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "session_filename": filename.name,
        }

        try:
            with open(filename, "w") as f:
                json.dump(enriched, f, indent=2)

            # Set restrictive permissions (owner read/write only)
            os.chmod(filename, 0o600)

            return filename.name
        except Exception as e:
            raise Exception(f"Failed to save session: {e}")

    # Keys that must be present for a session file to be considered valid.
    _REQUIRED_KEYS = {"client_type", "email"}

    def load_session(self, email: str) -> Optional[SessionData]:
        """Load session data for a specific email.

        Returns None if the file is missing, unreadable, or lacks the
        required keys (client_type, email).
        """
        filename = self.get_session_filename(email)

        if not filename.exists():
            return None

        try:
            with open(filename, "r") as f:
                data = json.load(f)
        except Exception as e:
            console.print(
                f"[yellow]Warning: Failed to load session {filename}: {e}[/yellow]"
            )
            return None

        missing = self._REQUIRED_KEYS - data.keys()
        if missing:
            console.print(
                f"[yellow]Warning: Session {filename} missing required keys: "
                f"{', '.join(sorted(missing))}[/yellow]"
            )
            return None

        return data

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

    def list_sessions(self) -> List[SessionListEntry]:
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
