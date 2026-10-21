"""Background workers so the UI never blocks on the network.

Every Telegram call runs off the GUI thread in a QThread and reports back via
signals. The core layer is plain Python, so workers just wrap a callable.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ..core import ArchiveProgress, TelegramError, archive


class CallWorker(QThread):
    """Run a no-arg callable off-thread; emit its result or an error string."""

    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, job: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._job = job

    def run(self) -> None:
        try:
            self.done.emit(self._job())
        except TelegramError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # defensive: surface anything rather than die silently
            self.failed.emit(f"Unexpected error: {exc}")


class GeneratorWorker(QThread):
    """Consume a generator job, emitting each item; supports cooperative stop."""

    item = pyqtSignal(object)
    done = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, job_factory: Callable[[Callable[[], bool]], Any], parent=None):
        super().__init__(parent)
        self._job_factory = job_factory
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            for item in self._job_factory(self._stop.is_set):
                self.item.emit(item)
                if self._stop.is_set():
                    break
            self.done.emit()
        except TelegramError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Unexpected error: {exc}")


class UpdatesPoller(QThread):
    """The single getUpdates consumer, running while a token is connected.

    It long-polls, records every chat it sees, and emits new members. Having one
    poller avoids the Bot API's "only one getUpdates at a time" conflict.
    """

    chat_seen = pyqtSignal(object)   # {id, title, type}
    new_member = pyqtSignal(object)  # {"user": {...}, "chat_id": ...}
    message = pyqtSignal(object)     # a normalized message dict (passive archive)
    stopped = pyqtSignal(str)        # "" clean, else the error

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self._client = client
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        offset = 0
        while not self._stop.is_set():
            try:
                updates = self._client.call(
                    "getUpdates", {"offset": offset, "timeout": 15}, http_method="GET")
            except TelegramError as exc:
                self.stopped.emit(str(exc))
                return
            except Exception as exc:
                self.stopped.emit(f"Unexpected error: {exc}")
                return
            for upd in updates or []:
                offset = upd["update_id"] + 1
                for obj in upd.values():
                    chat = obj.get("chat") if isinstance(obj, dict) else None
                    if chat and chat.get("id") is not None:
                        self.chat_seen.emit({
                            "id": chat["id"],
                            "title": (chat.get("title") or chat.get("username")
                                      or chat.get("first_name") or chat.get("type")),
                            "type": chat.get("type"),
                        })
                for key in ("message", "channel_post", "edited_message"):
                    msg = upd.get(key)
                    if not isinstance(msg, dict):
                        continue
                    for user in msg.get("new_chat_members", []) or []:
                        self.new_member.emit({"user": user,
                                              "chat_id": msg.get("chat", {}).get("id"),
                                              "message_id": msg.get("message_id"),
                                              "date": msg.get("date")})
                    if msg.get("text") or msg.get("caption") or msg.get("photo") \
                            or msg.get("document"):
                        self.message.emit(self._normalize(msg))
        self.stopped.emit("")

    @staticmethod
    def _normalize(msg: dict) -> dict:
        # Same shape as the archive/intel NDJSON, so Report can read it directly.
        sender = msg.get("from") or {}
        return {
            "message_id": msg.get("message_id"),
            "chat_id": msg.get("chat", {}).get("id"),
            "date": msg.get("date"),
            "text": msg.get("text") or msg.get("caption") or "",
            "from": {"id": sender.get("id"), "username": sender.get("username"),
                     "first_name": sender.get("first_name")},
        }


class BackfillWorker(QThread):
    """Fetch older messages of a chat by forwarding ids downward, in the background.

    Each message is forwarded (the only way to read a past one), normalized to the
    collected-message shape, emitted, then its copy is deleted. Stops on a long run
    of missing ids, on the id floor, or when asked.
    """

    message = pyqtSignal(object)  # normalized message dict
    progress = pyqtSignal(int)    # lowest message id reached so far
    done = pyqtSignal(int, bool)  # (how many captured, reached the bottom)
    failed = pyqtSignal(str)

    def __init__(self, client, *, source_chat, start_id, stop_id=1,
                 max_gap=400, max_total=None, cleanup=True, pace=3.2, parent=None):
        super().__init__(parent)
        self._client = client
        self._source = source_chat
        self._start = start_id
        self._stop_id = stop_id
        self._max_gap = max_gap        # stop after this many ids in a row with no message
        self._max_total = max_total    # None = no cap (fetch everything down to id 1)
        self._cleanup = cleanup
        # Telegram allows ~20 messages/min to a group and ~1/s to a chat, and a
        # forward IS a send. We pace at ~3.2s between forwards to stay under the
        # group limit so we don't trigger 429s; the client also honours
        # retry_after if we ever do. See core.telegram.org/bots/faq#my-bot-is-hitting-limits.
        self._pace = pace
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def _normalize(self, res: dict, original_id: int) -> dict:
        origin = res.get("forward_origin") or {}
        sender = origin.get("sender_user") or res.get("forward_from") or {}
        date = origin.get("date") or res.get("forward_date") or res.get("date")
        name = (sender.get("first_name") or origin.get("sender_user_name")
                or origin.get("author_signature")
                or (origin.get("chat") or {}).get("title"))
        return {
            "message_id": original_id,
            "chat_id": self._source,
            "date": date,
            "text": res.get("text") or res.get("caption") or "",
            "from": {"id": sender.get("id"), "username": sender.get("username"),
                     "first_name": name},
        }

    def run(self) -> None:
        from ..core.errors import APIError
        captured = 0
        gap = 0
        mid = self._start
        since_report = 0
        try:
            while (mid >= self._stop_id and gap < self._max_gap
                   and (self._max_total is None or captured < self._max_total)
                   and not self._stop.is_set()):
                try:
                    res = self._client.call("forwardMessage", {
                        "from_chat_id": self._source, "chat_id": self._source,
                        "message_id": mid})
                except APIError as exc:
                    if exc.error_code == 400:
                        gap += 1
                        mid -= 1
                        self._stop.wait(0.3)   # a missing id didn't send; probe gently
                        continue
                    raise
                gap = 0
                if res.get("text") or res.get("caption"):
                    self.message.emit(self._normalize(res, mid))
                    captured += 1
                if self._cleanup and res.get("message_id"):
                    try:
                        self._client.call("deleteMessage", {
                            "chat_id": self._source, "message_id": res["message_id"]})
                    except APIError:
                        pass
                mid -= 1
                # Report how far back we've walked, but not on every single id.
                since_report += 1
                if since_report >= 10:
                    since_report = 0
                    self.progress.emit(mid)
                # A forward is a send to the chat: pace to stay under the limit.
                self._stop.wait(self._pace)
            # "Bottom reached" = we stopped on our own terms (ran out of ids or a
            # long gap), not because we were asked to stop mid-walk.
            reached_bottom = not self._stop.is_set()
            self.progress.emit(max(mid, self._stop_id))
            self.done.emit(captured, reached_bottom)
        except Exception as exc:
            self.failed.emit(str(exc))


class EnrichWorker(QThread):
    """Run a set of enrichment providers for one subject off the UI thread,
    emitting each provider's result as it lands (some do network I/O)."""

    result = pyqtSignal(object)   # EnrichmentResult
    done = pyqtSignal()

    def __init__(self, providers, subject, parent=None):
        super().__init__(parent)
        self._providers = list(providers)
        self._subject = subject

    def run(self) -> None:
        from ..core.enrich.base import EnrichmentResult
        for p in self._providers:
            try:
                res = p.enrich(self._subject)
            except Exception as exc:
                res = EnrichmentResult(getattr(p, "name", "?"), ok=False, error=str(exc))
            self.result.emit(res)
        self.done.emit()


