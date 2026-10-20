#!/usr/bin/env python3
"""Discover the env values the live tests need, from a bot token alone.

Run it, then (while it waits) send a message in your test group and/or add the
bot. It reads getUpdates and prints the chat ids, a recent message id, and the
new members it sees - ready to paste as TG_TEST_CHAT / TG_TEST_MSG_ID.

    TG_TEST_TOKEN=123:abc python tests/live_setup.py

Note: getUpdates only works when the bot has no webhook set. If a webhook is
configured, this prints a hint to delete it.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_tools.core import TelegramClient, api


def main() -> int:
    token = os.environ.get("TG_TEST_TOKEN") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not token:
        print("Set TG_TEST_TOKEN or pass the token as an argument.")
        return 2
    client = TelegramClient(token)

    me = api.get_me(client)
    print(f"Bot: @{me.get('username')} (id {me.get('id')})")

    wh = api.get_webhook_info(client)
    if wh.get("url"):
        print(f"[!] A webhook is set ({wh['url']}). getUpdates is disabled while a "
              f"webhook exists. Delete it with deleteWebhook, then rerun.")
        return 1

    print("Listening ~20s. Now: send a message in your test group (and add the bot).")
    seen_chats: dict = {}
    deadline = time.time() + 20
    offset = 0
    while time.time() < deadline:
        updates = client.call("getUpdates", {"offset": offset, "timeout": 5},
                              http_method="GET")
        for upd in updates or []:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat = msg.get("chat") or {}
            if chat.get("id") is not None:
                info = seen_chats.setdefault(chat["id"], {
                    "title": chat.get("title") or chat.get("username") or chat.get("type"),
                    "type": chat.get("type"),
                    "max_msg_id": 0,
                    "new_members": [],
                })
                info["max_msg_id"] = max(info["max_msg_id"], msg.get("message_id", 0))
                for u in msg.get("new_chat_members", []) or []:
                    info["new_members"].append((u.get("id"), u.get("username")))

    if not seen_chats:
        print("\nNo updates captured. Send a message in the group while this runs,")
        print("and make sure the bot is a member (and privacy mode off for groups).")
        return 1

    print("\n=== Discovered - paste into your environment ===")
    for cid, info in seen_chats.items():
        print(f"\nChat: {info['title']} ({info['type']})")
        print(f"  TG_TEST_CHAT={cid}")
        if info["max_msg_id"]:
            print(f"  TG_TEST_MSG_ID={info['max_msg_id']}   "
                  f"(a recent message; point at an older id to prove the hack)")
        for uid, uname in info["new_members"]:
            print(f"  (new member seen) TG_TEST_USER={uid}  @{uname}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
