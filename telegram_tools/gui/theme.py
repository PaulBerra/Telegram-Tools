"""Light / dark look for the app, switchable at runtime.

Flat cards on a soft page, hairline borders, rounded corners, one blue accent.
Every colour lives in one of the two palettes below. `apply_mode()` copies the
chosen palette onto this module's globals and rebuilds the QSS strings, so the
rest of the app can keep importing `TEXT`, `SURFACE`, `QSS`, ... by name and
just re-read them after a switch.
"""

from __future__ import annotations

# Every name a palette defines - also the list of globals other modules import
# from here and must re-sync after a theme change.
_COLOR_KEYS = [
    "BG", "SURFACE", "SURFACE_2", "BORDER", "BORDER_STRONG",
    "TEXT", "TEXT_MUTED", "ACCENT", "ACCENT_HOVER", "SUCCESS", "DANGER", "WARNING",
    "HOVER", "NAV_SEL", "SEL", "SCROLL", "SCROLL_HOVER",
    "DISABLED_BG", "DISABLED_TEXT", "DISABLED_BORDER",
    "WARN_BG", "WARN_BORDER", "PROG_BG", "SYS_PILL",
]

LIGHT = {
    "BG": "#F2F2F4", "SURFACE": "#FFFFFF", "SURFACE_2": "#FBFBFC",
    "BORDER": "#E2E2E6", "BORDER_STRONG": "#D4D4D9",
    "TEXT": "#1D1D1F", "TEXT_MUTED": "#6E6E73",
    "ACCENT": "#2D6CE0", "ACCENT_HOVER": "#255FC9",
    "SUCCESS": "#1E9E5A", "DANGER": "#D64B42", "WARNING": "#9A6B00",
    "HOVER": "#F0F0F3", "NAV_SEL": "#ECECF0", "SEL": "#E7EEFC",
    "SCROLL": "#CBCBD2", "SCROLL_HOVER": "#ADADB6",
    "DISABLED_BG": "#ECECEF", "DISABLED_TEXT": "#B6B6BD", "DISABLED_BORDER": "#E4E4E8",
    "WARN_BG": "#FBEFD0", "WARN_BORDER": "#ECD9A6", "PROG_BG": "#ECECF0",
    "SYS_PILL": "#ECECF0",
}

DARK = {
    "BG": "#1B2027", "SURFACE": "#232A33", "SURFACE_2": "#2A323C",
    "BORDER": "#333C47", "BORDER_STRONG": "#3F4A57",
    "TEXT": "#E6E8EB", "TEXT_MUTED": "#97A1AD",
    "ACCENT": "#4C8DF0", "ACCENT_HOVER": "#5E99F2",
    "SUCCESS": "#46C98A", "DANGER": "#E8736A", "WARNING": "#E3B457",
    "HOVER": "#2E3741", "NAV_SEL": "#313B46", "SEL": "#2B3A52",
    "SCROLL": "#434D59", "SCROLL_HOVER": "#525E6C",
    "DISABLED_BG": "#262D36", "DISABLED_TEXT": "#5C6672", "DISABLED_BORDER": "#313A44",
    "WARN_BG": "#39311C", "WARN_BORDER": "#5A4B22", "PROG_BG": "#313B46",
    "SYS_PILL": "#313B46",
}

PALETTES = {"light": LIGHT, "dark": DARK}

# Current state (also what other modules import). Initialised to light; run()
# calls apply_mode() with the saved setting before the window is built.
MODE = "light"
FONT_SIZE = 13
# Populate the colour globals so `from .theme import TEXT` works at import time.
globals().update(LIGHT)

# Names other modules import and must re-sync after a switch.
EXPORTED = _COLOR_KEYS + ["QSS", "MENU_QSS", "MODE", "FONT_SIZE"]


def _build_menu_qss() -> str:
    g = globals()
    return f"""
QMenu {{
    background-color: {g['SURFACE']};
    color: {g['TEXT']};
    border: 1px solid {g['BORDER']};
    border-radius: 12px;
    padding: 6px;
}}
QMenu::item {{
    background-color: {g['SURFACE']};
    color: {g['TEXT']};
    padding: 9px 30px 9px 12px;
    border-radius: 8px;
    margin: 1px 2px;
}}
QMenu::item:selected {{ background-color: {g['HOVER']}; color: {g['TEXT']}; }}
QMenu::item:disabled {{ color: {g['TEXT_MUTED']}; background-color: {g['SURFACE']}; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::separator {{ height: 1px; background: {g['BORDER']}; margin: 5px 10px; }}
"""


