"""MTProto feature operations - the capabilities the Bot API cannot offer.

Each function takes a connected, authorized Telethon client (see
``client.session``) and returns plain dicts/lists, so the CLI only formats.
Message serialization matches the Bot-API archive NDJSON shape (message_id /
date / text / from), so ``core.intel`` can analyze MTProto history dumps too.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional, Union

from telethon import utils
from telethon.tl import types

Target = Union[int, str]


def _entity_kind(entity: Any) -> str:
    if isinstance(entity, types.User):
        return "bot" if entity.bot else "user"
    if isinstance(entity, types.Chat):
        return "group"
    if isinstance(entity, types.Channel):
        return "channel" if entity.broadcast else "supergroup"
    return type(entity).__name__


def resolve(client, target: Target) -> dict:
    """Resolve a @username / t.me link / phone / id to an entity record."""
    entity = client.get_entity(target)
    out: dict[str, Any] = {
        "id": entity.id,
        "kind": _entity_kind(entity),
        "username": getattr(entity, "username", None),
        "verified": getattr(entity, "verified", None),
        "scam": getattr(entity, "scam", None),
        "fake": getattr(entity, "fake", None),
    }
    if isinstance(entity, types.User):
        out.update(first_name=entity.first_name, last_name=entity.last_name,
                   phone=entity.phone)
    else:
        out.update(title=getattr(entity, "title", None),
                   participants_count=getattr(entity, "participants_count", None))
    return out


def _user_dict(u: Any) -> dict:
    return {
        "id": u.id,
        "username": getattr(u, "username", None),
        "first_name": getattr(u, "first_name", None),
        "last_name": getattr(u, "last_name", None),
        "bot": getattr(u, "bot", None),
        "deleted": getattr(u, "deleted", None),
        "phone": getattr(u, "phone", None),
    }


def members(client, target: Target, *, limit: Optional[int] = None,
            search: str = "") -> list[dict]:
    """Enumerate the members of a group/channel (Bot API cannot do this)."""
    out = []
    for user in client.iter_participants(target, limit=limit, search=search):
        out.append(_user_dict(user))
    return out


def message_to_dict(m: Any) -> dict:
    """Serialize a Telethon message into the archive/intel NDJSON shape."""
    sender_id = getattr(m, "sender_id", None)
    return {
        "message_id": m.id,
        "date": int(m.date.timestamp()) if getattr(m, "date", None) else None,
        "text": m.message or "",
        "from": {"id": sender_id} if sender_id else {},
        "media": bool(getattr(m, "media", None)),
        "views": getattr(m, "views", None),
        "forward": bool(getattr(m, "fwd_from", None)),
    }


def history(client, target: Target, *, limit: int = 200,
            min_id: int = 0, max_id: int = 0, search: str = "") -> Iterator[dict]:
    """Read message history directly - no forwarding, no copies, no spam."""
    for m in client.iter_messages(target, limit=limit, min_id=min_id,
                                  max_id=max_id, search=search or None):
        yield message_to_dict(m)


def common_chats(client, user: Target, *, limit: int = 100) -> list[dict]:
    """Groups/channels in common with a user - powerful for linking an actor."""
    entity = client.get_entity(user)
    out = []
    for chat in client.get_common_chats(entity):
        out.append({
            "id": chat.id,
            "kind": _entity_kind(chat),
            "title": getattr(chat, "title", None),
            "username": getattr(chat, "username", None),
        })
        if len(out) >= limit:
            break
    return out


def dialogs(client, *, limit: int = 100) -> list[dict]:
    """List the chats the logged-in account is part of."""
    out = []
    for d in client.iter_dialogs(limit=limit):
        out.append({
            "id": utils.get_peer_id(d.entity),
            "kind": _entity_kind(d.entity),
            "name": d.name,
            "username": getattr(d.entity, "username", None),
            "unread": d.unread_count,
        })
    return out
