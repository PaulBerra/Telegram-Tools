"""Real-conditions tests, one per feature, against the live Telegram Bot API.

Read-only tests run whenever TG_TEST_TOKEN (+ TG_TEST_CHAT) are set.
Side-effecting tests (they POST to Telegram) additionally require
TG_RUN_SIDEEFFECTS=1. The archive test is the crown jewel: it proves the
sequential-id deduction hack really captures message content.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from telegram_tools.core import api, archive, intel

pytestmark = pytest.mark.live


# --------------------------------------------------------------------------
# Read-only features.
# --------------------------------------------------------------------------

def test_get_me(live_client):
    me = api.get_me(live_client)
    assert me.get("is_bot") is True
    assert me.get("id") and me.get("username")


def test_profile_bot(live_client):
    prof = api.profile_bot(live_client)
    assert prof["me"]["is_bot"] is True
    # webhook_info is always available on a valid token.
    assert "url" in prof.get("webhook_info", {})


def test_get_chat(live_client, live_chat):
    chat = api.get_chat(live_client, live_chat)
    assert chat.get("id") is not None
    assert chat.get("type") in {"group", "supergroup", "channel", "private"}


def test_get_chat_member_count(live_client, live_chat):
    count = api.get_chat_member_count(live_client, live_chat)
    assert isinstance(count, int) and count >= 1


def test_get_admins(live_client, live_chat):
    admins = api.get_chat_administrators(live_client, live_chat)
    assert isinstance(admins, list) and len(admins) >= 1
    assert all("user" in a and "status" in a for a in admins)


def test_get_rights(live_client, live_chat):
    res = api.get_bot_permissions(live_client, live_chat)
    assert res.get("status") in {"administrator", "creator", "member", "left", "restricted"}


def test_get_member(live_client, live_chat):
    uid = os.environ.get("TG_TEST_USER")
    if not uid:
        pytest.skip("TG_TEST_USER not set")
    info = api.get_chat_member(live_client, live_chat, int(uid))
    assert info.get("user", {}).get("id") == int(uid)


# --------------------------------------------------------------------------
# Side-effecting features (opt-in: TG_RUN_SIDEEFFECTS=1).
# --------------------------------------------------------------------------

@pytest.mark.sideeffect
def test_make_invite(live_client, live_chat):
    link = api.create_chat_invite_link(
        live_client, live_chat, name="pytest-live", member_limit=1)
    assert link.get("invite_link", "").startswith("https://t.me/")
    # Clean up: revoke the link we just made.
    try:
        live_client.call("revokeChatInviteLink",
                         {"chat_id": live_chat, "invite_link": link["invite_link"]})
    except Exception:
        pass


@pytest.mark.sideeffect
def test_archive_id_deduction_captures_content(live_client, live_chat, live_archive_chat):
    """THE innovative feature: forward a known id to capture its content.

    Point TG_TEST_MSG_ID at an OLD message (ideally older than the bot joined)
    to also prove the 'retrieve messages the bot never received' property.
    """
    msg_id = os.environ.get("TG_TEST_MSG_ID")
    if not msg_id:
        pytest.skip("TG_TEST_MSG_ID not set - point it at an existing message id")
    msg_id = int(msg_id)

    out = os.path.join(tempfile.gettempdir(), "live_archive_test.ndjson")
    # Forward just the single known id (start==stop) to minimise side effects.
    prog = archive.archive_messages(
        live_client,
        source_chat=live_chat,
        start_id=msg_id,
        stop_id=msg_id,
        output_file=out,
        max_iters=1,
        dest_chat=live_archive_chat,
    )

    assert prog.found >= 1, "the known message id should have been captured"
    lines = [json.loads(l) for l in open(out, encoding="utf-8").read().splitlines()]
    assert lines, "NDJSON must contain the captured message"
    captured = lines[0]
    # The forwarded object carries the original content + a forward origin.
    assert captured.get("message_id")
    assert ("text" in captured or "caption" in captured
            or "photo" in captured or "document" in captured
            or "forward_origin" in captured or "forward_from" in captured), \
        "captured object should hold the original message's content/metadata"

    if os.environ.get("TG_TEST_CLEANUP") == "1":
        # Delete the copy we created in the destination chat.
        try:
            api.delete_message(live_client, live_archive_chat, captured["message_id"])
        except Exception:
            pass


@pytest.mark.sideeffect
def test_max_id_auto_start(live_client, live_chat):
    """Auto start-id: posts a marker, reads its id, deletes it."""
    mid = api.current_max_message_id(live_client, live_chat)
    assert isinstance(mid, int) and mid >= 1


@pytest.mark.sideeffect
def test_archive_then_intel(live_client, live_chat, live_archive_chat):
    """End-to-end: auto-start archive a few ids, then extract IOCs locally."""
    ceiling = api.current_max_message_id(live_client, live_chat)
    out = os.path.join(tempfile.gettempdir(), "live_archive_intel.ndjson")
    prog = archive.archive_messages(
        live_client, source_chat=live_chat, start_id=ceiling,
        stop_id=max(ceiling - 5, 1), output_file=out, max_iters=6,
        dest_chat=live_archive_chat,
    )
    # Clean up the copies we just forwarded.
    for line in open(out, encoding="utf-8").read().splitlines():
        try:
            api.delete_message(live_client, live_archive_chat,
                               json.loads(line)["message_id"])
        except Exception:
            pass
    report = intel.analyze(out)
    assert report.messages == prog.found
    assert isinstance(report.indicators, dict)  # may be empty on a clean test chat


@pytest.mark.slow
@pytest.mark.sideeffect
def test_listen_runs_without_error(live_client, live_chat):
    """Can't guarantee a join, but the long-poll cycle must run cleanly."""
    users = list(api.listen_new_users(live_client, live_chat, timeout=5, long_poll=2))
    assert isinstance(users, list)  # 0 or more, no exception
