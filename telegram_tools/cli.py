#!/usr/bin/env python3
"""Command-line interface for telegram_tools, built on the shared core.

No business logic lives here: every command calls ``telegram_tools.core`` and
only formats the result (human text, or ``--json`` for machine use). The token
is read from ``-t/--token`` or the ``TELEGRAM_BOT_TOKEN`` environment variable
(preferred - keeps it out of the process argument list).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

from .core import TelegramClient, TelegramError, api, archive, intel


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _chat_arg(value: str):
    """Accept a numeric chat id (incl. leading '-') or an @username / t.me link."""
    v = value.strip()
    if v.lstrip("-").isdigit():
        return int(v)
    return v


def _emit(obj: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))


def _resolve_token(args) -> str:
    token = args.token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("[ERROR] No token. Pass -t or set TELEGRAM_BOT_TOKEN.")
    return token


# --------------------------------------------------------------------------
# Command handlers - each takes (client, args) and prints.
# --------------------------------------------------------------------------

def cmd_profile_token(client, args):
    prof = api.profile_bot(client)
    if args.json:
        _emit(prof, True)
        return
    me = prof.get("me", {})
    print(f"Bot: @{me.get('username','?')}  (id {me.get('id','?')}, "
          f"name {me.get('first_name','')!r})")
    wh = prof.get("webhook_info", {})
    print(f"Webhook URL: {wh.get('url') or '(none - polling)'}")
    print(f"Pending updates: {wh.get('pending_update_count', '?')}")
    cmds = prof.get("my_commands", []) or []
    print(f"Declared commands: {len(cmds)}")
    for c in cmds:
        print(f"  /{c.get('command')} - {c.get('description')}")
    if prof.get("my_short_description", {}).get("short_description"):
        print(f"Short description: {prof['my_short_description']['short_description']}")
    if prof.get("my_description", {}).get("description"):
        print(f"Description: {prof['my_description']['description']}")
    if prof.get("errors"):
        print(f"[note] unavailable: {', '.join(prof['errors'])}")


def cmd_chat_info(client, args):
    chat = api.get_chat(client, args.chat)
    if args.json:
        try:
            chat = {**chat, "member_count": api.get_chat_member_count(client, args.chat)}
        except TelegramError:
            pass
        _emit(chat, True)
        return
    print(f"Chat: {chat.get('title') or chat.get('username') or chat.get('id')}")
    print(f"  type: {chat.get('type')}  id: {chat.get('id')}")
    if chat.get("username"):
        print(f"  @{chat['username']}")
    if chat.get("description"):
        print(f"  description: {chat['description']}")
    try:
        print(f"  members: {api.get_chat_member_count(client, args.chat)}")
    except TelegramError:
        pass


def cmd_get_admins(client, args):
    admins = api.get_chat_administrators(client, args.chat)
    if args.json:
        _emit(admins, True)
        return
    print("Chat administrators:")
    for adm in admins:
        u = adm.get("user", {})
        print(f" · {u.get('first_name','')} {u.get('last_name','')} "
              f"(@{u.get('username','')}) - {adm.get('status')}")


def cmd_get_member(client, args):
    info = api.get_chat_member(client, args.chat, args.user)
    if args.json:
        _emit(info, True)
        return
    u = info.get("user", {})
    print(f"[MEMBER] id={u.get('id')} name={u.get('first_name','')} "
          f"{u.get('last_name','')} @{u.get('username','')} status={info.get('status')}")


def cmd_get_rights(client, args):
    res = api.get_bot_permissions(client, args.chat)
    if args.json:
        _emit(res, True)
        return
    status = res.get("status")
    print(f"[BOT STATUS] {status}")
    if status in ("administrator", "creator"):
        for k, v in res.items():
            if k.startswith("can_"):
                print(f"  {k} = {v}")
    else:
        print("[INFO] Bot is not an administrator; no detailed permissions.")


def cmd_get_invite(client, args):
    link = api.export_chat_invite_link(client, args.chat)
    if args.json:
        _emit({"invite_link": link}, True)
        return
    print(f"[INVITE LINK] {link}")
    print("[note] exportChatInviteLink revoked the previous PRIMARY link. "
          "Use 'make-invite' for additional links.")


def cmd_make_invite(client, args):
    link = api.create_chat_invite_link(
        client, args.chat,
        name=args.name, expire_date=args.expire, member_limit=args.limit,
        creates_join_request=args.join_request,
    )
    if args.json:
        _emit(link, True)
        return
    print(f"[INVITE LINK] {link.get('invite_link')}")
    if link.get("name"):
        print(f"  name: {link['name']}")
    if link.get("member_limit"):
        print(f"  member_limit: {link['member_limit']}")
    if link.get("creates_join_request"):
        print("  creates_join_request: True (approve with join requests)")


def cmd_listen_users(client, args):
    found = []
    for user in api.listen_new_users(client, args.chat, timeout=args.duration):
        found.append(user)
        if not args.json:
            print(f"[NEW USER] id={user.get('id')} {user.get('first_name','')} "
                  f"{user.get('last_name','')} @{user.get('username','')}")
    if args.json:
        _emit(found, True)
    elif not found:
        print("[INFO] No new users during the listening window.")


def _min_message_id_in(path: str):
    """Lowest message_id already present in an NDJSON dump (for --resume)."""
    import json as _json
    lowest = None
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    mid = _json.loads(line).get("message_id")
                except _json.JSONDecodeError:
                    continue
                if isinstance(mid, int) and (lowest is None or mid < lowest):
                    lowest = mid
    except FileNotFoundError:
        return None
    return lowest


def cmd_archive_messages(client, args):
    """The sequential-id deduction hack (see core/archive.py)."""
    start_id = args.message_id
    append = False

    # --auto-start: discover the current ceiling instead of guessing a high id.
    if args.auto_start:
        start_id = api.current_max_message_id(client, args.chat)
        print(f"[INFO] Auto-detected current max message id: {start_id}", file=sys.stderr)

    # --resume: continue below the lowest id already archived (append mode).
    if args.resume:
        existing = _min_message_id_in(args.output_file)
        if existing is not None:
            start_id = existing - 1
            append = True
            print(f"[INFO] Resuming below id {existing} (start {start_id}).",
                  file=sys.stderr)

    if start_id is None:
        print("[ERROR] Provide -m/--message-id, or use --auto-start.", file=sys.stderr)
        return

    def on_progress(p: archive.ArchiveProgress):
        if args.json:
            return
        if p.current_id is not None:
            dl = p.extra.get("downloaded", 0)
            print(f"[.] id {p.current_id}  found={p.found} skipped={p.skipped} "
                  f"media={dl}", file=sys.stderr)

    print(f"[INFO] Archiving from id {start_id} downward into {args.output_file}",
          file=sys.stderr)
    if args.dest_chat is not None:
        print(f"[INFO] Forwarding to archive chat {args.dest_chat} "
              "(source chat untouched).", file=sys.stderr)
    else:
        print("[WARN] No --dest-chat: copies are posted back into the SOURCE chat.",
              file=sys.stderr)
    if args.download_media:
        print(f"[INFO] Downloading media into {args.media_dir} (<=20 MB each).",
              file=sys.stderr)
    try:
        prog = archive.archive_messages(
            client,
            source_chat=args.chat,
            start_id=start_id,
            stop_id=args.stop_id,
            output_file=args.output_file,
            max_iters=args.max_iterations,
            dest_chat=args.dest_chat,
            media_dir=args.media_dir if args.download_media else None,
            append=append,
            on_progress=on_progress,
        )
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted - partial dump already on disk (NDJSON).",
              file=sys.stderr)
        return
    summary = {"found": prog.found, "skipped": prog.skipped,
               "downloaded": prog.extra.get("downloaded", 0),
               "output_file": prog.output_file, "completed": prog.done}
    if args.json:
        _emit(summary, True)
    else:
        print(f"[DONE] {prog.found} messages, {prog.extra.get('downloaded',0)} media, "
              f"{prog.skipped} ids skipped -> {prog.output_file}", file=sys.stderr)


def cmd_max_id(client, args):
    mid = api.current_max_message_id(client, args.chat)
    if args.json:
        _emit({"max_message_id": mid}, True)
    else:
        print(f"[MAX ID] current highest message id in chat: {mid}")


def cmd_intel(client, args):
    """Local IOC extraction from an archived NDJSON dump (no network)."""
    report = intel.analyze(args.input)
    fmt = args.format
    if fmt == "json":
        text = intel.to_json(report)
    elif fmt == "csv":
        text = intel.to_csv(report)
    else:
        text = intel.to_markdown(report, source=args.input)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"[DONE] {report.total_indicators()} indicators across "
              f"{report.messages} messages -> {args.output}", file=sys.stderr)
    else:
        print(text)


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telegram-tools",
        description="CLI for the Telegram Bot API (OSINT / chat admin helpers).",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-t", "--token", default=None,
                        help="Bot token (or set TELEGRAM_BOT_TOKEN)")
    common.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    chat = argparse.ArgumentParser(add_help=False)
    chat.add_argument("-c", "--chat", required=True, type=_chat_arg,
                      help="Chat id (numeric, incl. leading '-') or @username")

    def add(name, parents, help_):
        return sub.add_parser(name, parents=parents, help=help_)

    add("profile-token", [common], "Profile a bot from its token (getMe + webhook/commands/etc.)")
    add("chat-info", [common, chat], "Resolve a chat: type, title, description, member count")
    add("get-admins", [common, chat], "List chat administrators")

    p = add("get-member", [common, chat], "Fetch info for a chat member")
    p.add_argument("-u", "--user", required=True, type=int, help="User id")

    add("get-rights", [common, chat], "Show the bot's permissions in the chat")
    add("get-invite", [common, chat], "Primary invite link (revokes the previous one)")

    p = add("make-invite", [common, chat], "Create an additional invite link with options")
    p.add_argument("--name", default=None)
    p.add_argument("--expire", type=int, default=None, help="Unix timestamp")
    p.add_argument("--limit", type=int, default=None, help="member_limit")
    p.add_argument("--join-request", action="store_true", help="creates_join_request")

    p = add("listen-users", [common, chat], "Watch for new users joining")
    p.add_argument("-d", "--duration", type=int, default=60, help="Seconds (default 60)")

    for alias in ("archive-messages", "dump-messages"):
        p = add(alias, [common, chat],
                "Archive messages by sequential-id deduction (forward hack)")
        p.add_argument("-m", "--message-id", type=int, default=None,
                       help="Highest id to start from (iterates downward)")
        p.add_argument("--auto-start", action="store_true",
                       help="Auto-detect the current highest id instead of -m")
        p.add_argument("-s", "--stop-id", type=int, default=None,
                       help="Stop once id drops below this")
        p.add_argument("-o", "--output-file", required=True, help="NDJSON output path")
        p.add_argument("-n", "--max-iterations", type=int, default=16000)
        p.add_argument("--dest-chat", type=_chat_arg, default=None,
                       help="Forward into this archive chat instead of the source")
        p.add_argument("--download-media", action="store_true",
                       help="Download photos/documents/etc (<=20 MB each)")
        p.add_argument("--media-dir", default="media",
                       help="Folder for downloaded media (default: ./media)")
        p.add_argument("--resume", action="store_true",
                       help="Continue below the lowest id already in the output file")

    add("max-id", [common, chat], "Print the chat's current highest message id")

    p = add("intel", [common], "Extract IOCs from an archived NDJSON dump (local, no token)")
    p.add_argument("-i", "--input", required=True, help="NDJSON dump to analyze")
    p.add_argument("-o", "--output", default=None, help="Write report here (else stdout)")
    p.add_argument("--format", choices=["md", "json", "csv"], default="md")

    return parser


_HANDLERS = {
    "profile-token": cmd_profile_token,
    "chat-info": cmd_chat_info,
    "get-admins": cmd_get_admins,
    "get-member": cmd_get_member,
    "get-rights": cmd_get_rights,
    "get-invite": cmd_get_invite,
    "make-invite": cmd_make_invite,
    "listen-users": cmd_listen_users,
    "archive-messages": cmd_archive_messages,
    "dump-messages": cmd_archive_messages,
    "max-id": cmd_max_id,
    "intel": cmd_intel,
}

# Commands that work purely locally and need no bot token / client.
_NO_CLIENT = {"intel"}


def main(argv: Optional[list[str]] = None) -> int:
    # Windows consoles default to a legacy code page; force UTF-8 so bot names,
    # usernames and message text don't mojibake. Harmless elsewhere.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)

    client = None
    if args.command not in _NO_CLIENT:
        token = _resolve_token(args)
        try:
            client = TelegramClient(token)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    try:
        _HANDLERS[args.command](client, args)
    except TelegramError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
