"""Fixtures and gating for the real-conditions (live) test suite.

These tests hit the real Telegram Bot API. They SKIP unless the relevant
environment variables are set, so running pytest without credentials is a no-op
rather than a failure:

    TG_TEST_TOKEN          bot token (from @BotFather)          [required]
    TG_TEST_CHAT           chat id / @username where the bot
                           is an admin                          [most tests]
    TG_TEST_USER           a known member's numeric id          [get-member]
    TG_TEST_MSG_ID         an existing message id in the chat   [archive hack]
    TG_TEST_ARCHIVE_CHAT   destination for forwarded copies
                           (defaults to TG_TEST_CHAT)
    TG_RUN_SIDEEFFECTS=1   enable tests that POST to Telegram
                           (make-invite, archive/forward)
    TG_TEST_CLEANUP=1      delete forwarded copies after the archive test

Discover TG_TEST_CHAT / TG_TEST_MSG_ID with:  python tests/live_setup.py
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def live_client():
    tok = os.environ.get("TG_TEST_TOKEN")
    if not tok:
        pytest.skip("TG_TEST_TOKEN not set - live test skipped")
    from telegram_tools.core import TelegramClient
    return TelegramClient(tok)


def _parse_chat(value: str):
    return int(value) if value.lstrip("-").isdigit() else value


@pytest.fixture(scope="session")
def live_chat():
    chat = os.environ.get("TG_TEST_CHAT")
    if not chat:
        pytest.skip("TG_TEST_CHAT not set - live chat test skipped")
    return _parse_chat(chat)


@pytest.fixture(scope="session")
def live_archive_chat():
    chat = os.environ.get("TG_TEST_ARCHIVE_CHAT") or os.environ.get("TG_TEST_CHAT")
    if not chat:
        pytest.skip("no archive/chat set")
    return _parse_chat(chat)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: hits the real Telegram API")
    config.addinivalue_line("markers", "sideeffect: POSTs to Telegram (opt-in)")
    config.addinivalue_line("markers", "slow: time-based, opt-in")


def pytest_collection_modifyitems(config, items):
    run_side = os.environ.get("TG_RUN_SIDEEFFECTS") == "1"
    skip_side = pytest.mark.skip(reason="set TG_RUN_SIDEEFFECTS=1 to run side-effecting tests")
    for item in items:
        if "sideeffect" in item.keywords and not run_side:
            item.add_marker(skip_side)
