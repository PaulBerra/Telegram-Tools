"""Core layer: UI-agnostic Telegram Bot API operations shared by CLI and GUI.

Nothing here prints or exits; functions return data or raise a TelegramError.
"""

from __future__ import annotations

from . import api, archive, graph, intel, rights_check
from .archive import ArchiveProgress, archive_messages
from .client import TelegramClient
from .errors import APIError, NetworkError, RateLimited, TelegramError

__all__ = [
    "api",
    "archive",
    "graph",
    "intel",
    "rights_check",
    "TelegramClient",
    "TelegramError",
    "APIError",
    "NetworkError",
    "RateLimited",
    "archive_messages",
    "ArchiveProgress",
]
