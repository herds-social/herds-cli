"""
Shared fixtures for unit tests.
"""

from unittest.mock import MagicMock

import pytest

from herds_cli.api import APIClient
from herds_cli.core.config import Config
from herds_cli.sessions import SessionManager


@pytest.fixture
def tmp_config_file(tmp_path):
    """Returns a path for a temporary config JSON file."""
    return tmp_path / "config.json"


@pytest.fixture
def mock_session_manager(tmp_path):
    """Real SessionManager pointed at a temp directory."""
    return SessionManager(base_dir=str(tmp_path))


@pytest.fixture
def mock_api_client(mock_session_manager):
    """APIClient with its HTTP session replaced by a MagicMock."""
    client = APIClient(
        base_url="http://localhost:8000",
        session_manager=mock_session_manager,
        timeout=5,
    )
    client.session = MagicMock()
    return client
