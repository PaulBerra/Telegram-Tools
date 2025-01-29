# Telegram Bot Scripts

This repository contains various Python scripts designed to interact with the Telegram Bot API. These scripts can be used to generate invitation links, retrieve user and administrator information, and forward or collect messages.

---

## **Available Scripts**

### **1. Invitation Link Generation and User Addition**
**File:** `generate_and_add_users.py`

This script:
- Generates an invitation link for a group or chat.
- Adds a user to a group using their Telegram ID.

**Usage:**
- Set the variables `BOT_TOKEN`, `CHAT_ID`, and `USER_ID`.
- Run the script to generate an invitation link or add a user to the chat.

---

### **2. Fetching Group Administrators**
**File:** `get_chat_administrators.py`

This script:
- Lists all administrators of a given group using the Telegram API.
- Displays first names, last names, usernames, and statuses of the admins.

**Usage:**
- Set `BOT_TOKEN` and `CHAT_ID` with the correct values.
- Run the script to retrieve the administrator list.

---

### **3. Monitoring New Users**
**File:** `listen_for_users.py`

This script:
- Listens for new activity in a Telegram chat.
- Identifies and logs previously unknown users.

**Usage:**
- Configure `BOT_TOKEN` with your bot’s token.
- Run the script for a specified duration to capture new user data.

---

### **4. Retrieve an Invitation Link**
**File:** `get_invite_link.py`

This script:
- Generates an invitation link for a Telegram group.

**Usage:**
- Set `BOT_TOKEN` and `CHAT_ID`.
- Run the script to obtain a valid invitation link.

---

### **5. Retrieving Member Information**
**File:** `get_chat_member.py`

This script:
- Retrieves details about a specific member in a Telegram group.
- Displays first name, last name, status, and username.

**Usage:**
- Set `BOT_TOKEN`, `CHAT_ID`, and `USER_ID`.
- Run the script to get information about the specified user.

---

### **6. Bot Permissions**
**File:** `get_bot_permissions.py`

This script:
- Checks the bot’s permissions in a given group.
- Indicates if the bot is an administrator and lists its privileges (such as pinning messages or managing users).

**Usage:**
- Use `-t` to specify the bot token, and `-c` for the group ID.
- Run the script to view the bot’s current permissions.

---

### **7. Message Forwarding and Collection**
**File:** `forward_and_dump_messages.py`

This script:
- Forwards messages from a Telegram group to itself.
- Collects and saves message data to a JSON file.

**Usage:**
- Use the following arguments:
  - `-t` or `--token` for the bot token.
  - `-c` or `--chat` for the group ID.
  - `-m` or `--message-id` for the starting message ID.
  - `-o` or `--output-file` for the output JSON file.
- Run the script to collect and save messages.

---

## **Installation and Dependencies**

1. **Prerequisites:**
   - Python 3.x
   - `requests` library (for making HTTP requests)

2. **Install dependencies:**
   ```bash
   pip install requests
