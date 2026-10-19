"""Colours, shapes and the global Qt stylesheet - a dark and a light theme. Everything is sized for fingers.

The colours are module attributes (``theme.ACCENT``…) read when something is drawn; apply()
switches them, rebuilds STYLESHEET and tells whoever listens (pictures drawn once, e.g. covers
without artwork, are drawn again).

The shape: top-left and bottom-right corners cut off at 45°, the other two square - on buttons,
cards, fields and covers alike. Qt stylesheets can only round corners, so every surface is a small
SVG drawn as a 9-slice ``border-image`` (box()); its corners never stretch, its edges do. The
highlight (controller focus) is an outline along the cut, with both cut edges lit up thicker.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Callable

THEMES = {"dark": "Dark", "light": "Light"}
DEFAULT = "dark"
# Settings -> Device -> Appearance: every text this much bigger (for reading at arm's length)
TEXT_SIZES = {"normal": ("Normal", 1.0), "large": ("Large", 1.15), "larger": ("Larger", 1.3)}
text_size = "normal"

DISPLAY_FONT = "Chakra Petch"  # titles, tabs, buttons (bundled in fonts/, SIL Open Font License)
# ... it has no symbols (⏻ ✓ ⌫ ⚙): those come from the next family that has them, not from
# whatever the system falls back to (often a small monospace one)
# (a text face right after it: without the display face no symbol font sets the lines' height)
DISPLAY_FAMILIES = [DISPLAY_FONT, "Noto Sans", "Noto Sans Symbols 2", "Noto Sans Symbols", "DejaVu Sans"]
FONTS = Path(__file__).resolve().parent / "fonts"

PALETTES = {
    "dark": {
        "BG": "#0f1013",
        "SURFACE": "#191b20",  # cards, bars
        "SURFACE_HI": "#24272e",  # buttons, fields, focused cards
        "SURFACE_HOVER": "#2d3139",
        "BORDER": "#32363f",
        "CARD_EDGE": "#191b20",  # cards need no edge on the dark background
        "TEXT": "#f1f3f6",
        "TEXT_DIM": "#8f96a4",
        "ACCENT": "#36c5ff",
        "ACCENT_HI": "#6fd6ff",
        "ACCENT_SOFT": "#0f2b3b",
        "ON_ACCENT": "#03131d",  # dark text on the bright cyan
        "FOCUS": "#ffffff",  # the ring on cyan buttons
        "DANGER": "#f55050",
        "DANGER_HI": "#ff6b6b",
        "SUCCESS": "#3ddc84",
        "ON_SUCCESS": "#03140b",
        "SCRIM": "rgba(4, 5, 8, 200)",
        "PATTERN": "#9fb4d0",  # the background's hexagons ...
        "PATTERN_ALPHA": "0.16",  # ... this strong at their strongest
    },
    "light": {
        "BG": "#e8ebf0",
        "SURFACE": "#ffffff",
        "SURFACE_HI": "#dfe3ea",
        "SURFACE_HOVER": "#d3d9e2",
        "BORDER": "#c3cad5",
        "CARD_EDGE": "#dbe0e8",
        "TEXT": "#10131a",
        "TEXT_DIM": "#566070",
        "ACCENT": "#0076c9",
        "ACCENT_HI": "#1b8ad9",
        "ACCENT_SOFT": "#d4e9f9",
        "ON_ACCENT": "#ffffff",
        "FOCUS": "#10131a",
        "DANGER": "#d8383b",
        "DANGER_HI": "#e65558",
        "SUCCESS": "#14864a",
        "ON_SUCCESS": "#ffffff",
        "SCRIM": "rgba(16, 20, 30, 130)",
        "PATTERN": "#3d5578",
        "PATTERN_ALPHA": "0.22",
    },
}

# the cut (px along each edge) and the 9-slice border it sits in - per kind of surface
CUT = {"card": 16, "button": 10, "field": 10, "key": 7, "pin": 16, "tab": 8, "cover": 10}
SLICE = {"card": 30, "button": 24, "field": 24, "key": 10, "pin": 30, "tab": 12}  # room for the glow
RING = 3  # the highlight's outline
GLOW = 6  # ... and its cut edges

current = DEFAULT
BG = SURFACE = SURFACE_HI = SURFACE_HOVER = BORDER = CARD_EDGE = TEXT = TEXT_DIM = ""
ACCENT = ACCENT_HI = ACCENT_SOFT = ON_ACCENT = FOCUS = DANGER = DANGER_HI = SUCCESS = ON_SUCCESS = SCRIM = ""
PATTERN = PATTERN_ALPHA = ""
STYLESHEET = ""
_listeners: list[Callable[[], None]] = []
_fonts_loaded = False


def _icon_folder() -> Path:
    import tempfile

    folder = Path(tempfile.gettempdir()) / "gamingcrypt-icons"
    folder.mkdir(exist_ok=True)
    return folder


def _svg_file(prefix: str, svg: str) -> str:
    """A picture for the stylesheet (Qt stylesheets need a file) - one per look, written once."""
    path = _icon_folder() / f"{prefix}-{hashlib.md5(svg.encode()).hexdigest()[:12]}.svg"
    if not path.exists():
        path.write_text(svg)
    return path.as_posix()


def _chevron(color: str) -> str:
    """The drop-down arrow, in the theme's colour."""
    return _svg_file("chevron", f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
                                f'<path d="M5 9l7 7 7-7" fill="none" stroke="{color}" stroke-width="2.6" '
                                f'stroke-linecap="square" stroke-linejoin="miter"/></svg>')


