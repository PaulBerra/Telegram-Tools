"""High-level Telegram Bot API operations.

Thin, UI-agnostic wrappers over ``TelegramClient.call``. Each returns plain
dict/list results straight from Telegram; formatting and printing belong to the
CLI/GUI, not here. Chat ids may be a numeric id or an ``@username``.

Message-history archiving lives in ``archive.py`` because it carries its own
iteration/IO logic.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Iterator, Optional, Union

from .client import TelegramClient
from .errors import APIError

ChatId = Union[int, str]


# --------------------------------------------------------------------------
# Bot self-profiling (token OSINT, à la "tosint") - all documented Bot API.
# --------------------------------------------------------------------------

def get_me(client: TelegramClient) -> dict:
    return client.call("getMe")


def get_webhook_info(client: TelegramClient) -> dict:
    return client.call("getWebhookInfo")


def get_my_commands(client: TelegramClient) -> list:
    return client.call("getMyCommands")


def get_my_name(client: TelegramClient) -> dict:
    return client.call("getMyName")


def get_my_description(client: TelegramClient) -> dict:
    return client.call("getMyDescription")


def get_my_short_description(client: TelegramClient) -> dict:
    return client.call("getMyShortDescription")


def get_my_default_administrator_rights(client: TelegramClient) -> dict:
    return client.call("getMyDefaultAdministratorRights")


def profile_bot(client: TelegramClient) -> dict:
    """Collect everything a bot token reveals about itself in one shot.

    Each sub-call is isolated: a method the running Bot API build does not
    support (or that is empty) is recorded under ``errors`` instead of
    aborting the whole profile.
    """
    profile: dict[str, Any] = {}
    errors: dict[str, str] = {}
    probes: dict[str, Callable[[TelegramClient], Any]] = {
        "me": get_me,
        "webhook_info": get_webhook_info,
        "my_commands": get_my_commands,
        "my_name": get_my_name,
        "my_short_description": get_my_short_description,
        "my_description": get_my_description,
        "default_administrator_rights": get_my_default_administrator_rights,
    }
    for key, fn in probes.items():
        try:
            profile[key] = fn(client)
        except APIError as exc:
            errors[key] = exc.description
    if errors:
        profile["errors"] = errors
    return profile


# --------------------------------------------------------------------------
# Chat / member inspection.
# --------------------------------------------------------------------------

def get_chat(client: TelegramClient, chat_id: ChatId) -> dict:
    return client.call("getChat", {"chat_id": chat_id})


def get_chat_member_count(client: TelegramClient, chat_id: ChatId) -> int:
    return client.call("getChatMemberCount", {"chat_id": chat_id})


def get_chat_administrators(client: TelegramClient, chat_id: ChatId) -> list:
    return client.call("getChatAdministrators", {"chat_id": chat_id})


def get_chat_member(client: TelegramClient, chat_id: ChatId, user_id: int) -> dict:
    return client.call("getChatMember", {"chat_id": chat_id, "user_id": user_id})


def get_bot_permissions(client: TelegramClient, chat_id: ChatId) -> dict:
    """The bot's own membership record in a chat (status + granted rights)."""
    return get_chat_member(client, chat_id, int(client.bot_id))


def send_message(client: TelegramClient, chat_id: ChatId, text: str, **kwargs) -> dict:
    """Send a text message to a chat as the bot. Returns the sent Message."""
    params = {"chat_id": chat_id, "text": text}
    params.update(kwargs)
    return client.call("sendMessage", params)


def can_send_from(member: dict, chat: dict) -> bool:
    """Whether a membership record allows sending messages in ``chat``.

    Pure: given a getChatMember result and a getChat result, decide if that member
    may post. Group members can send unless restricted; channel members can't
    (only admins with post rights); restricted members follow can_send_messages.
    """
    status = member.get("status")
    ctype = chat.get("type")
    if status == "creator":
        return True
    if status == "administrator":
        if ctype == "channel":
            return bool(member.get("can_post_messages"))
        return True
    if status == "restricted":
        return bool(member.get("can_send_messages"))
    if status == "member":
        if ctype == "channel":
            return False
        perms = chat.get("permissions") or {}
        return perms.get("can_send_messages", True) is not False
    return False   # left, kicked, or unknown


def bot_send_right(client: TelegramClient, chat_id: ChatId) -> bool:
    """Whether the bot may currently send messages to ``chat_id`` (two calls)."""
    member = get_bot_permissions(client, chat_id)
    if member.get("status") == "creator":
        return True
    return can_send_from(member, get_chat(client, chat_id))


def get_user_profile_photos(client: TelegramClient, user_id: int, limit: int = 1) -> dict:
    return client.call("getUserProfilePhotos", {"user_id": user_id, "limit": limit})


def get_file(client: TelegramClient, file_id: str) -> dict:
    return client.call("getFile", {"file_id": file_id})


def file_download_url(client: TelegramClient, file_path: str) -> str:
    return f"{client.base_url}/file/bot{client.token}/{file_path}"


