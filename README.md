![image](https://github.com/user-attachments/assets/a9042a56-6304-440a-a265-793794ce371c)

# Telegram Tools

A Telegram **OSINT toolkit built around bots**. Point it at a bot's token - usually one you've **recovered** during an investigation, not a bot you own or administer - and see what that bot can already access: the chats it's in, their members and rights, the message history it can reach, turned into intelligence (links, senders, crypto addresses, phone numbers...) on a dashboard. An optional user account unlocks what the Bot API forbids.

> **Authorized anti-scam investigation only.** It reads only what a connected bot - or your own user account - can *already* access: no exploit, no privilege escalation.

## Limits — read this first

What you can actually read depends on the access the bot or account already has:

| Target | Bot · member | Bot · admin | User account (MTProto) |
|---|---|---|---|
| New messages, live | commands / @mentions / replies only ¹ | all | n/a |
| History **after** the bot got access | yes (id-walk) | yes | yes, if member |
| History **before** the bot joined / got rights | no ² | no ² | yes, if member |
| Full member list | no | admins only | yes, if member |
| A user never seen (real id, scam flags, common groups) | no | no | yes, no join needed |

¹ default "group privacy": a member bot receives only these. ² a bot can only forward messages it had access to **when they were sent** - promoting it later won't unlock older ones. With a **recovered** token you take whatever access the bot already has (you usually can't change its privacy or make it admin); only a member **user account** reads pre-access history.

## Install & run

Python 3.9+.

```bash
pip install -r requirements.txt   # requests + PyQt6; telethon optional (user-account mode)
python main.py                    # GUI
python telegram_tools_cli.py --help   # or the CLI
```

GUI: paste a bot token at the top (it auto-connects and is remembered), pick a chat - every tab shares them.

## What's inside

- **Bot control** - operate the connected bot in one chat: a live Telegram-style **Conversation** (with a composer to post as the bot), **Admins**, the bot's own **Bot rights**, and **Invitations**.
- **Investigator** - one subject across *all* collected data: their groups, the users they're connected to, shared indicators, activity/hours/words - then auto-**enrich** from outside sources (web-search leads, the `t.me` preview, and, with a user account, their real id, scam/fake flags, common groups and the messages they posted there).
- **Nexus** - everything as an interactive graph: users, the groups they post in, and the indicators they share, linked across all bots and sources. Click a node to inspect, double-click to investigate.
- **Connection / Keys** - the bot token & chat picker, plus optional user-account credentials and provider API keys (stored locally).

Messages are collected passively as the bot sees them, and older ones are walked in the background (rate-limit aware). The gear (bottom-right) opens **Settings** (pace, dark mode, limits) and **Manage bots** (permanently deletes stored data).

## Advanced: user account (MTProto)

For what the Bot API forbids - listing all members, resolving any `@username`, reading full history without forwarding, finding groups in common - connect a user account. It needs an `api_id` / `api_hash`:

**Get them:** go to <https://my.telegram.org> → log in with your phone number (the code is sent **in the Telegram app**, not by SMS) → **API development tools** → create an app → copy the **api_id** (a number) and **api_hash** (32-char string). They belong to **your account**, not the bot - keep them private, and prefer a dedicated/burner account for OSINT. Paste them in **Keys** (GUI) or pass them to `login` (CLI); a 2FA password is asked only if your account has one.

```bash
python telegram_mtproto.py login --api-id <ID> --api-hash <HASH> --phone +...
python telegram_mtproto.py members @somegroup --limit 500
python telegram_mtproto.py history @somegroup --limit 1000 -o history.ndjson
```

## CLI

Every command takes `-t <TOKEN>` (or the `TELEGRAM_BOT_TOKEN` env var); most take `-c <CHAT_ID>`. Add `--json` for machine output.

```bash
python telegram_tools_cli.py profile-token    -t <TOKEN>
python telegram_tools_cli.py get-admins       -t <TOKEN> -c <CHAT_ID>
python telegram_tools_cli.py archive-messages -t <TOKEN> -c <CHAT_ID> --auto-start -o dump.ndjson
python telegram_tools_cli.py intel            -i dump.ndjson
```

<details>
<summary><b>How the archive works</b> (optional reading)</summary>

The Bot API can't read history. But message ids are sequential, so starting from a high id and walking **down** lets a bot forward - and thus capture the content of - messages it never received, down to the oldest it can reach. That's what `archive-messages` does; it writes NDJSON incrementally, so stopping always keeps what was collected.
</details>

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
