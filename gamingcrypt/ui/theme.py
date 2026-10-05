"""Colors and the global Qt stylesheet. Everything is sized for fingers."""

BG = "#0f1117"
SURFACE = "#1a1d27"
SURFACE_HI = "#252a38"
TEXT = "#e8eaf0"
TEXT_DIM = "#8b90a0"
ACCENT = "#4f8cff"
ACCENT_HI = "#6fa0ff"
DANGER = "#e5484d"
SUCCESS = "#3fb950"

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 20px;
}}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 40px; font-weight: 700; }}
QLabel#subtitle {{ font-size: 22px; color: {TEXT_DIM}; }}
QLabel#status {{ font-size: 20px; color: {TEXT_DIM}; }}
QLabel#status[error="true"] {{ color: {DANGER}; }}
QLabel#comingSoon {{ font-size: 36px; color: {TEXT_DIM}; }}
QLabel#cardTitle {{ font-size: 22px; font-weight: 600; }}
QLabel#cardMeta {{ font-size: 16px; color: {TEXT_DIM}; }}
QLabel#detailTitle {{ font-size: 36px; font-weight: 700; }}
QLabel#detailMeta {{ font-size: 20px; color: {TEXT_DIM}; }}
QPushButton {{
    background: {SURFACE_HI};
    border: none;
    border-radius: 14px;
    padding: 14px 26px;
    min-height: 40px;
    font-size: 22px;
}}
QPushButton:pressed {{ background: {ACCENT}; }}
QPushButton:checked {{ background: {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; background: {SURFACE}; }}
QPushButton#primary {{ background: {ACCENT}; font-weight: 700; }}
QPushButton#primary:pressed {{ background: {ACCENT_HI}; }}
QPushButton#danger {{ background: {DANGER}; font-weight: 700; }}
QPushButton#key {{ padding: 6px; min-height: 52px; min-width: 52px; font-size: 22px; }}
QPushButton#pinKey {{ min-height: 72px; min-width: 96px; font-size: 32px; border-radius: 40px; }}
QPushButton#tab {{
    background: transparent;
    border-radius: 0;
    border-bottom: 4px solid transparent;
    padding: 18px 22px;
    font-size: 24px;
    color: {TEXT_DIM};
}}
QPushButton#tab:checked {{ color: {TEXT}; border-bottom: 4px solid {ACCENT}; }}
QLineEdit, QComboBox {{
    background: {SURFACE};
    border: 2px solid {SURFACE_HI};
    border-radius: 14px;
    padding: 12px 18px;
    min-height: 40px;
    font-size: 24px;
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    selection-background-color: {ACCENT};
    font-size: 24px;
}}
QComboBox QAbstractItemView::item {{ min-height: 56px; }}
QSlider {{ min-height: 48px; background: transparent; }}
QSlider::groove:horizontal {{ height: 10px; background: {SURFACE_HI}; border-radius: 5px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 5px; }}
QSlider::handle:horizontal {{
    background: {TEXT}; width: 36px; height: 36px; margin: -13px 0; border-radius: 18px;
}}
QProgressBar {{ background: {SURFACE_HI}; border: none; border-radius: 6px; max-height: 12px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}
QLabel#section {{ font-size: 28px; font-weight: 700; }}
QFrame#card {{ background: {SURFACE}; border-radius: 18px; border: 3px solid transparent; }}
QFrame#card:focus {{ border: 3px solid {ACCENT}; background: {SURFACE_HI}; }}
QPushButton:focus {{ border: 4px solid {TEXT}; }}
QPushButton#primary:focus {{ background: {ACCENT_HI}; border: 4px solid {TEXT}; }}
QPushButton#danger:focus {{ background: #ff6b6f; border: 4px solid {TEXT}; }}
/* Controller highlight on a tab: a box, never the underline - the underline only marks the open tab */
QPushButton#tab:focus {{ background: {SURFACE_HI}; border: none; border-bottom: 4px solid transparent; color: {TEXT}; }}
QPushButton#tab:checked:focus {{ border-bottom: 4px solid {ACCENT}; }}
QComboBox:focus {{ border-color: {ACCENT}; }}
/* Controller highlight on a slider: frame + blue knob - grey on grey wasn't visible on a card */
QSlider:focus {{ background: {SURFACE_HI}; border: 3px solid {ACCENT}; border-radius: 12px; }}
QSlider::handle:horizontal:focus {{ background: {ACCENT_HI}; border: 3px solid {TEXT}; }}
QFrame#card:hover {{ background: {SURFACE_HI}; }}
QFrame#topBar {{ background: {SURFACE}; }}
QWidget#menuRow {{ background: transparent; }}
QLabel#battery {{ font-size: 22px; padding: 0 14px; color: {TEXT_DIM}; }}
QLabel#battery[charging="true"] {{ color: {SUCCESS}; }}
QLabel#battery[low="true"] {{ color: {DANGER}; font-weight: 700; }}
QLabel#sourceTitle {{ font-size: 30px; font-weight: 700; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ width: 8px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {SURFACE_HI}; border-radius: 4px; min-height: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""
