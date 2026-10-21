"""Local data the app keeps between launches, in ~/.telegram_tools.

Three things:
  - tokens:   the bots you've connected, so they come back in a dropdown.
  - chats:    every chat each bot has seen (so the picker never forgets one).
  - messages: a passive archive - every message a bot receives live is appended
              here, so you build an archive just by leaving the app running,
              without forwarding anything.
"""

from __future__ import annotations

import json
import os
import time

DIR = os.path.join(os.path.expanduser("~"), ".telegram_tools")
_CHATS = os.path.join(DIR, "known_chats.json")
_TOKENS = os.path.join(DIR, "tokens.json")
_MSG_DIR = os.path.join(DIR, "messages")
_SETTINGS = os.path.join(DIR, "settings.json")
_BACKFILL = os.path.join(DIR, "backfill.json")
_GRAPH_STYLE = os.path.join(DIR, "graph_style.json")


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


# --- known chats (per bot) ---
def load_chats(bot_id) -> dict:
    return _read(_CHATS, {}).get(str(bot_id), {})


def save_chats(bot_id, chats: dict) -> None:
    data = _read(_CHATS, {})
    data[str(bot_id)] = chats
    _write(_CHATS, data)


# Back-compat aliases.
load = load_chats
save = save_chats


# --- tokens (saved bots) ---
def load_tokens() -> dict:
    """{bot_id(str): {"token":..., "username":...}}"""
    return _read(_TOKENS, {})


def save_token(bot_id, token: str, username: str) -> None:
    data = _read(_TOKENS, {})
    data[str(bot_id)] = {"token": token, "username": username}
    _write(_TOKENS, data)


# --- permanent removal (used by Settings -> Manage bots) ---
def delete_chat_messages(bot_id, chat_id) -> None:
    """Rewrite a bot's message log without one chat's lines."""
    path = messages_path(bot_id)
    if not os.path.exists(path):
        return
    try:
        kept = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if not s:
                    continue
                try:
                    m = json.loads(s)
                except ValueError:
                    continue
                if str(m.get("chat_id")) != str(chat_id):
                    kept.append(s)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(kept) + ("\n" if kept else ""))
    except OSError:
        pass


def delete_chat_fully(bot_id, chat_id) -> None:
    """Forget a chat for good: its entry, its collected messages, its progress."""
    data = _read(_CHATS, {})
    per = data.get(str(bot_id))
    if per and str(chat_id) in per:
        per.pop(str(chat_id), None)
        _write(_CHATS, data)
    bf = _read(_BACKFILL, {})
    if str(bot_id) in bf:
        bf[str(bot_id)].pop(str(chat_id), None)
        _write(_BACKFILL, bf)
    delete_chat_messages(bot_id, chat_id)


def delete_bot(bot_id) -> None:
    """Forget a bot for good: token, chats, progress and the whole message log."""
    for path, key in ((_TOKENS, str(bot_id)), (_CHATS, str(bot_id)), (_BACKFILL, str(bot_id))):
        data = _read(path, {})
        if key in data:
            data.pop(key, None)
            _write(path, data)
    try:
        os.remove(messages_path(bot_id))
    except OSError:
        pass


# --- collected messages (passive archive, per bot, NDJSON) ---
def messages_path(bot_id) -> str:
    return os.path.join(_MSG_DIR, f"{bot_id}.ndjson")


