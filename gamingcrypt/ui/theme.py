"""Colours and the global Qt stylesheet - a dark and a light theme. Everything is sized for fingers.

The colours are module attributes (``theme.ACCENT``…) read when something is drawn; apply()
switches them, rebuilds STYLESHEET and tells whoever listens (pictures drawn once, e.g. covers
without artwork, are drawn again).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

THEMES = {"dark": "Dark", "light": "Light"}
DEFAULT = "dark"
# Settings -> Device -> Appearance: every text this much bigger (for reading at arm's length)
TEXT_SIZES = {"normal": ("Normal", 1.0), "large": ("Large", 1.15), "larger": ("Larger", 1.3)}
text_size = "normal"

PALETTES = {
    "dark": {
        "BG": "#0e1016",
        "SURFACE": "#181b23",  # cards, bars
        "SURFACE_HI": "#232733",  # buttons, fields, focused cards
        "SURFACE_HOVER": "#2c3140",
        "BORDER": "#2c313d",
        "CARD_EDGE": "#181b23",  # cards need no edge on the dark background
        "TEXT": "#eef0f5",
        "TEXT_DIM": "#959cab",
        "ACCENT": "#4f8cff",
        "ACCENT_HI": "#6f9fff",
        "ACCENT_SOFT": "#1f2c48",
        "ON_ACCENT": "#ffffff",
        "FOCUS": "#ffffff",  # the ring on blue buttons
        "DANGER": "#e5484d",
        "DANGER_HI": "#f06367",
        "SUCCESS": "#3fb950",
        "SCRIM": "rgba(5, 7, 12, 190)",
    },
    "light": {
        "BG": "#eef0f4",
        "SURFACE": "#ffffff",
        "SURFACE_HI": "#e6e9f0",
        "SURFACE_HOVER": "#dce1ea",
        "BORDER": "#d3d8e1",
        "CARD_EDGE": "#e1e5ec",
        "TEXT": "#161922",
        "TEXT_DIM": "#5c6474",
        "ACCENT": "#2f6fec",
        "ACCENT_HI": "#4a82f0",
        "ACCENT_SOFT": "#dce7fd",
        "ON_ACCENT": "#ffffff",
        "FOCUS": "#161922",
        "DANGER": "#d63a40",
        "DANGER_HI": "#e4575c",
        "SUCCESS": "#1e9b4b",
        "SCRIM": "rgba(20, 24, 34, 120)",
    },
}

current = DEFAULT
BG = SURFACE = SURFACE_HI = SURFACE_HOVER = BORDER = CARD_EDGE = TEXT = TEXT_DIM = ""
ACCENT = ACCENT_HI = ACCENT_SOFT = ON_ACCENT = FOCUS = DANGER = DANGER_HI = SUCCESS = SCRIM = ""
STYLESHEET = ""
_listeners: list[Callable[[], None]] = []


def _chevron(color: str) -> str:
    """The drop-down arrow, in the theme's colour (Qt stylesheets need a file)."""
    import tempfile

    folder = Path(tempfile.gettempdir()) / "gamingcrypt-icons"
    folder.mkdir(exist_ok=True)
    path = folder / f"chevron-{color.lstrip('#')}.svg"
    if not path.exists():
        path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
                        f'<path d="M6 9l6 6 6-6" fill="none" stroke="{color}" stroke-width="2.6" '
                        f'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return path.as_posix()