def _build_qss() -> str:
    g = globals()
    return f"""
QWidget {{
    background-color: {g['BG']};
    color: {g['TEXT']};
    font-family: "SF Pro Text", "Segoe UI", "Inter", Arial, sans-serif;
    font-size: {g['FONT_SIZE']}px;
}}
/* Labels inherit no page-grey fill, so text never sits on a grey square. */
QLabel {{ background: transparent; }}
QFrame#ConnectionBar {{
    background-color: {g['SURFACE']};
    border-bottom: 1px solid {g['BORDER']};
}}
QFrame#Sidebar {{
    background-color: {g['SURFACE']};
    border-right: 1px solid {g['BORDER']};
}}
QListWidget#Nav {{
    background: transparent;
    border: none;
    outline: 0;
    padding: 6px;
}}
QListWidget#Nav::item {{
    padding: 8px 12px;
    border-radius: 8px;
    color: {g['TEXT_MUTED']};
}}
QListWidget#Nav::item:selected {{
    background-color: {g['NAV_SEL']};
    color: {g['TEXT']};
}}
QListWidget#Nav::item:hover {{
    background-color: {g['HOVER']};
}}
QLabel#SectionLabel {{
    color: {g['TEXT_MUTED']};
    font-size: 11px;
    padding: 10px 12px 2px 12px;
}}
QLabel#PageTitle {{ font-size: 19px; font-weight: 600; }}
QLabel#Muted {{ color: {g['TEXT_MUTED']}; }}
QLabel#FieldLabel {{ color: {g['TEXT_MUTED']}; font-size: 12px; font-weight: 500; }}
/* All single-line controls share one height (padding 8 + 18 line ~= 34px). */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {g['SURFACE_2']};
    border: 1px solid {g['BORDER']};
    border-radius: 8px;
    padding: 8px 11px;
    min-height: 18px;
    color: {g['TEXT']};
    selection-background-color: {g['ACCENT']};
    selection-color: #FFFFFF;
}}
QPlainTextEdit, QTextEdit, QTableWidget {{
    background-color: {g['SURFACE_2']};
    border: 1px solid {g['BORDER']};
    border-radius: 8px;
    padding: 6px 8px;
    color: {g['TEXT']};
    selection-background-color: {g['ACCENT']};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {g['ACCENT']}; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border: 1px solid {g['BORDER_STRONG']}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    background-color: {g['DISABLED_BG']}; color: {g['DISABLED_TEXT']}; border: 1px solid {g['DISABLED_BORDER']};
}}
QLabel:disabled {{ color: {g['DISABLED_TEXT']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {g['SURFACE']};
    color: {g['TEXT']};
    border: 1px solid {g['BORDER']};
    selection-background-color: {g['ACCENT']};
    selection-color: #FFFFFF;
    outline: 0;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; }}
QPushButton, QToolButton {{
    background-color: {g['SURFACE']};
    color: {g['TEXT']};
    border: 1px solid {g['BORDER_STRONG']};
    border-radius: 8px;
    padding: 8px 14px;
    min-height: 18px;
}}
QPushButton:hover, QToolButton:hover {{ border: 1px solid {g['ACCENT']}; }}
QPushButton:pressed {{ background-color: {g['HOVER']}; }}
QPushButton#Primary, QToolButton#Primary {{
    background-color: {g['ACCENT']};
    border: none;
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#Primary:hover, QToolButton#Primary:hover {{ background-color: {g['ACCENT_HOVER']}; }}
QPushButton#Primary:disabled, QToolButton#Primary:disabled {{
    background-color: {g['DISABLED_BG']}; color: {g['DISABLED_TEXT']}; border: 1px solid {g['BORDER']};
}}
QToolButton#Primary::menu-button {{
    border: none;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
    width: 22px;
}}
QPushButton:disabled, QToolButton:disabled {{
    color: {g['DISABLED_TEXT']}; border: 1px solid {g['BORDER']}; background: {g['SURFACE_2']};
}}
QProgressBar {{
    background-color: {g['PROG_BG']};
    border: none;
    border-radius: 6px;
    text-align: center;
    color: {g['TEXT_MUTED']};
    height: 14px;
}}
QProgressBar::chunk {{ background-color: {g['ACCENT']}; border-radius: 6px; }}
QPlainTextEdit#Log {{
    background-color: {g['SURFACE_2']};
    color: {g['TEXT_MUTED']};
    font-family: "SF Mono", "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
    border-radius: 8px;
}}
QHeaderView::section {{
    background-color: {g['SURFACE']};
    color: {g['TEXT_MUTED']};
    border: none;
    border-bottom: 1px solid {g['BORDER']};
    padding: 6px;
}}
QTableWidget {{ gridline-color: {g['BORDER']}; }}
QFrame#Card {{
    background-color: {g['SURFACE']};
    border: 1px solid {g['BORDER']};
    border-radius: 12px;
}}
QFrame#Tile {{
    background-color: {g['SURFACE_2']};
    border: 1px solid {g['BORDER']};
    border-radius: 12px;
}}
QFrame#Bubble {{
    background-color: {g['SURFACE']};
    border: 1px solid {g['BORDER']};
    border-radius: 16px;
}}
/* iOS-style message composer at the bottom of the conversation. */
QFrame#Composer {{
    background-color: {g['SURFACE']};
    border: 1px solid {g['BORDER']};
    border-radius: 21px;
}}
QLineEdit#ComposerInput {{
    background: transparent; border: none; padding: 7px 10px; min-height: 18px;
}}
QToolButton#SendBtn {{
    background-color: {g['ACCENT']}; border: none; border-radius: 16px;
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; padding: 0;
}}
QToolButton#SendBtn:hover {{ background-color: {g['ACCENT_HOVER']}; }}
QToolButton#SendBtn:disabled {{ background-color: {g['DISABLED_BG']}; }}
QFrame#Warn {{
    background-color: {g['WARN_BG']};
    border: 1px solid {g['WARN_BORDER']};
    border-radius: 10px;
}}
QLabel#Dot {{ font-size: 13px; }}
QFrame#StatusChip {{
    background-color: {g['SURFACE_2']};
    border: 1px solid {g['BORDER']};
    border-radius: 16px;
}}
QFrame#StatusBar {{
    background-color: {g['SURFACE']};
    border-top: 1px solid {g['BORDER']};
}}
QDialog {{ background-color: {g['BG']}; }}

/* Modern thin scrollbars (the default ones look dated / square). */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {g['SCROLL']}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:horizontal {{ background: {g['SCROLL']}; border-radius: 5px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {g['SCROLL_HOVER']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Lists / tables: no square focus outline. */
QListWidget, QTableWidget, QAbstractItemView {{ outline: 0; }}
QTableWidget::item:selected {{ background: {g['SEL']}; color: {g['TEXT']}; }}
QScrollArea {{ background: transparent; }}

/* Spin buttons kept subtle and flat, not raised XP boxes. */
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: transparent; border: none; width: 16px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ width: 8px; height: 8px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ width: 8px; height: 8px; }}
QMenu::separator {{ height: 1px; background: {g['BORDER']}; margin: 4px 8px; }}
"""