class TelethonLoginWorker(QThread):
    """Drive Telethon's interactive login off-thread. It blocks on the code/
    password until the GUI supplies them (via provide_code / provide_password)."""

    code_needed = pyqtSignal()
    password_needed = pyqtSignal()
    done = pyqtSignal(object)      # {id, username, first_name, phone}
    failed = pyqtSignal(str)

    def __init__(self, api_id, api_hash, phone, session, parent=None):
        super().__init__(parent)
        self._api_id, self._api_hash = api_id, api_hash
        self._phone, self._session = phone, session
        self._code = None
        self._pw = None
        self._code_ev = threading.Event()
        self._pw_ev = threading.Event()

    def provide_code(self, code: str) -> None:
        self._code = code
        self._code_ev.set()

    def provide_password(self, pw: str) -> None:
        self._pw = pw
        self._pw_ev.set()

    def run(self) -> None:
        try:
            import telethon.sync  # noqa: F401  (blocking calls in this thread)
            from telethon import TelegramClient
            from telethon.errors import SessionPasswordNeededError
        except Exception as exc:
            self.failed.emit(f"Telethon not installed: {exc}")
            return
        try:
            client = TelegramClient(self._session, int(self._api_id), self._api_hash)
            client.connect()
            if not client.is_user_authorized():
                client.send_code_request(self._phone)
                self.code_needed.emit()
                self._code_ev.wait()
                try:
                    client.sign_in(self._phone, (self._code or "").strip())
                except SessionPasswordNeededError:
                    self.password_needed.emit()
                    self._pw_ev.wait()
                    client.sign_in(password=self._pw or "")
            me = client.get_me()
            out = {"id": me.id, "username": me.username,
                   "first_name": me.first_name, "phone": me.phone}
            client.disconnect()
            self.done.emit(out)
        except Exception as exc:
            self.failed.emit(str(exc))


class ArchiveWorker(QThread):
    """Run the id-deduction archive hack with live progress and cancellation."""

    progress = pyqtSignal(object)   # ArchiveProgress
    done = pyqtSignal(object)       # final ArchiveProgress
    failed = pyqtSignal(str)

    def __init__(self, client, params: dict, parent=None):
        super().__init__(parent)
        self._client = client
        self._params = params
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            final = archive.archive_messages(
                self._client,
                should_stop=self._stop.is_set,
                on_progress=lambda p: self.progress.emit(p),
                **self._params,
            )
            self.done.emit(final)
        except TelegramError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Unexpected error: {exc}")
