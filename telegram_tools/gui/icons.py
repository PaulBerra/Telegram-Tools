"""Tiny SVG icon set, tinted at runtime.

We draw our own outline icons so they match the UI and can be recolored to sit
left of a button label. No external icon pack, no font to ship.
"""

from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

# Each entry is the inner SVG markup for a 24x24 viewBox. Strokes use
# currentColor-style placeholder {c}; filled shapes set fill="{c}".
_SHAPES: dict[str, str] = {
    "plug": '<path d="M9 3v4M15 3v4M7 7h10v3a5 5 0 0 1-10 0z"/><path d="M12 15v6"/>',
    "robot": '<rect x="5" y="8" width="14" height="11" rx="2"/><path d="M12 8V5"/>'
             '<circle cx="9.5" cy="13" r="1" fill="{c}" stroke="none"/>'
             '<circle cx="14.5" cy="13" r="1" fill="{c}" stroke="none"/>',
    "shield": '<path d="M12 3l7 3v5c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6z"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.5 4-7 8-7s8 2.5 8 7"/>',
    "key": '<circle cx="7" cy="12" r="3.3"/><path d="M10.3 12H21M18 12v3M21 12v2.4"/>',
    "link": '<path d="M9.5 14.5l5-5"/><path d="M8 8L6.5 9.5a3.5 3.5 0 0 0 5 5L13 13"/>'
            '<path d="M16 16l1.5-1.5a3.5 3.5 0 0 0-5-5L11 11"/>',
    "broadcast": '<circle cx="12" cy="12" r="2.2" fill="{c}" stroke="none"/>'
                 '<path d="M8 8a5.5 5.5 0 0 0 0 8M16 8a5.5 5.5 0 0 1 0 8"/>'
                 '<path d="M5.5 5.5a9 9 0 0 0 0 13M18.5 5.5a9 9 0 0 1 0 13"/>',
    "archive": '<rect x="3" y="4" width="18" height="4" rx="1"/>'
               '<path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/><path d="M10 12h4"/>',
    "play": '<path d="M8 5l11 7-11 7z" fill="{c}" stroke="none"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="{c}" stroke="none"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M20.5 20.5L16.5 16.5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "trash": '<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/>',
    "users": '<circle cx="9" cy="9" r="3.2"/><path d="M3 20c0-3.2 3-5 6-5s6 1.8 6 5"/>'
             '<path d="M16 6.5a3 3 0 0 1 0 6M18.5 20c0-2.2-1.2-3.8-3.2-4.6"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 6.5"/>',
    "download": '<path d="M12 3v12M7.5 11.5L12 16l4.5-4.5M5 20h14"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 6.1"/><path d="M20 4v7h-7"/>',
    "chart": '<path d="M4 4v16h16"/>'
             '<rect x="7" y="11" width="3" height="6" rx="0.5" fill="{c}" stroke="none"/>'
             '<rect x="12" y="7" width="3" height="10" rx="0.5" fill="{c}" stroke="none"/>'
             '<rect x="17" y="13" width="3" height="4" rx="0.5" fill="{c}" stroke="none"/>',
    "back": '<path d="M15 5l-7 7 7 7"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "chevron_right": '<path d="M9 6l6 6-6 6"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    "message": '<path d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9l-4 4v-4H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/>'
            '<path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
    "forward": '<path d="M12 8V4l8 8-8 8v-4H4V8z"/>',
    "arrow_up": '<path d="M12 20V5M6 11l6-6 6 6"/>',
    "scan": '<circle cx="10" cy="9" r="3.4"/>'
            '<path d="M3.5 20c0-3.5 3-5.6 6.5-5.6 1 0 2 .18 2.9.5"/>'
            '<circle cx="16.5" cy="16" r="3.1"/><path d="M18.8 18.3L22 21.5"/>',
    "share": '<circle cx="6" cy="12" r="2.3" fill="{c}" stroke="none"/>'
             '<circle cx="18" cy="6" r="2.3" fill="{c}" stroke="none"/>'
             '<circle cx="18" cy="18" r="2.3" fill="{c}" stroke="none"/>'
             '<path d="M8 11l8-4M8 13l8 4"/>',
    "gear": '<circle cx="12" cy="12" r="3.2"/>'
            '<path d="M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2M6 6l1.4 1.4M16.6 16.6L18 18'
            'M18 6l-1.4 1.4M7.4 16.6L6 18"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4 7 7 0 1 0 20 14.5z"/>',
}

_VIEW = 24


# The app mark: a rounded accent tile with a white magnifier over a chat bubble -
# "investigate conversations". Used as the window / taskbar icon.
_APP_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
  <rect x="3" y="3" width="42" height="42" rx="11" fill="{a}"/>
  <path d="M13 15h16a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-9l-5 4v-4h-2a3 3 0 0 1-3-3v-9a3 3 0 0 1 3-3z"
        fill="none" stroke="#FFFFFF" stroke-width="2.4" stroke-linejoin="round" opacity="0.55"/>
  <circle cx="23" cy="22" r="5.6" fill="none" stroke="#FFFFFF" stroke-width="2.8"/>
  <line x1="27.2" y1="26.2" x2="32" y2="31" stroke="#FFFFFF" stroke-width="2.8" stroke-linecap="round"/>
</svg>"""


@lru_cache(maxsize=4)
def app_icon(accent: str = "#2D6CE0") -> QIcon:
    """Multi-size window/taskbar icon rendered from the app mark."""
    icon = QIcon()
    svg = _APP_SVG.replace("{a}", accent)
    renderer = QSvgRenderer(bytearray(svg, "utf-8"))
    for size in (16, 24, 32, 48, 64, 128):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(pix)
    return icon


@lru_cache(maxsize=256)
def make_icon(name: str, color: str = "#1D1D1F", size: int = 18) -> QIcon:
    inner = _SHAPES.get(name)
    if inner is None:
        return QIcon()
    inner = inner.replace("{c}", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_VIEW} {_VIEW}" '
           f'fill="none" stroke="{color}" stroke-width="2" '
           f'stroke-linecap="round" stroke-linejoin="round">{inner}</svg>')
    renderer = QSvgRenderer(bytearray(svg, "utf-8"))
    scale = 2  # render at 2x for crisp edges on hi-dpi
    pix = QPixmap(size * scale, size * scale)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    pix.setDevicePixelRatio(scale)
    return QIcon(pix)
