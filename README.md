![image](https://github.com/user-attachments/assets/a9042a56-6304-440a-a265-793794ce371c)

# Telegram Tools

A Telegram OSINT toolkit to investigate a group or bot whose token you've caught - see what that access already reaches and turn it into intelligence. An optional user account unlocks what the Bot API forbids.

## Limits

| Target | Bot · member | Bot · admin | User account |
|---|---|---|---|
| New messages, live | commands / @mentions / replies only ¹ | all | n/a |
| History **after** the bot got access | yes | yes | yes, if member |
| History **before** the bot joined / got rights | no ² | no ² | yes, if member |
| Full member list | no | admins only | yes, if member |
| A user never seen (real id, scam flags, common groups) | no | no | yes, no join |

¹ default "group privacy". ² a bot can't forward messages from before it had access, and a recovered token gives you only its current access - only a member **user account** reads pre-access history.

## Install & run

```bash
pip install -r requirements.txt       # requests + PyQt6; telethon optional
python main.py                        # GUI
python telegram_tools_cli.py --help   # CLI
```

GUI: paste a bot token at the top, pick a chat - every tab shares them.

## Workspaces

- **Bot control** - Conversation, Admins, Bot rights, Invitations.
- **Investigator** - one subject across all collected data, auto-enriched (web leads, `t.me`, and via a user account: real id, scam/fake flags, common groups and the messages they posted there).
- **Nexus** - everything as an interactive graph.
- **Connection / Keys** - token/chat picker and user-account credentials.

## User account (MTProto)

Needs an `api_id`/`api_hash`: <https://my.telegram.org> → log in (code sent **in the app**) → **API development tools** → create an app → copy both. They're yours, not the bot's - keep private. Paste in **Keys**, or:

```bash
python telegram_mtproto.py login   --api-id <ID> --api-hash <HASH> --phone +...
python telegram_mtproto.py members @group --limit 500
python telegram_mtproto.py history @group --limit 1000 -o history.ndjson
```

## CLI

```bash
python telegram_tools_cli.py profile-token    -t <TOKEN>
python telegram_tools_cli.py get-admins       -t <TOKEN> -c <CHAT_ID>
python telegram_tools_cli.py archive-messages -t <TOKEN> -c <CHAT_ID> --auto-start -o dump.ndjson
python telegram_tools_cli.py intel            -i dump.ndjson
```

## License

© 2025 Paul Berra. All Rights Reserved. Non-commercial use, modification and distribution permitted with credit and notice; commercial use prohibited without written permission. Contact: [paul.berra.pro@gmail.com](mailto:paul.berra.pro@gmail.com)
