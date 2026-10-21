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

from PyQt6.QtCore import Qt, QSize, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QFont, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QStackedWidget,
    QTableWidget, QTableWidgetItem, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QWidgetAction,
)

from ..cli import _chat_arg
from ..core import (TelegramClient, TelegramError, api, archive, creds, enrich,
                    graph, intel, rights_check)
from .charts import HBarList, TimeBars, stat_tile
from .export import build_export_button, style_menu
from .graphview import GraphView
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


from .workers import (ArchiveWorker, BackfillWorker, CallWorker, EnrichWorker,
                      GeneratorWorker, TelethonLoginWorker, UpdatesPoller)

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
    box.setObjectName("Field")   # transparent via QSS, so no grey box on white cards
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
        self.migrate_cb = None        # set by MainWindow: called on group->supergroup

    def is_connected(self) -> bool:
        """Single source of truth: are the bar's token/chat backing a live bot?"""
        return self.bot_id is not None

    def client(self) -> TelegramClient:
        if not self.token:
            raise ValueError("Enter a bot token first.")
        return TelegramClient(self.token, on_migrate=self.migrate_cb)

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
        # Show a letter avatar straight away (like Bot rights); the real photo,
        # if the bot has one reachable, replaces it when _show_avatar lands.
        name = me.get("first_name") or me.get("username") or "bot"
        self.avatar.setText(name[:1].upper())
        self.avatar.setStyleSheet(
            f"border-radius:32px; background:{SUCCESS}; color:#FFFFFF; "
            f"font-size:24px; font-weight:600;")
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
        self.refresh_btn = icon_button("Refresh", "refresh")
        self.refresh_btn.clicked.connect(lambda: self._go(self.refresh_btn))
        self.export_btn = build_export_button(
            self, [("Admin list", "admins", self._admins_dataset)], log=self.main.log)
        self.export_btn.setEnabled(False)
        bar.addStretch(1); bar.addWidget(self.refresh_btn); bar.addWidget(self.export_btn)
        self.root.addLayout(bar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Username", "ID", "Role"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.root.addWidget(self.table)
        self._init_empty(self.refresh_btn, self.export_btn, self.table)

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
        self.main.run_call(lambda: api.get_chat_administrators(client, chat), self._show,
                           button=btn, on_error=lambda m: self.main.log(f"[ERROR] Admins: {m}"))

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
        bar = QHBoxLayout()
        self.refresh_btn = icon_button("Refresh rights", "refresh")
        self.refresh_btn.setToolTip("Re-read the bot's current rights from Telegram "
                                    "(they aren't pushed - re-check after you change them).")
        self.refresh_btn.clicked.connect(lambda: self._go(force=True))
        bar.addStretch(1); bar.addWidget(self.refresh_btn)
        self.root.addLayout(bar)
        self.card = QFrame()
        self.card.setObjectName("Card")
        self.card_lay = QVBoxLayout(self.card)
        self.card_lay.setContentsMargins(18, 16, 18, 16)
        self.card_lay.setSpacing(10)
        self.card.setVisible(False)
        self.root.addWidget(self.card)
        # The card shows itself only once rendered; the refresh button hides with
        # the body when disconnected.
        self._init_empty(self.refresh_btn)

    def on_shown(self) -> None:
        if not self._apply_empty_state():
            return
        # Rights aren't pushed by Telegram, so re-read them every time the tab is
        # opened - that way a permission you just changed shows up.
        if self.session.chat is not None:
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
        bot_id = self.session.bot_id

        def job():
            member = api.get_bot_permissions(client, chat)
            try:
                member["_can_send"] = (True if member.get("status") == "creator"
                                       else api.can_send_from(member, api.get_chat(client, chat)))
            except TelegramError:
                member["_can_send"] = None
            return member

        def done(member):
            self._render(member)
            # Perms may have changed (e.g. delete-messages just granted): let the
            # backfill scheduler re-evaluate this chat instead of staying blocked.
            self.main.clear_backfill_block(bot_id, chat)

        self.main.run_call(job, done, button=self.refresh_btn, on_error=self._show_error)

    def _show_error(self, msg: str) -> None:
        self._clear_card()
        self.card.setVisible(True)
        lab = QLabel(f"Could not read the bot's rights: {msg}")
        lab.setStyleSheet(f"color:{DANGER};"); lab.setWordWrap(True)
        self.card_lay.addWidget(lab)

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
        sub = QLabel(f"status: {status}")
        sub.setStyleSheet(f"color:{SUCCESS if is_admin else TEXT_MUTED};")
        from datetime import datetime
        checked = QLabel(f"read live at {datetime.now().strftime('%H:%M:%S')}")
        checked.setObjectName("Muted")
        name_box.addWidget(nlab); name_box.addWidget(sub); name_box.addWidget(checked)
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
        self._set_msg("Creating...", error=False)
        approval = self.join.isChecked()
        # Telegram forbids a member limit together with approval.
        limit = None if approval else (self.limit.value() or None)
        self.main.run_call(
            lambda: api.create_chat_invite_link(
                client, chat, name=self.name.text().strip() or None,
                member_limit=limit, creates_join_request=approval),
            lambda r: (self.link.setText(r.get("invite_link", "")),
                       self._set_msg("Invite link created.", error=False),
                       self.main.log("[OK] Invite link created.")),
            button=btn,
            on_error=lambda m: self._set_msg(
                f"Failed: {m}. The bot needs the 'Invite users via link' admin right here.",
                error=True))


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
        self.main.run_call(
            lambda: api.bot_send_right(client, chat),
            lambda ok: self._set_can_send(bool(ok),
                                          "" if ok else "No rights to send messages here"),
            on_error=lambda m: self._set_can_send(False, f"Couldn't check rights ({m})"))

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
            self.main.log(f"[OK] Sent message {res.get('message_id')} to chat {chat}.")

        def failed(m):
            self.msg_in.setText(text)   # don't lose what you typed
            self.main.log(f"[ERROR] Send failed: {m}")

        self.main.run_call(lambda: api.send_message(client, chat, text), done,
                           button=self.send_btn, on_error=failed)

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
        # Order by TIME, not message id: after a group -> supergroup upgrade (and
        # between live vs backfilled messages) ids no longer track time, so id
        # order scrambled the timeline. Dateless messages fall to the end.
        from datetime import datetime

        def sort_key(m):
            d = m.get("date")
            mid = m.get("message_id") or 0
            return (0, d, mid) if d is not None else (1, 0, mid)

        ordered = sorted(self._msgs.values(), key=sort_key)[-limit:]
        last_sender = None
        last_day = None
        for msg in ordered:
            d = msg.get("date")
            if d is not None:
                day = datetime.fromtimestamp(d).date()   # local day
                if day != last_day:
                    self.col.insertWidget(self.col.count() - 1,
                                          self._date_separator(datetime.fromtimestamp(d)))
                    last_day = day
                    last_sender = None   # re-show the name after a date break
            sender = msg.get("from") or {}
            key = sender.get("id") or sender.get("username") or sender.get("first_name")
            self.col.insertWidget(self.col.count() - 1,
                                  self._bubble_row(msg, show_name=(key != last_sender)))
            last_sender = key
        if scroll_bottom:
            self._pin_to_bottom()

    def _pin_to_bottom(self) -> None:
        """Scroll to the newest message. Word-wrapped bubbles get their final
        height over a couple of layout passes, so a single scroll stops short -
        we re-pin on each range change until the content stops growing."""
        sb = self.scroll.verticalScrollBar()

        def go():
            try:
                sb.setValue(sb.maximum())
            except RuntimeError:
                pass   # widget gone (e.g. a theme rebuild) - ignore
        go()
        # rangeChanged fires as bubbles settle; re-pin, then stop listening.
        try:
            sb.rangeChanged.disconnect(self._on_scroll_range)
        except TypeError:
            pass
        sb.rangeChanged.connect(self._on_scroll_range)
        QTimer.singleShot(0, go)
        QTimer.singleShot(60, go)
        QTimer.singleShot(180, lambda: (go(), self._stop_pin()))

    def _on_scroll_range(self, _min, _max) -> None:
        try:
            self.scroll.verticalScrollBar().setValue(_max)
        except RuntimeError:
            pass

    def _stop_pin(self) -> None:
        try:
            self.scroll.verticalScrollBar().rangeChanged.disconnect(self._on_scroll_range)
        except (TypeError, RuntimeError):
            pass

    def _date_separator(self, dt) -> QWidget:
        lab = QLabel(dt.strftime("%d %B %Y"))
        lab.setStyleSheet(f"color:{TEXT_MUTED}; background:{SYS_PILL}; border-radius:10px; "
                          "padding:3px 12px; font-size:11px;")
        row = QWidget(); row.setStyleSheet("background:transparent;")
        rl = QHBoxLayout(row); rl.setContentsMargins(0, 8, 0, 2)
        rl.addStretch(1); rl.addWidget(lab); rl.addStretch(1)
        return row

    def _bubble_row(self, msg: dict, show_name: bool) -> QWidget:
        from datetime import datetime
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
            dt = datetime.fromtimestamp(date)   # local time, so it matches Telegram
            tl = QLabel(dt.strftime("%H:%M"))
            tl.setToolTip(dt.strftime("%Y-%m-%d %H:%M"))
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
        from datetime import datetime
        lines = []

        def sort_key(m):
            d = m.get("date"); mid = m.get("message_id") or 0
            return (0, d, mid) if d is not None else (1, 0, mid)

        for m in sorted(self._msgs.values(), key=sort_key):   # chronological, like the view
            if m.get("_system"):
                lines.append(m.get("text", "")); continue
            s = m.get("from") or {}
            who = ("@" + s["username"]) if s.get("username") else (s.get("first_name") or "unknown")
            d = m.get("date")
            ts = datetime.fromtimestamp(d).strftime("%Y-%m-%d %H:%M") if d else ""
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

# --------------------------------------------------------------------------
# Investigator / Nexus / Keys - the cross-bot, graph-backed workspaces.
# --------------------------------------------------------------------------

Subject = enrich.Subject


def _parse_subject(raw: str):
    """A '@handle', 'handle', or numeric id typed by the user -> a Subject."""
    raw = raw.strip()
    if not raw:
        return None
    if raw.lstrip("-").isdigit():
        return Subject(user_id=int(raw), label=f"id {raw}")
    return Subject(username=raw.lstrip("@"), label="@" + raw.lstrip("@"))


def make_bars(items, height: int = 24, on_click=None) -> HBarList:
    """items: list of (key, label, sub, value). Fixed height so it shows in a
    scroll/collapsible; `on_click(key)` wired to row clicks when given."""
    b = HBarList(row_height=height)
    b.set_rows(list(items))
    b.setFixedHeight(height * max(len(items), 1) + 4)
    if on_click is not None:
        b.clicked.connect(on_click)
    return b


_IND_LABELS = {"url": "Links", "telegram_invite": "Invite links", "email": "Emails",
               "btc": "BTC", "eth": "ETH", "ton": "TON", "mention": "@mentions",
               "phone": "Phones"}

# Short button labels / icons per enrichment provider name.
_PROV_LABEL = {"dorks": "Web leads", "t.me": "t.me", "tgstat": "TGStat", "telethon": "Telethon"}
_PROV_ICON = {"dorks": "search", "t.me": "message", "tgstat": "chart", "telethon": "key"}


class CredentialsPage(BasePage):
    title = "Keys"
    subtitle = "Optional credentials for deeper enrichment - stored locally only."

    def build(self) -> None:
        self._login_worker = None
        body = QWidget()
        outer = QVBoxLayout(body); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(12)
        intro = QLabel("Experimental. These third-party / account integrations may be "
                       "rate-limited, change, or need a paid tier. Credentials are stored "
                       "locally in ~/.telegram_tools/credentials.json (gitignored) and only "
                       "ever sent to Telegram / the provider you use. No-account enrichment "
                       "(web leads, t.me) needs nothing here.")
        intro.setObjectName("Muted"); intro.setWordWrap(True)
        outer.addWidget(intro)

        c = creds.load_credentials()
        card = QFrame(); card.setObjectName("Card")
        cl = QVBoxLayout(card); cl.setContentsMargins(16, 14, 16, 14); cl.setSpacing(10)
        t = QLabel("Telethon (your Telegram account) · experimental"); t.setStyleSheet("font-weight:600;")
        cl.addWidget(t)
        cl.addWidget(self._muted("api_id / api_hash come from https://my.telegram.org. "
                                 "Logging in unlocks common-groups, member lists and real ids."))
        self.api_id = QLineEdit(c.get("tg_api_id", "")); self.api_id.setPlaceholderText("e.g. 2040295")
        self.api_hash = QLineEdit(c.get("tg_api_hash", ""))
        self.api_hash.setPlaceholderText("32-character hash from my.telegram.org")
        self.phone = QLineEdit(c.get("tg_phone", "")); self.phone.setPlaceholderText("+33612345678")
        row = QHBoxLayout(); row.setSpacing(10)
        row.addWidget(field("API ID", self.api_id))
        row.addWidget(field("API hash", self.api_hash), 1)
        row.addWidget(field("Phone (country code)", self.phone))
        cl.addLayout(row)
        btns = QHBoxLayout()
        self.login_btn = icon_button("Log in to Telegram", "key", primary=True)
        self.login_btn.clicked.connect(self._login)
        self.login_status = QLabel(""); self.login_status.setObjectName("Muted")
        btns.addWidget(self.login_btn); btns.addWidget(self.login_status, 1)
        cl.addLayout(btns)
        outer.addWidget(card)

        card2 = QFrame(); card2.setObjectName("Card")
        c2 = QVBoxLayout(card2); c2.setContentsMargins(16, 14, 16, 14); c2.setSpacing(10)
        t2 = QLabel("Provider API keys (optional) · experimental"); t2.setStyleSheet("font-weight:600;")
        c2.addWidget(t2)
        self.tgstat = QLineEdit(c.get("tgstat_key", ""))
        self.tgstat.setPlaceholderText("paste your token from tgstat.ru")
        c2.addWidget(field("TGStat API token", self.tgstat))
        outer.addWidget(card2)

        save = icon_button("Save", "check"); save.clicked.connect(self._save)
        self.save_msg = QLabel(""); self.save_msg.setObjectName("Muted")
        sr = QHBoxLayout(); sr.addWidget(save); sr.addWidget(self.save_msg, 1)
        outer.addLayout(sr)
        outer.addStretch(1)
        self.root.addWidget(body)
        self._refresh_status()

    def _muted(self, text):
        lab = QLabel(text); lab.setObjectName("Muted"); lab.setWordWrap(True); return lab

    def _save(self) -> None:
        creds.save_credentials({
            "tg_api_id": self.api_id.text().strip(), "tg_api_hash": self.api_hash.text().strip(),
            "tg_phone": self.phone.text().strip(), "tgstat_key": self.tgstat.text().strip()})
        self.save_msg.setText("Saved.")
        self._refresh_status()

    def _refresh_status(self) -> None:
        if creds.has_telethon_creds():
            self.login_status.setText("Credentials set. Click to log in (or re-use the saved session).")
        else:
            self.login_status.setText("Enter api_id / api_hash, Save, then log in.")

    def _login(self) -> None:
        self._save()
        api_id, api_hash, phone = (self.api_id.text().strip(), self.api_hash.text().strip(),
                                   self.phone.text().strip())
        if not (api_id and api_hash and phone):
            self.login_status.setText("Need api_id, api_hash and phone to log in.")
            return
        self.login_btn.setEnabled(False)
        self.login_status.setText("Connecting to Telegram...")
        w = TelethonLoginWorker(api_id, api_hash, phone, creds.SESSION)
        self._login_worker = w
        self.main._track(w)
        w.code_needed.connect(lambda: self._ask(w, "code"))
        w.password_needed.connect(lambda: self._ask(w, "password"))
        w.done.connect(self._login_ok)
        w.failed.connect(self._login_err)
        w.start()

    def _ask(self, worker, what: str) -> None:
        if what == "code":
            text, ok = QInputDialog.getText(self, "Telegram code",
                                            "Enter the login code Telegram just sent you:")
            worker.provide_code(text if ok else "")
        else:
            text, ok = QInputDialog.getText(self, "Two-step password",
                                            "Enter your 2FA password:", QLineEdit.EchoMode.Password)
            worker.provide_password(text if ok else "")

    def _login_ok(self, me: dict) -> None:
        self.login_btn.setEnabled(True)
        self.login_status.setText(f"Logged in as @{me.get('username') or me.get('id')}. "
                                  "Telethon enrichment is now available.")
        self.main.log(f"[OK] Telethon logged in as {me.get('id')}.")

    def _login_err(self, msg: str) -> None:
        self.login_btn.setEnabled(True)
        self.login_status.setText(f"Login failed: {msg}")
        self.main.log(f"[ERROR] Telethon login: {msg}")


class InvestigatorPage(BasePage):
    title = "Investigator"
    fill = True
    subtitle = ("Zoom on one subject across every bot's collected data, then enrich from "
                "outside sources. The future of Member info.")

    def build(self) -> None:
        self._graph = None
        self._umsgs = {}
        self._subject_key = None
        self._pending = None
        self._enrich_worker = None

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QFrame(); left.setObjectName("Card")
        ll = QVBoxLayout(left); ll.setContentsMargins(12, 12, 12, 12); ll.setSpacing(8)
        top = QHBoxLayout(); top.setSpacing(6)
        self.sources_btn = self.main.sources_button(self._on_sources_changed)
        ov = icon_button("Overview", "chart"); ov.clicked.connect(self._show_overview)
        top.addWidget(self.sources_btn); top.addWidget(ov); top.addStretch(1)
        ll.addLayout(top)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a @handle / id or name to investigate")
        self.search.returnPressed.connect(self._manual_subject)
        self._filter_timer = QTimer(self); self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._on_search)
        self.search.textChanged.connect(lambda: self._filter_timer.start(250))
        # Enrichment auto-runs when a subject opens, but debounced: typing a handle
        # live opens a subject per keystroke, and we must not fire a lookup each time.
        self._enrich_debounce = QTimer(self); self._enrich_debounce.setSingleShot(True)
        self._enrich_debounce.timeout.connect(self._fire_enrich)
        self._pending_enrich = None
        ll.addWidget(self.search)
        self.subjects = QListWidget()
        self.subjects.itemClicked.connect(
            lambda it: self._open_key(it.data(Qt.ItemDataRole.UserRole)))
        ll.addWidget(self.subjects, 1)
        split.addWidget(left)

        self.dossier_host = QWidget()
        self.dossier_lay = QVBoxLayout(self.dossier_host)
        self.dossier_lay.setContentsMargins(0, 0, 0, 0)
        rs = QScrollArea(); rs.setWidgetResizable(True); rs.setFrameShape(QFrame.Shape.NoFrame)
        rs.setWidget(self.dossier_host)
        split.addWidget(rs)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1); split.setSizes([300, 760])
        self.root.addWidget(split, 1)
        self._placeholder("Pick a subject on the left, or paste a @handle / id above.")

    # ---- lifecycle ----
    def on_shown(self) -> None:
        self._graph, self._umsgs = self.main.get_graph()
        self._fill_list()
        if self._pending is not None:
            key, self._pending = self._pending, None
            self._open_key(key)
        elif self._subject_key is None:
            self._show_overview()

    def _on_sources_changed(self) -> None:
        self._graph, self._umsgs = self.main.get_graph()
        self._subject_key = None
        self._fill_list()
        self._show_overview()

    def _fill_list(self) -> None:
        self.subjects.clear()
        g = self._graph
        if g is None:
            return
        users = sorted(g.entities_of(graph.USER), key=lambda e: -g.degree(e.key))
        if not users:
            return
        q = self.search.text().strip().lower()
        shown = 0
        for e in users:
            hay = f"{e.label} {e.attrs.get('username','')} {e.attrs.get('id','')}".lower()
            if q and q not in hay:
                continue
            it = QListWidgetItem(f"{e.label}   ·   {g.degree(e.key)} links")
            it.setData(Qt.ItemDataRole.UserRole, e.key)
            self.subjects.addItem(it)
            shown += 1
            if shown >= 500:
                break

    def _on_search(self) -> None:
        """Live, on every keystroke: filter the list, and drive the right panel.

        No match among the collected users -> show the typed @handle/id as an
        unseen subject ("user not found") WITH the enrichment tools, so you can
        investigate someone the bots never saw. Narrowed to a single known user
        -> open it (with its tools). Anything broader -> keep the list to pick from.
        """
        self._fill_list()
        q = self.search.text().strip()
        if not q:
            return   # cleared: leave whatever is on the right (overview / open subject)
        n = self.subjects.count()
        if n == 0:
            subj = _parse_subject(q)
            if subj is not None:
                self._open_subject(subj, graph.user_key(subj.user_id, subj.handle()))
        elif n == 1:
            self._open_key(self.subjects.item(0).data(Qt.ItemDataRole.UserRole))

    def _manual_subject(self) -> None:
        subj = _parse_subject(self.search.text())
        if subj is None:
            return
        self._open_subject(subj, graph.user_key(subj.user_id, subj.handle()))

    def _open_key(self, key) -> None:
        if not key:
            return
        g = self._graph
        ent = g.entities.get(key) if g else None
        if ent is None:
            self._open_subject(Subject(label=str(key)), key)
        else:
            self._open_subject(Subject(user_id=ent.attrs.get("id"),
                                       username=ent.attrs.get("username"),
                                       label=ent.label), key)

    def open_pending(self, key) -> None:
        """Called by the window (e.g. from Nexus) before navigating here."""
        self._pending = key

    # ---- dossier ----
    def _placeholder(self, text) -> None:
        self._clear_dossier()
        lab = QLabel(text); lab.setObjectName("Muted"); lab.setWordWrap(True)
        lab.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.dossier_lay.addWidget(lab); self.dossier_lay.addStretch(1)

    def _clear_dossier(self) -> None:
        while self.dossier_lay.count():
            it = self.dossier_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    # ---- overview (the former Report, now graph-backed and cross-source) ----
    def _show_overview(self) -> None:
        self._subject_key = None
        self._clear_dossier()
        g = self._graph
        if g is None or not g.entities:
            if not self.main._selected_bots:
                self._placeholder("No data yet - pick a source (bot) in 'Sources' above to "
                                  "analyse its collected data.")
            else:
                self._placeholder("No data yet - the selected source hasn't collected messages.")
            return
        card = QFrame(); card.setObjectName("Card")
        lay = QVBoxLayout(card); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(4)
        head = QLabel("Overview"); head.setStyleSheet("font-weight:600; font-size:16px;")
        lay.addWidget(head)

        users = g.entities_of(graph.USER); groups = g.entities_of(graph.GROUP)
        inds = g.entities_of(graph.INDICATOR)
        by_layer: dict = {}
        for e in inds:
            by_layer.setdefault(graph.entity_layer(e), []).append(e)
        msgtotal = sum(len(m) for m in (self._umsgs or {}).values())
        lay.addWidget(self._muted(
            f"{msgtotal} messages  ·  {len(users)} people  ·  {len(groups)} groups  ·  "
            f"{len(inds)} indicators  ·  {len(self.main._selected_bots)} source(s)"))
        trow = QHBoxLayout(); trow.setSpacing(10)
        for name, val in (("Messages", msgtotal), ("People", len(users)), ("Groups", len(groups)),
                          ("Links", len(by_layer.get("links", []))),
                          ("Crypto", len(by_layer.get("crypto", []))),
                          ("@mentions", len(by_layer.get("mentions", [])))):
            trow.addWidget(stat_tile(name, str(val)))
        tw = QWidget(); tw.setLayout(trow); lay.addWidget(tw)

        people_rows = sorted(users, key=lambda e: -len((self._umsgs or {}).get(e.key, [])))[:40]
        lay.addWidget(Collapsible(f"Most active people ({len(users)})",
            lambda r=people_rows: make_bars([(e.key, e.label, "", len((self._umsgs or {}).get(e.key, [])))
                                             for e in r], on_click=self._open_key), open=True))
        group_rows = sorted(groups, key=lambda e: -g.degree(e.key))[:40]
        if group_rows:
            lay.addWidget(Collapsible(f"Groups ({len(groups)})",
                lambda r=group_rows: make_bars([(e.key, e.label, "", g.degree(e.key)) for e in r],
                    on_click=lambda k: self.main.open_terrain(g.entities[k].attrs.get("chat_id")))))
        for layer, label in (("links", "Top links"), ("crypto", "Top crypto"),
                             ("invites", "Invite links"), ("mentions", "Top @mentions"),
                             ("emails", "Emails"), ("phones", "Phones (possible)")):
            items = sorted(by_layer.get(layer, []), key=lambda e: -g.degree(e.key))[:40]
            if items:
                lay.addWidget(Collapsible(f"{label} ({len(items)})",
                    lambda r=items: make_bars([(e.key, e.label, "", g.degree(e.key)) for e in r],
                        on_click=self._open_indicator)))
        lay.addWidget(build_export_button(self, self._overview_datasets(), log=self.main.log),
                      0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        self.dossier_lay.addWidget(card)

    def _overview_datasets(self):
        g = self._graph

        def people():
            return (["id", "username", "name", "messages", "links"],
                    [[e.attrs.get("id"), e.attrs.get("username", ""), e.label,
                      len((self._umsgs or {}).get(e.key, [])), g.degree(e.key)]
                     for e in g.entities_of(graph.USER)])

        def groups():
            return (["chat_id", "title", "posters"],
                    [[e.attrs.get("chat_id"), e.label, g.degree(e.key)]
                     for e in g.entities_of(graph.GROUP)])

        def indicators():
            return (["type", "value", "shared_by"],
                    [[graph.LAYER_LABELS.get(graph.entity_layer(e), ""), e.label, g.degree(e.key)]
                     for e in g.entities_of(graph.INDICATOR)])

        return [("People", "people", people), ("Groups", "groups", groups),
                ("Indicators", "indicators", indicators)]

    def _open_indicator(self, key) -> None:
        g = self._graph
        ent = g.entities.get(key) if g else None
        if ent is None:
            return
        self._subject_key = key
        self._clear_dossier()
        layer = graph.entity_layer(ent)
        card = QFrame(); card.setObjectName("Card")
        lay = QVBoxLayout(card); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(4)
        head = QLabel(ent.label); head.setStyleSheet("font-weight:600; font-size:15px;")
        head.setWordWrap(True); head.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(head)
        sharers = [k for k in g.neighbors(key) if g.entities[k].kind == graph.USER]
        lay.addWidget(self._muted(f"{graph.LAYER_LABELS.get(layer, 'Indicator')}"
                                  f"{' (likely false positive)' if layer == 'phones' else ''}"
                                  f"  ·  shared by {len(sharers)} people"))
        lay.addSpacing(4)
        if sharers:
            lay.addWidget(Collapsible(f"Shared by ({len(sharers)})",
                lambda s=sharers: make_bars([(k, g.entities[k].label, "", g.degree(k)) for k in s],
                    on_click=self._open_key), open=True))
        val = ent.label
        hits = []
        for uk, msgs in (self._umsgs or {}).items():
            who = g.entities[uk].label if uk in g.entities else uk
            for m in msgs:
                t = " ".join(str(m.get(f, "")) for f in intel._TEXT_FIELDS)
                if val in t:
                    hits.append((intel._msg_date(m), who, t))
        hits.sort(key=lambda r: (r[0] or 0))
        lay.addWidget(Collapsible(f"Messages ({len(hits)})", lambda h=hits: self._hits_table(h)))
        lay.addStretch(1)
        self.dossier_lay.addWidget(card)

    def _hits_table(self, hits):
        from datetime import datetime, timezone
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Date", "From", "Message"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False); table.setShowGrid(False); table.setMaximumHeight(260)
        for date, who, text in hits[-300:][::-1]:
            r = table.rowCount(); table.insertRow(r)
            d = datetime.fromtimestamp(date, timezone.utc).strftime("%Y-%m-%d %H:%M") if date else ""
            table.setItem(r, 0, QTableWidgetItem(d))
            table.setItem(r, 1, QTableWidgetItem(str(who)))
            table.setItem(r, 2, QTableWidgetItem(text))
        return table

    def _open_subject(self, subject, key) -> None:
        self._subject_key = key
        self._subject = subject
        self._clear_dossier()
        card = QFrame(); card.setObjectName("Card")
        lay = QVBoxLayout(card); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(4)

        g = self._graph
        ent = g.entities.get(key) if g else None
        msgs = (self._umsgs or {}).get(key, [])

        title = QLabel(subject.display()); title.setStyleSheet("font-weight:600; font-size:16px;")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(title)
        idbits = []
        if ent and ent.attrs.get("id"):
            idbits.append(f"id {ent.attrs['id']}")
        elif subject.user_id:
            idbits.append(f"id {subject.user_id}")
        if (ent and ent.attrs.get("username")) or subject.handle():
            idbits.append("@" + ((ent and ent.attrs.get("username")) or subject.handle()))
        sub = QLabel("  ·  ".join(idbits) or "no local data - enrich below")
        sub.setObjectName("Muted"); lay.addWidget(sub)

        unseen = ent is None and not msgs
        if unseen:
            nf = QLabel("User not found in your collected data - use the enrichment "
                        "tools below to investigate this account.")
            nf.setWordWrap(True); nf.setStyleSheet(f"color:{ACCENT};")
            lay.addWidget(nf)

        groups = sorted((k for k in g.neighbors(key) if g.entities[k].kind == graph.GROUP),
                        key=lambda k: -g.degree(k)) if (g and ent) else []
        conns = g.connections_of(key, kinds=(graph.USER,)) if (g and ent) else {}
        inds = [k for k in g.neighbors(key) if g.entities[k].kind == graph.INDICATOR] \
            if (g and ent) else []

        lay.addWidget(self._muted(
            f"{len(msgs)} messages  ·  {len(groups)} groups  ·  {len(conns)} connected users  "
            f"·  {len(inds)} indicators"))
        lay.addSpacing(4)

        if groups:
            lay.addWidget(Collapsible(f"Groups seen in ({len(groups)})",
                                      lambda gs=groups: self._groups_bar(gs), open=True))
        if conns:
            lay.addWidget(Collapsible(f"Connected users ({len(conns)})",
                                      lambda cc=conns: self._conns_bar(cc)))
        if inds:
            lay.addWidget(Collapsible(f"Shared indicators ({len(inds)})",
                                      lambda ii=inds: self._inds_bar(ii)))
        if msgs:
            lay.addWidget(Collapsible("Activity over time",
                                      lambda m=msgs: self._activity(m), open=bool(groups) is False))
            lay.addWidget(Collapsible("Active hours (UTC)", lambda m=msgs: self._hours(m)))
            lay.addWidget(Collapsible("Most-used words", lambda m=msgs: self._words(m)))
            lay.addWidget(Collapsible(f"Messages ({len(msgs)})", lambda m=msgs: self._messages(m)))

        # Enrichment runs automatically and shows ONE consolidated, de-duplicated
        # report. The dork "web leads" are Google/DuckDuckGo/Lyzem SEARCH URLs to
        # open in a browser, not data - previewing a search page inline is useless -
        # so they live in a dropdown, never in the report.
        lay.addWidget(self._section("Enrichment · experimental"))
        bar = QHBoxLayout(); bar.setSpacing(8)
        self._enrich_status = self._muted("Running enrichment...")
        self._leads_btn = QToolButton(); self._leads_btn.setText("Web leads")
        self._leads_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._leads_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._leads_menu = QMenu(self._leads_btn); style_menu(self._leads_menu)
        self._leads_btn.setMenu(self._leads_menu); self._leads_btn.setEnabled(False)
        rerun = icon_button("Re-run", "refresh")
        rerun.clicked.connect(lambda _=False, s=subject, k=key: self._auto_enrich(s, k))
        bar.addWidget(self._enrich_status, 1)
        bar.addWidget(self._leads_btn); bar.addWidget(rerun)
        bw = QWidget(); bw.setLayout(bar); lay.addWidget(bw)

        # Propose a personal account when the credentialed providers aren't set up.
        tp = next((p for p in enrich.providers() if p.name == "telethon"), None)
        if tp is not None and not tp.ready()[0]:
            cta = QPushButton("Connect a personal Telegram account to unlock common groups, "
                              "member lists and real ids  →  Keys")
            cta.setFlat(True); cta.setCursor(Qt.CursorShape.PointingHandCursor)
            cta.setStyleSheet(f"QPushButton{{border:none; color:{ACCENT}; text-align:left; "
                              "padding:4px 0; background:transparent;}")
            cta.clicked.connect(self.main.open_keys)
            lay.addWidget(cta)

        self._enrich_box = QVBoxLayout(); self._enrich_box.setSpacing(4)
        ebw = QWidget(); ebw.setLayout(self._enrich_box); lay.addWidget(ebw)

        lay.addStretch(1)
        self.dossier_lay.addWidget(card)
        # Auto-run, debounced (live-typing opens a subject per keystroke).
        self._pending_enrich = (subject, key)
        self._enrich_debounce.start(450)

    # bar builders (lazy, inside collapsibles)
    def _groups_bar(self, groups):
        rows = []
        for k in groups[:40]:
            cid = self._graph.entities[k].attrs.get("chat_id")
            rows.append((k, self.main.chat_label(cid), "", self._graph.degree(k)))
        return make_bars(rows, on_click=lambda k: self.main.open_terrain(
            self._graph.entities[k].attrs.get("chat_id")))

    def _conns_bar(self, conns):
        items = sorted(conns.items(), key=lambda kv: -len(kv[1]))[:40]
        rows = [(k, self._graph.entities[k].label, f"via {len(via)}", len(via)) for k, via in items]
        return make_bars(rows, on_click=self._open_key)

    def _inds_bar(self, inds):
        rows = []
        for k in sorted(inds, key=lambda k: -self._graph.degree(k))[:40]:
            e = self._graph.entities[k]
            rows.append((k, e.label, _IND_LABELS.get(e.attrs.get("itype"), e.attrs.get("itype", "")),
                         self._graph.degree(k)))
        return make_bars(rows)

    def _rows_from_msgs(self, msgs):
        out = []
        for m in msgs:
            d = intel._msg_date(m)
            t = " ".join(str(m.get(f, "")) for f in intel._TEXT_FIELDS).strip()
            if t:
                out.append((d, m.get("message_id", 0), t))
        out.sort(key=lambda r: (r[0] or 0))
        return out

    def _activity(self, msgs):
        tb = TimeBars(); tb.set_buckets(intel.time_buckets(
            [intel._msg_date(m) for m in msgs if intel._msg_date(m)])); return tb

    def _hours(self, msgs):
        tb = TimeBars(); tb.setMinimumHeight(120)
        tb.set_buckets([(f"{h:02d}", c) for h, c in intel.hour_histogram(
            [intel._msg_date(m) for m in msgs if intel._msg_date(m)])])
        return tb

    def _words(self, msgs):
        texts = [t for _, _, t in self._rows_from_msgs(msgs)]
        words = intel.word_frequencies(texts, 15)
        return make_bars([(w, w, "", c) for w, c in words]) if words \
            else self._muted("Not enough text.")

    def _messages(self, msgs):
        from datetime import datetime, timezone
        rows = self._rows_from_msgs(msgs)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Date", "Message"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False); table.setShowGrid(False); table.setMaximumHeight(240)
        for date, _mid, text in rows[-300:][::-1]:
            r = table.rowCount(); table.insertRow(r)
            d = datetime.fromtimestamp(date, timezone.utc).strftime("%Y-%m-%d %H:%M") if date else ""
            table.setItem(r, 0, QTableWidgetItem(d)); table.setItem(r, 1, QTableWidgetItem(text))
        return table

    def _section(self, text):
        lab = QLabel(text); lab.setStyleSheet(f"color:{ACCENT}; padding-top:8px; font-size:12px;")
        return lab

    def _muted(self, text):
        lab = QLabel(text); lab.setObjectName("Muted"); lab.setWordWrap(True); return lab

    # ---- enrichment ----
    def _clear_enrich(self) -> None:
        # Each run shows its own fresh results - otherwise old rows (e.g. a stale
        # "not installed" from before you logged in) pile up and duplicate.
        while self._enrich_box.count():
            item = self._enrich_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _fire_enrich(self) -> None:
        pe = self._pending_enrich
        if pe and pe[1] == self._subject_key:
            self._auto_enrich(pe[0], pe[1])

    def _auto_enrich(self, subject, key) -> None:
        # One run, all ready providers, consolidated + de-duplicated. A run id
        # fences off stale results if the subject changed mid-lookup.
        self._enrich_run = getattr(self, "_enrich_run", 0) + 1
        self._leads, self._data, self._errors, self._msgs = [], {}, [], []
        self._msg_note = None
        self._clear_enrich(); self._render_leads()
        provs = [p for p in enrich.providers() if p.ready()[0]]
        if not provs:
            self._enrich_status.setText(
                "No enrichment source ready - connect Telethon / add a TGStat key in Keys.")
            return
        self._enrich_status.setText("Running " + ", ".join(p.name for p in provs) + "...")
        w = EnrichWorker(provs, subject)
        self._enrich_worker = w; self.main._track(w)
        rid = self._enrich_run
        w.result.connect(lambda r, i=rid: self._on_enrich_result(r, i))
        w.done.connect(lambda i=rid: self._on_enrich_done(i))
        w.start()

    def _on_enrich_result(self, result, rid) -> None:
        if rid != getattr(self, "_enrich_run", 0):
            return   # a newer subject superseded this run
        if not result.ok:
            msg = f"[{result.provider}] {result.error}"
            if msg not in self._errors:
                self._errors.append(msg)
            self._render_report()
            return
        for f in result.findings:
            if f.kind == "lead" and f.url:
                if f.url not in {l.url for l in self._leads}:   # same search, one entry
                    self._leads.append(f)
            elif f.kind == "message":
                # Their own words, pulled from a shared group via your account.
                self._msgs.append({"text": f.value, "group": f.detail.get("group"),
                                   "date": f.detail.get("date")})
            elif f.kind == "msgnote":
                self._msg_note = f.value   # why shared-group messages couldn't be read
            else:
                # De-dupe real data across tools: same (kind, value) -> one row,
                # crediting every source that reported it.
                k = (f.kind, (f.value or "").strip().lower())
                rec = self._data.get(k)
                if rec is None:
                    self._data[k] = {"kind": f.kind, "value": f.value, "url": f.url,
                                     "conf": f.confidence, "sources": {f.source},
                                     "detail": f.detail}
                else:
                    rec["sources"].add(f.source)
                    if f.confidence == "confirmed":
                        rec["conf"] = "confirmed"
                    if f.url and not rec["url"]:
                        rec["url"] = f.url
        self._render_leads(); self._render_report()

    def _on_enrich_done(self, rid) -> None:
        if rid != getattr(self, "_enrich_run", 0):
            return
        srcs = set().union(*(r["sources"] for r in self._data.values())) if self._data else set()
        if self._data or self._leads or self._msgs:
            parts = [f"{len(self._data)} finding(s) from {len(srcs)} source(s)"]
            if self._msgs:
                parts.append(f"{len(self._msgs)} messages")
            parts.append(f"{len(self._leads)} web leads")
            self._enrich_status.setText("  ·  ".join(parts))
        else:
            self._enrich_status.setText("No external data found - try the Web leads.")

    # ---- enrichment rendering ----
    _REPORT_ORDER = ["flag", "profile", "alias", "bio", "stat", "group"]
    _REPORT_LABEL = {"flag": "Flags", "profile": "Identity", "alias": "Aliases",
                     "bio": "Bio", "stat": "Stats", "group": "Groups in common"}

    def _render_leads(self) -> None:
        self._leads_menu.clear()
        for f in self._leads:
            act = self._leads_menu.addAction(f.value)
            act.triggered.connect(lambda _=False, u=f.url: QDesktopServices.openUrl(QUrl(u)))
        self._leads_btn.setEnabled(bool(self._leads))
        self._leads_btn.setText(f"Web leads ({len(self._leads)})" if self._leads else "Web leads")

    def _badge(self, text, color):
        lab = QLabel(text)
        lab.setStyleSheet(f"background:{color}; color:white; border-radius:9px; "
                          "padding:2px 10px; font-weight:600; font-size:11px;")
        return lab

    def _row_wrap(self, layout):
        w = QWidget(); w.setStyleSheet("background:transparent;"); w.setLayout(layout)
        return w

    def _avatar_widget(self, data):
        from PyQt6.QtGui import QPixmap
        av = QLabel(); av.setFixedSize(54, 54)
        av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        photo = next((r for r in data if r["kind"] == "photo"), None)
        if photo:
            pm = QPixmap(photo["value"])
            if not pm.isNull():
                av.setPixmap(pm.scaled(54, 54, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
                av.setStyleSheet("border-radius:8px;")
                return av
        ident = next((r for r in data if r["kind"] == "profile"
                      and (r.get("detail") or {}).get("id")), None)
        nm = ((ident or {}).get("detail") or {}).get("first_name") \
            or (self._subject.display() if getattr(self, "_subject", None) else "?")
        av.setText((nm or "?").lstrip("@")[:1].upper() or "?")
        av.setStyleSheet(f"background:{ACCENT}; color:white; border-radius:27px; "
                         "font-weight:700; font-size:22px;")
        return av

    def _render_report(self) -> None:
        self._clear_enrich()
        box = self._enrich_box
        data = list(self._data.values())
        of = lambda kind: [r for r in data if r["kind"] == kind]
        profiles = of("profile")
        ident = next((r for r in profiles if (r.get("detail") or {}).get("id")), None)
        det = (ident or {}).get("detail") or {}
        handle = (det.get("username")
                  or (self._subject.handle() if getattr(self, "_subject", None) else None))

        # ---- header: avatar + name + @handle/id + flag badges ----
        head = QHBoxLayout(); head.setSpacing(12)
        head.addWidget(self._avatar_widget(data), 0, Qt.AlignmentFlag.AlignTop)
        nb = QVBoxLayout(); nb.setSpacing(2)
        name = (det.get("first_name") or det.get("title")
                or (self._subject.display() if getattr(self, "_subject", None) else "?"))
        nlab = QLabel(name); nlab.setStyleSheet("font-weight:700; font-size:15px;")
        nlab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        nb.addWidget(nlab)
        bits = []
        if handle:
            bits.append("@" + handle)
        if det.get("id"):
            bits.append(f"id {det['id']}")
        if det.get("phone"):
            bits.append(det["phone"])
        if bits:
            sub = QLabel("   ·   ".join(bits)); sub.setObjectName("Muted")
            sub.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            nb.addWidget(sub)
        flags = of("flag")
        if flags:
            fr = QHBoxLayout(); fr.setSpacing(6)
            for rec in flags:
                fr.addWidget(self._badge(rec["value"], DANGER))
            fr.addStretch(1)
            nb.addWidget(self._row_wrap(fr))
        head.addLayout(nb, 1)
        box.addWidget(self._row_wrap(head))

        # ---- headline tiles ----
        groups = of("group")
        tiles = []
        if groups:
            tiles.append(("Groups in common", str(len(groups))))
        if self._msgs:
            tiles.append(("Messages found", str(len(self._msgs))))
        if tiles:
            tr = QHBoxLayout(); tr.setSpacing(10)
            for n, v in tiles:
                tr.addWidget(stat_tile(n, v))
            tr.addStretch(1)
            box.addWidget(self._row_wrap(tr))

        # ---- details (profile facts minus the header identity) / bio / aliases / stats ----
        facts = [r for r in profiles if r is not ident]
        if facts:
            box.addWidget(self._section("Details"))
            for rec in facts:
                box.addWidget(self._report_row(rec))
        for rec in of("bio"):
            box.addWidget(self._section("Bio"))
            txt = rec["value"][4:] if rec["value"].lower().startswith("bio:") else rec["value"]
            lab = QLabel(txt.strip()); lab.setWordWrap(True); lab.setStyleSheet("font-style:italic;")
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(lab)
        aliases = [r for r in of("alias")
                   if r["value"].lstrip("@").lower() != (handle or "").lower()]
        if aliases:
            box.addWidget(self._section("Aliases"))
            for rec in aliases:
                box.addWidget(self._report_row(rec))
        stats = of("stat")
        if stats:
            box.addWidget(self._section("Stats"))
            for rec in stats:
                box.addWidget(self._report_row(rec))

        # ---- groups in common ----
        if groups:
            box.addWidget(self._section(f"Groups in common ({len(groups)})"))
            for rec in groups[:10]:
                box.addWidget(self._report_row(rec))
            if len(groups) > 10:
                box.addWidget(Collapsible(f"{len(groups) - 10} more groups",
                                          lambda rr=groups[10:]: self._report_list(rr)))

        # ---- the pivot: their own messages, grouped by shared group ----
        if self._msgs:
            by: dict = {}
            for m in self._msgs:
                by.setdefault(m.get("group") or "?", []).append(m)
            box.addWidget(self._section(
                f"What they posted in your shared groups ({len(self._msgs)})"))
            for gname, ms in by.items():
                ms = sorted(ms, key=lambda m: -(m.get("date") or 0))
                box.addWidget(Collapsible(f"{gname} ({len(ms)})",
                                          lambda mm=ms: self._msgs_list(mm), open=len(by) <= 2))
        elif groups:
            box.addWidget(self._section("Messages in shared groups"))
            if self._msg_note:
                box.addWidget(self._muted(f"Couldn't read their messages: {self._msg_note}"))
            else:
                box.addWidget(self._muted("No messages from them in your shared groups - "
                                          "they may just be a member, or history is restricted."))

        for msg in self._errors:
            box.addWidget(self._muted(msg))

    def _msg_row(self, m):
        from datetime import datetime, timezone
        row = QWidget(); row.setStyleSheet("background:transparent;")
        v = QVBoxLayout(row); v.setContentsMargins(0, 2, 0, 2); v.setSpacing(1)
        d = (datetime.fromtimestamp(m["date"], timezone.utc).strftime("%Y-%m-%d %H:%M")
             if m.get("date") else "")
        meta = QLabel(f"{m.get('group') or ''}  ·  {d}")
        meta.setObjectName("Muted"); meta.setStyleSheet("font-size:11px;")
        txt = QLabel(m.get("text") or ""); txt.setWordWrap(True)
        txt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(meta); v.addWidget(txt)
        return row

    def _msgs_list(self, msgs):
        box = QWidget(); box.setStyleSheet("background:transparent;")
        l = QVBoxLayout(box); l.setContentsMargins(0, 0, 0, 0); l.setSpacing(2)
        for m in msgs:
            l.addWidget(self._msg_row(m))
        return box

    def _report_list(self, recs):
        box = QWidget(); box.setStyleSheet("background:transparent;")
        l = QVBoxLayout(box); l.setContentsMargins(0, 0, 0, 0); l.setSpacing(2)
        for rec in recs:
            l.addWidget(self._report_row(rec))
        return box

    def _report_row(self, rec):
        row = QWidget(); row.setStyleSheet("background:transparent;")
        rl = QHBoxLayout(row); rl.setContentsMargins(0, 1, 0, 1); rl.setSpacing(8)
        lab = QLabel(f"{rec['value']}   ·   {', '.join(sorted(rec['sources']))}")
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if rec["kind"] == "flag":
            lab.setStyleSheet(f"color:{DANGER}; font-weight:600;")
        elif rec["conf"] == "confirmed":
            lab.setStyleSheet("font-weight:600;")
        rl.addWidget(lab, 1)
        if rec["url"]:
            op = QPushButton("Open"); op.setFixedHeight(24)
            op.setCursor(Qt.CursorShape.PointingHandCursor)
            op.clicked.connect(lambda _=False, u=rec["url"]: QDesktopServices.openUrl(QUrl(u)))
            rl.addWidget(op, 0, Qt.AlignmentFlag.AlignTop)
        return row


class NexusPage(BasePage):
    title = "Graph"
    fill = True
    subtitle = ("Everyone and everything you've collected, linked. Users, the groups they "
                "post in, and the indicators they share - across all your bots and sources.")

    def build(self) -> None:
        bar = QHBoxLayout(); bar.setSpacing(8)
        self.focus = QLineEdit()
        self.focus.setPlaceholderText("a person / @handle / id - leave empty to see everyone")
        self.focus.returnPressed.connect(self._render)
        bar.addWidget(field("Center the graph on", self.focus), 1)

        self.sources_btn = self.main.sources_button(self._render)
        bar.addWidget(self.sources_btn, 0, Qt.AlignmentFlag.AlignBottom)

        # One dropdown holds every knob: depth + min-links sliders and the layer
        # multi-select, so the bar stays clean.
        self.view_btn = QToolButton(); self.view_btn.setText("View")
        self.view_btn.setIcon(make_icon("gear", TEXT, 16)); self.view_btn.setIconSize(ICON)
        self.view_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.view_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_btn.setMenu(self._build_view_menu())
        bar.addWidget(self.view_btn, 0, Qt.AlignmentFlag.AlignBottom)
        rebuild = icon_button("Rebuild", "refresh"); rebuild.clicked.connect(self._rebuild)
        fit = icon_button("Fit", "chart"); fit.clicked.connect(lambda: self.view.fit())
        bar.addWidget(rebuild, 0, Qt.AlignmentFlag.AlignBottom)
        bar.addWidget(fit, 0, Qt.AlignmentFlag.AlignBottom)
        self.root.addLayout(bar)

        self.view = GraphView()
        self.view.load_overrides(store.load_graph_style())
        self.view.nodeClicked.connect(self._on_node)
        self.view.nodeActivated.connect(self._on_activate)
        self.view.reclassify.connect(self._on_reclassify)
        self.view.styleChanged.connect(self._save_style)
        self.root.addWidget(self.view, 1)
        self.detail = QLabel("Click a node to inspect it; double-click a person to investigate, "
                             "a group to open it in Terrain. Right-click a node to rename, "
                             "recolour, resize or fix its type.")
        self.detail.setObjectName("Muted"); self.detail.setWordWrap(True)
        self.root.addWidget(self.detail)

    def _build_view_menu(self) -> QMenu:
        menu = style_menu(QMenu(self))
        self.radius = QSlider(Qt.Orientation.Horizontal); self.radius.setRange(1, 3); self.radius.setValue(1)
        self.radius.valueChanged.connect(self._render)
        menu.addAction(self._slider_row(menu, "Depth around focus", self.radius))
        self.min_deg = QSlider(Qt.Orientation.Horizontal); self.min_deg.setRange(1, 10); self.min_deg.setValue(1)
        self.min_deg.valueChanged.connect(self._render)
        menu.addAction(self._slider_row(menu, "Min links per node", self.min_deg))
        menu.addSeparator()
        hdr = menu.addAction("Layers to show"); hdr.setEnabled(False)
        # Phones are regex false-positive prone, so off by default; the rest on.
        default_on = set(graph.LAYERS) - {"phones"}
        self.layer_checks = {}
        for layer in graph.LAYERS:
            cb = QCheckBox(graph.LAYER_LABELS[layer]); cb.setChecked(layer in default_on)
            cb.toggled.connect(self._render)
            self.layer_checks[layer] = cb
            menu.addAction(self._wrap_action(menu, cb))
        return menu

    def _slider_row(self, menu, label, slider) -> QWidgetAction:
        slider.setFixedWidth(140)
        wa = QWidgetAction(menu)
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(10, 4, 10, 4); h.setSpacing(8)
        lab = QLabel(label); lab.setStyleSheet(f"color:{TEXT};")
        val = QLabel(str(slider.value())); val.setObjectName("Muted"); val.setFixedWidth(14)
        slider.valueChanged.connect(lambda v, vl=val: vl.setText(str(v)))
        h.addWidget(lab); h.addStretch(1); h.addWidget(val); h.addWidget(slider)
        wa.setDefaultWidget(w)
        return wa

    def _wrap_action(self, menu, widget) -> QWidgetAction:
        wa = QWidgetAction(menu)
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(12, 1, 12, 1); h.addWidget(widget)
        wa.setDefaultWidget(w)
        return wa

    def on_shown(self) -> None:
        self._graph, _ = self.main.get_graph()
        self._render()

    def _rebuild(self) -> None:
        self.main.invalidate_graph()
        self._graph, _ = self.main.get_graph()
        self._render()

    def _on_reclassify(self, key, layer) -> None:
        ent = self._graph.entities.get(key) if self._graph else None
        if ent is not None:
            ent.attrs["_layer"] = layer
            self.main.log(f"[OK] Reclassified node as {graph.LAYER_LABELS.get(layer, layer)}.")
        styles = store.load_graph_style()
        styles.setdefault(key, {})["layer"] = layer
        store.save_graph_style(styles)
        self._render()

    def _save_style(self, key) -> None:
        # Persist the node's hand styling (color/size/label) alongside any layer.
        styles = store.load_graph_style()
        rec = styles.setdefault(key, {})
        rec.update(self.view.overrides_for(key))
        store.save_graph_style(styles)

    def _resolve_focus(self):
        g = self._graph
        raw = self.focus.text().strip().lower()
        if not raw or g is None:
            return None
        for e in g.entities_of(graph.USER):
            hay = f"{e.label} {e.attrs.get('username','')} {e.attrs.get('id','')}".lower()
            if raw.lstrip("@") in hay:
                return e.key
        return None

    def _render(self) -> None:
        g = getattr(self, "_graph", None)
        if g is None or not g.entities:
            self.view.set_graph(None)
            if not self.main._selected_bots:
                self.detail.setText("No data yet - pick a source (bot) in 'Sources' to draw its graph.")
            else:
                self.detail.setText("No data yet - the selected source hasn't collected messages.")
            return
        focus = self._resolve_focus()
        view_g = g.ego(focus, radius=self.radius.value()) if focus else g
        # Layer filter (the multi-select in the View dropdown).
        enabled = {L for L, cb in self.layer_checks.items() if cb.isChecked()}
        keep = [k for k, e in view_g.entities.items() if graph.entity_layer(e) in enabled]
        view_g = view_g.subgraph(keep)
        md = self.min_deg.value()
        if md > 1:
            keep = [k for k in view_g.entities if view_g.degree(k) >= md]
            view_g = view_g.subgraph(keep)
        note = ""
        if len(view_g.entities) > 250:
            top = {e.key for e in view_g.top_by_degree(n=250)}
            view_g = view_g.subgraph(top)
            note = " (showing the 250 most-connected; focus a subject or raise 'min links' to narrow)"
        self.view.set_graph(view_g)
        self.detail.setText(f"{len(view_g.entities)} nodes · {len(view_g.edges)} links{note}")

    def _on_node(self, key) -> None:
        g = self._graph
        e = g.entities.get(key) if g else None
        if e is None:
            return
        extra = ""
        if e.kind == graph.USER:
            extra = " — double-click to investigate"
        elif e.kind == graph.GROUP:
            extra = f" — {self.main.chat_label(e.attrs.get('chat_id'))}, double-click to open in Terrain"
        self.detail.setText(f"{e.kind}: {e.label}  ·  {g.degree(key)} links{extra}")

    def _on_activate(self, key) -> None:
        g = self._graph
        e = g.entities.get(key) if g else None
        if e is None:
            return
        if e.kind == graph.USER:
            self.main.open_investigator_key(key)
        elif e.kind == graph.GROUP:
            self.main.open_terrain(e.attrs.get("chat_id"))


_NAV = [
    ("Connection", [("Bot & chat", ConnectionPage), ("Keys", CredentialsPage)]),
    ("Bot control", [("Conversation", ConversationPage), ("Admins", AdminsPage),
                     ("Bot rights", RightsPage), ("Invitations", InvitePage)]),
    ("Investigateur", [("Investigator", InvestigatorPage)]),
    ("Nexus", [("Graph", NexusPage)]),
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
    # Emitted (from any thread) when a group is upgraded to a supergroup mid-call.
    migrated = pyqtSignal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.session = Session()
        self.session.migrate_cb = lambda old, new: self.migrated.emit(old, new)
        self.migrated.connect(self._on_migrated)
        self.settings = store.load_settings()
        self._workers: set = set()
        self._threads: set = set()       # every live QThread, kept until finished
        self._pollers: dict = {}         # bot_id -> UpdatesPoller
        self._poller_retries: dict = {}  # bot_id -> consecutive poll failures (for backoff)
        self._chats_by_bot: dict = {}    # bot_id -> {chat_id: info}
        self._backfills: dict = {}       # (bot_id, chat_id) -> BackfillWorker | None (reserving)
        self._viewed_chat = None         # (bot_id, chat_id) shown in Conversation
        self._cant_backfill: set = set() # (bot_id, chat_id) the bot can't walk (no delete right)
        self._hidden_tokens: set = set() # bot_ids hidden from the picker this session
        self._hidden_chats: set = set()  # (bot_id, chat_id str) hidden from the picker this session
        self._graph_cache = None         # (graph, user_messages) built lazily from the store
        self._graph_cache_key = None
        # Which bots feed the graph. Empty by default: the graph shows nothing
        # until you pick a source, so it never guesses across unrelated bots.
        self._selected_bots = set(str(b) for b in self.settings.get("graph_sources", []))
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
            cid = c.get("id")
            if cid is None:
                continue
            title = c.get("title") or c.get("username") or c.get("first_name") or f"chat {cid}"
            ctype = c.get("type") or "?"
            icon = "message" if ctype == "channel" else "users"
            act = menu.addAction(make_icon(icon, TEXT, 17), f"{title}  ({ctype})  -  {cid}")
            act.setData(("chat", bot_id, str(cid)))
            act.triggered.connect(lambda _=False, c_id=cid: self._set_chat(c_id))
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
        "Bot & chat": "plug", "Keys": "key", "Admins": "users",
        "Bot rights": "shield", "Invitations": "link", "New arrivals": "broadcast",
        "Archive messages": "archive", "Report": "chart", "Conversation": "message",
        "Investigator": "scan", "Graph": "share",
    }

    def _build_sidebar(self) -> QWidget:
        side = QFrame(); side.setObjectName("Sidebar"); side.setFixedWidth(224)
        lay = QVBoxLayout(side); lay.setContentsMargins(8, 12, 8, 12)
        self.nav = QListWidget(); self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(17, 17))
        self._page_rows: list = []  # row index -> page class or None
        self._sections: list = []   # (header_item, [child_items]) - collapsible blocks
        for section, items in _NAV:
            head = QListWidgetItem(section.upper())
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)          # clickable, not selectable
            head.setIcon(make_icon("chevron", TEXT_MUTED, 13))
            f = QFont(); f.setPointSize(8); f.setBold(True); head.setFont(f)
            head.setForeground(QColor(TEXT_MUTED))
            head.setSizeHint(QSize(0, 30))
            head.setData(Qt.ItemDataRole.UserRole, ("header", len(self._sections)))
            self.nav.addItem(head)
            self._page_rows.append(None)
            children = []
            for label, cls in items:
                it = QListWidgetItem(make_icon(self._NAV_ICONS.get(label, "search"), TEXT_MUTED, 17), label)
                it.setSizeHint(QSize(0, 38))
                self.nav.addItem(it)
                self._page_rows.append(cls)
                children.append(it)
            self._sections.append((head, children))
        self.nav.currentRowChanged.connect(self._nav_changed)
        self.nav.itemClicked.connect(self._nav_item_clicked)
        lay.addWidget(self.nav)
        return side

    def _nav_item_clicked(self, item) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and data and data[0] == "header":
            self._toggle_section(data[1])

    def _toggle_section(self, idx: int) -> None:
        head, children = self._sections[idx]
        collapse = any(not c.isHidden() for c in children)   # any visible -> collapse all
        for c in children:
            c.setHidden(collapse)
        head.setIcon(make_icon("chevron_right" if collapse else "chevron", TEXT_MUTED, 13))

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
        # The latest activity / error, always visible (errors used to hide in the log).
        self.status_line = QLabel("")
        self.status_line.setStyleSheet(f"color:{TEXT_MUTED};")
        self.status_line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.status_line, 1)
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

    # ---- cross-bot graph + cross-tab navigation (Investigator / Nexus) ----
    def get_graph(self):
        """The relationship graph + per-user messages, built from the SELECTED
        bots only (empty when none are picked), cached until that or the data
        changes. Persisted reclassifications are re-applied here."""
        key = tuple(sorted(self._selected_bots))
        if self._graph_cache is None or self._graph_cache_key != key:
            sources = [(b, m) for b, m in store.all_sources() if b in self._selected_bots]
            g = graph.build_graph(sources)
            # Groups come out of the store as raw chat ids - give them the real
            # title from any bot's known chats so the graph shows names.
            for e in g.entities_of(graph.GROUP):
                title = self._chat_title(e.attrs.get("chat_id"))
                if title:
                    e.label = title
            # Re-apply saved hand reclassifications (color/size/label handled in the view).
            for k, st in store.load_graph_style().items():
                e = g.entities.get(k)
                if e is not None and st.get("layer"):
                    e.attrs["_layer"] = st["layer"]
            self._graph_cache = (g, graph.user_messages(sources))
            self._graph_cache_key = key
        return self._graph_cache

    def set_selected_bots(self, bots) -> None:
        self._selected_bots = set(str(b) for b in bots)
        self.settings["graph_sources"] = sorted(self._selected_bots)
        store.save_settings(self.settings)
        self.invalidate_graph()

    def sources_button(self, on_change) -> QToolButton:
        """A 'Sources' dropdown: tick which bots feed the graph. Repopulated each
        time it opens so newly-seen bots appear. Shared by Nexus and Investigator."""
        btn = QToolButton(); btn.setText("Sources")
        btn.setIcon(make_icon("robot", TEXT, 16)); btn.setIconSize(ICON)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        menu = style_menu(QMenu(btn))

        def repopulate():
            menu.clear()
            tokens = store.load_tokens()
            bots = store.message_bots()
            if not bots:
                a = menu.addAction("No collected data yet"); a.setEnabled(False)
                return
            for bid in bots:
                name = tokens.get(str(bid), {}).get("username")
                label = f"@{name}" if name else f"bot {bid}"
                cb = QCheckBox(f"{label}  ·  {store.collected_count(bid)} msgs")
                cb.setChecked(str(bid) in self._selected_bots)
                cb.toggled.connect(lambda on, b=str(bid): self._toggle_source(b, on, on_change))
                wa = QWidgetAction(menu); w = QWidget(); h = QHBoxLayout(w)
                h.setContentsMargins(12, 2, 12, 2); h.addWidget(cb)
                wa.setDefaultWidget(w); menu.addAction(wa)

        menu.aboutToShow.connect(repopulate)
        btn.setMenu(menu)
        return btn

    def _toggle_source(self, bid, on, on_change) -> None:
        sel = set(self._selected_bots)
        sel.add(bid) if on else sel.discard(bid)
        self.set_selected_bots(sel)
        on_change()

    def _chat_title(self, chat_id):
        if chat_id is None:
            return None
        for chats in self._chats_by_bot.values():
            c = chats.get(str(chat_id))
            if c and c.get("title"):
                return c["title"]
        return None

    def _on_migrated(self, old, new) -> None:
        """A group was upgraded to a supergroup: its id changed. Follow the new id
        everywhere - the client already retried the call, we move the state."""
        bot_id = self.session.bot_id
        self.log(f"[INFO] Chat {old} was upgraded to a supergroup -> {new}. Following it.")
        if bot_id is not None:
            chats = self._chats_by_bot.get(bot_id, {})
            entry = chats.pop(str(old), None) or {"id": new, "type": "supergroup"}
            entry["id"] = new
            chats[str(new)] = entry
            self._chats_by_bot[bot_id] = chats
            store.save_chats(bot_id, chats)
            store.migrate_chat_id(bot_id, old, new)
            store.migrate_backfill(bot_id, old, new)
            self._cant_backfill = {(b, new) if (b == bot_id and str(c) == str(old)) else (b, c)
                                   for (b, c) in self._cant_backfill}
        if str(self.session.chat) == str(old):
            self.session.chat = new
            self.chat_in.blockSignals(True); self.chat_in.setText(str(new)); self.chat_in.blockSignals(False)
            if self._viewed_chat and str(self._viewed_chat[1]) == str(old):
                self._viewed_chat = (bot_id, new)
            self._invalidate_display()
            self._refresh_active_page()
        self.invalidate_graph()
        self.schedule_backfills()

    def invalidate_graph(self) -> None:
        self._graph_cache = None

    def chat_label(self, chat_id) -> str:
        """A readable name for a chat id, from any bot's known chats."""
        if chat_id is None:
            return "?"
        for chats in self._chats_by_bot.values():
            c = chats.get(str(chat_id))
            if c and c.get("title"):
                return f"{c['title']} ({chat_id})"
        return str(chat_id)

    def _row_of(self, cls) -> Optional[int]:
        for row, c in enumerate(self._page_rows):
            if c is cls:
                return row
        return None

    def open_terrain(self, chat_id) -> None:
        if chat_id is None:
            return
        self._set_chat(chat_id)
        row = self._row_of(ConversationPage)
        if row is not None:
            self.nav.setCurrentRow(row)

    def open_investigator_key(self, key) -> None:
        row = self._row_of(InvestigatorPage)
        if row is None:
            return
        page = self._pages.get(row)
        if page is not None:
            page.open_pending(key)
        self.nav.setCurrentRow(row)

    def open_keys(self) -> None:
        row = self._row_of(CredentialsPage)
        if row is not None:
            self.nav.setCurrentRow(row)

    # ---- background pollers: one per saved bot, all running at once ----
    def _set_active_bot(self, bot_id) -> None:
        self.session.bot_id = bot_id
        self.session.known_chats = self._chats_by_bot.setdefault(
            bot_id, store.load_chats(bot_id))
        # Make the graph/investigator show the bot you just connected (you can
        # still deselect it, or add others, in 'Sources'). Fixes "I connected a
        # bot but Graph/Investigator are empty".
        bid = str(bot_id)
        if bid not in self._selected_bots:
            self._selected_bots.add(bid)
            self.settings["graph_sources"] = sorted(self._selected_bots)
            store.save_settings(self.settings)
            self.invalidate_graph()

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
        self._poller_retries[bot_id] = 0   # we're receiving again: reset backoff
        store.append_messages(bot_id, [msg])
        self._graph_cache = None   # store changed: the graph is rebuilt on next view
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
        if not reason:
            return   # clean stop (app closing / replaced)
        n = self._poller_retries.get(bot_id, 0) + 1
        self._poller_retries[bot_id] = n
        # A revoked/invalid token can't be fixed by retrying - surface it and stop.
        if "[401]" in reason or "unauthorized" in reason.lower():
            if bot_id == self.session.bot_id:
                self.set_bot_status(False, "Token invalid")
            self.log(f"[ERROR] Live updates stopped for bot {bot_id}: {reason}")
            return
        # Anything else (almost always a 409 Conflict - a previous long-poll still
        # open, or a second consumer) is transient and clears itself, so NEVER give
        # up: retry forever with capped backoff, quietly. Giving up would silently
        # kill reception while the status still shows "connected".
        self.log(f"[ERROR] Live updates for bot {bot_id} stopped: {reason}", quiet=True)
        delay = min(5 * n, 30)
        token = store.load_tokens().get(str(bot_id), {}).get("token", "")
        if token:
            QTimer.singleShot(delay * 1000,
                              lambda t=token, b=bot_id: self._ensure_poller(t, b))

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

    def clear_backfill_block(self, bot_id, chat_id) -> None:
        """Forget a 'can't walk this chat' mark (e.g. after the bot is granted the
        delete right) and let the scheduler try it again."""
        for key in [k for k in self._cant_backfill
                    if k[0] == bot_id and str(k[1]) == str(chat_id)]:
            self._cant_backfill.discard(key)
        self.schedule_backfills()

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
            # The original hack (messagesDumper.py) just forwards each id back and
            # reads the response - NO permission gate. A forward works for any bot
            # that can post here, and deleting the copy afterwards is deleting the
            # bot's OWN outgoing message, which needs no admin right. So there is no
            # delete-rights precondition; gating on it was a regression that wrongly
            # skipped the walk. Per-id forward failures are handled in the worker.
            if floor is not None:
                start = floor - 1
            elif min_collected is not None:
                start = min_collected - 1
            else:
                start = api.current_max_message_id(client, chat)
            return {"start": start}

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

    def log(self, msg: str, quiet: bool = False) -> None:
        self.logbox.appendPlainText(msg)
        # quiet = keep it in the Logs drawer only (e.g. the recurring getUpdates
        # 409 conflict), so the status bar isn't spammed with background noise.
        if quiet:
            return
        line = " ".join(str(msg).split())
        is_err = "[ERROR]" in line
        self.status_line.setText(line[:160])
        self.status_line.setStyleSheet(f"color:{DANGER};" if is_err else f"color:{TEXT_MUTED};")

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
