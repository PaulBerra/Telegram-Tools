"""Offline tests: a group->supergroup upgrade changes the chat id; the client
must follow the new id (parameters.migrate_to_chat_id) so calls still succeed."""

import json

from telegram_tools.core.client import TelegramClient


class _Resp:
    def __init__(self, data):
        self._d, self.status_code, self.text = data, 200, ""

    def json(self):
        return self._d


class _Session:
    """Returns the migration 400 for the old id, success for the new one."""
    def __init__(self, old, new):
        self.old, self.new, self.calls = old, new, []

    def post(self, url, json=None, timeout=None):
        self.calls.append(dict(json))
        if json.get("chat_id") == self.old:
            return _Resp({"ok": False, "error_code": 400,
                          "description": "Bad Request: group chat was upgraded to a supergroup chat",
                          "parameters": {"migrate_to_chat_id": self.new}})
        return _Resp({"ok": True, "result": {"message_id": 9, "chat_id": json["chat_id"]}})

    def get(self, *a, **k):
        return self.post(*a, **k)


def test_client_follows_group_to_supergroup_upgrade():
    seen = {}
    sess = _Session(-123, -1001999)
    c = TelegramClient("1:a", session=sess, on_migrate=lambda o, n: seen.update(old=o, new=n))
    res = c.call("sendMessage", {"chat_id": -123, "text": "hi"})
    assert res["chat_id"] == -1001999                 # call succeeded on the new id
    assert seen == {"old": -123, "new": -1001999}     # app was told to move state
    assert sess.calls[-1]["chat_id"] == -1001999      # it retried with the new id


def test_forward_hack_follows_upgrade_on_both_ids():
    # forwardMessage uses from_chat_id == chat_id; both must migrate.
    sess = _Session(-5, -1005)
    c = TelegramClient("1:a", session=sess)
    c.call("forwardMessage", {"chat_id": -5, "from_chat_id": -5, "message_id": 3})
    last = sess.calls[-1]
    assert last["chat_id"] == -1005 and last["from_chat_id"] == -1005


def test_migration_only_retries_once():
    # If the new id ALSO failed migration we must not loop forever.
    class Loop(_Session):
        def post(self, url, json=None, timeout=None):
            self.calls.append(dict(json))
            return _Resp({"ok": False, "error_code": 400, "description": "upgraded",
                          "parameters": {"migrate_to_chat_id": json["chat_id"] - 1}})
    sess = Loop(-1, -2)
    c = TelegramClient("1:a", session=sess)
    import pytest
    from telegram_tools.core.errors import APIError
    with pytest.raises(APIError):
        c.call("sendMessage", {"chat_id": -1, "text": "x"})
    assert len(sess.calls) == 2    # original + one retry, then it raises


def test_store_migrate_chat_id(tmp_path):
    from telegram_tools.gui import store
    store._MSG_DIR = str(tmp_path / "m")
    import os
    os.makedirs(store._MSG_DIR)
    store._BACKFILL = str(tmp_path / "bf.json")
    with open(store.messages_path(7), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"message_id": 1, "chat_id": -123, "text": "a"}) + "\n")
        fh.write(json.dumps({"message_id": 2, "chat_id": -999, "text": "b"}) + "\n")
    store.update_backfill(7, -123, lowest=10)
    store.migrate_chat_id(7, -123, -1001999)
    store.migrate_backfill(7, -123, -1001999)
    ids = [m["chat_id"] for m in store.load_all_messages(7)]
    assert ids == [-1001999, -999]                       # only the migrated chat moved
    assert store.backfill_record(7, -1001999).get("lowest") == 10
