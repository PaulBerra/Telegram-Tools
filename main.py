#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import json
import requests
from PyQt5.QtCore import (
    Qt, QSize, QProcess, QTimer, pyqtSlot, QRegExp
)
from PyQt5.QtGui import (
    QFont, QColor, QIcon, QPixmap, QStandardItemModel, QStandardItem, QRegExpValidator
)
from PyQt5.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QListWidget,
    QListWidgetItem, QLabel, QLineEdit, QPushButton, QTextEdit,
    QStackedWidget, QFrame, QFileDialog, QProgressBar, QMessageBox,
    QTableView, QHeaderView, QAbstractItemView
)

# -------------------------------------------------------------------
# 1. Load and apply a dark QSS stylesheet for a futuristic look
# -------------------------------------------------------------------
def load_stylesheet(app):
    qss = """
    /* Main window */
    QWidget#MainWindow {
        background-color: #121212;
        color: #E0E0E0;
        border-radius: 8px;
    }

    /* Sidebar panel */
    QFrame#SideBar {
        background-color: #1E1E2E;
        border-top-left-radius: 8px;
        border-bottom-left-radius: 8px;
    }

    /* Sidebar items */
    QListWidget {
        background-color: transparent;
        border: none;
    }
    QListWidget::item {
        padding: 12px 20px;
        color: #BBBBBB;
    }
    QListWidget::item:selected {
        background-color: #323248;
        color: #FFFFFF;
        border-left: 4px solid #448AFF;
    }

    /* Command form labels and line edits */
    QLabel {
        font-size: 14px;
        color: #E0E0E0;
    }
    QLineEdit {
        background-color: #1E1E2E;
        border: 1px solid #33334D;
        border-radius: 4px;
        padding: 6px;
        color: #FFFFFF;
    }
    QLineEdit:focus {
        border: 1px solid #448AFF;
    }

    /* Buttons */
    QPushButton {
        background-color: #448AFF;
        color: #FFFFFF;
        border: none;
        border-radius: 4px;
        padding: 8px 16px;
        font-size: 14px;
    }
    QPushButton:hover {
        background-color: #2979FF;
    }
    QPushButton:pressed {
        background-color: #2962FF;
    }

    /* Progress Bar */
    QProgressBar {
        text-align: center;
        color: #E0E0E0;
        border: 1px solid #33334D;
        border-radius: 4px;
        background-color: #1E1E2E;
    }
    QProgressBar::chunk {
        background-color: #448AFF;
        width: 10px;
    }

    /* Output console */
    QTextEdit#Console {
        background-color: #21212B;
        border: 1px solid #33334D;
        border-radius: 4px;
        padding: 8px;
        font-family: "Courier New", monospace;
        font-size: 12px;
        color: #00FF92;
    }
    """
    app.setStyleSheet(qss)

