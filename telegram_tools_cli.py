#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import sys
import json
import requests
import time
import signal


# -------------------------------------------------------------------
# 0. Preliminary parser to check for -hh flag
# -------------------------------------------------------------------
pre_parser = argparse.ArgumentParser(add_help=False)
pre_parser.add_argument(
    "-hh", "--help-examples", action="store_true",
    help="Show complete examples for every command and exit"
)
pre_args, remaining_argv = pre_parser.parse_known_args()

if pre_args.help_examples:
    examples = """
Complete Examples for Each Command:

1) add-members
   -----------------------
   Generate an invite link and add a user to a chat.
   - Required: BOT_TOKEN, CHAT_ID, USER_ID

   Usage:
     python3 telegram_tools_cli.py add-members \\
       -t <BOT_TOKEN> \\
       -c <CHAT_ID> \\
       -u <USER_ID>

   Example:
     python3 telegram_tools_cli.py add-members \\
       -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \\
       -c -1001122334455 \\
       -u 987654321

2) get-admins
   -----------------------
   List all administrators of a chat.
   - Required: BOT_TOKEN, CHAT_ID

   Usage:
     python3 telegram_tools_cli.py get-admins \\
       -t <BOT_TOKEN> \\
       -c <CHAT_ID>

   Example:
     python3 telegram_tools_cli.py get-admins \\
       -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \\
       -c -1001122334455

3) listen-users
   -----------------------
   Listen for new users joining a chat for a specified duration.
   - Required: BOT_TOKEN, CHAT_ID
   - Optional: DURATION (seconds, default 60)

   Usage:
     python3 telegram_tools_cli.py listen-users \\
       -t <BOT_TOKEN> \\
       -c <CHAT_ID> \\
       [-d <DURATION>]

   Examples:
     # Default duration (60 seconds)
     python3 telegram_tools_cli.py listen-users \\
       -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \\
       -c -1001122334455

     # Custom duration (120 seconds)
     python3 telegram_tools_cli.py listen-users \\
       -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \\
       -c -1001122334455 \\
       -d 120

4) get-invite
   -----------------------
   Generate and display an invite link for a chat.
   - Required: BOT_TOKEN, CHAT_ID

   Usage:
     python3 telegram_tools_cli.py get-invite \\
       -t <BOT_TOKEN> \\
       -c <CHAT_ID>

   Example:
     python3 telegram_tools_cli.py get-invite \\
       -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \\
       -c -1001122334455

5) get-member
   -----------------------
   Fetch detailed information about a specific chat member.
   - Required: BOT_TOKEN, CHAT_ID, USER_ID

   Usage:
     python3 telegram_tools_cli.py get-member \\
       -t <BOT_TOKEN> \\
       -c <CHAT_ID> \\
       -u <USER_ID>

   Example:
     python3 telegram_tools_cli.py get-member \\
       -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \\
       -c -1001122334455 \\
       -u 987654321

6) get-rights
   -----------------------
   Show the bot's permissions in a chat.
   - Required: BOT_TOKEN, CHAT_ID

   Usage:
     python3 telegram_tools_cli.py get-rights \\
       -t <BOT_TOKEN> \\
       -c <CHAT_ID>

   Example:
     python3 telegram_tools_cli.py get-rights \\
       -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \\
       -c -1001122334455

7) dump-messages
   -----------------------
   Forward and save messages from a starting ID down to a stop ID (or until max iterations).
   - Required: BOT_TOKEN, CHAT_ID, START_MESSAGE_ID, OUTPUT_FILE
   - Optional: STOP_MESSAGE_ID, MAX_ITERATIONS

   Usage:
     python3 telegram_tools_cli.py dump-messages \\
       -t <BOT_TOKEN> \\
       -c <CHAT_ID> \\
       -m <START_MESSAGE_ID> \\
       -o <OUTPUT_FILE> \\
       [-s <STOP_MESSAGE_ID>] \\
       [-n <MAX_ITERATIONS>]

   Examples:
     # Descending from 1010 down to 1, default max_iterations (16000)
     python3 telegram_tools_cli.py dump-messages \\
       -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \\
       -c -1001122334455 \\
       -m 1010 \\
       -s 1 \\
       -o dump.json

     # Descending from 2000 down to 1500, max 600 iterations
     python3 telegram_tools_cli.py dump-messages \\
       -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \\
       -c -1001122334455 \\
       -m 2000 \\
       -s 1500 \\
       -o partial_dump.json \\
       -n 600

     # Without a stop ID (will run until max_iterations or Ctrl+C)
     python3 telegram_tools_cli.py dump-messages \\
       -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \\
       -c -1001122334455 \\
       -m 5000 \\
       -o unlimited_dump.json \\
       -n 10000

     # Press Ctrl+C at any time to save progress to the specified output file.
"""
    print(examples.strip())
    sys.exit(0)


