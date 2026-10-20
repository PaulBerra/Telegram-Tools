"""PyQt6 GUI - calls the shared core in-process (no subprocess, never freezes).

Layout: a persistent connection bar (token + chat, validated once and shared),
a sidebar grouped by intent, a stack of pages, and a collapsible log drawer.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional

# What a Telegram bot token looks like: digits ":" then a long opaque string.
_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QAction, QColor, QFont, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..cli import _chat_arg
from ..core import TelegramClient, api, archive, intel, rights_check
from .charts import HBarList, TimeBars, stat_tile
from .export import build_export_button, style_menu
from .icons import app_icon, make_icon
from . import store
from . import theme
from .theme import (QSS, MENU_QSS, ACCENT, BG, BORDER, DANGER, SURFACE, SURFACE_2,
                    SUCCESS, SYS_PILL, TEXT, TEXT_MUTED, WARNING)


def styled_menu(parent=None) -> "QMenu":
    return style_menu(QMenu(parent))


class DeletableMenu(QMenu):
    """A styled popup whose entries can be removed with a right-click.

    Right-clicking an entry calls the delete handler with that action's data and
    closes the popup; left-click still triggers the action as usual. Used for the
    saved-token and known-chat pickers so you can forget an entry in place.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._on_delete = None

    def set_delete_handler(self, fn) -> None:
        self._on_delete = fn

    def contextMenuEvent(self, event):
        # Right-click over an entry removes it instead of opening a nested menu.
        if self._on_delete is not None:
            act = self.actionAt(event.pos())
            if act is not None and act.data() is not None:
                self.close()
                self._on_delete(act.data())
                event.accept()
                return
        event.accept()  # never show Qt's default (empty) context menu here


from .workers import (ArchiveWorker, BackfillWorker, CallWorker, GeneratorWorker,
                      UpdatesPoller)

ICON = QSize(16, 16)


def icon_button(text: str, icon_name: str, *, primary: bool = False) -> QPushButton:
    """A button with a small icon aligned left of the label."""
    b = QPushButton(text)
    if primary:
        b.setObjectName("Primary")
    b.setIcon(make_icon(icon_name, "#FFFFFF" if primary else TEXT, 16))
    b.setIconSize(ICON)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def field(label_text: str, widget: QWidget) -> QWidget:
    """Stack a small muted label above an input, with tight uniform spacing."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    lab = QLabel(label_text)
    lab.setObjectName("FieldLabel")
    lay.addWidget(lab)
    lay.addWidget(widget)
    return box


class Session:
    """Holds the validated token/chat, shared by every page."""

    def __init__(self) -> None:
        self.token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat: Any = None
        self.bot_username: str = ""
        self.bot_id: Optional[int] = None
        self.known_chats: dict = {}   # chat_id(str) -> {id, title, type}

    def is_connected(self) -> bool:
        """Single source of truth: are the bar's token/chat backing a live bot?"""
        return self.bot_id is not None

    def client(self) -> TelegramClient:
        if not self.token:
            raise ValueError("Enter a bot token first.")
        return TelegramClient(self.token)

    def require_chat(self) -> Any:
        if self.chat is None or self.chat == "":
            raise ValueError("Enter a chat id or @username first.")
        return self.chat


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

class BasePage(QWidget):
    title = "Page"
    subtitle = ""
    fill = False   # True = the page's own content fills the height (no trailing stretch)

    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.main = main
        self.session = main.session
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 20, 24, 20)
        self.root.setSpacing(12)
        t = QLabel(self.title)
        t.setObjectName("PageTitle")
        self.root.addWidget(t)
        self.build()
        if not self.fill:
            self.root.addStretch(1)

    def build(self) -> None:  # overridden
        ...

    # ---- empty state: a single "connect a bot" hint shown in place of the
    # page body whenever no bot is connected. Pages opt in by calling
    # _init_empty() at the end of build() (listing the body widgets to hide)
    # and _apply_empty_state() at the top of on_shown()/clear_view().
    def _init_empty(self, *body, note: str = "Connect a bot to see the information.") -> None:
        self._empty = QLabel(note)
        self._empty.setObjectName("Muted")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._empty.setVisible(False)
        # A VISIBLE transparent spacer holds the bottom so the title + message
        # stay pinned at the top. A hidden body-with-stretch can't do that: when
        # the only stretch item is invisible, QVBoxLayout spreads the free space
        # evenly around the visible rows, which is what dropped the message to
        # the middle of the page.
        self._empty_spacer = QWidget()
        self._empty_spacer.setStyleSheet("background:transparent;")
        self._empty_spacer.setSizePolicy(QSizePolicy.Policy.Preferred,
                                         QSizePolicy.Policy.Expanding)
        self._empty_spacer.setVisible(False)
        self.root.insertWidget(1, self._empty_spacer)  # ends up just below the message
        self.root.insertWidget(1, self._empty)         # message directly under the title
        self._empty_body = [w for w in body if w is not None]

    def _apply_empty_state(self) -> bool:
        """Show the hint (hide the body) while disconnected. Returns True when a
        bot is connected, so callers can `if not self._apply_empty_state(): return`."""
        connected = self.session.is_connected()
        if getattr(self, "_empty", None) is not None:
            self._empty.setVisible(not connected)
            self._empty_spacer.setVisible(not connected)
            for w in self._empty_body:
                w.setVisible(connected)
        return connected

    def run(self, job: Callable[[], Any], on_done: Callable[[Any], None],
            button: Optional[QPushButton] = None) -> None:
        self.main.run_call(job, on_done, button=button)


class ConnectionPage(BasePage):
    title = "Bot & chat"

    def build(self) -> None:
        self._profiled_for = None
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        row = QHBoxLayout()
        self.avatar = QLabel("?")
        self.avatar.setFixedSize(64, 64)
        self.avatar.setStyleSheet(
            f"border-radius:32px; background:{SYS_PILL}; color:{TEXT_MUTED}; font-size:24px;")
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info = QLabel("Not connected.")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.avatar)
        row.addSpacing(14)
        row.addWidget(self.info, 1)
        lay.addLayout(row)
        self.root.addWidget(card)

    def on_shown(self) -> None:
        # Profile the bot on its own once connected.
        if self.session.bot_id is not None and self._profiled_for != self.session.bot_id:
            self.do_profile()

    def clear_view(self) -> None:
        self._profiled_for = None
        self.info.setText("Not connected.")
        self.avatar.setPixmap(QPixmap())
        self.avatar.setText("?")

    def do_profile(self, force: bool = False) -> None:
        try:
            client = self.session.client()
        except ValueError as e:
            self.main.log(f"[ERROR] {e}")
            return
        self._profiled_for = self.session.bot_id
        self.run(lambda: api.profile_bot(client), self.show_profile)
        # Avatar in a second, independent call (failure is non-fatal).
        self.run(lambda: self._fetch_avatar(client), self._show_avatar)

    def _fetch_avatar(self, client) -> Optional[bytes]:
        me = api.get_me(client)
        photos = api.get_user_profile_photos(client, me["id"], limit=1)
        if not photos.get("total_count"):
            return None
        file_id = photos["photos"][0][-1]["file_id"]
        fpath = api.get_file(client, file_id)["file_path"]
        import requests
        return requests.get(api.file_download_url(client, fpath), timeout=15).content

    def _show_avatar(self, data: Optional[bytes]) -> None:
        if not data:
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            self.avatar.setPixmap(pix.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))

    def show_profile(self, prof: dict) -> None:
        me = prof.get("me", {})
        self.session.bot_username = me.get("username", "")
        self.main.set_bot_status(True, f"@{me.get('username','?')}")
        lines = [f"<b>@{me.get('username','?')}</b> - id {me.get('id','?')}"]
        wh = prof.get("webhook_info", {})
        lines.append(f"Webhook: {wh.get('url') or '(none, polling)'}  ·  "
                     f"pending {wh.get('pending_update_count','?')}")
        cmds = prof.get("my_commands") or []
        lines.append(f"Declared commands: {len(cmds)}")
        for c in cmds[:10]:
            lines.append(f"&nbsp;&nbsp;/{c.get('command')} - {c.get('description','')}")
        if prof.get("errors"):
            lines.append(f"<span style='color:{WARNING}'>unavailable: "
                         f"{', '.join(prof['errors'])}</span>")
        self.info.setText("<br>".join(lines))
        self.main.log(f"[OK] Bot @{me.get('username','?')} profiled.")


class AdminsPage(BasePage):
    title = "Admins"

    def build(self) -> None:
        self._admins: list = []
        self._loaded_for = None
        bar = QHBoxLayout()
        self.export_btn = build_export_button(
            self, [("Admin list", "admins", self._admins_dataset)], log=self.main.log)
        self.export_btn.setEnabled(False)
        bar.addStretch(1); bar.addWidget(self.export_btn)
        self.root.addLayout(bar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Username", "ID", "Role"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.root.addWidget(self.table)
        self._init_empty(self.export_btn, self.table)

    def on_shown(self) -> None:
        if not self._apply_empty_state():
            return
        # Loaded on its own; re-loaded only if the chat changed.
        if self.session.chat is not None and self._loaded_for != self.session.chat:
            self._go(None)

    def clear_view(self) -> None:
        self._loaded_for = None
        self._admins = []
        self.table.setRowCount(0)
        self.export_btn.setEnabled(False)
        self._apply_empty_state()

    def _go(self, btn, force: bool = False) -> None:
        try:
            client, chat = self.session.client(), self.session.require_chat()
        except ValueError as e:
            self.main.log(f"[ERROR] {e}")
            return
        self._loaded_for = chat
        self.run(lambda: api.get_chat_administrators(client, chat), self._show, btn)

    def _show(self, admins: list) -> None:
        self._admins = admins
        self.export_btn.setEnabled(bool(admins))
        self.table.setRowCount(0)
        for adm in admins:
            u = adm.get("user", {})
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [f"{u.get('first_name','')} {u.get('last_name','')}".strip(),
                    f"@{u.get('username','')}" if u.get("username") else "",
                    str(u.get("id", "")), adm.get("status", "")]
            for col, v in enumerate(vals):
                self.table.setItem(r, col, QTableWidgetItem(v))
        self.main.log(f"[OK] {len(admins)} administrators.")

    def _admins_dataset(self):
        rows = []
        for adm in self._admins:
            u = adm.get("user", {})
            rows.append([u.get("id"), u.get("username", ""),
                         f"{u.get('first_name','')} {u.get('last_name','')}".strip(),
                         adm.get("status", "")])
        return ["id", "username", "name", "role"], rows


class MemberPage(BasePage):
    title = "Member info"
    fill = True

    def build(self) -> None:
        self._loaded_for = None
        self._all: list = []        # everyone seen in this chat
        self._members: list = []    # currently displayed (filtered)

        row = QHBoxLayout(); row.setSpacing(10)
        self.uid = QLineEdit()
        self.uid.setPlaceholderText("Type to filter, or a full id to search wider")
        self._filter_timer = QTimer(self); self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._apply_filter)
        self.uid.textChanged.connect(lambda: self._filter_timer.start(350))
        self.export_btn = build_export_button(
            self, [("Members seen", "members", self._members_dataset)], log=self.main.log)
        self.export_btn.setEnabled(False)
        row.addWidget(field("Search users", self.uid), 1)
        row.addWidget(self.export_btn, 0, Qt.AlignmentFlag.AlignBottom)
        self.root.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Username", "ID", "Status"])
        # Columns share the width evenly and everything is centred.
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setShowGrid(False)
        self.root.addWidget(self.table, 1)
        # The table sizes to its rows (header + N rows) and a spacer fills the rest,
        # so a short list stays pinned at the top - the same behaviour as the empty
        # "No data" state. A long list fills the area and scrolls inside the table.
        self._mp_spacer = QWidget(); self._mp_spacer.setStyleSheet("background:transparent;")
        self._mp_spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.root.addWidget(self._mp_spacer)
        self._show_empty_table()

    def _cap_table(self) -> None:
        """Cap the table's height to its content (header + rows), so it never
        stretches past its data; the spacer below takes the slack."""
        rh = self.table.verticalHeader().defaultSectionSize() or 32
        hh = self.table.horizontalHeader().sizeHint().height() or 28
        n = max(self.table.rowCount(), 1)
        self.table.setMaximumHeight(hh + rh * n + 2 * self.table.frameWidth() + 2)

    @staticmethod
    def _cell(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def on_shown(self) -> None:
        key = (self.session.bot_id, self.session.chat)
        if self.session.bot_id is not None and self.session.chat is not None \
                and self._loaded_for != key:
            self._auto_load()

    def clear_view(self) -> None:
        self._loaded_for = None
        self._all = []
        self._members = []
        self._show_empty_table()
        self.export_btn.setEnabled(False)

    def _show_empty_table(self) -> None:
        """Collapse the table to its header + one centered 'no data' row."""
        self.table.clearSpans()
        self.table.setRowCount(0)
        self.table.insertRow(0)
        self.table.setSpan(0, 0, 1, self.table.columnCount())
        cell = self._cell("No data to show yet")
        cell.setFlags(Qt.ItemFlag.ItemIsEnabled)   # shown, not selectable
        self.table.setItem(0, 0, cell)
        self._cap_table()

    def _seen_users(self):
        users = {}
        for m in store.load_messages_for(self.session.bot_id, self.session.chat):
            f = m.get("from") or {}
            if f.get("id") is not None:
                users.setdefault(f["id"], f)
        return users

    def _auto_load(self) -> None:
        try:
            client, chat = self.session.client(), self.session.require_chat()
        except ValueError:
            return
        users = self._seen_users()
        self._loaded_for = (self.session.bot_id, self.session.chat)
        if not users:
            self._all = []
            self._apply_filter()
            return
        ids = list(users)[:300]

        def job():
            out = []
            for uid in ids:
                try:
                    out.append(api.get_chat_member(client, chat, uid))
                except TelegramError:
                    f = users[uid]
                    out.append({"user": {"id": uid, "username": f.get("username"),
                                         "first_name": f.get("first_name")}, "status": "?"})
            return out

        def done(members):
            self._all = members
            self._apply_filter()
        self.run(job, done)

    def _render_table(self, members: list) -> None:
        self._members = members
        self.export_btn.setEnabled(bool(members))
        if not members:
            self._show_empty_table()
            return
        self.table.clearSpans()
        self.table.setRowCount(0)
        for info in members:
            u = info.get("user", {})
            r = self.table.rowCount(); self.table.insertRow(r)
            vals = [f"{u.get('first_name','')} {u.get('last_name','')}".strip(),
                    f"@{u.get('username','')}" if u.get("username") else "",
                    str(u.get("id", "")), info.get("status", "")]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, self._cell(v))
        self._cap_table()

    def _apply_filter(self) -> None:
        text = self.uid.text().strip().lower()
        if not text:
            self._render_table(self._all)
            return

        def haystack(info):
            u = info.get("user", {})
            return (f"{u.get('id','')} {u.get('username','')} "
                    f"{u.get('first_name','')} {u.get('last_name','')}").lower()

        matches = [m for m in self._all if text in haystack(m)]
        if matches:
            self._render_table(matches)
        elif text.isdigit() and len(text) >= 5:
            # A full id with nothing in what we know -> look beyond this chat.
            self._broader_lookup(int(text))
        else:
            self._render_table([])

    def _broader_lookup(self, uid: int) -> None:
        try:
            client, chat = self.session.client(), self.session.require_chat()
        except ValueError:
            return

        def job():
            try:
                return ("user", api.get_chat(client, uid))
            except TelegramError:
                return ("member", api.get_chat_member(client, chat, uid))

        def done(res):
            kind, data = res
            info = data if kind == "member" else {"user": data, "status": "(not in this chat)"}
            self._render_table([info])
        self.run(job, done)

    def _members_dataset(self):
        rows = []
        for info in self._members:
            u = info.get("user", {})
            rows.append([u.get("id"), u.get("username", ""),
                         f"{u.get('first_name','')} {u.get('last_name','')}".strip(),
                         info.get("status", "")])
        return ["id", "username", "name", "status"], rows


