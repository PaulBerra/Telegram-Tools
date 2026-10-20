#!/usr/bin/env python3
"""MTProto CLI (advanced mode) - user-account features via Telethon.

Separate from the Bot-API CLI because it authenticates as a user account, not a
bot. Run `login` once, then the other commands reuse the saved session.

    python -m telegram_tools.mtproto login --api-id 123 --api-hash abc --phone +33...
    python -m telegram_tools.mtproto members @somegroup --limit 500 --json
    python -m telegram_tools.mtproto history @somegroup --limit 1000 -o hist.ndjson
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from .client import MTProtoConfig, MTProtoError, NotAuthorizedError, login, session
from . import features


def _target(value: str):
    v = value.strip()
    return int(v) if v.lstrip("-").isdigit() else v


def _emit(obj, as_json: bool, text_fn) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    else:
        text_fn(obj)


def cmd_login(config, args):
    me = login(config)
    print(f"[OK] Logged in as @{me.get('username')} (id {me.get('id')}). "
          f"Session saved to {config.session}")


def cmd_resolve(config, args):
    with session(config) as client:
        res = features.resolve(client, args.target)
    _emit(res, args.json, lambda r: print(
        f"{r['kind']}  id={r['id']}  @{r.get('username')}  "
        f"{r.get('title') or (str(r.get('first_name') or '') + ' ' + str(r.get('last_name') or '')).strip()}"
        + (f"  [scam]" if r.get('scam') else "") + (f"  [verified]" if r.get('verified') else "")))


def cmd_members(config, args):
    with session(config) as client:
        mem = features.members(client, args.target, limit=args.limit, search=args.search or "")
    if args.json:
        print(json.dumps(mem, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"[{len(mem)} members]")
        for u in mem:
            print(f"  id={u['id']} @{u.get('username') or ''} "
                  f"{u.get('first_name') or ''} {u.get('last_name') or ''}"
                  + ("  (bot)" if u.get('bot') else ""))


def cmd_history(config, args):
    count = 0
    with session(config) as client:
        gen = features.history(client, args.target, limit=args.limit,
                               min_id=args.min_id, max_id=args.max_id,
                               search=args.search or "")
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                for m in gen:
                    fh.write(json.dumps(m, ensure_ascii=False) + "\n")
                    count += 1
            print(f"[DONE] {count} messages -> {args.output} "
                  f"(run `intel` on it)", file=sys.stderr)
        else:
            for m in gen:
                count += 1
                if not args.json:
                    print(f"  #{m['message_id']} from={m['from'].get('id')} "
                          f"{(m['text'] or '')[:80]}")
                else:
                    print(json.dumps(m, ensure_ascii=False, default=str))


def cmd_common_chats(config, args):
    with session(config) as client:
        chats = features.common_chats(client, args.target, limit=args.limit)
    if args.json:
        print(json.dumps(chats, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"[{len(chats)} chats in common]")
        for c in chats:
            print(f"  {c['kind']} id={c['id']} @{c.get('username') or ''} {c.get('title') or ''}")


def cmd_dialogs(config, args):
    with session(config) as client:
        ds = features.dialogs(client, limit=args.limit)
    if args.json:
        print(json.dumps(ds, ensure_ascii=False, indent=2, default=str))
    else:
        for d in ds:
            print(f"  {d['kind']} id={d['id']} {d['name']} "
                  f"(@{d.get('username') or ''}) unread={d['unread']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telegram-tools-mtproto",
        description="Advanced MTProto features (user account via Telethon).")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-id", type=int, default=None)
    common.add_argument("--api-hash", default=None)
    common.add_argument("--session", default=None, help="Session file (default telegram_tools.session)")
    common.add_argument("--json", action="store_true")

    tgt = argparse.ArgumentParser(add_help=False)
    tgt.add_argument("target", type=_target, help="@username, t.me link, phone or id")

    p = sub.add_parser("login", parents=[common], help="One-time interactive login")
    p.add_argument("--phone", default=None, help="Phone number (or TG_PHONE)")

    sub.add_parser("resolve", parents=[common, tgt], help="Resolve a username/link/id to an entity")

    p = sub.add_parser("members", parents=[common, tgt], help="Enumerate members of a group/channel")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--search", default="", help="Filter members by name")

    p = sub.add_parser("history", parents=[common, tgt], help="Read full history (no forward/spam)")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--min-id", type=int, default=0)
    p.add_argument("--max-id", type=int, default=0)
    p.add_argument("--search", default="", help="Only messages matching this text")
    p.add_argument("-o", "--output", default=None, help="Write NDJSON (intel-compatible)")

    p = sub.add_parser("common-chats", parents=[common, tgt], help="Chats in common with a user")
    p.add_argument("--limit", type=int, default=100)

    p = sub.add_parser("dialogs", parents=[common], help="List chats this account is in")
    p.add_argument("--limit", type=int, default=100)

    return parser


_HANDLERS = {
    "login": cmd_login,
    "resolve": cmd_resolve,
    "members": cmd_members,
    "history": cmd_history,
    "common-chats": cmd_common_chats,
    "dialogs": cmd_dialogs,
}


def main(argv: Optional[list[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        config = MTProtoConfig.from_env(
            api_id=args.api_id, api_hash=args.api_hash,
            session=args.session, phone=getattr(args, "phone", None))
    except MTProtoError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    try:
        _HANDLERS[args.command](config, args)
    except NotAuthorizedError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 3
    except MTProtoError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