# -------------------------------------------------------------------
# 1. Functions extracted/refactored from individual scripts
# -------------------------------------------------------------------

def generate_and_add_user(bot_token: str, chat_id: int, user_id: int):
    """
    Generates an invite link for the chat, then adds the specified user.
    """
    # 1. Generate the invite link
    url_invite = f"https://api.telegram.org/bot{bot_token}/exportChatInviteLink?chat_id={chat_id}"
    resp = requests.get(url_invite)
    if not resp.ok:
        print(f"[ERROR] Failed to generate invite link: {resp.text}", file=sys.stderr)
        return
    invite_link = resp.json().get("result")
    print(f"[INVITE LINK GENERATED] {invite_link}")

    # 2. Add the user to the chat
    url_add = f"https://api.telegram.org/bot{bot_token}/inviteChatMember"
    params = {"chat_id": chat_id, "user_id": user_id}
    resp_add = requests.post(url_add, data=params)
    data_add = resp_add.json()
    if data_add.get("ok"):
        print(f"[SUCCESS] User {user_id} added to chat {chat_id}.")
    else:
        print(f"[ERROR] Could not add user {user_id}: {data_add}", file=sys.stderr)


def list_chat_administrators(bot_token: str, chat_id: int):
    """
    Lists all administrators of a Telegram chat (group).
    """
    url = f"https://api.telegram.org/bot{bot_token}/getChatAdministrators?chat_id={chat_id}"
    resp = requests.get(url)
    if not resp.ok:
        print(f"[ERROR] {resp.text}", file=sys.stderr)
        return
    admins = resp.json().get("result", [])
    print("Chat Administrators:")
    for adm in admins:
        user = adm.get("user", {})
        status = adm.get("status")
        print(f" · {user.get('first_name','')} {user.get('last_name','')} "
              f"(@{user.get('username','')}) – role: {status}")


