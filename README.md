# 🚀 Telegram Tools

A combined **CLI** and **Graphical** application for interacting with the Telegram Bot API. This project provides:

* A **command-line interface** (`telegram_tools_cli.py`) with multiple subcommands to manage Telegram chats, users, and messages.
* A **modern PyQt5 GUI** (`main.py`) that wraps all CLI functionality in a user-friendly, futuristic interface (dark theme, progress indicators, “Stop” buttons, live chat preview, etc.).

---

## Table of Contents

1. [Features](#features)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [CLI Usage](#cli-usage)

   * [Common Arguments](#common-arguments)
   * [Subcommands & Examples](#subcommands--examples)
5. [GUI Usage](#gui-usage)
6. [File Structure](#file-structure)
7. [Contributing](#contributing)
8. [License](#license)

---

## Features

* **Add Members**: Generate an invite link and add a user to a chat.
* **Get Admins**: List all administrators of a chat.
* **Listen Users**: Listen for new users joining a chat for a configurable duration.
* **Get Invite**: Retrieve (and display) a chat’s invite link.
* **Get Member Info**: Fetch and display detailed information about a specific chat member.
* **Get Bot Permissions**: Check what the bot can (or cannot) do in the chat.
* **Dump Messages**: Forward a range of messages (by ID) from a chat into a JSON file, with progress tracking and “stop” capability.
* **Bot Config Panel** (GUI only): Test/validate your bot token (via `getMe`), display the bot’s username and avatar.
* **Chat Preview** (GUI only): Fetch and display the last 20 messages from your chat, with a live filter on message text.
* **Modern PyQt5 GUI**: Dark-themed, responsive, with progress bars, clear/stop buttons, and real-time output console.

---

## Requirements

* **Python 3.8+** (3.9/3.10/3.11 recommended)
* **PyQt5**
* **requests**

You can use a virtual environment to isolate dependencies:

```bash
python3 -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate.bat      # Windows
pip install -r requirements.txt
```

A sample `requirements.txt` (generated via `pip freeze`) might look like:

```
PyQt5==5.15.6
requests==2.31.0
```

---

## Installation (Python)

1. **Clone this repository**

   ```bash
   git clone https://github.com/PaulBerra/Telegram-Tools.git
   cd Telegram-Tools
   ```
2. **Create & activate a virtual environment** (optional but recommended)

   ```bash
   python3 -m venv venv
   source venv/bin/activate        # macOS/Linux
   # venv\Scripts\activate.bat     # Windows
   ```
3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```
4. **Make sure both scripts are executable**

   ```bash
   chmod +x telegram_tools_cli.py
   chmod +x main.py
   ```
## Installation (Windows)


Pour distribuer rapidement l’application sous forme d’un exécutable Windows, suivez ces étapes :

1. **Cloner le dépôt et accéder au dossier**  
   ```powershell
   git clone https://github.com/PaulBerra/Telegram-Tools.git
   cd Telegram-Tools

2. **Créer & activer un environnement virtuel (recommandé)**
   ```powershell
   python -m venv venv
   venv\Scripts\activate

3. **Installer les dépendances**
   ```powershell
   pip install -r requirements.txt

4. **Installer PyInstaller**
   ```powershell
   pip install pyinstaller

5. **Générer l’exécutable**

   Depuis la racine du projet, lancez PyInstaller sur *main.py* :
   
   ```powershell
      pyinstaller --noconfirm --onefile --windowed main.py --icon=logo.ico
   ```
   --onefile : crée un seul fichier .exe.

   --windowed : désactive la console Windows (utile pour une GUI PyQt5).

   --icon=logo.ico : inclut votre icône (convertissez logo.png en logo.ico ou fournissez un .ico).

6. **Tester l’exécutable**

Double-cliquez sur *dist\main.exe*. La fenêtre PyQt5 doit se lancer sans nécessiter Python installé sur la machine cible (venant du bundling avec PyInstaller).

**Remarque** : si vous utilisez des chemins relatifs ou des fichiers supplémentaires (comme telegram_tools_cli.py), assurez-vous de :

Les inclure dans le même dossier dist\ ou ajouter les options "--add-data" à PyInstaller, par exemple :

   ```powershell
      pyinstaller --onefile --windowed --icon=logo.ico `
      --add-data "telegram_tools_cli.py;." `
      main.py
   ```
---

## CLI Usage

The CLI script is named `telegram_tools_cli.py`.  It exposes seven subcommands.  A helpful `-hh` or `--help-examples` flag prints complete usage examples.

### Common Arguments

* `-t, --token <BOT_TOKEN>`
  Your Telegram Bot Token (e.g., `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`).

* `-c, --chat <CHAT_ID>`
  The target chat or group ID (include the leading minus sign if it’s a supergroup, e.g., `-1001122334455`).

---

### Subcommands & Examples

#### 1) `add-members`

Generate an invite link and add a user to a chat.

```bash
python3 telegram_tools_cli.py add-members \
  -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \
  -c -1001122334455 \
  -u 987654321
```

* **`-u <USER_ID>`**  – ID of the user to add.

---

#### 2) `get-admins`

List all administrators of a chat.

```bash
python3 telegram_tools_cli.py get-admins \
  -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \
  -c -1001122334455
```

---

#### 3) `listen-users`

Listen for new users joining a chat for a specified duration.

```bash
# Default duration (60 seconds)
python3 telegram_tools_cli.py listen-users \
  -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \
  -c -1001122334455

# Custom duration (e.g. 120 seconds)
python3 telegram_tools_cli.py listen-users \
  -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \
  -c -1001122334455 \
  -d 120
```

* **`-d <DURATION>`** (optional) – Number of seconds to listen (default 60).

---

#### 4) `get-invite`

Generate and display an invite link for a chat.

```bash
python3 telegram_tools_cli.py get-invite \
  -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \
  -c -1001122334455
```

---

#### 5) `get-member`

Fetch detailed information about a specific chat member.

```bash
python3 telegram_tools_cli.py get-member \
  -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \
  -c -1001122334455 \
  -u 987654321
```

* **`-u <USER_ID>`** – ID of the user to fetch info for.

---

#### 6) `get-rights`

Show the bot’s permissions in a chat.

```bash
python3 telegram_tools_cli.py get-rights \
  -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \
  -c -1001122334455
```

---

#### 7) `dump-messages`

Forward and save a range of messages from `start_message_id` down to `stop_message_id` (or until max iterations). Useful for archiving older conversation history.

```bash
# Dump messages from ID 1010 down to 1, default max_iterations (16000)
python3 telegram_tools_cli.py dump-messages \
  -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \
  -c -1001122334455 \
  -m 1010 \
  -s 1 \
  -o dump.json

# Dump from ID 2000 down to 1500, max 600 iterations
python3 telegram_tools_cli.py dump-messages \
  -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \
  -c -1001122334455 \
  -m 2000 \
  -s 1500 \
  -o partial_dump.json \
  -n 600

# Without a stop ID (will run until max iterations or Ctrl+C)
python3 telegram_tools_cli.py dump-messages \
  -t 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 \
  -c -1001122334455 \
  -m 5000 \
  -o unlimited_dump.json \
  -n 10000
```

* **`-m <START_MESSAGE_ID>`** – The first (highest) message ID to forward.
* **`-s <STOP_MESSAGE_ID>`** (optional) – Stops when `<current_message_id> < STOP_MESSAGE_ID`.
* **`-o <OUTPUT_FILE>`** – Path to the output JSON file.
* **`-n <MAX_ITERATIONS>`** (optional, default 16000) – Maximum number of messages to attempt.

Press **Ctrl+C** at any time to stop the dump; collected messages will still be written to the JSON.

---

## GUI Usage

Launch the PyQt5 GUI by running:

```bash
python3 main.py
```

### Main Window Overview

1. **Sidebar** – Select one of eight tabs:

   * **Bot Config**
   * **Chat Preview**
   * **add-members**, **get-admins**, **listen-users**, **get-invite**, **get-member**, **get-rights**, **dump-messages**
2. **Shared Inputs** – At the top of every form, enter:

   * **Bot Token**
   * **Chat ID**
     These values “sync” across all tabs automatically.
3. **Clear Button** – Clears the output console.
4. **Stop Button** (only in “dump-messages” tab) – Acts like Ctrl+C: aborts the in-progress dump and still writes collected messages.
5. **Progress Bar** – Shows percentage progress while dumping messages.
6. **Console** – Displays live, pretty-printed output (including JSON dumps) from the CLI subprocess.

### Bot Config Tab

* **Test Bot Token** – Click to call `getMe`. If valid, shows your bot’s username and avatar.

### Chat Preview Tab

* **Fetch Last 20 Messages** – Pulls the latest 20 updates from `getUpdates` and populates a table (Msg ID | Date | Text).
* **Filter** – Dynamically hide rows that don’t contain the typed keyword.

### Running Any Command

1. Select the desired tab in the sidebar (e.g. “dump-messages”).
2. Fill in **Bot Token** and **Chat ID** (automatically shared).
3. Fill in any command-specific fields (e.g. “Start Message ID”, “Stop Message ID”, “Output File” for dump-messages).
4. Click **Run <command>**.

   * For `dump-messages`, a **Stop** button becomes enabled—clicking it kills the subprocess.
   * Output appears in the console below, JSON is pretty-printed when possible.
   * Progress bar updates based on “Dump Message ID X” lines.

---

## File Structure

```
Telegram-Tools/
├── main.py                   # PyQt5 GUI
├── telegram_tools_cli.py     # CLI entry-point (multiple subcommands)
├── logo.png                  # Application icon
├── requirements.txt          # pip dependencies (PyQt5, requests)
└── README.md                 # ← (this file)
```

* **`main.py`** – Launches the GUI; wraps all CLI commands as QProcess calls.
* **`telegram_tools_cli.py`** – Implements subcommands for `add-members`, `get-admins`, `listen-users`, `get-invite`, `get-member`, `get-rights`, and `dump-messages`.
* **`logo.png`** – Used as window icon and small logo in each form header.
* **`requirements.txt`** – List of Python packages required.

---

## Contributing

1. Fork this repository.
2. Create a new branch:

   ```bash
   git checkout -b feature/my-new-feature
   ```
3. Install dependencies in your virtual environment.
4. Make your changes, ensuring both CLI and GUI continue to work.
5. Submit a pull request.

Please keep commits focused, include relevant tests/examples, and update this README if you add or modify commands.

---

## License

This project is released under the [MIT License](LICENSE). Feel free to copy, modify, and redistribute as you wish.