def cut_points(x: float, y: float, w: float, h: float, cut: float) -> list[tuple[float, float]]:
    """The outline: top-left and bottom-right cut off, the other corners square."""
    cut = max(0.0, min(cut, w / 2, h / 2))
    return [(x + cut, y), (x + w, y), (x + w, y + h - cut), (x + w - cut, y + h), (x, y + h), (x, y + cut)]


def cut_path(rect, cut: float):
    """cut_points() as a QPainterPath - for whatever is painted (covers, badges, pattern dots)."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath, QPolygonF

    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(px, py) for px, py in cut_points(rect.x(), rect.y(), rect.width(),
                                                                         rect.height(), cut)]))
    path.closeSubpath()
    return path


def _inset(size: float, cut: float, d: float) -> str:
    """cut_points() of a size×size square moved ``d`` inwards (where a stroke of 2·d is centred)."""
    k = cut + d * (math.sqrt(2) - 1)  # the cut edges move inwards along their own normal
    pts = [(k, d), (size - d, d), (size - d, size - k), (size - k, size - d), (d, size - d), (d, k)]
    return " ".join(f"{px:.2f},{py:.2f}" for px, py in pts)


def box(kind: str, fill: str, stroke: str | None = None, width: float = 0, glow: bool = False) -> str:
    """The stylesheet lines that draw a cut-corner surface: ``fill`` inside, an optional
    ``stroke`` along the edge, and with ``glow`` the cut edges lit up (the highlight)."""
    cut, s = CUT[kind], SLICE[kind]
    size = 2 * s + 8  # the middle 8 px stretch
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">']
    if stroke and width:
        parts.append(f'<polygon points="{_inset(size, cut, width / 2)}" fill="{fill}" stroke="{stroke}" '
                     f'stroke-width="{width}" stroke-linejoin="miter" stroke-miterlimit="4"/>')
    else:
        parts.append(f'<polygon points="{_inset(size, cut, 0)}" fill="{fill}"/>')
    if glow and stroke:
        d = GLOW / 2
        k = cut + d * (math.sqrt(2) - 1)
        arm = min(s - k - 1, cut)  # a bracket: the cut edge and a little of both sides (in the corner slice)
        for a, b, c, e in (((k + arm, d), (k, d), (d, k), (d, k + arm)),
                           ((size - k - arm, size - d), (size - k, size - d), (size - d, size - k),
                            (size - d, size - k - arm))):
            line = " ".join(f"{px:.2f},{py:.2f}" for px, py in (a, b, c, e))
            parts.append(f'<polyline points="{line}" fill="none" stroke="{stroke}" stroke-width="{GLOW}" '
                         f'stroke-linejoin="miter" stroke-linecap="butt"/>')
    parts.append("</svg>")
    path = _svg_file(kind, "".join(parts))
    return f"border-image: url({path}) {s} {s} {s} {s} stretch stretch; border-width: {s}px;"


def tab_marker(color: str, fill: str = "transparent") -> str:
    """The open tab's mark: a bar along the bottom with its ends cut like the corners (and the
    controller's box behind it, if ``fill``)."""
    s, cut = SLICE["tab"], CUT["tab"]
    size = 2 * s + 8
    bar = 4
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">']
    if fill != "transparent":
        parts.append(f'<polygon points="{_inset(size, cut, 0)}" fill="{fill}"/>')
    parts.append(f'<polygon points="{bar},{size - bar} {size},{size - bar} {size - bar},{size} 0,{size}" fill="{color}"/>')
    parts.append("</svg>")
    path = _svg_file("tab", "".join(parts))
    return f"border-image: url({path}) {s} {s} {s} {s} stretch stretch; border-width: {s}px;"