def listen_for_new_users(bot_token: str, chat_id: int, timeout: int = 60):
    """
    Listens to incoming updates for 'timeout' seconds and prints new users as they join.
    """
    offset = 0
    print(f"[INFO] Listening for new users in chat {chat_id} for {timeout} seconds...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        params = {"timeout": 10, "offset": offset}
        resp = requests.get(url, params=params)
        if not resp.ok:
            print(f"[ERROR] getUpdates failed: {resp.text}", file=sys.stderr)
            break
        updates = resp.json().get("result", [])
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message", {})
            new_members = msg.get("new_chat_members", [])
            for new_user in new_members:
                print(f"[NEW USER] ID: {new_user.get('id')} – "
                      f"{new_user.get('first_name')} {new_user.get('last_name')} "
                      f"(@{new_user.get('username','')})")
    print("[INFO] Listening finished.")


def get_invite_link(bot_token: str, chat_id: int):
    """
    Generates and prints an invite link for the chat.
    """
    url = f"https://api.telegram.org/bot{bot_token}/exportChatInviteLink?chat_id={chat_id}"
    resp = requests.get(url)
    if not resp.ok:
        print(f"[ERROR] {resp.text}", file=sys.stderr)
        return
    link = resp.json().get("result")
    print(f"[INVITE LINK] {link}")


def get_chat_member_info(bot_token: str, chat_id: int, user_id: int):
    """
    Fetches and prints info about a specific chat member.
    """
    url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
    params = {"chat_id": chat_id, "user_id": user_id}
    resp = requests.get(url, params=params)
    if not resp.ok:
        print(f"[ERROR] {resp.text}", file=sys.stderr)
        return
    info = resp.json().get("result", {})
    user = info.get("user", {})
    status = info.get("status")
    print(f"[MEMBER INFO] ID: {user.get('id')} | "
          f"First Name: {user.get('first_name')} | "
          f"Last Name: {user.get('last_name')} | "
          f"Username: @{user.get('username','')} | "
          f"Status: {status}")


def get_bot_permissions(bot_token: str, chat_id: int):
    """
    Checks and prints the bot's permissions in a given chat.
    """
    url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
    bot_user_id = bot_token.split(":")[0]
    params = {"chat_id": chat_id, "user_id": bot_user_id}
    resp = requests.get(url, params=params)
    if not resp.ok:
        print(f"[ERROR] {resp.text}", file=sys.stderr)
        return
    res = resp.json().get("result", {})
    status = res.get("status")
    print(f"[BOT STATUS] Status in chat: {status}")
    if status in ("administrator", "creator"):
        can_pin = res.get("can_pin_messages")
        can_invite = res.get("can_invite_users")
        can_delete = res.get("can_delete_messages")
        print(f"Permissions: can_pin_messages={can_pin}, can_invite_users={can_invite}, can_delete_messages={can_delete}")
    else:
        print("[INFO] Bot is not an administrator; no detailed permissions available.")


# -------------------------------------------------------------------
# 2. Enhanced dump_messages with KeyboardInterrupt and stop‐id
# -------------------------------------------------------------------

# Global list to collect all successful forwarded message objects
collected_messages = []


def forward_message(bot_token: str, chat_id: str, message_id: int):
    """
    Forwards a single message with message_id from chat_id back to chat_id.
    Returns the 'result' field (Telegram message object) on success, None on failure.
    """
    url = f"https://api.telegram.org/bot{bot_token}/forwardMessage"
    payload = {
        "from_chat_id": chat_id,
        "chat_id": chat_id,
        "message_id": message_id
    }
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers)
    except requests.RequestException as e:
        print(f"[ERROR] Request failed for message {message_id}: {e}", file=sys.stderr)
        return None

    if response.status_code == 200:
        print(f"[OK] Message {message_id} forwarded successfully.")
        return response.json().get("result")  # Only store the message object :contentReference[oaicite:4]{index=4}
    elif response.status_code == 429:
        # Rate‐limited: wait and retry
        print("[WARN] Rate limit encountered (429). Sleeping 15 seconds...", file=sys.stderr)
        time.sleep(15)
        return forward_message(bot_token, chat_id, message_id)
    else:
        print(f"[ERROR] Failed to forward message {message_id}: "
              f"{response.status_code} – {response.text}", file=sys.stderr)
        return None


def save_collected_messages(output_file: str):
    """
    Writes the collected_messages list into output_file as JSON. If no messages,
    prints an informational note instead of creating an empty file.
    """
    if not collected_messages:
        print("[INFO] No messages were collected. Exiting without writing file.", file=sys.stderr)
        return

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(collected_messages, f, ensure_ascii=False, indent=4)
        print(f"[DONE] {len(collected_messages)} messages written to '{output_file}'.")
    except IOError as e:
        print(f"[ERROR] Failed to write to {output_file}: {e}", file=sys.stderr)


def handle_interrupt(signum, frame):
    """
    Signal handler for SIGINT (Ctrl+C). Saves collected messages and exits.
    """
    print("\n[INFO] KeyboardInterrupt detected. Saving collected messages...", file=sys.stderr)
    # Use the OUTPUT_FILE from outer scope by setting a sentinel
    save_collected_messages(OUTPUT_FILE_GLOBAL)
    sys.exit(0)


def dump_messages(bot_token: str, chat_id: str, start_id: int, stop_id: int or None,
                  output_file: str, max_iters: int = 16000):
    """
    Iteratively forwards messages from 'start_id' downward. Stops if:
      • message_id < stop_id (if stop_id is provided)
      • reached max_iters
      • user presses Ctrl+C
    """
    global OUTPUT_FILE_GLOBAL
    OUTPUT_FILE_GLOBAL = output_file  # For use in the signal handler

    message_id = start_id
    iteration = 0
    print(f"[INFO] Starting dump from message ID {start_id}", file=sys.stderr)
    if stop_id is not None:
        print(f"[INFO] Will stop when message_id < {stop_id}", file=sys.stderr)
    print(f"[INFO] Max iterations = {max_iters}", file=sys.stderr)
    print("Press Ctrl+C to stop at any time and save progress.\n", file=sys.stderr)

    # Register the Ctrl+C signal handler
    signal.signal(signal.SIGINT, handle_interrupt)  # :contentReference[oaicite:5]{index=5}

    while iteration < max_iters:
        if stop_id is not None and message_id < stop_id:
            print(f"[INFO] Reached stop_id threshold ({stop_id}). Stopping.", file=sys.stderr)
            break

        result = forward_message(bot_token, chat_id, message_id)
        if result:
            collected_messages.append(result)
        else:
            print(f"[WARN] Message {message_id} not found or error. Continuing...", file=sys.stderr)

        message_id -= 1
        iteration += 1

    # After the loop (either normal or due to stop condition), write out the JSON
    save_collected_messages(output_file)  # :contentReference[oaicite:6]{index=6}


