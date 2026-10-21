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


def _status_text(status: Any) -> Optional[str]:
    """Human-readable 'last seen' from a User.status (privacy-dependent; may be
    hidden). Uses the type name so we don't import every status class."""
    if status is None:
        return None
    name = type(status).__name__
    mapping = {
        "UserStatusOnline": "online now",
        "UserStatusRecently": "last seen recently",
        "UserStatusLastWeek": "last seen within a week",
        "UserStatusLastMonth": "last seen within a month",
    }
    if name in mapping:
        return mapping[name]
    if name == "UserStatusOffline":
        was = getattr(status, "was_online", None)
        return f"last seen {was:%Y-%m-%d %H:%M UTC}" if was else "offline"
    return name


def full_profile(client, target: Target) -> dict:
    """Deeper profile than ``resolve``: bio, last-seen, premium/restricted/deleted,
    Telegram's own common-chats count, and story/photo presence. User account only
    (uses users.GetFullUser plus the User object). Every piece is best-effort:
    privacy settings can hide most of it, so missing keys are normal."""
    from telethon.tl import functions
    entity = client.get_entity(target)
    out: dict[str, Any] = {
        "id": getattr(entity, "id", None),
        "premium": getattr(entity, "premium", None),
        "restricted": getattr(entity, "restricted", None),
        "deleted": getattr(entity, "deleted", None),
        "bot": getattr(entity, "bot", None),
        "last_seen": _status_text(getattr(entity, "status", None)),
    }
    rr = getattr(entity, "restriction_reason", None)
    if rr:
        out["restriction_reason"] = "; ".join(
            f"{getattr(r, 'platform', '?')}:{getattr(r, 'reason', '?')}" for r in rr)
    try:
        full = client(functions.users.GetFullUserRequest(entity))
        fu = getattr(full, "full_user", None)
        if fu is not None:
            out["about"] = getattr(fu, "about", None)
            out["common_chats_count"] = getattr(fu, "common_chats_count", None)
            out["blocked"] = getattr(fu, "blocked", None)
            out["has_stories"] = bool(getattr(fu, "stories_pinned_available", None))
    except Exception:
        pass
    try:
        photos = client.get_profile_photos(entity, limit=1)
        out["photo_count"] = getattr(photos, "total", None)
    except Exception:
        pass
    return out


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
    """Groups/channels in common with a user - powerful for linking an actor.

    Telethon has no high-level helper (get_common_chats is a Pyrogram method),
    so this calls the raw messages.getCommonChats. Only a user account may call
    it - not a bot - which is exactly MTProto mode.
    """
    from telethon import utils
    from telethon.tl import functions
    entity = client.get_entity(user)
    result = client(functions.messages.GetCommonChatsRequest(
        user_id=utils.get_input_user(entity), max_id=0, limit=limit))
    out = []
    for chat in getattr(result, "chats", []):
        out.append({
            "id": chat.id,
            "kind": _entity_kind(chat),
            "title": getattr(chat, "title", None),
            "username": getattr(chat, "username", None),
        })
        if len(out) >= limit:
            break
    return out


def _media_label(m: Any) -> Optional[str]:
    """A short tag for a media message with no text, e.g. 'photo', 'sticker'."""
    for attr in ("photo", "video", "voice", "video_note", "gif", "sticker",
                 "audio", "document", "contact", "geo", "poll", "dice"):
        if getattr(m, attr, None):
            return attr.replace("_", " ")
    return "media" if getattr(m, "media", None) else None


def _richtext_plain(rt: Any) -> str:
    """Flatten a Telegram RichText tree (bold/italic/concat/...) to plain text."""
    if rt is None:
        return ""
    if isinstance(rt, str):
        return rt
    t = getattr(rt, "text", None)
    if isinstance(t, str):
        return t
    if t is not None:
        return _richtext_plain(t)
    texts = getattr(rt, "texts", None)
    if texts:
        return "".join(_richtext_plain(x) for x in texts)
    return ""


def _rich_message_text(rich: Any, limit: int = 300) -> str:
    """Pull readable text from a RichMessage's page blocks (headings, paragraphs,
    captions). Dividers/tables/buttons carry none; we take whatever is there."""
    parts = []
    for b in getattr(rich, "blocks", None) or []:
        for attr in ("title", "subtitle", "header", "text", "caption"):
            s = _richtext_plain(getattr(b, attr, None)).strip()
            if s:
                parts.append(s)
    return " ".join(" ".join(parts).split())[:limit]   # collapse whitespace, cap


def _message_text(m: Any) -> str:
    """Best readable text for a message: its text, else a media tag, else the text
    of a forwarded rich/instant-view post (what many users actually post), else a
    '[forwarded post]' marker. Empty only when there is genuinely nothing to show."""
    t = (getattr(m, "message", None) or "").strip()
    if t:
        return t
    fwd = bool(getattr(m, "fwd_from", None))
    rich = getattr(m, "rich_message", None)
    if rich is not None:
        rt = _rich_message_text(rich)
        if rt:
            return ("↪ " + rt) if fwd else rt
    lbl = _media_label(m)
    if lbl:
        return ("↪ " if fwd else "") + f"[{lbl}]"
    if fwd:
        return "[forwarded post]"
    return ""


def download_profile_photo(client, user: Target, dest_dir: str) -> Optional[str]:
    """Download the user's current profile photo into ``dest_dir``. Returns the
    local path, or None if they have no photo / it's hidden by privacy."""
    import os
    entity = client.get_entity(user)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{getattr(entity, 'id', 'photo')}.jpg")
    return client.download_profile_photo(entity, file=dest)


def common_chats_with_messages(client, user: Target, *, limit: int = 200,
                               msg_groups: int = 8, msg_limit: int = 25) -> list[dict]:
    """Groups in common with a user AND, for the first ``msg_groups`` of them, that
    user's own recent messages there - read through YOUR account, no bot, no
    forward. This is the pivot: what the target actually said, and where. Each
    group dict carries a ``messages`` list (possibly empty: privacy, or none sent)."""
    from telethon.tl import functions
    entity = client.get_entity(user)
    result = client(functions.messages.GetCommonChatsRequest(
        user_id=utils.get_input_user(entity), max_id=0, limit=limit))
    out: list[dict] = []
    for i, chat in enumerate(getattr(result, "chats", [])):
        info = {
            "id": chat.id,
            "kind": _entity_kind(chat),
            "title": getattr(chat, "title", None),
            "username": getattr(chat, "username", None),
            "messages": [],
        }
        if i < msg_groups:
            try:
                for m in client.iter_messages(chat, from_user=entity, limit=msg_limit):
                    text = _message_text(m)   # text / media tag / forwarded-rich text
                    if text:
                        info["messages"].append({
                            "message_id": m.id,
                            "date": int(m.date.timestamp()) if getattr(m, "date", None) else None,
                            "text": text,
                            "media": bool(getattr(m, "media", None)),
                        })
            except Exception as exc:
                info["error"] = str(exc)   # surfaced to the UI, not swallowed
        out.append(info)
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