def download_file(client: TelegramClient, file_id: str, dest_dir: str,
                  *, timeout: float = 60.0) -> dict:
    """Download a file the bot can see into ``dest_dir``.

    Returns ``{"path", "size", "sha256", "file_path"}``. The Bot API caps
    downloads at 20 MB; larger files raise APIError from getFile.
    """
    import hashlib
    import requests

    info = get_file(client, file_id)
    file_path = info["file_path"]
    url = file_download_url(client, file_path)
    os.makedirs(dest_dir, exist_ok=True)
    local_name = file_path.replace("/", "_").replace("\\", "_")
    dest = os.path.join(dest_dir, local_name)
    h = hashlib.sha256()
    size = 0
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(8192):
                fh.write(chunk)
                h.update(chunk)
                size += len(chunk)
    return {"path": dest, "size": size, "sha256": h.hexdigest(), "file_path": file_path}


def current_max_message_id(client: TelegramClient, chat_id: ChatId) -> int:
    """Discover the chat's current highest message id, to auto-seed an archive.

    Message ids are sequential, so the id of a message we send *now* is the
    current ceiling. We post a tiny marker and immediately delete it - the only
    reliable Bot API way to learn the ceiling without guessing. Mildly intrusive
    (a message appears for a moment), so callers gate it behind an explicit flag.
    """
    # Telegram trims whitespace/zero-width text, so the marker must be a visible
    # character. It appears for a moment, then we delete it.
    sent = client.call("sendMessage", {"chat_id": chat_id, "text": ".",
                                        "disable_notification": True})
    mid = sent["message_id"]
    try:
        delete_message(client, chat_id, mid)
    except APIError:
        pass  # couldn't delete the marker; the id is still valid
    return mid


# --------------------------------------------------------------------------
# Invite links (replaces the broken add-members: the Bot API has no way to add
# an arbitrary user by id; a link they click is the only path).
# --------------------------------------------------------------------------

def export_chat_invite_link(client: TelegramClient, chat_id: ChatId) -> str:
    """Primary link. NOTE: this revokes the previous primary link."""
    return client.call("exportChatInviteLink", {"chat_id": chat_id})


def create_chat_invite_link(
    client: TelegramClient,
    chat_id: ChatId,
    *,
    name: Optional[str] = None,
    expire_date: Optional[int] = None,
    member_limit: Optional[int] = None,
    creates_join_request: Optional[bool] = None,
) -> dict:
    """Additional named link with options; does not revoke the primary one."""
    return client.call("createChatInviteLink", {
        "chat_id": chat_id,
        "name": name,
        "expire_date": expire_date,
        "member_limit": member_limit,
        "creates_join_request": creates_join_request,
    })


def approve_chat_join_request(client: TelegramClient, chat_id: ChatId, user_id: int) -> bool:
    return client.call("approveChatJoinRequest", {"chat_id": chat_id, "user_id": user_id})


def delete_message(client: TelegramClient, chat_id: ChatId, message_id: int) -> bool:
    """Delete a message the bot can delete (e.g. clean up forwarded test copies).

    Telegram only lets a bot delete its own recent messages, or any message if it
    is an admin with ``can_delete_messages``.
    """
    return client.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})


# --------------------------------------------------------------------------
# Live updates / new-member watch.
# --------------------------------------------------------------------------

def list_known_chats(client: TelegramClient, *, limit: int = 100) -> list[dict]:
    """Chats the bot has recently seen, from getUpdates.

    The Bot API can't list every chat a bot is in; this returns the ones that
    appear in pending updates (recent activity, within ~24h, and only when no
    webhook is set). Each entry is {id, title, type}. Reading updates this way
    does not consume them.
    """
    # No allowed_updates filter: we want every pending update type so we catch
    # as many chats as possible (messages, the bot being added/promoted, etc.).
    updates = client.call("getUpdates", {"limit": limit, "timeout": 0},
                          http_method="GET")
    seen: dict = {}
    for upd in updates or []:
        for obj in upd.values():
            chat = obj.get("chat") if isinstance(obj, dict) else None
            if chat and chat.get("id") is not None:
                seen[chat["id"]] = {
                    "id": chat["id"],
                    "title": (chat.get("title") or chat.get("username")
                              or chat.get("first_name") or chat.get("type")),
                    "type": chat.get("type"),
                }
    return list(seen.values())


def listen_new_users(
    client: TelegramClient,
    chat_id: ChatId,
    *,
    timeout: Optional[int] = 60,
    long_poll: int = 10,
    should_stop: Optional[Callable[[], bool]] = None,
    now: Callable[[], float] = time.monotonic,
) -> Iterator[dict]:
    """Yield each user that joins ``chat_id``.

    Runs for ``timeout`` seconds, or until ``should_stop()`` is True. Pass
    ``timeout=None`` to watch with no time limit (stop via ``should_stop``).
    Yields Telegram ``User`` objects; consumes updates with a moving offset.
    """
    chat_key = str(chat_id)
    offset = 0
    deadline = None if timeout is None else now() + timeout
    while (deadline is None or now() < deadline) and not (should_stop and should_stop()):
        updates = client.call("getUpdates", {
            "offset": offset,
            "timeout": long_poll,
            "allowed_updates": ["message", "chat_member"],
        }, http_method="GET")
        for upd in updates or []:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != chat_key:
                continue
            for user in msg.get("new_chat_members", []) or []:
                yield user
