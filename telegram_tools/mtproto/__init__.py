"""MTProto advanced mode (user account via Telethon).

Features impossible on the Bot API: full member enumeration, username->id
resolution, full history without forwarding, and chats in common with a user.
Needs api_id/api_hash from https://my.telegram.org and a one-time login.
"""

from __future__ import annotations

from .client import MTProtoConfig, MTProtoError, NotAuthorizedError, login, session

__all__ = ["MTProtoConfig", "MTProtoError", "NotAuthorizedError", "login", "session"]
