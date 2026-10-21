![image](https://github.com/user-attachments/assets/a9042a56-6304-440a-a265-793794ce371c)

# Telegram Tools

A Telegram **OSINT toolkit built around bots**. Point it at a bot's token - typically one you've **recovered or obtained** during an investigation, not a bot you own or administer - and see what that bot can already see: profile it from its token, inspect the chats it's in, its members and rights, recover and archive the message history it can reach, and turn a dump into intelligence (links, senders, crypto addresses, phone numbers...) from a dashboard. A user account (advanced mode) adds what the Bot API forbids.

It ships as a **CLI** (`telegram_tools_cli.py`) and a **PyQt6 GUI** (`main.py`) that share the same core, so both do exactly the same things.

## Quick start

Python 3.9+.

```bash
pip install -r requirements.txt   # requests (CLI) + PyQt6 (GUI); telethon is optional, for MTProto
python main.py                    # GUI
#
# OR
#
python telegram_tools_cli.py --help   # CLI
```

In the GUI, type your bot token at the top (it auto-connects and is remembered) and pick a chat; every tab shares them. The sidebar is four workspaces:

- **Terrain** - field work on one group through a bot: a live **Conversation** timeline (Telegram-style, with a composer to post as the bot), a **Report** dashboard (links, senders, crypto, phones over time with Splunk-style drill-down per sender), admins, the bot's own rights, invite links.
- **Investigateur** - zoom on one subject across *every* bot's collected data: their groups, the users they're connected to, indicators they shared, activity/hours/words, then **enrich** from outside sources (web-search leads and the `t.me` preview with no account; common-groups, flags and the real id via your own account when you set up **Keys**).
- **Nexus** - the whole thing as an interactive graph: users, the groups they post in, and the indicators they share, linked across all your bots and sources. Two accounts that share a group - or the same crypto address - are tied together through it. Click a node to inspect, double-click to investigate.
- **Connection** - the bot token/chat picker and **Keys** (optional Telethon credentials + provider API keys, stored locally).

Messages are collected passively as the bot sees them, and older ones are walked in the background (rate-limit aware, a few chats at a time, the open chat first). The gear (bottom-right) opens **Settings** - pace, theme incl. **dark mode**, limits - and **Manage bots**, which permanently deletes stored data. On the CLI the token can also come from the `TELEGRAM_BOT_TOKEN` environment variable.

> OSINT reminder: this reads only what a connected bot (or your own user account) can already access - no exploit, no privilege escalation. External enrichment is best-effort and partial (Telegram exposes no "which groups is this user in"), every finding is labelled with its source, and it's meant for **authorized** anti-scam investigation - not for intruding into private groups.

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

### What you can read (limits by access)

| Target | Bot – member | Bot – admin | Your account (MTProto) |
|---|---|---|---|
| New messages, live | commands / @mentions / replies only ¹ | all | n/a |
| History **after** the bot got access | yes (id-walk) | yes | yes, if member |
| History **before** the bot joined / got rights | no ² | no ² | yes, if member |
| Full member list | no | admins only | yes, if member |
| A user never seen (real id, scam flags, common groups) | no | no | yes, no join needed |

¹ default "group privacy": a member bot receives only these. You work with the bot's **existing** access - changing its privacy (@BotFather) or making it admin needs control of the bot/group, which in an OSINT setting you usually don't have; with a recovered token you take whatever access it already has. ² a bot can only forward messages it had access to **when they were sent**; promoting it later does not unlock older ones - only a member **user account** can read those.

### Advanced (MTProto)

For what the Bot API forbids - listing all members, resolving any `@username`, reading full history without forwarding - use the user-account mode (needs an `api_id`/`api_hash`).

**Get your `api_id` / `api_hash`:** go to <https://my.telegram.org> → log in with your phone number (the code is sent **in the Telegram app**, not by SMS) → **API development tools** → fill the short form to create an app → copy the **App api_id** (a number) and **App api_hash** (32-char string). They belong to **your user account**, not the bot - keep them private, and prefer a dedicated/burner account for OSINT. In the GUI, paste them in **Keys** and log in; on the CLI, pass them to `login` (a 2FA password is asked only if your account has one set):

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