# Bot API getChatMember field -> Telegram "Admin rights" panel label, in TG order.
_RIGHTS_ROWS = [
    ("Change group info", "can_change_info"),
    ("Delete messages", "can_delete_messages"),
    ("Ban users", "can_restrict_members"),
    ("Invite users via link", "can_invite_users"),
    ("Pin messages", "can_pin_messages"),
    ("Manage stories", ("can_post_stories", "can_edit_stories", "can_delete_stories")),
    ("Manage video chats", "can_manage_video_chats"),
    ("Remain anonymous", "is_anonymous"),
    ("Add new admins", "can_promote_members"),
]


# Rights that can be verified by actually trying them -> probe key.
_RIGHT_TO_PROBE = {
    "can_change_info": "change_info",
    "can_delete_messages": "post_delete",
    "can_invite_users": "invite",
    "can_pin_messages": "pin",
}


class RightsPage(BasePage):
    title = "Bot rights"
    subtitle = ("What the bot is allowed to do, read from its info. For a right that can be "
                "verified, a Check actually tries it - risky ones ask before writing.")

    def build(self) -> None:
        self._loaded_for = None
        self.card = QFrame()
        self.card.setObjectName("Card")
        self.card_lay = QVBoxLayout(self.card)
        self.card_lay.setContentsMargins(18, 16, 18, 16)
        self.card_lay.setSpacing(10)
        self.card.setVisible(False)
        self.root.addWidget(self.card)
        # The card shows itself only once rendered, so it isn't in the body list;
        # the hint just needs to appear when disconnected.
        self._init_empty()

    def on_shown(self) -> None:
        if not self._apply_empty_state():
            return
        # Auto-check once connected, unless we already did for this chat.
        key = (self.session.bot_id, self.session.chat)
        if self.session.chat is not None and self._loaded_for != key:
            self._go()

    def clear_view(self) -> None:
        self._loaded_for = None
        self._clear_card()
        self.card.setVisible(False)
        self._apply_empty_state()

    def _go(self, force: bool = False) -> None:
        try:
            client, chat = self.session.client(), self.session.require_chat()
        except ValueError as e:
            self.main.log(f"[ERROR] {e}")
            return
        self._loaded_for = (self.session.bot_id, chat)

        def job():
            member = api.get_bot_permissions(client, chat)
            try:
                member["_can_send"] = (True if member.get("status") == "creator"
                                       else api.can_send_from(member, api.get_chat(client, chat)))
            except TelegramError:
                member["_can_send"] = None
            return member

        self.run(job, self._render)

    def _clear_card(self) -> None:
        while self.card_lay.count():
            item = self.card_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _set_pill(self, pill: QLabel, state) -> None:
        # state: True granted, False denied, None unknown (n/a).
        if state is True:
            text, color = "✓", SUCCESS
        elif state is False:
            text, color = "✗", DANGER
        else:
            text, color = "n/a", TEXT_MUTED
        pill.setText(text)
        pill.setStyleSheet(
            f"color:#FFFFFF; background:{color}; border-radius:11px; "
            f"padding:2px 10px; font-weight:600;")
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _new_pill(self, state) -> QLabel:
        pill = QLabel(); self._set_pill(pill, state)
        return pill

    def _render(self, res: dict) -> None:
        self._clear_card()
        self.card.setVisible(True)
        user = res.get("user", {})
        name = user.get("first_name") or user.get("username") or "bot"
        status = res.get("status", "")
        is_admin = status in ("administrator", "creator")

        header = QHBoxLayout()
        avatar = QLabel(name[:1].upper())
        avatar.setFixedSize(48, 48)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"background:{SUCCESS}; color:#FFFFFF; border-radius:24px; "
            f"font-size:20px; font-weight:600;")
        name_box = QVBoxLayout(); name_box.setSpacing(0)
        nlab = QLabel(name); nlab.setStyleSheet("font-size:16px; font-weight:600;")
        sub = QLabel("has access to messages" if is_admin else f"status: {status}")
        sub.setStyleSheet(f"color:{SUCCESS if is_admin else TEXT_MUTED};")
        name_box.addWidget(nlab); name_box.addWidget(sub)
        header.addWidget(avatar); header.addSpacing(12); header.addLayout(name_box); header.addStretch(1)
        hw = QWidget(); hw.setStyleSheet("background:transparent;"); hw.setLayout(header)
        self.card_lay.addWidget(hw)

        # Messaging: can the bot actually write here? (member-level, the first
        # thing you want to know - independent of the admin rights below.)
        mtitle = QLabel("Messaging")
        mtitle.setStyleSheet(f"color:{ACCENT}; padding-top:6px;")
        self.card_lay.addWidget(mtitle)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Send messages"))
        srow.addStretch(1)
        srow.addWidget(self._new_pill(res.get("_can_send")))
        sw = QWidget(); sw.setStyleSheet("background:transparent;"); sw.setLayout(srow)
        self.card_lay.addWidget(sw)

        title = QLabel("Admin rights")
        title.setStyleSheet(f"color:{ACCENT}; padding-top:6px;")
        self.card_lay.addWidget(title)

        # Every right is shown. Value comes from the bot's info when known;
        # otherwise it's n/a with a Check button to verify it for real.
        for label, key in _RIGHTS_ROWS:
            row = QHBoxLayout()
            if isinstance(key, tuple):   # Manage stories -> x/3
                n = sum(1 for k in key if res.get(k))
                row.addWidget(QLabel(f"{label}  {n}/{len(key)}"))
                row.addStretch(1)
                row.addWidget(self._new_pill(n > 0 if is_admin else None))
            else:
                state = bool(res.get(key)) if (is_admin and key in res) else None
                pill = self._new_pill(state)
                row.addWidget(QLabel(label))
                row.addStretch(1)
                # Only offer a Check where the info is missing (n/a) and the right
                # can actually be verified.
                probe = _RIGHT_TO_PROBE.get(key)
                if probe and state is None:
                    check = QPushButton("Check"); check.setFixedHeight(26)
                    check.setCursor(Qt.CursorShape.PointingHandCursor)
                    check.clicked.connect(
                        lambda _=False, pk=probe, pl=pill: self._check_right(pk, pl))
                    row.addWidget(check)
                row.addWidget(pill)
            rw = QWidget(); rw.setStyleSheet("background:transparent;"); rw.setLayout(row)
            self.card_lay.addWidget(rw)
        self.main.log(f"[OK] Rendered bot rights ({status}).")

    def _check_right(self, probe_key: str, pill: QLabel) -> None:
        try:
            client, chat = self.session.client(), self.session.require_chat()
        except ValueError as e:
            self.main.log(f"[ERROR] {e}")
            return
        meta = {k: (lbl, inv) for k, lbl, inv, _ in rights_check.PROBES}[probe_key]
        label, invasive = meta
        if invasive and not self._confirm_run(label):
            return

        def done(results):
            r = results[0] if results else None
            self._set_pill(pill, r.ok if r else None)
            if r:
                pill.setToolTip(r.detail)
                self.main.log(f"[OK] {label}: {r.detail}")

        self.run(lambda: rights_check.run_probes(client, chat, [probe_key]), done)

    def _confirm_run(self, label: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Run this check?")
        box.setText(f"\"{label}\" writes to the chat to verify the right. The change is "
                    "reverted right away, but it leaves a service message that can't be "
                    "removed.\n\nRun anyway?")
        run = box.addButton("Run anyway", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is run


class InvitePage(BasePage):
    title = "Invitations"
    subtitle = "Create a link people can use to join the chat. A bot can't add someone directly - they click the link."

    def build(self) -> None:
        # Whole form lives in one widget, so the empty-state hint can swap it out.
        # NB: don't give this container a bare "background:transparent" stylesheet -
        # in Qt that cascades to children and would wipe the Primary button's fill.
        body = QWidget()
        outer = QVBoxLayout(body); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.name = QLineEdit(); self.name.setPlaceholderText("optional")
        self.limit = QSpinBox(); self.limit.setRange(0, 99999); self.limit.setSpecialValueText("no limit")
        self.join = QCheckBox("Require approval")
        self.join.setToolTip("People who use the link don't join right away - an admin has "
                             "to approve each one first. (Can't be combined with a member limit.)")
        # Telegram forbids a limit together with approval, so grey it out.
        self.join.toggled.connect(self.limit.setDisabled)
        row.addWidget(field("Link name", self.name), 1)
        row.addWidget(field("Member limit", self.limit))
        row.addWidget(self.join, 0, Qt.AlignmentFlag.AlignBottom)
        outer.addLayout(row)
        btn_row = QHBoxLayout(); btn_row.setSpacing(10)
        btn = icon_button("Create invite link", "link", primary=True)
        btn.clicked.connect(lambda: self._go(btn))
        self.invite_msg = QLabel(""); self.invite_msg.setWordWrap(True)
        btn_row.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        btn_row.addWidget(self.invite_msg, 1, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(btn_row)
        self.link = QLineEdit(); self.link.setReadOnly(True)
        self.link.setPlaceholderText("Generated link appears here")
        outer.addWidget(field("Invite link", self.link))
        self.root.addWidget(body)
        self._init_empty(body)

    def _set_msg(self, text: str, error: bool = False) -> None:
        self.invite_msg.setText(text)
        color = DANGER if error else TEXT_MUTED
        self.invite_msg.setStyleSheet(f"color:{color};")

    def on_shown(self) -> None:
        self._apply_empty_state()

    def clear_view(self) -> None:
        self.link.clear()
        self._set_msg("")
        self._apply_empty_state()

    def _go(self, btn) -> None:
        if self.session.chat is None:
            # Bot token is set but no chat picked: say so right next to the button.
            self._set_msg("Select a group first.", error=True)
            return
        try:
            client, chat = self.session.client(), self.session.require_chat()
        except ValueError as e:
            self._set_msg(str(e), error=True)
            return
        self._set_msg("")
        approval = self.join.isChecked()
        # Telegram forbids a member limit together with approval.
        limit = None if approval else (self.limit.value() or None)
        self.run(lambda: api.create_chat_invite_link(
            client, chat, name=self.name.text().strip() or None,
            member_limit=limit, creates_join_request=approval),
            lambda r: (self.link.setText(r.get("invite_link", "")),
                       self._set_msg("Invite link created.", error=False),
                       self.main.log("[OK] Invite link created.")), btn)


class ListenPage(BasePage):
    title = "New arrivals"
    subtitle = ("People who join a chat the bot is in, as it happens. This runs on its own "
                "in the background while a token is connected - no need to start anything.")

    def build(self) -> None:
        row = QHBoxLayout()
        self.only_current = QCheckBox("Only the selected chat")
        self.only_current.toggled.connect(self._rerender)
        clear = icon_button("Clear", "trash")
        clear.clicked.connect(lambda: (self.main.arrivals.clear(), self._rerender()))
        row.addWidget(self.only_current)
        row.addStretch(1)
        row.addWidget(clear)
        self.root.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "Chat", "User id", "Name"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.root.addWidget(self.table)

    def on_shown(self) -> None:
        self._rerender()

    def add_arrival(self, ev: dict) -> None:
        # Only redraw if we're the visible page; otherwise it buffers in main.
        if self.isVisible():
            self._rerender()

    def _rerender(self) -> None:
        from datetime import datetime
        self.table.setRowCount(0)
        chat_filter = self.session.chat if self.only_current.isChecked() else None
        for ev in self.main.arrivals:
            if chat_filter is not None and str(ev.get("chat_id")) != str(chat_filter):
                continue
            u = ev.get("user", {})
            r = self.table.rowCount(); self.table.insertRow(r)
            vals = [datetime.now().strftime("%H:%M:%S"), str(ev.get("chat_id", "")),
                    str(u.get("id", "")),
                    f"{u.get('first_name','')} {u.get('last_name','')} "
                    f"@{u.get('username','')}".strip()]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))


class ArchivePage(BasePage):
    title = "Archive messages"
    subtitle = ("Backfill OLD messages the bot never received. (Recent ones are already collected "
                "automatically - see Report, \"Load collected\".) A bot can't read a past message "
                "directly, so each one is briefly forwarded to read it, then written to your file.")

    def build(self) -> None:
        warn = QFrame(); warn.setObjectName("Warn")
        wl = QHBoxLayout(warn); wl.setContentsMargins(12, 10, 12, 10); wl.setSpacing(10)
        wicon = QLabel(); wicon.setPixmap(make_icon("archive", WARNING, 18).pixmap(18, 18))
        wicon.setAlignment(Qt.AlignmentFlag.AlignTop)
        wtext = QLabel("Forwarding leaves a copy in the destination. Point it at a separate "
                       "archive chat you own (below), and tick \"delete copies\" so nothing is "
                       "left behind once the content is saved.")
        wtext.setWordWrap(True); wtext.setStyleSheet(f"color:{WARNING};")
        wl.addWidget(wicon); wl.addWidget(wtext, 1)
        self.root.addWidget(warn)

        row1 = QHBoxLayout(); row1.setSpacing(10)
        self.start = QSpinBox(); self.start.setRange(1, 2_000_000_000); self.start.setValue(1000)
        self.stop = QSpinBox(); self.stop.setRange(0, 2_000_000_000); self.stop.setSpecialValueText("none")
        self.maxit = QSpinBox(); self.maxit.setRange(1, 1_000_000); self.maxit.setValue(16000)
        for sb in (self.start, self.stop, self.maxit):
            sb.setMinimumWidth(110)
        row1.addWidget(field("Start id", self.start))
        row1.addWidget(field("Stop id", self.stop))
        row1.addWidget(field("Max", self.maxit))
        row1.addStretch(1)
        self.root.addLayout(row1)

        self.dest = QLineEdit(); self.dest.setPlaceholderText("optional, e.g. @my_archive")
        self.root.addWidget(field("Forward through (archive chat)", self.dest))
        self.cleanup = QCheckBox("Delete the copies after saving (needs delete rights there)")
        self.cleanup.setChecked(True)
        self.root.addWidget(self.cleanup)

        row3 = QHBoxLayout(); row3.setSpacing(10)
        self.outfile = QLineEdit(); self.outfile.setPlaceholderText("Pick where to save (Browse)")
        browse = icon_button("Browse", "folder"); browse.clicked.connect(self._browse)
        row3.addWidget(field("Save to", self.outfile), 1)
        row3.addWidget(browse, 0, Qt.AlignmentFlag.AlignBottom)
        self.root.addLayout(row3)

        row4 = QHBoxLayout()
        self.start_btn = icon_button("Start archive", "play", primary=True)
        self.stop_btn = icon_button("Stop", "stop"); self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start); self.stop_btn.clicked.connect(self._stop)
        row4.addWidget(self.start_btn); row4.addWidget(self.stop_btn); row4.addStretch(1)
        self.root.addLayout(row4)

        self.bar = QProgressBar(); self.bar.setRange(0, 100); self.bar.setValue(0)
        self.root.addWidget(self.bar)
        self.counts = QLabel("found 0 · skipped 0"); self.counts.setObjectName("Muted")
        self.root.addWidget(self.counts)
        self._worker: Optional[ArchiveWorker] = None
        self._total = 1

        # Advanced, de-emphasised: the grab & erase lever lives here, not up front.
        self.root.addSpacing(8)
        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"color:{BORDER};"); self.root.addWidget(div)
        adv = QHBoxLayout()
        advlbl = QLabel("Advanced"); advlbl.setObjectName("Muted")
        self.grab_btn = icon_button("Grab && erase", "trash")
        self.grab_btn.clicked.connect(self._grab_erase_dialog)
        self._set_grab_enabled(None)   # unknown until we've checked the chat
        adv.addWidget(advlbl); adv.addStretch(1); adv.addWidget(self.grab_btn)
        self.root.addLayout(adv)

    def _set_grab_enabled(self, can_delete) -> None:
        # None = not checked yet, True/False = known from the bot's rights.
        if can_delete:
            self.grab_btn.setEnabled(True)
            self.grab_btn.setToolTip("Capture one message to your archive, then delete the original.")
        else:
            self.grab_btn.setEnabled(False)
            self.grab_btn.setToolTip(
                "Connect to a chat first." if can_delete is None
                else "The bot can't delete messages here - it needs admin rights with "
                     "'Delete messages' (see the Bot rights tab).")

    def on_shown(self) -> None:
        # Refresh the grab lever's availability from the bot's actual rights.
        if self.session.chat is None or not self.session.token:
            self._set_grab_enabled(None)
            return
        try:
            client, chat = self.session.client(), self.session.chat
        except ValueError:
            self._set_grab_enabled(None)
            return

        def done(res):
            status = res.get("status")
            can = status == "creator" or (status == "administrator"
                                          and bool(res.get("can_delete_messages")))
            self._set_grab_enabled(can)
        self.main.run_call(lambda: api.get_bot_permissions(client, chat), done,
                           on_error=lambda m: self._set_grab_enabled(False))

    def _grab_erase_dialog(self) -> None:
        try:
            client, chat = self.session.client(), self.session.require_chat()
        except ValueError as e:
            self.main.log(f"[ERROR] {e}")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Grab & erase")
        v = QVBoxLayout(dlg); v.setContentsMargins(18, 16, 18, 16); v.setSpacing(12)
        warn = QLabel(
            "This captures one message by forwarding it to your archive chat, then "
            "PERMANENTLY DELETES the original from the source chat.\n\n"
            "It cannot be undone, and the original sender may notice the message is gone.")
        warn.setWordWrap(True); warn.setStyleSheet(f"color:{DANGER};")
        v.addWidget(warn)
        mid = QSpinBox(); mid.setRange(1, 2_000_000_000)
        dest = QLineEdit(); dest.setPlaceholderText("@my_archive (a chat you own)")
        v.addWidget(field("Message id (in the source chat)", mid))
        v.addWidget(field("Archive chat", dest))
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        go = box.addButton("Grab && erase", QDialogButtonBox.ButtonRole.DestructiveRole)
        go.setStyleSheet(f"background:{DANGER}; color:#FFFFFF; border:none; font-weight:600;")
        box.rejected.connect(dlg.reject)
        go.clicked.connect(dlg.accept)
        v.addWidget(box)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        d = dest.text().strip()
        if not d:
            self.main.log("[ERROR] Grab & erase needs an archive chat.")
            return
        message_id = mid.value(); dest_chat = _chat_arg(d)
        self.main.log(f"[INFO] Grab & erase: message {message_id} -> {dest_chat}, then delete original.")
        self.run(lambda: archive.grab_and_erase(
            client, source_chat=chat, message_id=message_id, dest_chat=dest_chat),
            lambda r: self.main.log(f"[OK] Captured message {r.get('message_id')} "
                                    f"and erased the original."))

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save archive as", "archive.ndjson",
                                              "Archive file (*.ndjson);;All files (*)")
        if path:
            self.outfile.setText(path)

    def _start(self) -> None:
        try:
            client, chat = self.session.client(), self.session.require_chat()
        except ValueError as e:
            self.main.log(f"[ERROR] {e}")
            return
        out = self.outfile.text().strip()
        if not out:
            self.main.log("[ERROR] Choose an output file.")
            return
        start_id = self.start.value()
        stop_id = self.stop.value() or None
        dest = _chat_arg(self.dest.text().strip()) if self.dest.text().strip() else None
        self._total = (start_id - stop_id + 1) if stop_id else self.maxit.value()
        params = dict(source_chat=chat, start_id=start_id, stop_id=stop_id,
                      output_file=out, max_iters=self.maxit.value(), dest_chat=dest,
                      cleanup=self.cleanup.isChecked())
        self._worker = ArchiveWorker(client, params)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self.start_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        self.bar.setValue(0)
        self.main.log(f"[INFO] Archiving into {out}" + (f" via {dest}" if dest else " (into source chat)"))
        self._worker.start()

    def _on_progress(self, p: archive.ArchiveProgress) -> None:
        self.counts.setText(f"found {p.found} · skipped {p.skipped}"
                            + (f" · at id {p.current_id}" if p.current_id else ""))
        done = p.found + p.skipped
        self.bar.setValue(min(int(done / self._total * 100), 100) if self._total else 0)

    def _stop(self) -> None:
        if self._worker:
            self._worker.stop()
            self.main.log("[INFO] Stop requested - partial dump is already saved.")

    def _on_done(self, p: archive.ArchiveProgress) -> None:
        self.bar.setValue(100)
        self.start_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        self.main.log(f"[DONE] {p.found} messages written, {p.skipped} skipped -> {p.output_file}")

    def _on_failed(self, msg: str) -> None:
        self.start_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        self.main.log(f"[ERROR] {msg}")