def append_messages(bot_id, rows: list) -> None:
    if not rows:
        return
    path = messages_path(bot_id)
    try:
        os.makedirs(_MSG_DIR, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError:
        pass


def collected_count(bot_id) -> int:
    try:
        with open(messages_path(bot_id), encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


# --- settings (user-tunable knobs, one small file) ---
DEFAULT_SETTINGS = {
    "theme": "light",            # "light" | "dark"
    "font_size": 13,             # base UI font size (px)
    "backfill_pace": 3.2,        # seconds between forwards when walking the past
    "max_backfills": 3,          # chats walked backwards at once (viewed one included)
    "max_gap": 400,              # give up after this many missing ids in a row
    "conversation_limit": 500,   # messages kept on screen in the timeline
    "logs_open": False,          # show the log drawer on launch
    "graph_sources": [],         # bot ids whose data feeds the graph (empty = none)
}


def load_settings() -> dict:
    data = _read(_SETTINGS, {})
    out = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        for k, v in data.items():
            if k in DEFAULT_SETTINGS and isinstance(v, type(DEFAULT_SETTINGS[k])):
                out[k] = v
    return out


def save_settings(settings: dict) -> None:
    _write(_SETTINGS, {k: settings.get(k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS})


# --- graph node styling / reclassification (persists what the user customises) ---
def load_graph_style() -> dict:
    """{node_key: {"color":.., "size":.., "label":.., "layer":..}} - any subset."""
    data = _read(_GRAPH_STYLE, {})
    return data if isinstance(data, dict) else {}


def save_graph_style(data: dict) -> None:
    _write(_GRAPH_STYLE, data)


# --- backfill progress: how far back we've walked each chat, per bot ---
def load_backfill(bot_id) -> dict:
    """{chat_id(str): {"lowest": id, "max_seen": id, "done": bool, "updated": ts}}"""
    return _read(_BACKFILL, {}).get(str(bot_id), {})


def backfill_record(bot_id, chat_id) -> dict:
    return load_backfill(bot_id).get(str(chat_id), {})


def migrate_backfill(bot_id, old_chat, new_chat) -> None:
    data = _read(_BACKFILL, {})
    per = data.get(str(bot_id))
    if per and str(old_chat) in per:
        per[str(new_chat)] = per.pop(str(old_chat))
        _write(_BACKFILL, data)


def migrate_chat_id(bot_id, old_chat, new_chat) -> None:
    """Rewrite a bot's message log, moving one chat's messages to a new id
    (group -> supergroup upgrade changes the id)."""
    path = messages_path(bot_id)
    if not os.path.exists(path):
        return
    try:
        out = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if not s:
                    continue
                try:
                    m = json.loads(s)
                except ValueError:
                    continue
                if str(m.get("chat_id")) == str(old_chat):
                    m["chat_id"] = new_chat
                out.append(json.dumps(m, ensure_ascii=False))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + ("\n" if out else ""))
    except OSError:
        pass


def update_backfill(bot_id, chat_id, *, lowest=None, max_seen=None, done=None) -> None:
    data = _read(_BACKFILL, {})
    per = data.setdefault(str(bot_id), {})
    rec = per.setdefault(str(chat_id), {})
    if lowest is not None:
        rec["lowest"] = min(lowest, rec["lowest"]) if "lowest" in rec else lowest
    if max_seen is not None:
        rec["max_seen"] = max(max_seen, rec.get("max_seen", 0))
    if done is not None:
        rec["done"] = bool(done)
    rec["updated"] = int(time.time())
    _write(_BACKFILL, data)


def message_bots() -> list:
    """Bot ids that have a collected-message log on disk."""
    try:
        return [fn[:-len(".ndjson")] for fn in os.listdir(_MSG_DIR) if fn.endswith(".ndjson")]
    except OSError:
        return []


def load_all_messages(bot_id) -> list:
    """Every message collected for a bot, across all its chats (no de-dup)."""
    out = []
    try:
        with open(messages_path(bot_id), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out


def all_sources() -> list:
    """(bot_id, messages) for every bot - feed straight to core.graph.build_graph."""
    return [(bid, load_all_messages(bid)) for bid in message_bots()]


def load_messages_for(bot_id, chat_id) -> list:
    """Collected messages of one chat, de-duplicated by id and sorted oldest->newest."""
    by_id: dict = {}
    try:
        with open(messages_path(bot_id), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if str(m.get("chat_id")) == str(chat_id) and m.get("message_id") is not None:
                    by_id[m["message_id"]] = m
    except OSError:
        return []
    return [by_id[k] for k in sorted(by_id)]
