"""Small hand-drawn chart widgets for the report dashboard.

QPainter, no extra dependency, themed to match the rest of the app. Two that
matter: a clickable horizontal bar list (top links, top senders - click a row to
drill in) and a time histogram (how an item trends over time).
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .theme import ACCENT, BORDER, HOVER, PROG_BG, SURFACE_2, TEXT, TEXT_MUTED


def stat_tile(label: str, value: str) -> QFrame:
    """A metric tile: small muted label, big number under it."""
    f = QFrame(); f.setObjectName("Tile")
    lay = QVBoxLayout(f); lay.setContentsMargins(14, 10, 14, 12); lay.setSpacing(2)
    l = QLabel(label); l.setObjectName("FieldLabel")
    v = QLabel(value); v.setStyleSheet("font-size:22px; font-weight:600;")
    v.setObjectName("TileValue")
    lay.addWidget(l); lay.addWidget(v)
    f._value = v  # so callers can update it
    return f


class HBarList(QWidget):
    """Ranked horizontal bars. Rows are clickable to drill into one item."""

    clicked = pyqtSignal(object)   # emits the row key

    def __init__(self, parent=None, row_height: int = 30):
        super().__init__(parent)
        self._rows: list[tuple] = []   # (key, label, sub, value)
        self._row_h = row_height
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_rows(self, rows) -> None:
        # rows: list of (key, label, sub, value)
        self._rows = list(rows)
        self.setMinimumHeight(max(self._row_h * len(self._rows), self._row_h))
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(300, max(self._row_h * len(self._rows), self._row_h))

    def _row_at(self, y) -> int:
        i = int(y // self._row_h)
        return i if 0 <= i < len(self._rows) else -1

    def mouseMoveEvent(self, e):
        i = self._row_at(e.position().y())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        i = self._row_at(e.position().y())
        if i >= 0:
            self.clicked.emit(self._rows[i][0])

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._rows:
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No data yet")
            p.end(); return
        w = self.width()
        label_w = int(w * 0.42)
        count_w = 48
        bar_x = label_w + 8
        bar_w = max(w - bar_x - count_w - 6, 10)
        maxv = max((r[3] for r in self._rows), default=1) or 1
        fm = QFontMetrics(self.font())
        small = QFont(self.font()); small.setPointSize(max(self.font().pointSize() - 1, 8))

        for i, (key, label, sub, value) in enumerate(self._rows):
            y = i * self._row_h
            rrect = QRectF(0, y, w, self._row_h)
            if i == self._hover:
                p.fillRect(rrect, QColor(HOVER))
            # label (elided)
            p.setPen(QColor(TEXT))
            txt = fm.elidedText(label, Qt.TextElideMode.ElideMiddle, label_w - 6)
            p.drawText(QRectF(2, y, label_w - 6, self._row_h),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), txt)
            # bar
            bw = bar_w * (value / maxv)
            track = QRectF(bar_x, y + self._row_h / 2 - 5, bar_w, 10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(PROG_BG)); p.drawRoundedRect(track, 5, 5)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(bar_x, y + self._row_h / 2 - 5, max(bw, 2), 10), 5, 5)
            # count
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(QRectF(w - count_w, y, count_w - 4, self._row_h),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                       str(value))
        p.end()


class TimeBars(QWidget):
    """Vertical bars over time buckets: label + count pairs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buckets: list[tuple] = []
        self.setMinimumHeight(150)

    def set_buckets(self, buckets) -> None:
        self._buckets = list(buckets)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if not self._buckets:
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no dated messages")
            p.end(); return
        pad_l, pad_b, pad_t = 8, 24, 16
        plot_h = h - pad_b - pad_t
        plot_w = w - pad_l - 8
        n = len(self._buckets)
        maxv = max(c for _, c in self._buckets) or 1
        gap = 3
        bw = max((plot_w - gap * (n - 1)) / n, 2)

        # max-value guide
        p.setPen(QColor(TEXT_MUTED))
        p.drawText(QRectF(0, 0, w, 14),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop), f"max {maxv}")

        every = max(1, n // 8)
        fm = QFontMetrics(self.font())
        for i, (label, c) in enumerate(self._buckets):
            x = pad_l + i * (bw + gap)
            bh = plot_h * (c / maxv)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(x, pad_t + (plot_h - bh), bw, bh), 2, 2)
            if i % every == 0:
                p.setPen(QColor(TEXT_MUTED))
                lbl = fm.elidedText(label, Qt.TextElideMode.ElideRight, int(bw * every))
                p.drawText(QRectF(x, h - pad_b + 4, bw * every + 20, pad_b - 4),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), lbl)
        p.end()