# --------------------------------------------------------------------------
# Report dashboard (OSINT): load a dump, see links / senders / IOCs, drill in.
# --------------------------------------------------------------------------

# mode -> (title, indicator types, icon). "senders" is handled on its own.
_REPORT_CARDS = [
    ("links", "Links", intel.LINK_TYPES, "link"),
    ("senders", "Senders", (), "users"),
    ("crypto", "Crypto addresses", intel.CRYPTO_TYPES, "key"),
    ("mentions", "Mentions", ("mention",), "user"),
]
_MODE_TYPES = {"links": intel.LINK_TYPES, "crypto": intel.CRYPTO_TYPES,
               "mentions": ("mention",)}


class Collapsible(QWidget):
    """A Splunk-style drill-down row: a clickable header (chevron + title, the
    title usually carries a count) over a body that is built lazily the first
    time it's opened. Sober by default, full detail one click away."""

    def __init__(self, title: str, builder, *, open: bool = False, parent=None):
        super().__init__(parent)
        self._builder = builder
        self._built = False
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        self._btn = QToolButton()
        self._btn.setText(title.replace("&", "&&"))   # & is a mnemonic in buttons
        self._btn.setCheckable(True)
        self._btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._btn.setIcon(make_icon("chevron_right", TEXT_MUTED, 13))
        self._btn.setIconSize(QSize(13, 13))
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn.setStyleSheet(
            "QToolButton{border:none; background:transparent; padding:6px 2px; "
            "font-weight:600; text-align:left;}"
            f"QToolButton:hover{{color:{ACCENT};}}")
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(4, 0, 2, 6); self._body_lay.setSpacing(6)
        self._body.setVisible(False)
        self._btn.toggled.connect(self._on_toggle)
        v.addWidget(self._btn); v.addWidget(self._body)
        if open:
            self._btn.setChecked(True)

    def _on_toggle(self, on: bool) -> None:
        self._btn.setIcon(make_icon("chevron" if on else "chevron_right", TEXT_MUTED, 13))
        if on and not self._built:
            w = self._builder()
            if w is not None:
                self._body_lay.addWidget(w)
            self._built = True
        self._body.setVisible(on)