def apply_mode(mode: str, font_size: int | None = None) -> None:
    """Switch the whole module to `mode` ("light"/"dark") and rebuild the QSS."""
    global MODE, FONT_SIZE, QSS, MENU_QSS
    MODE = mode if mode in PALETTES else "light"
    if font_size:
        FONT_SIZE = int(font_size)
    globals().update(PALETTES[MODE])
    QSS = _build_qss()
    MENU_QSS = _build_menu_qss()


def build_palette(mode: str | None = None):
    """A QPalette matching `mode`, so Fusion-drawn chrome and popups stay legible."""
    from PyQt6.QtGui import QColor, QPalette
    g = PALETTES.get(mode or MODE, LIGHT)
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(g["BG"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(g["TEXT"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(g["SURFACE"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(g["SURFACE_2"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(g["TEXT"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(g["SURFACE"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(g["TEXT"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(g["SURFACE"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(g["TEXT"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(g["TEXT_MUTED"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(g["ACCENT"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    disabled = QPalette.ColorGroup.Disabled
    pal.setColor(disabled, QPalette.ColorRole.Text, QColor(g["DISABLED_TEXT"]))
    pal.setColor(disabled, QPalette.ColorRole.ButtonText, QColor(g["DISABLED_TEXT"]))
    pal.setColor(disabled, QPalette.ColorRole.WindowText, QColor(g["DISABLED_TEXT"]))
    return pal


# Build the initial (light) QSS so imports have something immediately.
QSS = _build_qss()
MENU_QSS = _build_menu_qss()
