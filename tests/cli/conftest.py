"""
Shared fixtures for CLI tests.

Provides pre-built mock dependencies that can be injected into Click's
CliRunner via the obj= parameter, bypassing all config loading and
real HTTP/IO in the cli() group handler.
"""

import re
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from herds_cli.api import APIClient
from herds_cli.core.config import Config
from herds_cli.images import ImageUploader
from herds_cli.output import OutputFormatter
from herds_cli.sessions import SessionManager

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from Rich-formatted output."""
    return _ANSI_RE.sub("", text)


@pytest.fixture
def mock_config():
    """Config with test defaults — no file I/O."""
    return Config(
        api_url="http://localhost:8000",
        api_timeout=5,
        output_format="json",
        verbose=False,
        debug_requests=False,
        timezone="America/New_York",
    )


@pytest.fixture
def mock_session_manager(tmp_path):
    """Real SessionManager pointed at a temp directory."""
    return SessionManager(base_dir=str(tmp_path))


@pytest.fixture
def mock_api_client(mock_session_manager):
    """Real APIClient with its HTTP session replaced by a MagicMock."""
    client = APIClient(
        base_url="http://localhost:8000",
        session_manager=mock_session_manager,
        timeout=5,
    )
    client.session = MagicMock()
    return client


@pytest.fixture
def mock_image_uploader(mock_api_client, mock_session_manager):
    """ImageUploader wired to the mocked api_client + session_manager."""
    return ImageUploader(
        api_client=mock_api_client,
        session_manager=mock_session_manager,
    )


@pytest.fixture
def cli_obj(mock_config, mock_session_manager, mock_api_client, mock_image_uploader):
    """Pre-populated ctx.obj dict matching what cli() builds in production."""
    return {
        "_initialized": True,
        "config": mock_config,
        "session_manager": mock_session_manager,
        "api_client": mock_api_client,
        "image_uploader": mock_image_uploader,
        "output_formatter": OutputFormatter(),
        "timezone": mock_config.timezone,
        "format": mock_config.output_format,
        "base_url": mock_config.api_url,
    }


@pytest.fixture
def cli_runner():
    return CliRunner()