class ReportPage(BasePage):
    title = "Report"
    fill = True
    subtitle = ("Open a saved archive and explore it: the links, people and crypto addresses that appear, "
                "and when. Click anything to see more detail.")

    def build(self) -> None:
        self.index: Optional[intel.Index] = None
        self._source = ""
        self._loaded_for = None
        self.messages: list = []

        top = QHBoxLayout(); top.setSpacing(10)
        # The collected messages ARE the data (the local store is the DB), so
        # there's no "load external file" - the report always reads the store.
        self.loaded = QLabel("Nothing collected yet."); self.loaded.setObjectName("Muted")
        self.export_btn = build_export_button(self, self._overview_datasets(), log=self.main.log)
        self.export_btn.setEnabled(False)
        top.addWidget(self.loaded, 1); top.addWidget(self.export_btn)
        self.root.addLayout(top)

        self.inner = QStackedWidget()
        self.inner.addWidget(self._build_overview())   # index 0
        self.detail_host = QWidget()
        self.detail_host_lay = QVBoxLayout(self.detail_host)
        self.detail_host_lay.setContentsMargins(0, 0, 0, 0)
        self.inner.addWidget(self.detail_host)          # index 1
        self.root.addWidget(self.inner, 1)
        self._init_empty(self.loaded, self.export_btn, self.inner)

    # ---- overview ----
    def _build_overview(self) -> QWidget:
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget(); lay = QVBoxLayout(host); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(14)

        self.tiles_row = QHBoxLayout(); self.tiles_row.setSpacing(10)
        self._tiles = {}
        for key, label in [("messages", "Messages"), ("senders", "Senders"),
                           ("links", "Links"), ("crypto", "Crypto"),
                           ("phone", "Phones"), ("media", "Media")]:
            t = stat_tile(label, "-"); self._tiles[key] = t
            self.tiles_row.addWidget(t)
        lay.addLayout(self.tiles_row)

        grid = QGridLayout(); grid.setSpacing(12)
        self._cards = {}
        for i, (mode, title, types, icon_name) in enumerate(_REPORT_CARDS):
            card, bars = self._category_card(mode, title, icon_name)
            self._cards[mode] = bars
            grid.addWidget(card, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _category_card(self, mode, title, icon_name):
        card = QFrame(); card.setObjectName("Card")
        lay = QVBoxLayout(card); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(8)
        head = QHBoxLayout()
        ic = QLabel(); ic.setPixmap(make_icon(icon_name, TEXT, 16).pixmap(16, 16))
        t = QLabel(title); t.setStyleSheet("font-weight:600; font-size:14px;")
        more = icon_button("Details", "chart")
        more.clicked.connect(lambda _, m=mode: self._open_detail(m, None))
        head.addWidget(ic); head.addSpacing(6); head.addWidget(t); head.addStretch(1); head.addWidget(more)
        lay.addLayout(head)
        bars = HBarList()
        bars.setFixedHeight(186)   # room for ~6 rows; cards must not collapse
        bars.clicked.connect(lambda value, m=mode: self._open_detail(m, value))
        lay.addWidget(bars)
        return card, bars

    # ---- dynamic: analyse the collected messages on its own ----
    def on_shown(self) -> None:
        if not self._apply_empty_state():
            return
        key = (self.session.bot_id, self.session.chat)
        if self._loaded_for != key:
            self._load_collected()

    def clear_view(self) -> None:
        self._loaded_for = None
        self.index = None
        self.messages = []
        self._source = ""
        self.loaded.setText("Nothing collected yet.")
        self.export_btn.setEnabled(False)
        for t in self._tiles.values():
            t._value.setText("-")
        for bars in self._cards.values():
            bars.set_rows([])
        self.inner.setCurrentIndex(0)
        self._apply_empty_state()

    def _collected_messages(self) -> list:
        bot_id = self.session.bot_id
        if self.session.chat is not None:
            return store.load_messages_for(bot_id, self.session.chat)
        path = store.messages_path(bot_id)
        return intel.load_messages(path) if os.path.exists(path) else []

    def _load_collected(self) -> None:
        bot_id = self.session.bot_id
        if bot_id is None:
            return
        self._loaded_for = (bot_id, self.session.chat)
        where = f"chat {self.session.chat}" if self.session.chat is not None else "all chats"
        try:
            self.messages = self._collected_messages()
            self.index = intel.scan_messages(self.messages)
        except Exception as exc:
            self.main.log(f"[ERROR] Could not analyse collected messages: {exc}")
            self.clear_view()
            return
        if not self.messages:
            self.clear_view()
            self.loaded.setText("Nothing collected yet - messages are archived as the bot sees them.")
            return
        self._source = f"collected ({where})"
        self._show_loaded()

    def _show_loaded(self) -> None:
        self.export_btn.setEnabled(True)
        try:
            self._refresh_overview()
        except Exception as exc:
            self.main.log(f"[ERROR] Could not render the report: {exc}")
            return
        self.inner.setCurrentIndex(0)
        self.main.log(f"[OK] {self.index.messages} messages analysed ({self._source}).")

    def _refresh_overview(self) -> None:
        idx = self.index
        span = ""
        if idx.date_min and idx.date_max:
            from datetime import datetime, timezone
            fmt = "%Y-%m-%d"
            span = (f"  ·  {datetime.fromtimestamp(idx.date_min, timezone.utc).strftime(fmt)} "
                    f"-> {datetime.fromtimestamp(idx.date_max, timezone.utc).strftime(fmt)}")
        self.loaded.setText(f"{os.path.basename(self._source)}  ·  {idx.messages} messages{span}")
        totals = idx.type_totals()
        vals = {
            "messages": idx.messages, "senders": len(idx.senders),
            "links": sum(totals.get(t, 0) for t in intel.LINK_TYPES),
            "crypto": sum(totals.get(t, 0) for t in intel.CRYPTO_TYPES),
            "phone": totals.get("phone", 0), "media": idx.media_count,
        }
        for k, v in vals.items():
            self._tiles[k]._value.setText(str(v))
        for mode, bars in self._cards.items():
            bars.set_rows(self._top_rows(mode, 6))

    def _top_rows(self, mode, n):
        idx = self.index
        if idx is None:
            return []
        if mode == "senders":
            return [(s.label, s.label, "", s.count) for s in idx.top_senders(n)]
        rows = idx.top_values(_MODE_TYPES[mode], n)
        return [(value, value, kind, count) for value, kind, count in rows]

    # ---- detail drill-down ----
    def _open_detail(self, mode, value) -> None:
        if self.index is None:
            return
        while self.detail_host_lay.count():
            w = self.detail_host_lay.takeAt(0).widget()
            if w:
                w.deleteLater()

        header = QHBoxLayout()
        back = icon_button("Back", "back"); back.clicked.connect(lambda: self.inner.setCurrentIndex(0))
        title = QLabel(("Senders" if mode == "senders" else dict((m, t) for m, t, *_ in _REPORT_CARDS)[mode]))
        title.setStyleSheet("font-weight:600; font-size:15px;")
        header.addWidget(back); header.addSpacing(8); header.addWidget(title); header.addStretch(1)
        hw = QWidget(); hw.setLayout(header); self.detail_host_lay.addWidget(hw)

        all_rows = self._top_rows(mode, 40)
        if not all_rows:
            # Nothing for this category: just a single hint, no list, no panel.
            note = QLabel("No data yet"); note.setObjectName("Muted")
            note.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            self.detail_host_lay.addWidget(note, 1)
            self.inner.setCurrentIndex(1)
            return

        body = QHBoxLayout(); body.setSpacing(14)
        # left: full ranked list of items in this mode
        left = QFrame(); left.setObjectName("Card"); left.setMaximumWidth(330)
        ll = QVBoxLayout(left); ll.setContentsMargins(12, 12, 12, 12)
        ll.addWidget(QLabel("All items" if mode != "senders" else "All senders"))
        self._detail_list = HBarList(row_height=28)
        self._detail_list.set_rows(all_rows)
        self._detail_list.clicked.connect(lambda v, m=mode: self._show_item(m, v))
        lscroll = QScrollArea(); lscroll.setWidgetResizable(True); lscroll.setFrameShape(QFrame.Shape.NoFrame)
        lscroll.setWidget(self._detail_list)
        ll.addWidget(lscroll)
        body.addWidget(left)

        # right: the selected item's panel
        self._detail_right = QVBoxLayout()
        rightw = QWidget(); rightw.setLayout(self._detail_right)
        body.addWidget(rightw, 1)
        bw = QWidget(); bw.setLayout(body); self.detail_host_lay.addWidget(bw, 1)

        self._show_item(mode, value if value is not None else all_rows[0][0])
        self.inner.setCurrentIndex(1)

    def _show_item(self, mode, value) -> None:
        while self._detail_right.count():
            w = self._detail_right.takeAt(0).widget()
            if w:
                w.deleteLater()
        if value is None:
            return
        panel = (self._sender_panel(value) if mode == "senders"
                 else self._indicator_panel(mode, value))
        self._detail_right.addWidget(panel)

    def _occ_for(self, mode, value):
        occ = []
        for t in _MODE_TYPES[mode]:
            occ += self.index.occurrences(t, value)
        return occ

    def _indicator_panel(self, mode, value) -> QWidget:
        from collections import Counter
        occ = self._occ_for(mode, value)
        card = QFrame(); card.setObjectName("Card")
        lay = QVBoxLayout(card); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(3)
        head = QLabel(value); head.setStyleSheet("font-weight:600; font-size:15px;"); head.setWordWrap(True)
        head.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(head)
        sub = QLabel(f"{len(occ)} occurrences  ·  {len({o.sender for o in occ})} sender(s)")
        sub.setObjectName("Muted"); lay.addWidget(sub)
        lay.addSpacing(4)
        lay.addWidget(Collapsible("Over time",
                                  lambda: self._tb(intel.time_buckets([o.date for o in occ])), open=True))
        by = Counter(o.sender for o in occ)
        lay.addWidget(Collapsible(f"Posted by ({len(by)})",
                                  lambda: self._bar(by.most_common(15))))
        lay.addWidget(Collapsible(f"Messages ({len(occ)})",
                                  lambda: self._messages_table(occ)))
        lay.addWidget(self._item_export_button(value, occ), 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame); scroll.setWidget(card)
        return scroll

    # Indicator types grouped for the per-sender profile, with honest labels.
    _SENDER_IOC_GROUPS = [
        ("Links & addresses shared", ("url", "telegram_invite", "email", "btc", "eth", "ton")),
        ("@mentions used", ("mention",)),
        ("Possible phone numbers", ("phone",)),   # regex is loose, so: "possible"
    ]

    def _sender_panel(self, label) -> QWidget:
        from datetime import datetime, timezone
        st = self.index.senders.get(label)
        rows = intel.sender_texts(self.messages, label)   # (date, mid, text), oldest first
        texts = [t for _, _, t in rows]
        dates = [d for d, _, _ in rows if d]

        card = QFrame(); card.setObjectName("Card")
        lay = QVBoxLayout(card); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(3)
        head = QLabel(label); head.setStyleSheet("font-weight:600; font-size:15px;")
        head.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(head)

        # One honest summary line: volume, span, how many distinct days, size.
        n = st.count if st else len(texts)
        bits = [f"{n} text messages"]
        if dates:
            d0 = datetime.fromtimestamp(min(dates), timezone.utc).strftime("%Y-%m-%d")
            d1 = datetime.fromtimestamp(max(dates), timezone.utc).strftime("%Y-%m-%d")
            days = len({datetime.fromtimestamp(d, timezone.utc).date() for d in dates})
            bits.append(f"{d0} -> {d1}")
            bits.append(f"{days} active day(s)")
        if texts:
            bits.append(f"~{sum(len(t) for t in texts) // max(len(texts), 1)} chars/msg")
        sub = QLabel("  ·  ".join(bits)); sub.setObjectName("Muted"); sub.setWordWrap(True)
        lay.addWidget(sub)

        # Headline figures stay sober; everything else is one click away.
        shared = sum(len(v) for t, v in self._sender_indicators(label).items())
        chips = QLabel(f"{shared} indicator(s) shared  ·  click a section below to dig in")
        chips.setObjectName("Muted"); lay.addWidget(chips)
        lay.addSpacing(4)

        # The one default visual: when did they talk.
        lay.addWidget(Collapsible("Activity over time",
                                  lambda: self._tb(intel.time_buckets(dates)), open=True))
        lay.addWidget(Collapsible("Active hours (UTC) - quiet hours hint at a timezone",
                                  lambda: self._tb([(f"{h:02d}", c)
                                                    for h, c in intel.hour_histogram(dates)], 120)))
        words = intel.word_frequencies(texts, 15)
        lay.addWidget(Collapsible(f"Most-used words ({len(words)})",
                                  lambda: self._bar([(w, c) for w, c in words]) if words
                                  else self._muted("Not enough text to rank words.")))

        posted = self._sender_indicators(label)
        for title, types in self._SENDER_IOC_GROUPS:
            group = sorted(((v, c) for t in types for v, c in posted.get(t, [])),
                           key=lambda r: -r[1])
            if group:
                lay.addWidget(Collapsible(f"{title} ({len(group)})",
                                          lambda g=group: self._bar(g[:15])))
        lay.addWidget(Collapsible(f"Their messages ({len(rows)})",
                                  lambda: self._sender_messages_table(rows)))
        lay.addWidget(self._sender_export_button(label, rows), 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)

        # Tall profile: let it scroll inside the detail area.
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame); scroll.setWidget(card)
        return scroll

    def _tb(self, buckets, minh=None) -> TimeBars:
        tb = TimeBars()
        if minh:
            tb.setMinimumHeight(minh)
        tb.set_buckets(buckets)
        return tb

    def _sender_indicators(self, label) -> dict:
        from collections import defaultdict
        out = defaultdict(list)
        for t, values in self.index.indicators.items():
            for value, occ in values.items():
                c = sum(1 for o in occ if o.sender == label)
                if c:
                    out[t].append((value, c))
        return out

    def _bar(self, rows) -> HBarList:
        b = HBarList(row_height=24)
        b.set_rows([(v, v, "", c) for v, c in rows])
        b.setFixedHeight(24 * max(len(rows), 1) + 4)
        return b

    def _muted(self, text) -> QLabel:
        l = QLabel(text); l.setObjectName("Muted"); l.setWordWrap(True)
        return l

    def _sender_messages_table(self, rows) -> QTableWidget:
        from datetime import datetime, timezone
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Date", "Message"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False); table.setShowGrid(False)
        table.setWordWrap(True); table.setMaximumHeight(240)
        for date, _mid, text in rows[-300:][::-1]:   # newest first
            r = table.rowCount(); table.insertRow(r)
            d = datetime.fromtimestamp(date, timezone.utc).strftime("%Y-%m-%d %H:%M") if date else ""
            table.setItem(r, 0, QTableWidgetItem(d))
            table.setItem(r, 1, QTableWidgetItem(text))
        return table

    def _sender_export_button(self, label, rows):
        from datetime import datetime, timezone

        def data():
            out = []
            for date, mid, text in rows:
                iso = datetime.fromtimestamp(date, timezone.utc).isoformat() if date else ""
                out.append([mid, iso, text])
            return ["message_id", "date", "text"], out

        safe = re.sub(r"[^\w.-]+", "_", label).strip("_") or "sender"
        return build_export_button(self, [("This sender's messages", f"sender_{safe}", data)],
                                   log=self.main.log)

    def _section(self, text) -> QLabel:
        l = QLabel(text); l.setStyleSheet(f"color:{ACCENT}; padding-top:4px; font-size:12px;")
        return l

    def _messages_table(self, occ) -> QTableWidget:
        from datetime import datetime, timezone
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Msg", "Date", "Text"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False); table.setShowGrid(False)
        table.setMaximumHeight(200)
        for o in occ[:200]:
            r = table.rowCount(); table.insertRow(r)
            d = (datetime.fromtimestamp(o.date, timezone.utc).strftime("%Y-%m-%d %H:%M")
                 if o.date else "")
            for c, v in enumerate([str(o.message_id), d, o.text]):
                table.setItem(r, c, QTableWidgetItem(v))
        return table

    # ---- export datasets (one Export button, choose what + CSV/JSON) ----
    def _overview_datasets(self):
        from datetime import datetime, timezone

        def iso(ts):
            return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else ""

        def messages():
            rows = [[m.get("message_id"), iso(intel._msg_date(m)),
                     intel._sender_label(m), m.get("text") or m.get("caption") or ""]
                    for m in self.messages]
            return ["message_id", "date", "sender", "text"], rows

        def senders():
            rows = [[s.label, s.count, ", ".join(f"{k}:{v}" for k, v in s.types.items())]
                    for s in (self.index.top_senders() if self.index else [])]
            return ["sender", "messages", "indicators"], rows

        def links():
            rows = [[v, t, c] for v, t, c in
                    (self.index.top_values(intel.LINK_TYPES) if self.index else [])]
            return ["link", "type", "count"], rows

        def indicators():
            rows = []
            if self.index:
                for t, values in self.index.indicators.items():
                    for value, occ in values.items():
                        rows.append([t, value, len(occ)])
            return ["type", "value", "count"], rows

        return [
            ("Messages", "messages", messages),
            ("Members / senders", "senders", senders),
            ("Links", "links", links),
            ("All indicators", "indicators", indicators),
        ]

    def _item_export_button(self, value, occ):
        from datetime import datetime, timezone

        def provider():
            rows = [[o.message_id,
                     datetime.fromtimestamp(o.date, timezone.utc).isoformat() if o.date else "",
                     o.sender, o.text] for o in occ]
            return ["message_id", "date", "sender", "text"], rows

        safe = "".join(c for c in value[:24] if c.isalnum() or c in "-_") or "item"
        return build_export_button(self, [("Occurrences", f"occ_{safe}", provider)],
                                   log=self.main.log, label="Export")