# -------------------------------------------------------------------
# 2. Main Window
# -------------------------------------------------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("MainWindow")
        self.setWindowTitle("🚀 Telegram Tools GUI")
        self.setWindowIcon(QIcon("logo.png"))  # Make sure “logo.png” is present
        self.resize(1200, 700)

        # Store token and chat ID centrally
        self.bot_token = ""
        self.chat_id = ""
        self.proc = None
        self.stop_buttons = {}

        # Main layout: Sidebar + Vertical Splitter (forms / console)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Sidebar
        self.sidebar = QFrame(self)
        self.sidebar.setObjectName("SideBar")
        self.sidebar.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)

        # List of commands (including new tabs)
        self.command_list = QListWidget(self.sidebar)
        # Add “Bot Config” and “Chat Preview” to the top
        commands = [
            "Bot Config", "Chat Preview",
            "add-members", "get-admins", "listen-users",
            "get-invite", "get-member", "get-rights", "dump-messages"
        ]
        self.int_validator = QRegExpValidator(QRegExp(r"\d+"))
        for cmd in commands:
            item = QListWidgetItem(cmd)
            item.setSizeHint(QSize(220, 40))
            self.command_list.addItem(item)

        sidebar_layout.addWidget(self.command_list)
        main_layout.addWidget(self.sidebar)

        # Stacked widget for forms
        self.stack = QStackedWidget(self)
        main_layout.addWidget(self.stack, 1)

        # Console output at bottom
        console_frame = QFrame(self)
        console_frame.setFixedHeight(200)
        console_frame.setObjectName("ConsoleFrame")
        console_layout = QVBoxLayout(console_frame)
        console_layout.setContentsMargins(8, 4, 8, 8)
        console_label = QLabel("Output Console:")
        console_label.setFont(QFont("Arial", 12, QFont.Bold))
        # Clear button for console
        clear_btn = QPushButton("Clear")
        clear_btn.setMaximumWidth(80)
        clear_btn.clicked.connect(self.clear_console)

        # Layout for label and clear button
        header_h = QHBoxLayout()
        header_h.addWidget(console_label)
        header_h.addStretch()
        header_h.addWidget(clear_btn)
        console_layout.addLayout(header_h)

        self.console = QTextEdit(console_frame)
        self.console.setObjectName("Console")
        self.console.setReadOnly(True)
        console_layout.addWidget(self.console)

        # Container: vertical layout containing the stack + console
        container = QWidget(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.stack)
        container_layout.addWidget(console_frame)
        main_layout.addWidget(container, 4)

        # Initialize forms for each command
        self.forms = {}
        for cmd in commands:
            form = self.build_form(cmd)
            self.forms[cmd] = form
            self.stack.addWidget(form)

        # Connect sidebar selection to stack index
        self.command_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.command_list.setCurrentRow(0)

        # Validators
        self.int_validator = QRegExpValidator(QRegExp(r"\d+"))

    # -------------------------------------------
    # 2.1. Build a dynamic form for each command
    # -------------------------------------------
    def build_form(self, cmd):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Title + optional logo on each form
        header_layout = QHBoxLayout()
        logo = QLabel()
        pixmap = QPixmap("logo.png").scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        logo.setPixmap(pixmap)
        title = QLabel(f"<span style='font-size:18pt; font-weight:600;'>Telegram Tools – {cmd}</span>")
        header_layout.addWidget(logo)
        header_layout.addSpacing(8)
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Shared token & chat: populate from central variables
        token_label = QLabel("Bot Token:")
        self.token_line = QLineEdit(self.bot_token)
        self.token_line.setPlaceholderText("Enter Bot Token here")
        chat_label = QLabel("Chat ID:")
        self.chat_line = QLineEdit(self.chat_id)
        self.chat_line.setPlaceholderText("Enter Chat ID here")
        # When either changes, update central storage and replicate to other forms
        self.token_line.textChanged.connect(self.sync_token)
        self.chat_line.textChanged.connect(self.sync_chat)

        layout.addWidget(token_label)
        layout.addWidget(self.token_line)
        layout.addWidget(chat_label)
        layout.addWidget(self.chat_line)

        # Command-specific inputs
        if cmd == "Bot Config":
            # Test token + show bot info
            test_btn = QPushButton("Test Bot Token")
            test_btn.clicked.connect(self.test_bot_token)
            self.bot_info_label = QLabel("Bot info will appear here.")
            self.bot_avatar = QLabel()
            self.bot_avatar.setFixedSize(80, 80)
            avatar_layout = QHBoxLayout()
            avatar_layout.addWidget(self.bot_avatar)
            avatar_layout.addWidget(self.bot_info_label)
            avatar_layout.addStretch()
            layout.addSpacing(12)
            layout.addWidget(test_btn)
            layout.addLayout(avatar_layout)

        elif cmd == "Chat Preview":
            preview_btn = QPushButton("Fetch Last 20 Messages")
            preview_btn.clicked.connect(self.fetch_chat_preview)
            filter_label = QLabel("Filter (keyword):")
            self.filter_line = QLineEdit()
            self.filter_line.setPlaceholderText("Type to filter…")
            self.filter_line.textChanged.connect(self.apply_filter)

            layout.addSpacing(12)
            layout.addWidget(preview_btn)
            layout.addWidget(filter_label)
            layout.addWidget(self.filter_line)

            # Table view for messages
            self.table_model = QStandardItemModel(0, 3, self)
            self.table_model.setHorizontalHeaderLabels(["Msg ID", "Date", "Text"])
            self.table_view = QTableView()
            self.table_view.setModel(self.table_model)
            self.table_view.horizontalHeader().setStretchLastSection(True)
            self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
            layout.addWidget(self.table_view)

        else:
            # All other commands: same as before
            # Each will need a “Run” button, a Stop button (for dump-messages), a progress bar, etc.
            if cmd == "add-members":
                self.user_id_line = QLineEdit()
                self.user_id_line.setPlaceholderText("User ID to add")
                self.user_id_line.setValidator(self.int_validator)
                layout.addWidget(QLabel("User ID:"))
                layout.addWidget(self.user_id_line)

            elif cmd == "get-admins":
                pass  # no extra inputs

            elif cmd == "listen-users":
                self.duration_line = QLineEdit()
                self.duration_line.setPlaceholderText("Duration (seconds, default 60)")
                self.duration_line.setValidator(self.int_validator)
                layout.addWidget(QLabel("Duration:"))
                layout.addWidget(self.duration_line)

            elif cmd == "get-invite":
                pass  # no extra inputs

            elif cmd == "get-member":
                self.member_id_line = QLineEdit()
                self.member_id_line.setPlaceholderText("User ID to fetch info")
                self.member_id_line.setValidator(self.int_validator)
                layout.addWidget(QLabel("User ID:"))
                layout.addWidget(self.member_id_line)

            elif cmd == "get-rights":
                pass  # no extra inputs

            elif cmd == "dump-messages":
                self.start_id_line = QLineEdit()
                self.start_id_line.setPlaceholderText("Start Message ID")
                self.start_id_line.setValidator(self.int_validator)
                self.stop_id_line = QLineEdit()
                self.stop_id_line.setPlaceholderText("Stop Message ID (optional)")
                self.stop_id_line.setValidator(self.int_validator)
                self.output_file_line = QLineEdit()
                self.output_file_line.setPlaceholderText("Output JSON file path")
                browse_btn = QPushButton("Browse...")
                browse_btn.clicked.connect(lambda: self.browse_file(self.output_file_line))
                layout.addWidget(QLabel("Start Message ID:"))
                layout.addWidget(self.start_id_line)
                layout.addWidget(QLabel("Stop Message ID (optional):"))
                layout.addWidget(self.stop_id_line)
                layout.addWidget(QLabel("Output File:"))
                layout.addWidget(self.output_file_line)
                layout.addWidget(browse_btn)

            # Add a progress bar for long commands
            self.progress = QProgressBar()
            self.progress.setValue(0)
            self.progress.setHidden(True)
            layout.addSpacing(10)
            layout.addWidget(self.progress)

            # Run and Stop buttons
            run_btn = QPushButton(f"Run {cmd}")
            run_btn.clicked.connect(lambda _, c=cmd: self.run_command(c))
            layout.addWidget(run_btn)

            if cmd == "dump-messages":
                stop_btn = QPushButton("Stop")
                stop_btn.setEnabled(False)
                stop_btn.clicked.connect(lambda _, c=cmd: self.stop_process(c))
                layout.addWidget(stop_btn)
                self.stop_buttons[cmd] = stop_btn

        layout.addStretch()
        return widget

    # -------------------------------------------
    # 2.2. Synchronize token/chat across all forms
    # -------------------------------------------
    def sync_token(self, text):
        self.bot_token = text
        # Update every form’s token_line
        for form in self.forms.values():
            line = form.findChild(QLineEdit)  # first QLineEdit is token
            if line and line.text() != text:
                line.blockSignals(True)
                line.setText(text)
                line.blockSignals(False)

    def sync_chat(self, text):
        self.chat_id = text
        for form in self.forms.values():
            # find the second QLineEdit (chat_id)
            lines = form.findChildren(QLineEdit)
            if len(lines) > 1 and lines[1].text() != text:
                lines[1].blockSignals(True)
                lines[1].setText(text)
                lines[1].blockSignals(False)

    # -------------------------------------------
    # 2.3. Browse for output file path
    # -------------------------------------------
    def browse_file(self, line_edit: QLineEdit):
        path, _ = QFileDialog.getSaveFileName(
            self, "Select Output File", "", "JSON Files (*.json);;All Files (*)"
        )
        if path:
            line_edit.setText(path)

    # -------------------------------------------
    # 2.4. Clear console
    # -------------------------------------------
    def clear_console(self):
        self.console.clear()

    # -------------------------------------------
    # 2.5. Stop process (like Ctrl+C)
    # -------------------------------------------
    def stop_process(self, cmd):
        if self.proc and self.proc.state() == QProcess.Running:
            self.proc.kill()
            self.console.append("[INFO] dump-messages stopped by user.")
        stop_btn = self.stop_buttons.get(cmd)
        if stop_btn:
            stop_btn.setEnabled(False)

    # -------------------------------------------------------------------
    # 2.6. Asynchronous Execution & Progress Indicators
    # Run selected command using QProcess; parse “dump-messages” progress
    # -------------------------------------------------------------------
    def run_command(self, cmd):
        # Validate shared inputs
        token = self.bot_token.strip()
        chat = self.chat_id.strip()
        if not token or not chat:
            self.console.append("[ERROR] Bot Token and Chat ID are required.")
            return

        # Build base command
        base_cmd = ["python3", "telegram_tools_cli.py", cmd, "-t", token, "-c", chat]

        # Add command-specific flags
        current_form = self.forms[cmd]
        if cmd == "add-members":
            user = current_form.findChild(QLineEdit, None, Qt.FindDirectChildrenOnly).text().strip()
            if not user:
                self.console.append("[ERROR] User ID is required.")
                return
            base_cmd += ["-u", user]

        elif cmd == "listen-users":
            duration = current_form.findChildren(QLineEdit)[2].text().strip()
            if duration:
                base_cmd += ["-d", duration]

        elif cmd == "get-member":
            member_id = current_form.findChildren(QLineEdit)[2].text().strip()
            if not member_id:
                self.console.append("[ERROR] User ID is required.")
                return
            base_cmd += ["-u", member_id]

        elif cmd == "dump-messages":
            start_id = current_form.findChildren(QLineEdit)[2].text().strip()
            output_file = current_form.findChildren(QLineEdit)[4].text().strip()
            if not start_id or not output_file:
                self.console.append("[ERROR] Start ID and Output File are required.")
                return
            base_cmd += ["-m", start_id]
            stop_id = current_form.findChildren(QLineEdit)[3].text().strip()
            if stop_id:
                base_cmd += ["-s", stop_id]
            base_cmd += ["-o", output_file]
            # Show progress bar
            self.progress = current_form.findChild(QProgressBar)
            self.progress.setValue(0)
            self.progress.setHidden(False)
            # Enable Stop button
            stop_btn = self.stop_buttons.get(cmd)
            if stop_btn:
                stop_btn.setEnabled(True)

        # Echo command
        self.console.append(f"[CMD] {' '.join(base_cmd).split('.py')[1].split('-t')[0]}")

        # Launch with QProcess
        self.proc = QProcess(self)
        self.proc.setProgram(base_cmd[0])
        self.proc.setArguments(base_cmd[1:])
        self.proc.readyReadStandardOutput.connect(lambda: self.on_stdout(cmd))
        self.proc.readyReadStandardError.connect(self.on_stderr)
        self.proc.finished.connect(lambda exitCode, _: self.on_finished(cmd, exitCode))
        self.proc.start()

    @pyqtSlot()
    def on_stdout(self, cmd):
        data = self.proc.readAllStandardOutput().data().decode()
        for raw_line in data.splitlines():
            line = raw_line.strip()
            # Attempt to pretty-print JSON
            if line.startswith("{") or line.startswith("["):
                try:
                    parsed = json.loads(line)
                    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
                    self.console.append(pretty)
                    continue
                except Exception:
                    pass
            # Otherwise, display the raw line
            self.console.append(line)

            # If cmd == dump-messages, look for “Dump Message ID X” to update progress
            if cmd == "dump-messages" and "Dump Message ID" in line:
                try:
                    parts = line.split()
                    msg_id = int(parts[-1])
                    form = self.forms[cmd]
                    start_id = int(form.findChildren(QLineEdit)[2].text().strip())
                    stop_id_text = form.findChildren(QLineEdit)[3].text().strip()
                    stop_id = int(stop_id_text) if stop_id_text else 0
                    total = start_id - stop_id + 1 if stop_id else start_id
                    done = start_id - msg_id + 1
                    percent = int(done / total * 100) if total > 0 else 0
                    self.progress.setValue(min(max(percent, 0), 100))
                except:
                    pass

    @pyqtSlot()
    def on_stderr(self):
        data = self.proc.readAllStandardError().data().decode()
        for line in data.splitlines():
            self.console.append(f"[ERR] {line}")

    def on_finished(self, cmd, exitCode):
        if cmd == "dump-messages":
            self.progress.setValue(100)
            # Disable Stop button
            stop_btn = self.stop_buttons.get(cmd)
            if stop_btn:
                stop_btn.setEnabled(False)
        if exitCode != 0:
            self.console.append(f"[ERROR] '{cmd}' exited with code {exitCode}")
        else:
            self.console.append(f"[INFO] '{cmd}' completed successfully.")
        # Hide progress bar after a short delay
        if cmd == "dump-messages":
            QTimer.singleShot(1500, lambda: self.progress.setHidden(True))

    # -------------------------------------------------------------------
    # 2.7. Integrated Bot Configuration Panel
    # Test token with getMe and display bot username + avatar
    # -------------------------------------------------------------------
    def test_bot_token(self):
        form = self.forms["Bot Config"]
        token = form.findChildren(QLineEdit)[0].text().strip()
        if not token:
            QMessageBox.warning(self, "Input Error", "Please enter a Bot Token.")
            return
        self.console.append("[INFO] Testing Bot Token…")
        url = f"https://api.telegram.org/bot{token}/getMe"
        try:
            resp = requests.get(url, timeout=5)
            data = resp.json()
            if not data.get("ok"):
                QMessageBox.critical(self, "Token Invalid", f"Error: {data.get('description', 'Unknown')}")
                self.console.append(f"[ERROR] Token test failed: {data.get('description')}")
                return
            result = data["result"]
            bot_name = result.get("username", "<unknown>")
            form.findChild(QLabel, None).setText(f"<b>Bot:</b> @{bot_name}")
            # Fetch avatar (if exists)
            user_id = result.get("id")
            photos_url = f"https://api.telegram.org/bot{token}/getUserProfilePhotos?user_id={user_id}&limit=1"
            p_resp = requests.get(photos_url)
            p_data = p_resp.json()
            if p_data.get("ok") and p_data["result"]["total_count"] > 0:
                # get file_id of first photo
                file_id = p_data["result"]["photos"][0][-1]["file_id"]
                af_resp = requests.get(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}")
                af_data = af_resp.json()
                file_path = af_data["result"]["file_path"]
                file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                pic_data = requests.get(file_url).content
                pixmap = QPixmap()
                pixmap.loadFromData(pic_data)
                form.findChild(QLabel).setPixmap(pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.console.append(f"[INFO] Bot @{bot_name} is valid.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to reach Telegram API:\n{e}")
            self.console.append(f"[ERROR] Exception during token test: {e}")

    # -------------------------------------------------------------------
    # 2.8. Chat Preview & Message Filtering
    # Fetch last 20 messages and populate table; apply filter on text
    # -------------------------------------------------------------------
    def fetch_chat_preview(self):
        form = self.forms["Chat Preview"]
        token = form.findChildren(QLineEdit)[0].text().strip()
        chat = form.findChildren(QLineEdit)[1].text().strip()
        if not token or not chat:
            QMessageBox.warning(self, "Input Error", "Bot Token and Chat ID are required.")
            return
        self.console.append("[INFO] Fetching last 20 messages…")
        url = f"https://api.telegram.org/bot{token}/getUpdates?limit=20"
        try:
            resp = requests.get(url, timeout=5)
            data = resp.json()
            if not data.get("ok"):
                QMessageBox.critical(self, "API Error", f"{data.get('description', 'Unknown error')}")
                self.console.append(f"[ERROR] getUpdates failed: {data.get('description')}")
                return
            updates = data["result"]
            self.table_model.removeRows(0, self.table_model.rowCount())
            for upd in updates:
                if "message" in upd:
                    msg = upd["message"]
                    msg_id = msg.get("message_id", "")
                    date = msg.get("date", "")
                    text = msg.get("text", "") or msg.get("caption", "")
                    items = [
                        QStandardItem(str(msg_id)),
                        QStandardItem(str(date)),
                        QStandardItem(text)
                    ]
                    self.table_model.appendRow(items)
            self.console.append("[INFO] Chat preview updated.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to fetch updates:\n{e}")
            self.console.append(f"[ERROR] Exception during preview: {e}")

    def apply_filter(self, text):
        # Simple filter: hide rows not containing text in the “Text” column
        for row in range(self.table_model.rowCount()):
            index = self.table_model.index(row, 2)  # “Text” column
            cell_text = self.table_model.data(index)
            should_show = True if text.lower() in cell_text.lower() else False
            self.table_view.setRowHidden(row, not should_show)

# -------------------------------------------------------------------
# 3. Application entry point
# -------------------------------------------------------------------
def main():
    # Set High DPI scaling before creating QApplication
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    load_stylesheet(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