def _handle(fill: str, stroke: str | None = None) -> str:
    """The slider's knob: a small cut square."""
    size, cut = 30, 9
    edge = f' stroke="{stroke}" stroke-width="3"' if stroke else ""
    d = 1.5 if stroke else 0
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
           f'<polygon points="{_inset(size, cut, d)}" fill="{fill}"{edge}/></svg>')
    return _svg_file("knob", svg)


HEX_RADIUS = 30  # px, centre to corner
HEX_GAP = 2.5  # between neighbours: tiles, not a net
HEX_FIELD = (1400, 1000)  # the picture, anchored at the screen's bottom right
HEX_REACH = 1150  # px from that corner, where the last cells fade out


def hex_field(line: str, alpha: float, accent: str) -> str:
    """The background: flat-topped hexagons in the bottom right corner, fading out towards the
    top left (where the tabs and headers are), a few of them lit in the accent colour. Every
    cell its own opacity (Qt's SVG has no masks); the same picture every time (no randomness)."""
    w, h = HEX_FIELD
    r, step_x, step_y = HEX_RADIUS, 1.5 * HEX_RADIUS, math.sqrt(3) * HEX_RADIUS
    inner = r - HEX_GAP
    corners = [(inner * math.cos(math.radians(a)), inner * math.sin(math.radians(a))) for a in range(0, 360, 60)]
    cells = []
    for col in range(int(w / step_x) + 2):
        for row in range(int(h / step_y) + 2):
            cx = w - col * step_x  # counted from the corner: it sits the same on every screen
            cy = h - row * step_y - (step_y / 2 if col % 2 else 0)
            # an ellipse: along the bottom further than up (the tabs and headers stay calm)
            t = 1 - math.hypot((w - cx) * 0.85, (h - cy) * 1.35) / HEX_REACH
            if t <= 0:
                continue
            noise = int(hashlib.md5(f"{col},{row}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
            if noise > 0.3 + 1.4 * t:  # thinning out at the edge, not a hard circle
                continue
            points = " ".join(f"{cx + dx:.1f},{cy + dy:.1f}" for dx, dy in corners)
            strength = alpha * t ** 1.6
            if t > 0.5 and noise < 0.06:  # lit, near the corner only
                cells.append(f'<polygon points="{points}" fill="{accent}" fill-opacity="{0.03 + 0.07 * t:.3f}" '
                             f'stroke="{accent}" stroke-opacity="{0.15 + 0.3 * t:.3f}" stroke-width="1.5"/>')
            else:
                cells.append(f'<polygon points="{points}" fill="none" stroke="{line}" '
                             f'stroke-opacity="{strength:.3f}" stroke-width="1.25"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
           + "".join(cells) + "</svg>")
    return _svg_file("hexes", svg)


def load_fonts() -> None:
    """The display face (needs a running QGuiApplication; without one nothing happens)."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    from PySide6.QtGui import QFontDatabase, QGuiApplication

    if QGuiApplication.instance() is None:
        return
    for file in sorted(FONTS.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(file))
    _fonts_loaded = True


def display_font(pixels: int, weight: int = 700):
    """A QFont in the display face - for titles drawn by hand (cover initials)."""
    from PySide6.QtGui import QFont

    load_fonts()
    font = QFont()
    font.setFamilies(DISPLAY_FAMILIES)
    font.setPixelSize(pixels)
    font.setWeight(QFont.Weight(weight))
    return font


def stylesheet(c: dict) -> str:
    chevron = _chevron(c["TEXT_DIM"])
    display = "font-family: " + ", ".join(f'"{family}"' for family in DISPLAY_FAMILIES)

    def pad(kind: str, vertical: int, horizontal: int) -> str:
        """The padding that keeps the old room around the text inside the (wider) 9-slice border."""
        s = SLICE[kind]
        return f"padding: {vertical - s}px {horizontal - s}px;"

    hexes = hex_field(c["PATTERN"], float(c["PATTERN_ALPHA"]), c["ACCENT"])
    return f"""
QWidget {{
    background: transparent;  /* the hexagons show through: only whole screens paint (below) */
    color: {c['TEXT']};
    font-size: 20px;
}}
QWidget[cover="true"] {{ background: {c['BG']}; }}  /* hides what scrolls beneath it */
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 34px; font-weight: 700; {display}; }}
QLabel#subtitle {{ font-size: 20px; color: {c['TEXT_DIM']}; }}
QLabel#status {{ font-size: 19px; color: {c['TEXT_DIM']}; }}
QLabel#status[error="true"] {{ color: {c['DANGER']}; }}
QLabel#comingSoon {{ font-size: 34px; color: {c['TEXT_DIM']}; {display}; }}
QLabel#cardTitle {{ font-size: 21px; font-weight: 600; {display}; }}
QLabel#cardMeta {{ font-size: 16px; color: {c['TEXT_DIM']}; }}
QLabel#detailTitle {{ font-size: 36px; font-weight: 700; {display}; }}
QLabel#detailMeta {{ font-size: 19px; color: {c['TEXT_DIM']}; }}
QLabel#section {{ font-size: 25px; font-weight: 700; {display}; }}
QLabel#sourceTitle {{ font-size: 27px; font-weight: 700; {display}; }}

