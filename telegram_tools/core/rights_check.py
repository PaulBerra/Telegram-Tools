"""Actually try each bot right, instead of only reading the flags.

getChatMember tells you what Telegram *says* the bot can do. These probes do the
real thing and undo it, so you learn what actually works.

Careful: some probes leave a trace that can't be wiped. Changing the title or the
auto-delete timer drops a service line in the chat that stays even after you put
the value back. So probes are split in two:

  - non-invasive: send a message then delete it, make an invite link then revoke
    it. Nothing permanent is left behind.
  - invasive: change the title and restore it, pin then unpin. The action is
    reverted but a service message remains.

The UI ticks only the non-invasive ones by default; the invasive ones are opt-in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Union

from .client import TelegramClient
from .errors import APIError

ChatId = Union[int, str]


@dataclass
class ProbeResult:
    key: str
    label: str
    invasive: bool
    ok: Optional[bool]      # True works, False denied/failed, None not run
    detail: str


def _probe_post_delete(client, chat, label, invasive):
    # Posts a tiny dot and removes it right away. Tests "can post" + "can delete".
    try:
        sent = client.call("sendMessage", {"chat_id": chat, "text": ".",
                                            "disable_notification": True})
        client.call("deleteMessage", {"chat_id": chat, "message_id": sent["message_id"]})
        return ProbeResult("post_delete", label, invasive, True, "posted and deleted a message")
    except APIError as exc:
        return ProbeResult("post_delete", label, invasive, False, exc.description)


def _probe_invite(client, chat, label, invasive):
    # Makes a one-use link then revokes it. Nothing shows up in the chat.
    try:
        link = client.call("createChatInviteLink", {"chat_id": chat,
                                                     "name": "rights-check", "member_limit": 1})
        client.call("revokeChatInviteLink", {"chat_id": chat, "invite_link": link["invite_link"]})
        return ProbeResult("invite", label, invasive, True, "created and revoked an invite link")
    except APIError as exc:
        return ProbeResult("invite", label, invasive, False, exc.description)


def _probe_change_info(client, chat, label, invasive):
    # Nudges the title and puts it back. Heads up: this leaves a service line.
    try:
        info = client.call("getChat", {"chat_id": chat})
        title = info.get("title")
        if not title:
            return ProbeResult("change_info", label, invasive, None, "no title to test (not a group)")
        client.call("setChatTitle", {"chat_id": chat, "title": title + " "})
        client.call("setChatTitle", {"chat_id": chat, "title": title})
        return ProbeResult("change_info", label, invasive, True,
                           "changed the title and restored it (left a service message)")
    except APIError as exc:
        return ProbeResult("change_info", label, invasive, False, exc.description)


def _probe_pin(client, chat, label, invasive):
    # Pins a throwaway message then unpins and deletes it. May leave a notice.
    sent = None
    try:
        sent = client.call("sendMessage", {"chat_id": chat, "text": "rights-check",
                                           "disable_notification": True})
        client.call("pinChatMessage", {"chat_id": chat, "message_id": sent["message_id"],
                                       "disable_notification": True})
        client.call("unpinChatMessage", {"chat_id": chat, "message_id": sent["message_id"]})
        return ProbeResult("pin", label, invasive, True, "pinned and unpinned a message")
    except APIError as exc:
        return ProbeResult("pin", label, invasive, False, exc.description)
    finally:
        if sent:
            try:
                client.call("deleteMessage", {"chat_id": chat, "message_id": sent["message_id"]})
            except APIError:
                pass


# key -> (label, invasive, fn). Order is the display order.
PROBES: list[tuple[str, str, bool, Callable]] = [
    ("post_delete", "Post then delete a message", False, _probe_post_delete),
    ("invite", "Create then revoke an invite link", False, _probe_invite),
    ("change_info", "Change then restore the title", True, _probe_change_info),
    ("pin", "Pin then unpin a message", True, _probe_pin),
]

DEFAULT_KEYS = [key for key, _, invasive, _ in PROBES if not invasive]


def run_probes(client: TelegramClient, chat: ChatId, keys) -> list[ProbeResult]:
    """Run the probes whose key is in ``keys`` and return their results."""
    wanted = set(keys)
    out = []
    for key, label, invasive, fn in PROBES:
        if key in wanted:
            out.append(fn(client, chat, label, invasive))
    return out