# --------------------------------------------------------------------------
# Conversation: a Telegram-style timeline of a chat, auto-backfilled.
# --------------------------------------------------------------------------

_SENDER_COLORS = ["#E17076", "#5CAF7D", "#4F9FD6", "#9B86E3", "#DE7AA8",
                  "#53B7B9", "#E09B52", "#6E8FE0"]


class ConversationPage(BasePage):
    title = "Conversation"
    fill = True
    subtitle = ("The chat's messages laid out like Telegram - who said what, when. Fills in live, "
                "and walks the whole history backwards on its own (no limit) in the background.")

    def build(self) -> None:
        self._msgs: dict = {}       # message_id -> msg
        self._render_pending = False

        self.header = QLabel("Connect to a chat to see its conversation.")
        self.header.setObjectName("Muted")
        self.root.addWidget(self.header)

        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.host = QWidget(); self.host.setStyleSheet("background:transparent;")
        self.col = QVBoxLayout(self.host)
        self.col.setContentsMargins(4, 4, 4, 4); self.col.setSpacing(4)
        self.col.addStretch(1)
        self.scroll.setWidget(self.host)
        self.root.addWidget(self.scroll, 1)

        # iOS-style composer: type a message and send it as the bot, right in the
        # conversation. Disabled with a reason when the bot can't post here.
        self.composer = QFrame(); self.composer.setObjectName("Composer")
        cl = QHBoxLayout(self.composer); cl.setContentsMargins(6, 4, 6, 4); cl.setSpacing(6)
        self.msg_in = QLineEdit(); self.msg_in.setObjectName("ComposerInput")
        self.msg_in.setPlaceholderText("Message")
        self.msg_in.returnPressed.connect(self._send)
        self.send_btn = QToolButton(); self.send_btn.setObjectName("SendBtn")
        self.send_btn.setIcon(make_icon("arrow_up", "#FFFFFF", 16))
        self.send_btn.setIconSize(QSize(16, 16))
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self._send)
        cl.addWidget(self.msg_in, 1); cl.addWidget(self.send_btn)
        self.root.addWidget(self.composer)
        self._can_send = False
        self._set_can_send(False, "Connect to a chat to send")

        self._init_empty(self.header, self.scroll, self.composer)

    # ---- lifecycle ----
    def clear_view(self) -> None:
        self._msgs = {}
        self._render(scroll_bottom=False)
        self.header.setText("Connect to a chat to see its conversation.")
        self.msg_in.clear()
        self._set_can_send(False, "Connect to a chat to send")
        self.main.set_viewed_chat(None)
        self._apply_empty_state()

    def on_shown(self) -> None:
        if not self._apply_empty_state():
            self.main.set_viewed_chat(None)
            return
        chat = self.session.chat
        if chat is None or self.session.bot_id is None:
            self.main.set_viewed_chat(None)
            self.clear_view()
            return
        self.header.setText(f"Chat {chat}")
        self._msgs = {m["message_id"]: m for m in
                      store.load_messages_for(self.session.bot_id, chat)
                      if m.get("message_id") is not None}
        if self._msgs:
            store.update_backfill(self.session.bot_id, chat, max_seen=max(self._msgs))
        self._render(scroll_bottom=True)
        self._check_send_right()
        # Hand priority to the chat on screen; the window owns and bounds the walk.
        self.main.set_viewed_chat(self.session.bot_id, chat)

    # ---- composer: send a message as the bot, gated on send rights ----
    def _set_can_send(self, ok: bool, reason: str = "") -> None:
        self._can_send = ok
        self.msg_in.setEnabled(ok)
        self.send_btn.setEnabled(ok)
        self.msg_in.setPlaceholderText("Message" if ok else (reason or "No rights to send messages here"))

    def _check_send_right(self) -> None:
        try:
            client, chat = self.session.client(), self.session.require_chat()
        except ValueError:
            self._set_can_send(False, "Connect to a chat to send")
            return
        self._set_can_send(False, "Checking if the bot can post here...")
        self.run(lambda: api.bot_send_right(client, chat),
                 lambda ok: self._set_can_send(bool(ok),
                                               "" if ok else "No rights to send messages here"))

    def _send(self) -> None:
        if not self._can_send:
            return
        text = self.msg_in.text().strip()
        if not text:
            return
        try:
            client, chat = self.session.client(), self.session.require_chat()
        except ValueError:
            return
        self.msg_in.clear()
        bot_id = self.session.bot_id

        def done(res):
            # getUpdates doesn't echo the bot's own messages, so add it ourselves.
            msg = {"message_id": res.get("message_id"), "chat_id": chat,
                   "date": res.get("date"),
                   "text": res.get("text") or text,
                   "from": {"id": bot_id, "username": self.session.bot_username,
                            "first_name": self.session.bot_username or "this bot"}}
            store.append_messages(bot_id, [msg])
            self.add_message(msg)

        self.run(lambda: api.send_message(client, chat, text), done, self.send_btn)

    def on_hidden(self) -> None:
        # Losing focus only drops priority: the walk may keep going if it still
        # fits the window's budget of chats, or yield its slot to an older chat.
        self.main.set_viewed_chat(None)

    def refresh_header(self) -> None:
        """Called by the window when this chat's walk starts/stops."""
        if self.session.chat is not None and self.session.bot_id is not None:
            self._render(scroll_bottom=False)

    # ---- live + backfill feed ----
    def add_message(self, msg: dict) -> None:
        mid = msg.get("message_id")
        if mid is None or mid in self._msgs:
            return
        self._msgs[mid] = msg
        self._schedule_render()

    def _schedule_render(self) -> None:
        if not self._render_pending:
            self._render_pending = True
            QTimer.singleShot(200, lambda: self._render(scroll_bottom=True))

    # ---- rendering ----
    def _render(self, *, scroll_bottom: bool) -> None:
        self._render_pending = False
        if self.session.chat is not None:
            walking = self.main.is_backfilling(self.session.bot_id, self.session.chat)
            suffix = " · fetching older..." if walking else ""
            self.header.setText(f"Chat {self.session.chat}  ·  {len(self._msgs)} messages{suffix}")
        # Clear everything except the trailing stretch.
        while self.col.count() > 1:
            item = self.col.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        limit = self.main.settings.get("conversation_limit", 500)
        ordered = [self._msgs[k] for k in sorted(self._msgs)][-limit:]
        last_sender = None
        for msg in ordered:
            sender = msg.get("from") or {}
            key = sender.get("id") or sender.get("username") or sender.get("first_name")
            self.col.insertWidget(self.col.count() - 1,
                                  self._bubble_row(msg, show_name=(key != last_sender)))
            last_sender = key
        if scroll_bottom:
            QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()))

    def _bubble_row(self, msg: dict, show_name: bool) -> QWidget:
        from datetime import datetime, timezone
        if msg.get("_system"):
            lab = QLabel(msg.get("text", ""))
            lab.setStyleSheet(
                f"color:{TEXT_MUTED}; background:{SYS_PILL}; border-radius:10px; padding:3px 12px;")
            row = QWidget(); row.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(row); rl.setContentsMargins(0, 2, 0, 2)
            rl.addStretch(1); rl.addWidget(lab); rl.addStretch(1)
            return row
        bubble = QFrame(); bubble.setObjectName("Bubble")
        bl = QVBoxLayout(bubble); bl.setContentsMargins(12, 7, 12, 5); bl.setSpacing(1)
        sender = msg.get("from") or {}
        parts = [bubble]
        if show_name:
            name = ("@" + sender["username"]) if sender.get("username") else (
                sender.get("first_name") or (f"id {sender['id']}" if sender.get("id") else "unknown"))
            color = _SENDER_COLORS[hash(str(sender.get("id") or name)) % len(_SENDER_COLORS)]
            nl = QLabel(name); nl.setStyleSheet(f"color:{color}; font-weight:600; font-size:12px;")
            nl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            bl.addWidget(nl); parts.append(nl)
        txt = QLabel(msg.get("text") or ""); txt.setWordWrap(True)
        txt.setMaximumWidth(520)
        txt.setStyleSheet(f"color:{TEXT}; font-size:13px;")  # explicit: every bubble reads the same
        txt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bl.addWidget(txt); parts.append(txt)
        # Time bottom-right, compact (HH:MM), full date on hover - like Telegram.
        date = msg.get("date")
        if date:
            dt = datetime.fromtimestamp(date, timezone.utc)
            tl = QLabel(dt.strftime("%H:%M"))
            tl.setToolTip(dt.strftime("%Y-%m-%d %H:%M UTC"))
        else:
            tl = QLabel("")
        tl.setStyleSheet(f"color:{TEXT_MUTED}; font-size:10px;")
        tl.setAlignment(Qt.AlignmentFlag.AlignRight)
        bl.addWidget(tl); parts.append(tl)

        # Right-click a message for the styled menu, wherever you click on it. The
        # inner labels are text-selectable, which would otherwise pop their own
        # default menu over part of the bubble - so every part routes here.
        for w in parts:
            self._attach_msg_menu(w, msg)

        row = QWidget(); row.setStyleSheet("background:transparent;")
        rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(bubble); rl.addStretch(1)
        return row

    def _attach_msg_menu(self, widget, msg: dict) -> None:
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda pos, w=widget, m=msg: self._msg_menu(m, w, pos))

    def _msg_menu(self, msg: dict, widget, pos) -> None:
        menu = styled_menu(widget)
        menu.addAction(make_icon("copy", TEXT, 17), "Copy text",
                       lambda: self._copy(msg.get("text", "")))
        menu.addAction(make_icon("copy", TEXT, 17), "Copy all", self._copy_all)
        menu.addSeparator()
        menu.addAction(make_icon("trash", DANGER, 17), "Erase",
                       lambda: self._grab_erase(msg))
        menu.exec(widget.mapToGlobal(pos))

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text or "")

    def _copy_all(self) -> None:
        from datetime import datetime, timezone
        lines = []
        for mid in sorted(self._msgs):
            m = self._msgs[mid]
            if m.get("_system"):
                lines.append(m.get("text", "")); continue
            s = m.get("from") or {}
            who = ("@" + s["username"]) if s.get("username") else (s.get("first_name") or "unknown")
            d = m.get("date")
            ts = datetime.fromtimestamp(d, timezone.utc).strftime("%Y-%m-%d %H:%M") if d else ""
            lines.append(f"[{ts}] {who}: {m.get('text','')}")
        QApplication.clipboard().setText("\n".join(lines))
        self.main.log(f"[OK] Copied {len(lines)} messages to the clipboard.")

    def _grab_erase(self, msg: dict) -> None:
        mid = msg.get("message_id")
        if not isinstance(mid, int) or mid < 1:
            return
        try:
            client, chat = self.session.client(), self.session.require_chat()
        except ValueError as e:
            self.main.log(f"[ERROR] {e}")
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Erase message")
        box.setText("This PERMANENTLY DELETES this message from the chat. Its content is "
                    "already saved here, so you keep it - but the original is removed for "
                    "everyone and the sender may notice.\n\nRun anyway?")
        run = box.addButton("Run anyway", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is not run:
            return

        def done(_):
            self._msgs.pop(mid, None)
            self._render(scroll_bottom=False)
            self.main.log(f"[OK] Message {mid} erased from the chat.")
        self.run(lambda: api.delete_message(client, chat, mid), done)


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

_NAV = [
    ("Connection", [("Bot & chat", ConnectionPage)]),
    ("Members", [("Admins", AdminsPage), ("Member info", MemberPage),
                 ("Bot rights", RightsPage), ("Invitations", InvitePage)]),
    ("Analyse", [("Conversation", ConversationPage), ("Report", ReportPage)]),
]


class SettingsDialog(QDialog):
    """A small panel of easily-tuned knobs. `values()` returns the new settings."""

    def __init__(self, parent, settings: dict, main=None):
        super().__init__(parent)
        self._main = main
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)
        form = QFormLayout(self)
        form.setContentsMargins(22, 20, 22, 16)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.theme = QComboBox(); self.theme.addItems(["Light", "Dark"])
        self.theme.setCurrentIndex(1 if settings.get("theme") == "dark" else 0)
        form.addRow("Theme", self.theme)

        self.font = QSpinBox(); self.font.setRange(11, 18); self.font.setSuffix("  px")
        self.font.setValue(int(settings.get("font_size", 13)))
        form.addRow("Font size", self.font)

        self.pace = QDoubleSpinBox(); self.pace.setRange(1.0, 15.0)
        self.pace.setSingleStep(0.1); self.pace.setDecimals(1); self.pace.setSuffix("  s")
        self.pace.setValue(float(settings.get("backfill_pace", 3.2)))
        self.pace.setToolTip("Delay between each forwarded message when walking the past.\n"
                             "Lower is faster but risks Telegram's rate limit.")
        form.addRow("Backfill pace", self.pace)

        self.maxbf = QSpinBox(); self.maxbf.setRange(1, 5)
        self.maxbf.setValue(int(settings.get("max_backfills", 3)))
        self.maxbf.setToolTip("How many chats are walked into the past at once "
                              "(the one on screen is always one of them).")
        form.addRow("Chats walked at once", self.maxbf)

        self.gap = QSpinBox(); self.gap.setRange(50, 2000); self.gap.setSingleStep(50)
        self.gap.setValue(int(settings.get("max_gap", 400)))
        self.gap.setToolTip("Stop walking a chat after this many missing ids in a row "
                            "(you've likely hit the start).")
        form.addRow("Give up after N gaps", self.gap)

        self.limit = QSpinBox(); self.limit.setRange(100, 5000); self.limit.setSingleStep(100)
        self.limit.setValue(int(settings.get("conversation_limit", 500)))
        self.limit.setToolTip("Most recent messages kept on screen in the timeline.")
        form.addRow("Messages on screen", self.limit)

        self.logs = QCheckBox("Show the logs drawer on launch")
        self.logs.setChecked(bool(settings.get("logs_open", False)))
        form.addRow("", self.logs)

        manage = icon_button("Manage bots", "robot")
        manage.setToolTip("Permanently delete a saved bot (token + its chats and messages) "
                          "or a single chat.")
        manage.clicked.connect(self._manage_bots)
        form.addRow("Stored data", manage)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setObjectName("Primary")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _manage_bots(self) -> None:
        BotManagementDialog(self, self._main).exec()

    def values(self) -> dict:
        return {
            "theme": "dark" if self.theme.currentIndex() == 1 else "light",
            "font_size": self.font.value(),
            "backfill_pace": round(self.pace.value(), 1),
            "max_backfills": self.maxbf.value(),
            "max_gap": self.gap.value(),
            "conversation_limit": self.limit.value(),
            "logs_open": self.logs.isChecked(),
        }


