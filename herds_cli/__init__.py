"""
Herds CLI Package

A unified command-line interface for Herds API operations including
user management and image uploads with session-based authentication.
"""

__version__ = "4.2.0"
__author__ = "Herds Team"
__description__ = "Unified CLI for Herds API operations"

from .api import APIClient
from .sessions import SessionManager
from .images import ImageUploader
from .output import OutputFormatter

__all__ = [
    "APIClient",
    "SessionManager",
    "ImageUploader",
    "OutputFormatter",
]