/* buttons: the focus ring's room is always there (in the 9-slice border), so focusing never moves text */
QPushButton {{
    background: transparent;
    color: {c['TEXT']};
    {box('button', c['SURFACE_HI'])}
    {pad('button', 13, 25)}
    min-height: 42px;
    font-size: 21px;
    font-weight: 600;
    {display};
}}
QPushButton:hover {{ {box('button', c['SURFACE_HOVER'])} }}
QPushButton:pressed, QPushButton:checked {{ {box('button', c['ACCENT'])} color: {c['ON_ACCENT']}; }}
QPushButton:disabled {{ color: {c['TEXT_DIM']}; {box('button', c['SURFACE'])} }}
QPushButton:focus {{ {box('button', c['SURFACE_HI'], c['ACCENT'], RING, glow=True)} }}
QPushButton:checked:focus {{ {box('button', c['ACCENT'], c['FOCUS'], RING, glow=True)} }}
QPushButton#primary {{ {box('button', c['ACCENT'])} color: {c['ON_ACCENT']}; font-weight: 700; }}
QPushButton#primary:hover, QPushButton#primary:pressed {{ {box('button', c['ACCENT_HI'])} }}
QPushButton#primary:focus {{ {box('button', c['ACCENT_HI'], c['FOCUS'], RING, glow=True)} }}
QPushButton#danger {{ {box('button', c['DANGER'])} color: #ffffff; font-weight: 700; }}
QPushButton#danger:hover, QPushButton#danger:pressed {{ {box('button', c['DANGER_HI'])} }}
QPushButton#danger:focus {{ {box('button', c['DANGER_HI'], c['FOCUS'], RING, glow=True)} }}
QPushButton#key {{ {box('key', c['SURFACE_HI'])} {pad('key', 5, 5)} min-height: 52px; min-width: 52px;
                   font-size: 22px; font-weight: 500; }}
