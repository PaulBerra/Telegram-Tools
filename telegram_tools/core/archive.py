"""Message archiving by sequential-id deduction - the deliberate core hack.

Telegram message ids are sequential per chat. By starting at a high id and
walking DOWN, a bot can forward (hence read the content of) messages it never
received as updates, including messages that predate the bot joining the chat.
This bypasses the Bot API's "no history" limitation and is the whole point of
the command - it must stay.

``forwardMessage`` (singular) is what captures CONTENT: it returns the full
Message object in the response. The batch ``forwardMessages``/``copyMessages``
return only MessageIds, so they cannot replace this for archiving content.

Everything around the hack is a non-destructive wrapper:
  * incremental NDJSON write (one message per line, flushed) so any stop -
    cancel, Ctrl+C, crash - preserves what was already collected;
  * ``retry_after`` honoured by the client;
  * cooperative cancellation via ``should_stop``;
  * optional separate archive destination so the source chat is not spammed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union

from .client import TelegramClient
from .errors import APIError

ChatId = Union[int, str]

# Substrings in a 400 description that mean "this id has no forwardable message"
# - a normal gap (deleted / service message / never existed), so we skip and
# keep walking. Anything else at 400 (chat not found, bot not a member, not
# enough rights) is fatal and must surface.
_SKIP_MARKERS = (
    "message to forward not found",
    "message to copy not found",
    "message not found",
    "message_id_invalid",
    "message id is invalid",
)


def _is_skippable(exc: APIError) -> bool:
    if exc.error_code != 400:
        return False
    desc = (exc.description or "").lower()
    return any(marker in desc for marker in _SKIP_MARKERS)


def _media_file_ids(msg: dict) -> list[tuple[str, str]]:
    """Extract (kind, file_id) pairs for every downloadable attachment.

    ``photo`` is a size ladder - we take the largest. Everything else carries a
    single ``file_id``.
    """
    out: list[tuple[str, str]] = []
    photo = msg.get("photo")
    if isinstance(photo, list) and photo:
        out.append(("photo", photo[-1]["file_id"]))
    for kind in ("document", "video", "audio", "voice", "animation",
                 "video_note", "sticker"):
        obj = msg.get(kind)
        if isinstance(obj, dict) and obj.get("file_id"):
            out.append((kind, obj["file_id"]))
    return out


def _download_message_media(client: TelegramClient, msg: dict, media_dir: str) -> list[dict]:
    """Best-effort: download every attachment of ``msg`` into ``media_dir``.

    Returns one record per attachment (downloaded or errored); never raises, so
    a failed download (e.g. a file over the 20 MB Bot API cap) does not abort the
    archive run.
    """
    from . import api
    records: list[dict] = []
    for kind, file_id in _media_file_ids(msg):
        rec: dict[str, Any] = {"kind": kind, "file_id": file_id}
        try:
            got = api.download_file(client, file_id, media_dir)
            rec.update(path=got["path"], size=got["size"], sha256=got["sha256"])
        except Exception as exc:  # APIError (too big / not found) or network
            rec["error"] = str(exc)
        records.append(rec)
    return records


@dataclass
class ArchiveProgress:
    found: int = 0
    skipped: int = 0
    current_id: Optional[int] = None
    done: bool = False
    stopped: bool = False
    output_file: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


# Event callback: receives an ArchiveProgress snapshot after each id.
ProgressCb = Callable[[ArchiveProgress], None]


def archive_messages(
    client: TelegramClient,
    *,
    source_chat: ChatId,
    start_id: int,
    output_file: str,
    stop_id: Optional[int] = None,
    max_iters: int = 16000,
    dest_chat: Optional[ChatId] = None,
    media_dir: Optional[str] = None,
    append: bool = False,
    cleanup: bool = False,
    should_stop: Optional[Callable[[], bool]] = None,
    on_progress: Optional[ProgressCb] = None,
) -> ArchiveProgress:
    """Forward messages from ``start_id`` downward, writing each to NDJSON.

    Args:
        source_chat: chat the ids belong to (``from_chat_id``).
        start_id: highest id to try; iteration decrements from here.
        output_file: NDJSON path; each captured Message is one JSON line,
            flushed immediately.
        stop_id: stop once the current id drops below this (inclusive bound).
        max_iters: hard cap on attempts.
        dest_chat: where to forward to. Defaults to ``source_chat`` (the
            original behaviour); set to an archive chat you own to avoid
            posting copies back into the source.
        media_dir: if set, download each captured message's media here and
            annotate its NDJSON line with a ``_media`` list (path + sha256).
        append: open ``output_file`` in append mode (for --resume) instead of
            truncating it.
        cleanup: delete each forwarded copy right after its content is saved, so
            nothing lasting is left in the destination (the forward is only a way
            to read the content - the Bot API can't read it otherwise).
        should_stop: polled each iteration for cooperative cancellation.
        on_progress: called with an ``ArchiveProgress`` after each id.

    Returns:
        The final ``ArchiveProgress``.
    """
    destination = dest_chat if dest_chat is not None else source_chat
    progress = ArchiveProgress(output_file=output_file)
    progress.extra["downloaded"] = 0

    message_id = start_id
    iteration = 0
    # Line-buffered text so each written line reaches disk promptly; we also
    # flush explicitly after every capture.
    with open(output_file, "a" if append else "w", encoding="utf-8") as fh:
        while iteration < max_iters:
            if should_stop and should_stop():
                progress.stopped = True
                break
            if stop_id is not None and message_id < stop_id:
                break

            progress.current_id = message_id
            try:
                result = client.call("forwardMessage", {
                    "from_chat_id": source_chat,
                    "chat_id": destination,
                    "message_id": message_id,
                })
                if media_dir:
                    result["_media"] = _download_message_media(client, result, media_dir)
                    progress.extra["downloaded"] += sum(
                        1 for m in result["_media"] if "path" in m)
                fh.write(json.dumps(result, ensure_ascii=False) + "\n")
                fh.flush()
                progress.found += 1
                if cleanup and result.get("message_id"):
                    # The forward was only to read the content; remove the copy.
                    try:
                        from . import api
                        api.delete_message(client, destination, result["message_id"])
                    except APIError:
                        pass
            except APIError as exc:
                if _is_skippable(exc):
                    progress.skipped += 1
                else:
                    # Fatal (bad chat, missing rights, bot not a member, ...):
                    # record what we have and re-raise for the caller to handle.
                    if on_progress:
                        on_progress(progress)
                    raise

            if on_progress:
                on_progress(progress)

            message_id -= 1
            iteration += 1

    progress.done = not progress.stopped
    progress.current_id = None
    if on_progress:
        on_progress(progress)
    return progress


def grab_and_erase(client: TelegramClient, *, source_chat: ChatId,
                   message_id: int, dest_chat: ChatId) -> dict:
    """Capture one message to an archive chat, then delete the original.

    A lever, not a routine: it forwards the message to ``dest_chat`` (so its
    content is saved on your side), then permanently removes it from
    ``source_chat``. The delete is irreversible and needs delete rights. Callers
    must confirm with the user first - nothing here asks.
    """
    from . import api
    captured = client.call("forwardMessage", {
        "from_chat_id": source_chat,
        "chat_id": dest_chat,
        "message_id": message_id,
    })
    api.delete_message(client, source_chat, message_id)
    return captured
