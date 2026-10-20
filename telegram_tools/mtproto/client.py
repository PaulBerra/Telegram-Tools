"""MTProto client (user account) via Telethon.

This is the "advanced mode": it logs in as a real Telegram user account, not a
bot, so it can do what the Bot API forbids - list all members, resolve any
@username to an id, read full history WITHOUT forwarding/spam, and find chats in
common with a user. It needs an api_id / api_hash from https://my.telegram.org
and a one-time interactive login (phone + code, and 2FA password if set).

Configuration is read from arguments or the environment:
    TG_API_ID, TG_API_HASH        developer credentials (my.telegram.org)
    TG_MTPROTO_SESSION            session file path (default ./telegram_tools.session)
    TG_PHONE                      phone number (login only)

Credentials and the session file are the user's; keep the .session out of
version control (it authorizes the account).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

try:
    import telethon.sync  # noqa: F401  (enables blocking calls outside an async loop)
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "MTProto mode needs Telethon. Install it with: pip install telethon"
    ) from exc


class MTProtoError(Exception):
    """Base error for the MTProto layer."""


class NotAuthorizedError(MTProtoError):
    """The session exists but is not logged in - run `login` first."""


@dataclass
class MTProtoConfig:
    api_id: int
    api_hash: str
    session: str = "telegram_tools.session"
    phone: Optional[str] = None

    @classmethod
    def from_env(cls, *, api_id: Optional[int] = None, api_hash: Optional[str] = None,
                 session: Optional[str] = None, phone: Optional[str] = None) -> "MTProtoConfig":
        raw_id = api_id or os.environ.get("TG_API_ID")
        raw_hash = api_hash or os.environ.get("TG_API_HASH")
        if not raw_id or not raw_hash:
            raise MTProtoError(
                "Missing api_id/api_hash. Get them at https://my.telegram.org "
                "and pass --api-id/--api-hash or set TG_API_ID/TG_API_HASH.")
        return cls(
            api_id=int(raw_id),
            api_hash=str(raw_hash),
            session=session or os.environ.get("TG_MTPROTO_SESSION", "telegram_tools.session"),
            phone=phone or os.environ.get("TG_PHONE"),
        )


def build_client(config: MTProtoConfig) -> TelegramClient:
    return TelegramClient(config.session, config.api_id, config.api_hash)


def login(config: MTProtoConfig, *,
          code_cb=input, password_cb=None) -> dict:
    """Interactive one-time login; persists the session file.

    ``code_cb`` is called to obtain the SMS/app code, ``password_cb`` for the
    2FA password. Defaults read from stdin, which suits a terminal.
    """
    import getpass
    client = build_client(config)
    client.connect()
    try:
        if not client.is_user_authorized():
            if not config.phone:
                raise MTProtoError("Set --phone or TG_PHONE to log in.")
            client.send_code_request(config.phone)
            code = code_cb("Enter the code you received: ")
            try:
                client.sign_in(config.phone, code)
            except SessionPasswordNeededError:
                pw = (password_cb or getpass.getpass)("2FA password: ")
                client.sign_in(password=pw)
        me = client.get_me()
        return {"id": me.id, "username": me.username,
                "first_name": me.first_name, "phone": me.phone}
    finally:
        client.disconnect()


@contextmanager
def session(config: MTProtoConfig) -> Iterator[TelegramClient]:
    """Connected, authorized client as a context manager.

    Raises NotAuthorizedError if no valid session exists (run `login` first).
    """
    client = build_client(config)
    client.connect()
    try:
        if not client.is_user_authorized():
            raise NotAuthorizedError(
                f"Session '{config.session}' is not logged in. Run the `login` command first.")
        yield client
    finally:
        client.disconnect()