class BotManagementDialog(QDialog):
    """Permanently delete stored data: a whole bot (token + chats + messages) or
    a single chat. This removes files under ~/.telegram_tools - it does not touch
    anything on Telegram."""

    def __init__(self, parent, main):
        super().__init__(parent)
        self._main = main
        self.setWindowTitle("Manage bots")
        self.setMinimumSize(520, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(10)
        intro = QLabel("Saved locally on this machine. Deleting is permanent and removes "
                       "the collected messages too - it does not affect Telegram.")
        intro.setObjectName("Muted"); intro.setWordWrap(True)
        lay.addWidget(intro)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Bot / Chat", "ID", "Messages"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._sync_button)
        lay.addWidget(self.tree, 1)

        row = QHBoxLayout()
        self.del_btn = icon_button("Delete permanently", "trash")
        self.del_btn.setEnabled(False)
        self.del_btn.clicked.connect(self._delete_selected)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        row.addWidget(self.del_btn); row.addStretch(1); row.addWidget(close)
        lay.addLayout(row)
        self._reload()

    def _reload(self) -> None:
        self.tree.clear()
        tokens = store.load_tokens()
        # Every bot we have anything for: a token, known chats, or a message log.
        bot_ids = set(tokens)
        bot_ids.update(_read_json_keys())
        for bid in sorted(bot_ids, key=lambda x: str(x)):
            info = tokens.get(str(bid), {})
            name = f"@{info.get('username')}" if info.get("username") else f"bot {bid}"
            top = QTreeWidgetItem([name, str(bid), str(store.collected_count(bid))])
            top.setData(0, Qt.ItemDataRole.UserRole, ("bot", str(bid)))
            top.setIcon(0, make_icon("robot", TEXT, 16))
            chats = store.load_chats(bid)
            for cid, c in sorted(chats.items(), key=lambda kv: str(kv[1].get("title") or "")):
                title = c.get("title") or cid
                child = QTreeWidgetItem([f"{title}  ({c.get('type','?')})", str(cid), ""])
                child.setData(0, Qt.ItemDataRole.UserRole, ("chat", str(bid), str(cid)))
                child.setIcon(0, make_icon("users", TEXT_MUTED, 16))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
        self.tree.expandAll()
        self._sync_button()

    def _sync_button(self) -> None:
        self.del_btn.setEnabled(bool(self.tree.selectedItems()))

    def _delete_selected(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if data[0] == "bot":
            bid = data[1]
            label = items[0].text(0)
            if not self._confirm(f"Delete {label} and everything collected with it "
                                 "(all its chats and messages)?"):
                return
            store.delete_bot(bid)
            if self._main is not None:
                self._main._after_bot_deleted(bid)
        else:
            _, bid, cid = data
            if not self._confirm(f"Delete chat {cid} and its collected messages?"):
                return
            store.delete_chat_fully(bid, cid)
            if self._main is not None:
                self._main._after_chat_deleted(bid, cid)
        self._reload()

    def _confirm(self, text: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Delete permanently")
        box.setText(text + "\n\nThis cannot be undone.")
        yes = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is yes


def _read_json_keys() -> set:
    """Bot ids that appear in the stored chats, backfill or message files."""
    ids: set = set()
    try:
        ids.update(store._read(store._CHATS, {}).keys())
    except Exception:
        pass
    try:
        ids.update(store._read(store._BACKFILL, {}).keys())
    except Exception:
        pass
    try:
        for fn in os.listdir(store._MSG_DIR):
            if fn.endswith(".ndjson"):
                ids.add(fn[:-len(".ndjson")])
    except OSError:
        pass
    return ids


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.session = Session()
        self.settings = store.load_settings()
        self._workers: set = set()
        self._threads: set = set()       # every live QThread, kept until finished
        self._pollers: dict = {}         # bot_id -> UpdatesPoller
        self._chats_by_bot: dict = {}    # bot_id -> {chat_id: info}
        self._backfills: dict = {}       # (bot_id, chat_id) -> BackfillWorker | None (reserving)
        self._viewed_chat = None         # (bot_id, chat_id) shown in Conversation
        self._cant_backfill: set = set() # (bot_id, chat_id) the bot can't walk (no delete right)
        self._hidden_tokens: set = set() # bot_ids hidden from the picker this session
        self._hidden_chats: set = set()  # (bot_id, chat_id str) hidden from the picker this session
        self.arrivals: list = []
        self.setWindowTitle("Telegram Tools")
        self.setWindowIcon(app_icon(ACCENT))
        self.resize(1040, 680)

        self._current_page = None
        self._build_ui()
        self.nav.setCurrentRow(1)  # first real page (row 0 is a section label)
        self._refresh_token_menu()
        self._start_saved_pollers()

    def _build_ui(self) -> None:
        """Construct the whole visual tree. Called again (keeping the session and
        pollers) when the theme/font changes, so every inline-coloured widget is
        rebuilt from the new palette."""
        central = QWidget()
        self.setCentralWidget(central)   # replaces + deletes any previous tree
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_connection_bar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0); right.setSpacing(0)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        right.addWidget(self._build_log_drawer())
        right.addWidget(self._build_status_bar())
        rightw = QWidget(); rightw.setLayout(right)
        body.addWidget(rightw, 1)
        bodyw = QWidget(); bodyw.setLayout(body)
        outer.addWidget(bodyw, 1)

        self._build_pages()
        self.logbox.setVisible(self.settings.get("logs_open", False))
        self.logs_toggle.setChecked(self.settings.get("logs_open", False))

    # ---- chrome ----
    def _build_connection_bar(self) -> QWidget:
        bar = QFrame(); bar.setObjectName("ConnectionBar")
        lay = QHBoxLayout(bar); lay.setContentsMargins(16, 11, 16, 11); lay.setSpacing(12)

        # Status chip on the far left: a coloured dot + the bot name.
        chip = QFrame(); chip.setObjectName("StatusChip")
        cl = QHBoxLayout(chip); cl.setContentsMargins(12, 6, 12, 6); cl.setSpacing(8)
        self.dot = QLabel("●"); self.dot.setObjectName("Dot"); self.dot.setStyleSheet(f"color:{DANGER};")
        self.status = QLabel("Not connected")
        cl.addWidget(self.dot); cl.addWidget(self.status)

        # Token is shown in clear: this is an OSINT tool, you need to see which
        # key you're working with.
        self.token_in = QLineEdit(self.session.token)
        self.token_in.setPlaceholderText("Bot token")
        # Picker: the bots you've already connected.
        self.token_btn = QToolButton()
        self.token_btn.setIcon(make_icon("chevron", TEXT, 16))
        self.token_btn.setIconSize(ICON)
        self.token_btn.setToolTip("Pick a saved bot")
        self.token_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.token_btn.clicked.connect(self._pick_token)

        self.chat_in = QLineEdit()
        self.chat_in.setPlaceholderText("Chat id or @username")
        self.chat_in.setMaximumWidth(210)
        # Picker: list the chats the bot can see so you don't need to know the id.
        self.pick_btn = QToolButton()
        self.pick_btn.setIcon(make_icon("chevron", TEXT, 16))
        self.pick_btn.setIconSize(ICON)
        self.pick_btn.setToolTip("List chats the bot can see")
        self.pick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pick_btn.clicked.connect(self._pick_chat)

        # No Connect button: typing a valid token connects on its own; the dot
        # is the indicator (red not connected, amber checking, green connected).
        self._token_timer = QTimer(self); self._token_timer.setSingleShot(True)
        self._token_timer.timeout.connect(self._maybe_auto_connect)
        self.token_in.textChanged.connect(self._on_token_changed)
        self._chat_timer = QTimer(self); self._chat_timer.setSingleShot(True)
        self._chat_timer.timeout.connect(self._on_chat_settled)
        self.chat_in.textChanged.connect(self._on_chat_changed)

        chat_group = QWidget(); chat_group.setStyleSheet("background:transparent;")
        cg = QHBoxLayout(chat_group); cg.setContentsMargins(0, 0, 0, 0); cg.setSpacing(4)
        cg.addWidget(self._field_with_icon("users", self.chat_in))
        cg.addWidget(self.pick_btn)

        token_group = QWidget(); token_group.setStyleSheet("background:transparent;")
        tg = QHBoxLayout(token_group); tg.setContentsMargins(0, 0, 0, 0); tg.setSpacing(4)
        tg.addWidget(self._field_with_icon("key", self.token_in, stretch=True), 1)
        tg.addWidget(self.token_btn)

        lay.addWidget(chip)
        lay.addWidget(token_group, 1)
        lay.addWidget(chat_group)
        return bar

    def _refresh_token_menu(self) -> None:
        # Nothing persistent to build here; the menu is created on click.
        pass

    def _pick_token(self) -> None:
        tokens = {bid: info for bid, info in store.load_tokens().items()
                  if int(bid) not in self._hidden_tokens}
        menu = style_menu(DeletableMenu(self.token_btn))
        menu.set_delete_handler(self._menu_delete)
        if not tokens:
            act = menu.addAction("No saved bots yet - connect one and it's remembered")
            act.setEnabled(False)
        for bid, info in tokens.items():
            label = f"@{info.get('username') or bid}"
            act = menu.addAction(make_icon("robot", TEXT, 17), label)
            act.setData(("token", int(bid)))
            act.triggered.connect(lambda _=False, t=info.get("token", ""): self._use_token(t))
        if tokens:
            hint = menu.addAction("Right-click an entry to forget it")
            hint.setEnabled(False)
        menu.exec(self.token_btn.mapToGlobal(self.token_btn.rect().bottomLeft()))

    def _use_token(self, token: str) -> None:
        self.token_in.setText(token)
        self._connect()

    def _resolve_chat(self, client, username: str) -> None:
        def done(chat):
            self._set_chat(chat["id"])
            self._on_chat_seen(self.session.bot_id, {
                "id": chat["id"], "title": chat.get("title") or username,
                "type": chat.get("type")})
            self.log(f"[OK] {username} resolved to {chat['id']}.")
        self.run_call(lambda: api.get_chat(client, username), done,
                      on_error=lambda m: self.log(f"[INFO] Could not resolve {username}: {m}"))

    def _pick_chat(self) -> None:
        # The background poller fills this list as it sees chats; it's remembered
        # on disk, so chats stay available even after their updates are gone.
        bot_id = self.session.bot_id
        chats = sorted((c for c in self.session.known_chats.values()
                        if (bot_id, str(c.get("id"))) not in self._hidden_chats),
                       key=lambda c: str(c.get("title") or ""))
        menu = style_menu(DeletableMenu(self.pick_btn))
        menu.set_delete_handler(self._menu_delete)
        if not chats:
            act = menu.addAction("No chats seen yet - have someone post in a group "
                                 "where the bot is, then it appears here")
            act.setEnabled(False)
        for c in chats:
            icon = "message" if c.get("type") in ("channel",) else "users"
            act = menu.addAction(make_icon(icon, TEXT, 17),
                                 f"{c['title']}  ({c['type']})  -  {c['id']}")
            act.setData(("chat", bot_id, str(c["id"])))
            act.triggered.connect(lambda _=False, cid=c["id"]: self._set_chat(cid))
        if chats:
            hint = menu.addAction("Right-click an entry to forget it")
            hint.setEnabled(False)
        menu.exec(self.pick_btn.mapToGlobal(self.pick_btn.rect().bottomLeft()))

    def _menu_delete(self, data) -> None:
        """Forget a picker entry for this session only (the on-disk history is
        kept; permanent removal lives in Settings -> Manage bots)."""
        kind = data[0]
        if kind == "token":
            bot_id = data[1]
            self._hidden_tokens.add(bot_id)
            # Forgetting a bot forgets its chats too, as asked.
            for cid in list(self._chats_by_bot.get(bot_id, {})):
                self._hidden_chats.add((bot_id, str(cid)))
            self.log(f"[INFO] Bot {bot_id} hidden from the picker for this session.")
        elif kind == "chat":
            bot_id, chat_id = data[1], str(data[2])
            self._hidden_chats.add((bot_id, chat_id))
            self.log(f"[INFO] Chat {chat_id} hidden from the picker for this session.")

    # ---- permanent deletion fallout (from Manage bots) ----
    def _after_bot_deleted(self, bot_id) -> None:
        b = int(bot_id)
        poller = self._pollers.pop(b, None)
        if poller is not None:
            poller.stop()
        for (bb, cc), w in list(self._backfills.items()):
            if bb == b and w is not None:
                w.stop()
        self._chats_by_bot.pop(b, None)
        self._hidden_tokens.discard(b)
        self._hidden_chats = {(x, c) for (x, c) in self._hidden_chats if x != b}
        if self.session.bot_id == b:
            self._disconnect_active("Bot deleted.")
        self.log(f"[OK] Bot {b} and its stored data were deleted.")

    def _after_chat_deleted(self, bot_id, chat_id) -> None:
        b, c = int(bot_id), str(chat_id)
        w = self._backfills.get((b, int(c))) if c.lstrip("-").isdigit() else None
        if w is not None:
            w.stop()
        self._chats_by_bot.get(b, {}).pop(c, None)
        self._hidden_chats.discard((b, c))
        self._cant_backfill.discard((b, int(c)) if c.lstrip("-").isdigit() else (b, c))
        if self.session.bot_id == b and str(self.session.chat) == c:
            self.session.chat = None
            self.chat_in.blockSignals(True); self.chat_in.clear(); self.chat_in.blockSignals(False)
            self._invalidate_display()
        else:
            self._refresh_active_page()
        self.schedule_backfills()
        self.log(f"[OK] Chat {c} of bot {b} and its messages were deleted.")

    def _disconnect_active(self, why: str) -> None:
        self._connected_token = None
        self.session.bot_id = None
        self.session.chat = None
        self.token_in.blockSignals(True); self.token_in.clear(); self.token_in.blockSignals(False)
        self.chat_in.blockSignals(True); self.chat_in.clear(); self.chat_in.blockSignals(False)
        self.set_bot_status(False, "Not connected")
        self._stop_all_backfills()
        self._invalidate_display()
        if why:
            self.log(f"[INFO] {why}")

    def _set_chat(self, chat_id) -> None:
        self.chat_in.setText(str(chat_id))
        self.session.chat = chat_id
        self.log(f"[OK] Chat set to {chat_id}.")

    def _field_with_icon(self, icon_name: str, line: QLineEdit, stretch: bool = False) -> QWidget:
        # Icon sits just left of the field and is centred on it, so it always
        # lines up with the text (Qt's inline action icons drift vertically).
        w = QWidget(); w.setStyleSheet("background:transparent;")
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(7)
        ic = QLabel(); ic.setPixmap(make_icon(icon_name, TEXT_MUTED, 16).pixmap(16, 16))
        ic.setFixedWidth(16)
        h.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(line, 1 if stretch else 0)
        return w

    _NAV_ICONS = {
        "Bot & chat": "plug", "Admins": "users", "Member info": "user",
        "Bot rights": "shield", "Invitations": "link", "New arrivals": "broadcast",
        "Archive messages": "archive", "Report": "chart", "Conversation": "message",
    }

    def _build_sidebar(self) -> QWidget:
        side = QFrame(); side.setObjectName("Sidebar"); side.setFixedWidth(224)
        lay = QVBoxLayout(side); lay.setContentsMargins(8, 12, 8, 12)
        self.nav = QListWidget(); self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(17, 17))
        self._page_rows: list = []  # row index -> page class or None
        for section, items in _NAV:
            head = QListWidgetItem(section.upper())
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            f = QFont(); f.setPointSize(8); f.setBold(True); head.setFont(f)
            head.setForeground(QColor(TEXT_MUTED))
            head.setSizeHint(QSize(0, 30))
            self.nav.addItem(head)
            self._page_rows.append(None)
            for label, cls in items:
                it = QListWidgetItem(make_icon(self._NAV_ICONS.get(label, "search"), TEXT_MUTED, 17), label)
                it.setSizeHint(QSize(0, 38))
                self.nav.addItem(it)
                self._page_rows.append(cls)
        self.nav.currentRowChanged.connect(self._nav_changed)
        lay.addWidget(self.nav)
        return side

    def _build_log_drawer(self) -> QWidget:
        # Hidden by default: results take the space, logs stay out of the way.
        self.logbox = QPlainTextEdit(); self.logbox.setObjectName("Log")
        self.logbox.setReadOnly(True); self.logbox.setFixedHeight(130)
        self.logbox.setVisible(False)
        return self.logbox

    def _build_status_bar(self) -> QWidget:
        bar = QFrame(); bar.setObjectName("StatusBar"); bar.setFixedHeight(30)
        lay = QHBoxLayout(bar); lay.setContentsMargins(16, 0, 10, 0); lay.setSpacing(8)
        self.logs_toggle = QToolButton()
        self.logs_toggle.setText("Logs")
        self.logs_toggle.setIcon(make_icon("list", TEXT_MUTED, 14))
        self.logs_toggle.setIconSize(QSize(14, 14))
        self.logs_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.logs_toggle.setCheckable(True)
        self.logs_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logs_toggle.setStyleSheet("border:none; padding:4px 8px; color:" + TEXT_MUTED + ";")
        self.logs_toggle.toggled.connect(self.logbox.setVisible)
        settings_btn = QToolButton()
        settings_btn.setText("Settings")
        settings_btn.setIcon(make_icon("gear", TEXT_MUTED, 14))
        settings_btn.setIconSize(QSize(14, 14))
        settings_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setStyleSheet("border:none; padding:4px 8px; color:" + TEXT_MUTED + ";")
        settings_btn.clicked.connect(self._open_settings)
        lay.addStretch(1)
        lay.addWidget(settings_btn)
        lay.addWidget(self.logs_toggle)
        return bar

    def _build_pages(self) -> None:
        self._pages: dict = {}
        for row, cls in enumerate(self._page_rows):
            if cls is None:
                self.stack.addWidget(QWidget())  # placeholder to keep indices aligned
            else:
                page = cls(self)
                self._pages[row] = page
                self.stack.addWidget(page)

    # ---- behaviour ----
    def _nav_changed(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            prev = getattr(self, "_current_page", None)
            if prev is not None and hasattr(prev, "on_hidden"):
                prev.on_hidden()
            self.stack.setCurrentIndex(row)
            page = self._pages.get(row)
            self._current_page = page
            if page and hasattr(page, "on_shown"):
                page.on_shown()

    def _connect(self) -> None:
        self.session.token = self.token_in.text().strip()
        txt = self.chat_in.text().strip()
        self.session.chat = _chat_arg(txt) if txt else None
        try:
            client = self.session.client()
        except ValueError as e:
            self.log(f"[ERROR] {e}")
            self.set_bot_status(False, "Not connected")
            return
        self.log("[INFO] Validating token...")

        token = self.session.token

        def ok(me):
            bot_id = me.get("id")
            self._connected_token = token
            self.set_bot_status(True, f"@{me.get('username','?')}")
            self.log(f"[OK] Connected as @{me.get('username','?')}")
            self.session.bot_username = me.get("username", "")
            store.save_token(bot_id, token, me.get("username", ""))
            self._set_active_bot(bot_id)
            self._ensure_poller(token, bot_id)
            self._refresh_token_menu()
            # If a public @username was typed, resolve it to a numeric id.
            if isinstance(self.session.chat, str) and self.session.chat.startswith("@"):
                self._resolve_chat(client, self.session.chat)
            self._refresh_active_page()
            self.schedule_backfills()

        self.run_call(lambda: api.get_me(client), ok,
                      on_error=lambda m: self.set_bot_status(False, "Token invalid"))

    def _on_token_changed(self) -> None:
        tok = self.token_in.text().strip()
        if tok == getattr(self, "_connected_token", None):
            return
        # A token we validated before (in another session too): restore instantly.
        for bid, info in store.load_tokens().items():
            if info.get("token") == tok:
                self._connected_token = tok
                self.session.token = tok
                self.session.bot_username = info.get("username", "")
                self.set_bot_status(True, f"@{info.get('username') or bid}")
                self._set_active_bot(int(bid))
                self._ensure_poller(tok, int(bid))
                self._refresh_active_page()
                self.schedule_backfills()
                return
        # Not (yet) a known/valid bot: drop the display, keep background pollers.
        self._connected_token = None
        self.session.bot_id = None
        self._stop_all_backfills()
        if _TOKEN_RE.match(tok):
            self.set_bot_status(None, "Checking...")
            self._token_timer.start(700)
        else:
            self.set_bot_status(False, "Not connected" if tok else "No token")
        self._invalidate_display()

    def _maybe_auto_connect(self) -> None:
        tok = self.token_in.text().strip()
        if _TOKEN_RE.match(tok) and tok != getattr(self, "_connected_token", None):
            self._connect()

    def _on_chat_changed(self) -> None:
        # The chat in the bar changed: the old chat's data is no longer what's
        # asked for, so hide it right away; reload after the user stops typing.
        self._invalidate_display()
        self._chat_timer.start(500)

    def _on_chat_settled(self) -> None:
        txt = self.chat_in.text().strip()
        new = _chat_arg(txt) if txt else None
        self.session.chat = new
        if self.session.bot_id is not None and new is not None:
            if isinstance(new, str) and new.startswith("@"):
                try:
                    self._resolve_chat(self.session.client(), new)
                except ValueError:
                    pass
            self._refresh_active_page()

    def _invalidate_display(self) -> None:
        # Forget what each page loaded, and clear the one on screen, so nothing
        # stale from the previous bot/chat stays visible.
        for p in self._pages.values():
            if hasattr(p, "_loaded_for"):
                p._loaded_for = None
            if hasattr(p, "_profiled_for"):
                p._profiled_for = None
        page = getattr(self, "_current_page", None)
        if page is not None and hasattr(page, "clear_view"):
            page.clear_view()

    def _refresh_active_page(self) -> None:
        page = getattr(self, "_current_page", None)
        if page is not None and hasattr(page, "on_shown"):
            page.on_shown()

    # ---- background pollers: one per saved bot, all running at once ----
    def _set_active_bot(self, bot_id) -> None:
        self.session.bot_id = bot_id
        self.session.known_chats = self._chats_by_bot.setdefault(
            bot_id, store.load_chats(bot_id))

    def _ensure_poller(self, token: str, bot_id) -> None:
        if bot_id in self._pollers:
            return
        self._chats_by_bot.setdefault(bot_id, store.load_chats(bot_id))
        try:
            client = TelegramClient(token)
        except ValueError:
            return
        poller = UpdatesPoller(client)
        poller.chat_seen.connect(lambda c, b=bot_id: self._on_chat_seen(b, c))
        poller.new_member.connect(self._on_new_member)
        poller.message.connect(lambda m, b=bot_id: self._on_message(b, m))
        poller.stopped.connect(lambda r, b=bot_id: self._on_poller_stopped(b, r))
        self._pollers[bot_id] = poller
        self._track(poller)
        poller.start()

    def _start_saved_pollers(self) -> None:
        # Keep collecting for every bot you've used, even while you work on another.
        for bid, info in store.load_tokens().items():
            self._ensure_poller(info.get("token", ""), int(bid))

    def _on_chat_seen(self, bot_id, chat: dict) -> None:
        chats = self._chats_by_bot.setdefault(bot_id, {})
        cid = str(chat["id"])
        if chats.get(cid) != chat:
            chats[cid] = chat
            store.save_chats(bot_id, chats)
            if bot_id == self.session.bot_id:
                self.schedule_backfills()   # a new chat to consider walking

    def _on_message(self, bot_id, msg: dict) -> None:
        # Passive archive: every message the bot receives is kept locally.
        store.append_messages(bot_id, [msg])
        # Live-feed the conversation view if it's showing this chat.
        if bot_id == self.session.bot_id and str(msg.get("chat_id")) == str(self.session.chat):
            conv = next((p for p in self._pages.values()
                         if p.__class__.__name__ == "ConversationPage"), None)
            if conv is not None:
                conv.add_message(msg)

    def _on_new_member(self, ev: dict) -> None:
        self.arrivals.append(ev)
        # Show joins inside the conversation timeline (as a system line).
        if str(ev.get("chat_id")) == str(self.session.chat):
            conv = next((p for p in self._pages.values()
                         if p.__class__.__name__ == "ConversationPage"), None)
            if conv is not None:
                u = ev.get("user", {})
                name = ("@" + u["username"]) if u.get("username") else (
                    u.get("first_name") or f"id {u.get('id')}")
                conv.add_message({
                    "message_id": ev.get("message_id") or (-abs(hash((ev.get("date"), u.get("id")))) % 10**9),
                    "chat_id": ev.get("chat_id"), "date": ev.get("date"),
                    "_system": True, "text": f"{name} joined the chat"})

    def _on_poller_stopped(self, bot_id, reason: str) -> None:
        self._pollers.pop(bot_id, None)
        if reason:
            self.log(f"[ERROR] Background poller for bot {bot_id} stopped: {reason}")

    # ---- backfill scheduler: walk the past of at most N chats at once ----
    # Rate limits make walking every chat's history at once impossible, so we
    # bound it: the chat on screen has priority, then the ones least-recently
    # advanced, capped at `max_backfills` (the viewed one counts). The rest wait.
    def set_viewed_chat(self, bot_id=None, chat_id=None) -> None:
        new = (bot_id, chat_id) if (bot_id is not None and chat_id is not None) else None
        if new != self._viewed_chat:
            self._viewed_chat = new
            self.schedule_backfills()

    def is_backfilling(self, bot_id, chat_id) -> bool:
        return self._backfills.get((bot_id, chat_id)) is not None

    def schedule_backfills(self) -> None:
        bot_id = self.session.bot_id
        if bot_id is None:
            self._stop_all_backfills()
            return
        cap = max(1, int(self.settings.get("max_backfills", 3)))
        recs = store.load_backfill(bot_id)

        def done(cid):
            return recs.get(str(cid), {}).get("done")

        known = [int(c) for c in self._chats_by_bot.get(bot_id, {}).keys()
                 if str(c).lstrip("-").isdigit()]
        viewed = (self._viewed_chat[1] if self._viewed_chat
                  and self._viewed_chat[0] == bot_id else None)
        if viewed is not None and viewed not in known:
            known.append(viewed)   # a manually-typed chat still deserves a walk
        candidates = [c for c in known
                      if not done(c) and (bot_id, c) not in self._cant_backfill]
        # Priority: viewed chat first, then least-recently-advanced (never = 0).
        others = sorted((c for c in candidates if c != viewed),
                        key=lambda c: recs.get(str(c), {}).get("updated", 0))
        ordered = ([viewed] if viewed in candidates else []) + others
        selected = ordered[:cap]

        # Stop walks that fell out of the selection (they'll finish and free up).
        for (b, c), w in list(self._backfills.items()):
            if b != bot_id or c not in selected:
                if w is not None:
                    w.stop()
        # Start newly selected chats that aren't already running/reserved.
        for cid in selected:
            if (bot_id, cid) not in self._backfills:
                self._start_backfill(bot_id, cid)

    def _start_backfill(self, bot_id, chat) -> None:
        try:
            client = self.session.client()
        except ValueError:
            return
        self._backfills[(bot_id, chat)] = None  # reserve the slot while we prepare
        rec = store.backfill_record(bot_id, chat)
        floor = rec.get("lowest")
        collected = store.load_messages_for(bot_id, chat)
        min_collected = min((m["message_id"] for m in collected
                             if m.get("message_id") is not None), default=None)
        pace = float(self.settings.get("backfill_pace", 3.2))
        gap = int(self.settings.get("max_gap", 400))

        def prepare():
            perms = api.get_bot_permissions(client, chat)
            can_delete = perms.get("status") == "creator" or (
                perms.get("status") == "administrator" and perms.get("can_delete_messages"))
            if floor is not None:
                start = floor - 1
            elif min_collected is not None:
                start = min_collected - 1
            else:
                start = api.current_max_message_id(client, chat)
            return {"can_delete": bool(can_delete), "start": start}

        def go(info):
            # If the slot was released while preparing (bot changed/disconnected),
            # drop it quietly.
            if (bot_id, chat) not in self._backfills or bot_id != self.session.bot_id:
                self._backfills.pop((bot_id, chat), None)
                return
            if info["start"] < 1:
                store.update_backfill(bot_id, chat, done=True)  # nothing older exists
                self._backfills.pop((bot_id, chat), None)
                self.schedule_backfills()
                return
            if not info["can_delete"]:
                # Can't clean up the copies it would make - skip for this session.
                self._cant_backfill.add((bot_id, chat))
                self._backfills.pop((bot_id, chat), None)
                self.log(f"[INFO] Chat {chat}: walking the past needs the bot to be an admin "
                         "with delete rights (to remove the copies it makes). Skipped.")
                self.schedule_backfills()
                return
            w = BackfillWorker(client, source_chat=chat, start_id=info["start"],
                               max_total=None, cleanup=True, pace=pace, max_gap=gap)
            w.message.connect(lambda m, b=bot_id: self._on_message(b, m))
            w.progress.connect(lambda mid, b=bot_id, c=chat: store.update_backfill(b, c, lowest=mid))
            w.done.connect(lambda n, bottom, b=bot_id, c=chat: self._on_backfill_done(b, c, n, bottom))
            w.failed.connect(lambda e, c=chat: self.log(f"[ERROR] Chat {c} backfill: {e}"))
            w.finished.connect(lambda b=bot_id, c=chat, ww=w: self._backfill_finished(b, c, ww))
            self._backfills[(bot_id, chat)] = w
            self._track(w)
            self.log(f"[INFO] Walking chat {chat} back from id {info['start']} "
                     f"(paced {pace:g}s/msg to respect Telegram limits)...")
            w.start()
            self._tell_conversation(chat)

        self.run_call(prepare, go)

    def _on_backfill_done(self, bot_id, chat, captured, reached_bottom) -> None:
        if reached_bottom:
            store.update_backfill(bot_id, chat, done=True)
        if captured:
            self.log(f"[OK] Chat {chat}: fetched {captured} older messages"
                     + (" (reached the start)." if reached_bottom else "."))

    def _backfill_finished(self, bot_id, chat, worker) -> None:
        self._threads.discard(worker)
        if self._backfills.get((bot_id, chat)) is worker:
            self._backfills.pop((bot_id, chat), None)
        self._tell_conversation(chat)
        self.schedule_backfills()  # a slot opened up - let the next chat in

    def _tell_conversation(self, chat) -> None:
        if str(chat) != str(self.session.chat):
            return
        conv = next((p for p in self._pages.values()
                     if p.__class__.__name__ == "ConversationPage"), None)
        if conv is not None:
            conv.refresh_header()

    def _stop_all_backfills(self) -> None:
        for w in self._backfills.values():
            if w is not None:
                w.stop()

    def closeEvent(self, event):
        # Ask every live thread to stop, then wait briefly so none is destroyed
        # while still running (the source of the random QThread crashes).
        for p in list(self._pollers.values()):
            p.stop()
        self._stop_all_backfills()
        for t in list(self._threads):
            try:
                t.requestInterruption()
            except Exception:
                pass
        for t in list(self._threads):
            t.wait(2000)
        self._pollers.clear()
        self._backfills.clear()
        super().closeEvent(event)

    def set_bot_status(self, ok, text: str) -> None:
        # ok: True green, False red, None amber (checking).
        color = WARNING if ok is None else (SUCCESS if ok else DANGER)
        self.dot.setStyleSheet(f"color:{color};")
        self.status.setText(text)

    def log(self, msg: str) -> None:
        # Kept in the (hidden) Logs drawer only; nothing noisy on the bar.
        self.logbox.appendPlainText(msg)

    # ---- settings ----
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self, self.settings, main=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        old = self.settings
        new = dlg.values()
        self.settings = new
        store.save_settings(new)
        # Cheap knobs apply right away.
        self.logbox.setVisible(new["logs_open"])
        self.logs_toggle.setChecked(new["logs_open"])
        self.schedule_backfills()        # pace / cap / gap may have changed
        self._refresh_active_page()      # re-render with the new on-screen limit
        # Theme or font need the inline-coloured widgets rebuilt.
        if new["theme"] != old["theme"] or new["font_size"] != old["font_size"]:
            self._apply_theme_live(new["theme"], new["font_size"])

    def _apply_theme_live(self, mode: str, font_size: int) -> None:
        apply_theme(mode, font_size)
        row = self.nav.currentRow()
        tok, chat = self.token_in.text(), self.chat_in.text()
        self._current_page = None
        self._build_ui()                 # fresh widgets read the new palette
        # Restore the bar without re-triggering connect (the session is unchanged).
        self.token_in.blockSignals(True); self.token_in.setText(tok); self.token_in.blockSignals(False)
        self.chat_in.blockSignals(True); self.chat_in.setText(chat); self.chat_in.blockSignals(False)
        if self.session.is_connected():
            self.set_bot_status(True, f"@{self.session.bot_username or self.session.bot_id}")
        self.nav.setCurrentRow(row if row > 0 else 1)

    def _track(self, thread) -> None:
        """Keep a strong ref to a QThread until it has really finished, so it is
        never garbage-collected mid-run (that triggers Qt's 'Destroyed while
        thread is still running' and random crashes)."""
        self._threads.add(thread)
        thread.finished.connect(lambda t=thread: self._threads.discard(t))

    def run_call(self, job: Callable[[], Any], on_done: Callable[[Any], None],
                 button: Optional[QPushButton] = None,
                 on_error: Optional[Callable[[str], None]] = None) -> None:
        worker = CallWorker(job)
        self._track(worker)
        if button:
            button.setEnabled(False)

        def re_enable():
            if button:
                button.setEnabled(True)

        def ok(res):
            try:
                on_done(res)
            finally:
                re_enable()

        def err(msg):
            self.log(f"[ERROR] {msg}")
            if on_error:
                on_error(msg)
            re_enable()

        worker.done.connect(ok)
        worker.failed.connect(err)
        worker.start()


def apply_theme(mode: str, font_size: Optional[int] = None) -> None:
    """Switch light/dark everywhere: rebuild the theme, re-sync the colour names
    imported into the GUI modules (functions read them as globals at call time,
    so widgets built afterwards use the new palette), and repaint the app."""
    import sys as _sys
    from . import export as _export
    from . import charts as _charts
    theme.apply_mode(mode, font_size)
    me = _sys.modules[__name__]
    for name in theme.EXPORTED:
        val = getattr(theme, name)
        for mod in (me, _export, _charts):
            if hasattr(mod, name):
                setattr(mod, name, val)
    app = QApplication.instance()
    if app is not None:
        try:  # keep native dialogs (file picker) in step with our palette
            app.styleHints().setColorScheme(
                Qt.ColorScheme.Dark if theme.MODE == "dark" else Qt.ColorScheme.Light)
        except (AttributeError, TypeError):
            pass
        app.setStyleSheet(theme.QSS)
        app.setPalette(theme.build_palette(theme.MODE))


def run() -> int:
    import sys
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    s = store.load_settings()
    apply_theme(s.get("theme", "light"), s.get("font_size", 13))
    app.setWindowIcon(app_icon(ACCENT))
    win = MainWindow()
    win.show()
    return app.exec()
