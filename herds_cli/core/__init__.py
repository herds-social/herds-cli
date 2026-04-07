"""
Core functionality for the Herds CLI.

This module contains shared base classes, configuration management,
and utilities used across all command modules.
"""

from .base import CommandBase, APIResponseHandler, EventCommandBase, ImageCommandBase, HerdsContext
from .config import Config
from .exceptions import (
    AmbiguousSessionError,
    APIRequestError,
    AuthenticationError,
    HerdsError,
    NoSessionsError,
    SessionNotFoundError,
    UserIdNotFoundError,
)

__all__ = [
    "CommandBase",
    "APIResponseHandler",
    "EventCommandBase",
    "ImageCommandBase",
    "HerdsContext",
    "Config",
    "AmbiguousSessionError",
    "APIRequestError",
    "AuthenticationError",
    "HerdsError",
    "NoSessionsError",
    "SessionNotFoundError",
    "UserIdNotFoundError",
]
