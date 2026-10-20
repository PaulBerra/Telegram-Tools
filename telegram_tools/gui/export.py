"""One export control instead of CSV buttons scattered everywhere.

An Export button opens a small menu: pick what to export (messages, members,
links, indicators...) then the format (CSV or JSON). Each dataset is a callable
resolved at click time, so it always exports the current state. The file dialog
is the only thing that writes to disk.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Callable

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction, QColor, QPalette
from PyQt6.QtWidgets import QFileDialog, QMenu, QToolButton

from .icons import make_icon
from .theme import ACCENT, MENU_QSS, SURFACE, TEXT


def style_menu(m: QMenu) -> QMenu:
    """Legible light menu via both stylesheet and palette (popups don't reliably
    inherit the app theme on a dark-mode OS)."""
    m.setStyleSheet(MENU_QSS)
    pal = m.palette()
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base):
        pal.setColor(role, QColor(SURFACE))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText):
        pal.setColor(role, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    m.setPalette(pal)
    return m

# A dataset provider returns (headers, rows) where rows is a list of lists.
Provider = Callable[[], tuple]


def _to_csv(headers, rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    return buf.getvalue()


def _to_json(headers, rows) -> str:
    return json.dumps([dict(zip(headers, r)) for r in rows], ensure_ascii=False, indent=2)


def build_export_button(parent, datasets, log=None, label: str = "Export") -> QToolButton:
    """datasets: list of (name, suggested_filename, provider)."""
    btn = QToolButton()
    btn.setText(label)
    btn.setIcon(make_icon("download", TEXT, 16))
    btn.setIconSize(QSize(16, 16))
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)

    menu = style_menu(QMenu(btn))

    def add_formats(target, fname, provider):
        for fmt in ("CSV", "JSON"):
            act = QAction(fmt, target)
            act.triggered.connect(
                lambda _=False, p=provider, f=fname, k=fmt.lower():
                _save(parent, p, f, k, log))
            target.addAction(act)

    if len(datasets) == 1:
        # One dataset: skip the extra level, offer CSV / JSON directly.
        _, fname, provider = datasets[0]
        add_formats(menu, fname, provider)
    else:
        for name, fname, provider in datasets:
            sub = style_menu(menu.addMenu(name))   # submenus need styling too
            add_formats(sub, fname, provider)
    btn.setMenu(menu)
    return btn


def _save(parent, provider: Provider, suggested: str, fmt: str, log):
    try:
        headers, rows = provider()
    except Exception as exc:
        if log:
            log(f"[ERROR] Export failed: {exc}")
        return
    if not rows:
        if log:
            log("[INFO] Nothing to export.")
        return
    ext = "csv" if fmt == "csv" else "json"
    flt = "CSV (*.csv)" if fmt == "csv" else "JSON (*.json)"
    path, _ = QFileDialog.getSaveFileName(parent, "Export", f"{suggested}.{ext}", flt)
    if not path:
        return
    text = _to_csv(headers, rows) if fmt == "csv" else _to_json(headers, rows)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    if log:
        import os
        log(f"[OK] Exported {len(rows)} rows -> {os.path.basename(path)}")