QPushButton#key:hover {{ {box('key', c['SURFACE_HOVER'])} }}
QPushButton#key:pressed, QPushButton#key:checked {{ {box('key', c['ACCENT'])} }}
QPushButton#key:focus {{ {box('key', c['SURFACE_HI'], c['ACCENT'], RING)} }}
QPushButton#key:checked:focus {{ {box('key', c['ACCENT'], c['FOCUS'], RING)} }}
QPushButton#key[current="true"] {{ {box('key', c['SURFACE_HI'], c['ACCENT'], RING)} }}
QPushButton#key[current="true"]:checked {{ {box('key', c['ACCENT'], c['FOCUS'], RING)} }}
QPushButton#pinKey {{ {box('pin', c['SURFACE_HI'])} {pad('pin', 13, 25)} min-height: 72px; min-width: 96px;
                      font-size: 32px; font-weight: 500; }}
QPushButton#pinKey:hover {{ {box('pin', c['SURFACE_HOVER'])} }}
QPushButton#pinKey:pressed {{ {box('pin', c['ACCENT'])} color: {c['ON_ACCENT']}; }}
QPushButton#pinKey:focus {{ {box('pin', c['SURFACE_HI'], c['ACCENT'], RING, glow=True)} }}

/* tabs: the open one marked with a bar, the controller's one a box */
QPushButton#tab {{
    {box('tab', 'transparent')}
    {pad('tab', 16, 20)}
    padding-bottom: {19 - SLICE['tab']}px;
    font-size: 22px;
    font-weight: 500;
    color: {c['TEXT_DIM']};
}}
QPushButton#tab:hover {{ color: {c['TEXT']}; }}
QPushButton#tab:checked {{ color: {c['TEXT']}; font-weight: 700; {tab_marker(c['ACCENT'])} }}
QPushButton#tab:focus {{ {box('tab', c['SURFACE_HI'])} color: {c['TEXT']};
                         /* no bar: the highlight must not look like the open tab */ }}
QPushButton#tab:checked:focus {{ {tab_marker(c['ACCENT'], c['SURFACE_HI'])} }}

QLineEdit, QComboBox {{
    background: transparent;
    color: {c['TEXT']};
    {box('field', c['SURFACE'], c['BORDER'], 2)}
    {pad('field', 12, 18)}
    min-height: 42px;
    font-size: 21px;
    selection-background-color: {c['ACCENT']};
    selection-color: {c['ON_ACCENT']};
}}
QLineEdit:focus, QComboBox:focus {{ {box('field', c['SURFACE'], c['ACCENT'], 2, glow=True)} }}
QComboBox:hover {{ {box('field', c['SURFACE_HI'], c['BORDER'], 2)} }}
QComboBox:hover:focus {{ {box('field', c['SURFACE_HI'], c['ACCENT'], 2, glow=True)} }}
QComboBox::drop-down {{ border: none; width: 44px; background: transparent; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 22px; height: 22px; }}
QComboBox QAbstractItemView, QListView#comboList {{
    background: {c['SURFACE']};
    color: {c['TEXT']};
    border: 2px solid {c['BORDER']};
    border-top: 3px solid {c['ACCENT']};
    border-radius: 0;
    padding: 6px;
    outline: none;
    selection-background-color: {c['ACCENT']};
    selection-color: {c['ON_ACCENT']};
    font-size: 21px;
}}
QComboBox QAbstractItemView::item, QListView#comboList::item {{ min-height: 52px; padding: 0 12px; border-radius: 0; }}
QListView#comboList::item:hover {{ background: {c['SURFACE_HOVER']}; }}
QListView#comboList::item:selected {{ background: {c['ACCENT']}; color: {c['ON_ACCENT']}; }}