# -------------------------------------------------------------------
# 3. CLI parser configuration with argparse (all in English)
# -------------------------------------------------------------------

def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="telegram-tools",
        description=(
            "CLI for interacting with Telegram Bot API.\n\n"
            "Add -hh or --help-examples to see complete usage examples for each command."
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "-hh", "--help-examples", action="store_true",
        help=argparse.SUPPRESS
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Common arguments
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-t", "--token", dest="token", required=True,
        help="Bot authentication token"
    )
    common.add_argument(
        "-c", "--chat", dest="chat", type=int, required=True,
        help="Telegram chat/group ID (include leading minus if needed)"
    )

    # add-members
    parser_add = subparsers.add_parser(
        "add-members", help="Generate invite link & add a user", parents=[common]
    )
    parser_add.add_argument(
        "-u", "--user", dest="user", type=int, required=True,
        help="ID of the user to add"
    )

    # get-admins
    parser_admins = subparsers.add_parser(
        "get-admins", help="List chat administrators", parents=[common]
    )

    # listen-users
    parser_listen = subparsers.add_parser(
        "listen-users", help="Listen and show new users", parents=[common]
    )
    parser_listen.add_argument(
        "-d", "--duration", dest="duration", type=int, default=60,
        help="Seconds to listen for new users (default: 60s)"
    )

    # get-invite
    parser_link = subparsers.add_parser(
        "get-invite", help="Generate & display invite link", parents=[common]
    )

    # get-member
    parser_member = subparsers.add_parser(
        "get-member", help="Fetch info for a chat member", parents=[common]
    )
    parser_member.add_argument(
        "-u", "--user", dest="user", type=int, required=True,
        help="ID of the user to fetch info for"
    )

    # get-rights
    parser_rights = subparsers.add_parser(
        "get-rights", help="Show bot permissions in chat", parents=[common]
    )

    # dump-messages
    parser_dump = subparsers.add_parser(
        "dump-messages", help="Forward & save messages to JSON", parents=[common]
    )
    parser_dump.add_argument(
        "-m", "--message-id", dest="message_id", type=int, required=True,
        help="ID of the first (highest) message to forward"
    )
    parser_dump.add_argument(
        "-s", "--stop-id", dest="stop_id", type=int, default=None,
        help="Optional: ID of the last message (inclusive). Stops when message_id < stop_id."
    )
    parser_dump.add_argument(
        "-o", "--output-file", dest="output_file", type=str, required=True,
        help="Path to JSON output file"
    )
    parser_dump.add_argument(
        "-n", "--max-iterations", dest="max_iterations", type=int, default=16000,
        help="Maximum number of messages to attempt (default: 16000)"
    )

    return parser


# -------------------------------------------------------------------
# 4. main() function to dispatch calls
# -------------------------------------------------------------------

def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.command == "add-members":
        generate_and_add_user(args.token, args.chat, args.user)

    elif args.command == "get-admins":
        list_chat_administrators(args.token, args.chat)

    elif args.command == "listen-users":
        listen_for_new_users(args.token, args.chat, timeout=args.duration)

    elif args.command == "get-invite":
        get_invite_link(args.token, args.chat)

    elif args.command == "get-member":
        get_chat_member_info(args.token, args.chat, args.user)

    elif args.command == "get-rights":
        get_bot_permissions(args.token, args.chat)

    elif args.command == "dump-messages":
        dump_messages(
            bot_token=args.token,
            chat_id=str(args.chat),
            start_id=args.message_id,
            stop_id=args.stop_id,
            output_file=args.output_file,
            max_iters=args.max_iterations
        )

    else:
        print("[ERROR] Unknown command. Use --help to see available subcommands.", file=sys.stderr)
        sys.exit(1)


# -------------------------------------------------------------------
# 5. Entry point
# -------------------------------------------------------------------

if __name__ == "__main__":
    main()