def stylesheet(c: dict) -> str:
    chevron = _chevron(c["TEXT_DIM"])
    return f"""
QWidget {{
    background: {c['BG']};
    color: {c['TEXT']};
    font-size: 20px;
}}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 34px; font-weight: 700; }}
QLabel#subtitle {{ font-size: 20px; color: {c['TEXT_DIM']}; }}
QLabel#status {{ font-size: 19px; color: {c['TEXT_DIM']}; }}
QLabel#status[error="true"] {{ color: {c['DANGER']}; }}
QLabel#comingSoon {{ font-size: 34px; color: {c['TEXT_DIM']}; }}
QLabel#cardTitle {{ font-size: 20px; font-weight: 600; }}
QLabel#cardMeta {{ font-size: 16px; color: {c['TEXT_DIM']}; }}
QLabel#detailTitle {{ font-size: 34px; font-weight: 700; }}
QLabel#detailMeta {{ font-size: 19px; color: {c['TEXT_DIM']}; }}
QLabel#section {{ font-size: 24px; font-weight: 700; }}
QLabel#sourceTitle {{ font-size: 26px; font-weight: 700; }}

/* buttons: the focus ring's room is always there (transparent), so focusing never moves text */
QPushButton {{
    background: {c['SURFACE_HI']};
    color: {c['TEXT']};
    border: 3px solid transparent;
    border-radius: 14px;
    padding: 10px 22px;
    min-height: 42px;
    font-size: 21px;
}}
QPushButton:hover {{ background: {c['SURFACE_HOVER']}; }}
QPushButton:pressed, QPushButton:checked {{ background: {c['ACCENT']}; color: {c['ON_ACCENT']}; }}
QPushButton:disabled {{ color: {c['TEXT_DIM']}; background: {c['SURFACE']}; }}
QPushButton:focus {{ border-color: {c['ACCENT']}; }}
QPushButton:checked:focus {{ border-color: {c['FOCUS']}; }}
QPushButton#primary {{ background: {c['ACCENT']}; color: {c['ON_ACCENT']}; font-weight: 700; }}
QPushButton#primary:hover, QPushButton#primary:pressed {{ background: {c['ACCENT_HI']}; }}
QPushButton#primary:focus {{ background: {c['ACCENT_HI']}; border-color: {c['FOCUS']}; }}
QPushButton#danger {{ background: {c['DANGER']}; color: {c['ON_ACCENT']}; font-weight: 700; }}
QPushButton#danger:hover, QPushButton#danger:pressed {{ background: {c['DANGER_HI']}; }}
QPushButton#danger:focus {{ background: {c['DANGER_HI']}; border-color: {c['FOCUS']}; }}
QPushButton#key {{ padding: 2px; min-height: 52px; min-width: 52px; font-size: 22px; border-radius: 12px; }}
QPushButton#pinKey {{ min-height: 72px; min-width: 96px; font-size: 32px; border-radius: 40px; }}

/* tabs: the open one underlined, the controller's one a soft box */
QPushButton#tab {{
    background: transparent;
    border: none;
    border-radius: 0;
    border-bottom: 3px solid transparent;
    padding: 16px 20px;
    font-size: 22px;
    color: {c['TEXT_DIM']};
}}
QPushButton#tab:hover {{ color: {c['TEXT']}; }}
QPushButton#tab:checked {{ color: {c['TEXT']}; font-weight: 600; border-bottom: 3px solid {c['ACCENT']}; }}
QPushButton#tab:focus {{ background: {c['SURFACE_HI']}; color: {c['TEXT']}; border-radius: 12px;
                         border-bottom: 3px solid transparent; }}
QPushButton#tab:checked:focus {{ border-radius: 12px; border-bottom: 3px solid {c['ACCENT']}; }}

QLineEdit, QComboBox {{
    background: {c['SURFACE']};
    color: {c['TEXT']};
    border: 2px solid {c['BORDER']};
    border-radius: 14px;
    padding: 10px 16px;
    min-height: 42px;
    font-size: 21px;
    selection-background-color: {c['ACCENT']};
    selection-color: {c['ON_ACCENT']};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {c['ACCENT']}; }}
QComboBox:hover {{ background: {c['SURFACE_HI']}; }}
QComboBox::drop-down {{ border: none; width: 44px; background: transparent; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 22px; height: 22px; }}
QComboBox QAbstractItemView {{
    background: {c['SURFACE']};
    color: {c['TEXT']};
    border: 2px solid {c['BORDER']};
    border-radius: 12px;
    padding: 6px;
    outline: none;
    selection-background-color: {c['ACCENT']};
    selection-color: {c['ON_ACCENT']};
    font-size: 21px;
}}
QComboBox QAbstractItemView::item {{ min-height: 52px; padding: 0 12px; border-radius: 10px; }}

QSlider {{ min-height: 48px; background: transparent; }}
QSlider::groove:horizontal {{ height: 8px; background: {c['SURFACE_HI']}; border-radius: 4px; }}
QSlider::sub-page:horizontal {{ background: {c['ACCENT']}; border-radius: 4px; }}
QSlider::handle:horizontal {{
    background: {c['TEXT']}; width: 32px; height: 32px; margin: -12px 0; border-radius: 16px;
}}
QSlider:focus {{ background: {c['ACCENT_SOFT']}; border: 3px solid {c['ACCENT']}; border-radius: 14px; }}
QSlider::handle:horizontal:focus {{ background: {c['ACCENT']}; border: 3px solid {c['FOCUS']}; }}
QProgressBar {{ background: {c['SURFACE_HI']}; border: none; border-radius: 5px; max-height: 10px; }}
QProgressBar::chunk {{ background: {c['ACCENT']}; border-radius: 5px; }}

/* cards: games, libraries, settings sections - the focus ring is the card's edge */
QFrame#card {{ background: {c['SURFACE']}; border-radius: 18px; border: 3px solid {c['CARD_EDGE']}; }}
QFrame#card:hover {{ background: {c['SURFACE_HI']}; }}
QFrame#card:focus {{ border: 3px solid {c['ACCENT']}; background: {c['SURFACE_HI']}; }}

QFrame#topBar {{ background: {c['SURFACE']}; border-bottom: 1px solid {c['BORDER']}; }}
QWidget#menuRow {{ background: transparent; }}
QLabel#hintBar {{ background: {c['SURFACE']}; color: {c['TEXT_DIM']}; font-size: 17px; padding: 8px 24px;
                  border-top: 1px solid {c['BORDER']}; }}
QLabel#battery {{ font-size: 20px; padding: 0 14px; color: {c['TEXT_DIM']}; }}
QLabel#battery[charging="true"] {{ color: {c['SUCCESS']}; }}
QLabel#battery[low="true"] {{ color: {c['DANGER']}; font-weight: 700; }}
QLabel#healthOk {{ color: {c['SUCCESS']}; font-size: 24px; font-weight: 700; }}
QLabel#healthBad {{ color: {c['DANGER']}; font-size: 24px; font-weight: 700; }}
QLabel#healthOptional {{ color: {c['TEXT_DIM']}; font-size: 24px; font-weight: 700; }}

/* full-screen layers */
LaunchOverlay, LockScreen, ControlsPage {{ background: {c['BG']}; }}
QuickMenu, PowerMenu, BatteryWarning, DisplayConfirm, _Overlay {{ background: {c['SCRIM']}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ width: 8px; background: transparent; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: {c['BORDER']}; border-radius: 4px; min-height: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: {c['SURFACE_HI']}; color: {c['TEXT']}; border: 1px solid {c['BORDER']}; padding: 6px; }}
"""