QSlider {{ min-height: 48px; background: transparent; }}
QSlider::groove:horizontal {{ height: 6px; background: {c['SURFACE_HOVER']}; border-radius: 0; }}
QSlider::sub-page:horizontal {{ background: {c['ACCENT']}; border-radius: 0; }}
QSlider::handle:horizontal {{
    image: url({_handle(c['TEXT'])}); width: 30px; height: 30px; margin: -12px 0; background: transparent;
}}
QSlider:focus {{ {box('field', c['ACCENT_SOFT'], c['ACCENT'], RING)} padding: {3 - SLICE['field']}px; }}
QSlider::handle:horizontal:focus {{ image: url({_handle(c['ACCENT'], c['FOCUS'])}); }}
QProgressBar {{ background: {c['SURFACE_HI']}; border: none; border-radius: 0; max-height: 10px; }}
QProgressBar::chunk {{ background: {c['ACCENT']}; border-radius: 0; }}

/* cards: games, libraries, settings sections - the focus ring is the card's edge */
QFrame#card {{ background: transparent; {box('card', c['SURFACE'], c['CARD_EDGE'], 3)}
               padding: {3 - SLICE['card']}px; }}
QFrame#card:hover {{ {box('card', c['SURFACE_HI'], c['CARD_EDGE'], 3)} }}
QFrame#card:focus {{ {box('card', c['SURFACE_HI'], c['ACCENT'], RING, glow=True)} }}

QFrame#topBar {{ background: {c['SURFACE']}; border-bottom: 1px solid {c['BORDER']}; }}
QWidget#menuRow {{ background: transparent; }}
QLabel#hintBar {{ background: {c['SURFACE']}; color: {c['TEXT_DIM']}; font-size: 17px; padding: 8px 24px;
                  border-top: 1px solid {c['BORDER']}; }}
QLabel#battery {{ font-size: 20px; padding: 0 14px; color: {c['TEXT_DIM']}; {display}; font-weight: 500; }}
QLabel#battery[charging="true"] {{ color: {c['SUCCESS']}; }}
QLabel#battery[low="true"] {{ color: {c['DANGER']}; font-weight: 700; }}
QLabel#healthOk {{ color: {c['SUCCESS']}; font-size: 24px; font-weight: 700; }}
QLabel#healthBad {{ color: {c['DANGER']}; font-size: 24px; font-weight: 700; }}
QLabel#healthOptional {{ color: {c['TEXT_DIM']}; font-size: 24px; font-weight: 700; }}

/* whole screens: the colour and the hexagons (everything on them is transparent) */
MainWindow, LaunchOverlay, LockScreen, AuthSetupWizard, ControlsPage, BluetoothPage, SaveStatesPage {{
    background-color: {c['BG']};
    background-image: url({hexes});
    background-repeat: no-repeat;
    background-position: bottom right;
}}
QuickMenu, PowerMenu, BatteryWarning, DisplayConfirm, _Overlay {{ background: {c['SCRIM']}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ width: 6px; background: transparent; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: {c['BORDER']}; border-radius: 0; min-height: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: {c['SURFACE_HI']}; color: {c['TEXT']}; border: 1px solid {c['BORDER']};
            border-left: 3px solid {c['ACCENT']}; padding: 6px; }}
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
        load_fonts()
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
