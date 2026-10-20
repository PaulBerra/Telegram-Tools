![image](https://github.com/user-attachments/assets/a9042a56-6304-440a-a265-793794ce371c)

# Telegram Tools

A Telegram **OSINT toolkit built around bots**. You drive a bot (and, in advanced mode, a user account) to investigate chats: profile a bot from its token, inspect members and rights, recover and archive message history, and turn a dump into intelligence (links, senders, crypto addresses, phone numbers...) from a dashboard.

It ships as a **CLI** (`telegram_tools_cli.py`) and a **PyQt6 GUI** (`main.py`) that share the same core, so both do exactly the same things.

## Quick start

Python 3.9+.

```bash
pip install -r requirements.txt   # requests (CLI) + PyQt6 (GUI); telethon is optional, for MTProto
python main.py                    # GUI
python telegram_tools_cli.py --help   # CLI
```

In the GUI, type your bot token at the top (it auto-connects and is remembered) and pick a chat; every tab shares them. The sidebar is grouped by intent:

- **Members** - admins, per-user info, the bot's own rights, invite links.
- **Analyse** - a live **Conversation** timeline (Telegram-style) and a **Report** dashboard (links, senders, crypto, phones over time), with a per-sender profile: activity, active hours, top words, what they shared.

Messages are collected passively as the bot sees them, and older ones are walked in the background (rate-limit aware, a few chats at a time, the open chat first). The gear (bottom-right) opens **Settings** - pace, theme incl. **dark mode**, limits - and **Manage bots**, which permanently deletes stored data. On the CLI the token can also come from the `TELEGRAM_BOT_TOKEN` environment variable.

## Usage

Every CLI command takes `-t <TOKEN>` (or the env var) and most take `-c <CHAT_ID>`; add `--json` for machine output. A few examples:

```bash
python telegram_tools_cli.py profile-token -t <TOKEN>
python telegram_tools_cli.py get-admins   -t <TOKEN> -c <CHAT_ID>
python telegram_tools_cli.py archive-messages -t <TOKEN> -c <CHAT_ID> --auto-start -o dump.ndjson
python telegram_tools_cli.py intel -i dump.ndjson
```

### How the archive works

The Bot API can't read history. But message ids are sequential, so starting from a high id and walking **down** lets a bot forward (and thus capture the content of) messages it never received - including ones older than it. That's what `archive-messages` does; it writes NDJSON incrementally, so stopping always keeps what was collected.

### Advanced (MTProto)

For what the Bot API forbids - listing all members, resolving any `@username`, reading full history without forwarding - use the user-account mode (needs `api_id`/`api_hash` from <https://my.telegram.org>):

```bash
python telegram_mtproto.py login --api-id <ID> --api-hash <HASH> --phone +...
python telegram_mtproto.py members @somegroup --limit 500
python telegram_mtproto.py history @somegroup --limit 1000 -o history.ndjson
```

## Structure

```
telegram_tools/        core (API client, archive, intel) + cli + gui + mtproto
telegram_tools_cli.py  CLI entry point
main.py                GUI entry point
telegram_mtproto.py    MTProto (advanced mode) entry point
tests/                 live integration tests (see tests/conftest.py)
```

## License

© 2025 Paul Berra. All Rights Reserved.

Non-commercial use, modification and distribution are permitted, provided that Paul Berra is credited and notified. Commercial use or distribution is strictly prohibited without prior written permission.

Pour toute demande d'autorisation commerciale : [paul.berra.pro@gmail.com](mailto:paul.berra.pro@gmail.com)