FIXED_SIZE = ("QPushButton#tab",)  # the tab rows: short words, and they must fit the screen's width


def scaled(sheet: str, factor: float) -> str:
    """Every font size in the stylesheet times ``factor`` (but the tab rows')."""
    import re

    if factor == 1.0:
        return sheet

    def rule(match: re.Match) -> str:
        text = match.group(0)
        selector = text.split("{")[0].split("*/")[-1].strip()  # (after a comment in front of it)
        if selector.startswith(FIXED_SIZE):
            return text
        return re.sub(r"font-size: (\d+)px", lambda m: f"font-size: {round(int(m.group(1)) * factor)}px", text)

    return re.sub(r"[^{}]*\{[^{}]*\}", rule, sheet)  # rule by rule: selector { … }


def apply(name: str, app=None, size: str | None = None) -> str:
    """Switch to a theme ("dark" / "light") - and a text size (TEXT_SIZES), if given; with
    ``app``, its stylesheet too. The name used."""
    global current, STYLESHEET, text_size
    name = name if name in PALETTES else DEFAULT
    current = name
    if size is not None:
        text_size = size if size in TEXT_SIZES else "normal"
    globals().update(PALETTES[name])
    STYLESHEET = scaled(stylesheet(PALETTES[name]), TEXT_SIZES[text_size][1])
    if app is not None:
        app.setStyleSheet(STYLESHEET)
    for listener in list(_listeners):
        try:
            listener()
        except RuntimeError:  # its widget is gone
            _listeners.remove(listener)
    return name


def on_change(listener: Callable[[], None]) -> None:
    _listeners.append(listener)


def from_config(config: dict) -> str:
    return (config.get("appearance") or {}).get("theme") or DEFAULT


def size_from_config(config: dict) -> str:
    return (config.get("appearance") or {}).get("text_size") or "normal"


apply(DEFAULT)
