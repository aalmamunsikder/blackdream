"""Two glass themes and the rules both of them keep.

The window is a translucent sheet floating over a painted pastel backdrop; depth is
a white border and a background step, not a drop shadow. ``QGraphicsDropShadowEffect``
renders its whole subtree into an offscreen pixmap on every repaint, which is exactly
the wrong trade for a window whose log pane redraws while a build streams.

The engine log is deliberately identical in both themes: it is a console surface
inside a GUI, and keeping it dark makes engine output unmistakable no matter which
theme the chrome is wearing.

Every colour used by QSS lives here as a finished QSS value (``rgba(...)`` included),
so a palette can be handed to a painter as well as to a stylesheet.
"""

from __future__ import annotations

import re
from string import Template

from PySide6.QtGui import QColor

_LIGHT_BLOBS = (
    (0.02, 0.02, 0.55, "#6f8ff0", 235),
    (0.92, 0.00, 0.50, "#f59ac0", 215),
    (0.98, 0.95, 0.55, "#f7b26a", 225),
    (0.00, 0.92, 0.55, "#5fc8e8", 210),
    (0.55, 0.45, 0.60, "#b79cf0", 120),
)

_DARK_BLOBS = (
    (0.02, 0.02, 0.55, "#2e4ea8", 210),
    (0.92, 0.00, 0.50, "#6b2f5e", 180),
    (0.98, 0.95, 0.55, "#7a4322", 170),
    (0.00, 0.92, 0.55, "#14506b", 180),
    (0.55, 0.45, 0.60, "#3d2f74", 150),
)

LIGHT = {
    "bgTop": "#a9bcf5",
    "bgMid": "#e9defb",
    "bgBottom": "#f4cbd6",
    "blobs": _LIGHT_BLOBS,
    "shellBg": "rgba(255,255,255,158)",
    "shellBorder": "rgba(255,255,255,226)",
    "sidebarBg": "rgba(255,255,255,120)",
    "sidebarBorder": "rgba(255,255,255,196)",
    "cardBg": "rgba(255,255,255,190)",
    "cardBorder": "rgba(255,255,255,228)",
    "pathRowBg": "rgba(255,255,255,152)",
    "fieldBg": "rgba(255,255,255,150)",
    "fieldBorder": "rgba(148,163,196,92)",
    "buttonBg": "rgba(255,255,255,168)",
    "buttonHoverBg": "rgba(255,255,255,236)",
    "menuBg": "#ffffff",
    "text": "#1c2233",
    "muted": "#66708a",
    "faint": "#8b93a8",
    "accent": "#2563eb",
    "accentSoft": "#3b82f6",
    "accentDeep": "#4338ca",
    "navHover": "rgba(255,255,255,156)",
    "selection": "rgba(79,142,247,58)",
    "rowHover": "rgba(255,255,255,120)",
    "rowAlt": "rgba(255,255,255,72)",
    "grid": "rgba(120,140,180,40)",
    "groove": "rgba(120,140,180,60)",
    "scrollHandle": "rgba(126,139,166,110)",
    "ok": "#15803d",
    "okBg": "rgba(22,163,74,30)",
    "okBorder": "rgba(22,163,74,76)",
    "warn": "#b45309",
    "warnBg": "rgba(245,158,11,34)",
    "warnBorder": "rgba(245,158,11,92)",
    "fail": "#b91c1c",
    "failBg": "rgba(239,68,68,30)",
    "failBorder": "rgba(239,68,68,80)",
    "unknown": "#6b7280",
    "unknownBg": "rgba(107,114,128,26)",
    "unknownBorder": "rgba(107,114,128,64)",
    "tileIcon": "#3b6ef6",
    "tileBg": "rgba(59,110,246,26)",
    "taskBg": "rgba(244,247,255,180)",
    "taskBorder": "rgba(255,255,255,228)",
    "metricBg": "rgba(255,255,255,150)",
    "errorBg": "rgba(254,226,226,218)",
    "errorFg": "#8c1d24",
    "errorBorder": "rgba(239,68,68,120)",
    "errorCode": "#9a666c",
    "logBg": "#101319",
    "logFg": "#d8dbe4",
    "logMuted": "#7d8496",
    "logBorder": "rgba(255,255,255,26)",
    "logSelection": "rgba(96,130,214,120)",
    "shadow": "rgba(30,40,70,40)",
}

DARK = {
    "bgTop": "#141a2c",
    "bgMid": "#1d1b33",
    "bgBottom": "#2a1c2a",
    "blobs": _DARK_BLOBS,
    "shellBg": "rgba(20,24,38,188)",
    "shellBorder": "rgba(255,255,255,26)",
    "sidebarBg": "rgba(15,19,30,150)",
    "sidebarBorder": "rgba(255,255,255,22)",
    "cardBg": "rgba(31,37,55,196)",
    "cardBorder": "rgba(255,255,255,26)",
    "pathRowBg": "rgba(12,16,26,110)",
    "fieldBg": "rgba(12,16,26,120)",
    "fieldBorder": "rgba(255,255,255,34)",
    "buttonBg": "rgba(255,255,255,18)",
    "buttonHoverBg": "rgba(255,255,255,34)",
    "menuBg": "#232a3c",
    "text": "#e8ebf4",
    "muted": "#9aa3b8",
    "faint": "#7c8498",
    "accent": "#8db4ff",
    "accentSoft": "#4f8ef7",
    "accentDeep": "#4338ca",
    "navHover": "rgba(255,255,255,22)",
    "selection": "rgba(80,130,246,84)",
    "rowHover": "rgba(255,255,255,14)",
    "rowAlt": "rgba(255,255,255,6)",
    "grid": "rgba(255,255,255,22)",
    "groove": "rgba(255,255,255,30)",
    "scrollHandle": "rgba(255,255,255,40)",
    "ok": "#8fd6a4",
    "okBg": "rgba(45,138,82,48)",
    "okBorder": "rgba(90,190,125,80)",
    "warn": "#f0c274",
    "warnBg": "rgba(196,138,38,44)",
    "warnBorder": "rgba(235,180,90,80)",
    "fail": "#f2a0a8",
    "failBg": "rgba(190,58,72,52)",
    "failBorder": "rgba(240,120,132,90)",
    "unknown": "#a3a9b8",
    "unknownBg": "rgba(255,255,255,20)",
    "unknownBorder": "rgba(255,255,255,36)",
    "tileIcon": "#9dbcff",
    "tileBg": "rgba(100,140,255,36)",
    "taskBg": "rgba(255,255,255,14)",
    "taskBorder": "rgba(255,255,255,26)",
    "metricBg": "rgba(255,255,255,12)",
    "errorBg": "rgba(74,28,34,222)",
    "errorFg": "#f2b0b6",
    "errorBorder": "rgba(240,120,132,90)",
    "errorCode": "#c88a90",
    "logBg": "#0d1016",
    "logFg": "#d8dbe4",
    "logMuted": "#7d8496",
    "logBorder": "rgba(255,255,255,22)",
    "logSelection": "rgba(96,130,214,120)",
    "shadow": "rgba(0,0,0,90)",
}

_QSS = Template("""
QWidget {
    color: $text;
    font-size: 13px;
}
QMainWindow { background: transparent; }
QDialog { background: $menuBg; }

QLabel { color: $text; }
QLabel#pageTitle { font-size: 29px; font-weight: 800; }
QLabel#pageSubtitle { color: $muted; font-size: 13px; }
QLabel#brand { font-size: 18px; font-weight: 800; }
QLabel#brandHint { color: $muted; font-size: 11px; }
QLabel#cardTitle { font-size: 15px; font-weight: 700; }
QLabel#cardHint { color: $muted; font-size: 12px; }
QLabel#emptyNote { color: $muted; font-size: 12px; }
QLabel#summary {
    background: $okBg; color: $ok; border: 1px solid $okBorder;
    border-radius: 12px; padding: 10px 12px;
    font-size: 13px; font-weight: 600;
}
QLabel#summary[state="empty"] {
    background: $fieldBg; color: $muted; border-color: $fieldBorder;
    font-weight: 500;
}
QLabel#summary[state="error"] {
    background: $errorBg; color: $errorFg; border-color: $errorBorder;
    font-weight: 600;
}
QLabel#summaryNote { color: $muted; font-size: 11px; }
QLabel#pathLabel { color: $muted; font-size: 10px; font-weight: 600; }
QLabel#numberBadge {
    background: $tileBg; color: $tileIcon; border-radius: 10px;
    font-size: 11px; font-weight: 800;
}
QLabel#dialogTitle { font-size: 20px; font-weight: 800; }
QLabel#dialogBody { color: $text; font-size: 12px; }
QLabel#dialogMuted { color: $muted; font-size: 11px; }
QLabel#aboutVersion { font-size: 18px; font-weight: 800; }
QLabel#rowTitle { font-size: 13px; font-weight: 700; }
QLabel#rowBody { color: $muted; font-size: 12px; }
QLabel#errorCard {
    background: $errorBg; color: $errorFg; border: 1px solid $errorBorder;
    border-radius: 14px; padding: 13px 16px;
}
QLabel#fieldState { background: transparent; }
QLabel#badge {
    border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 700;
    background: $unknownBg; color: $unknown; border: 1px solid $unknownBorder;
}
QLabel#badge[state="supported"] { background: $okBg; color: $ok; border-color: $okBorder; }
QLabel#badge[state="limited"] { background: $warnBg; color: $warn; border-color: $warnBorder; }
QLabel#badge[state="unsupported"] { background: $failBg; color: $fail; border-color: $failBorder; }
QLabel#badge[state="unknown"] { background: $unknownBg; color: $unknown; border-color: $unknownBorder; }
QLabel#kbd {
    color: $faint; background: $fieldBg; border: 1px solid $fieldBorder;
    border-radius: 5px; padding: 1px 5px; font-size: 10px;
}
QLabel#stepLabel { color: $muted; font-size: 12px; font-weight: 600; }
QLabel#percent { font-size: 17px; font-weight: 800; }
QLabel#detailKey { color: $muted; font-size: 11px; font-weight: 600; }
QLabel#detailValue { font-size: 12px; font-weight: 600; }
QLabel#detailRecommendation { font-size: 12px; font-weight: 500; }
QLabel#detailRecommendation[state="supported"] { color: $ok; }
QLabel#detailRecommendation[state="limited"] { color: $warn; }
QLabel#detailRecommendation[state="unsupported"] { color: $fail; }
QLabel#taskTitle { color: $muted; font-size: 10px; font-weight: 700; }
QLabel#taskName { font-size: 13px; font-weight: 800; }
QLabel#taskDetail { color: $muted; font-size: 11px; }
QLabel#metricLabel { color: $muted; font-size: 10px; }
QLabel#metricValue { font-size: 13px; font-weight: 700; }
QLabel#stageName { font-size: 12px; font-weight: 500; }
QLabel#stageName[state="pending"] { color: $muted; font-weight: 400; }
QLabel#stageName[state="running"] { font-weight: 700; }
QLabel#stageName[state="failed"] { color: $fail; }
QLabel#stageName[state="cancelled"] { color: $muted; }
QLabel#stageTime { color: $faint; font-size: 11px; }

QFrame#shell {
    background: $shellBg;
    border: 1px solid $shellBorder;
    border-radius: 26px;
}
QFrame#sidebar {
    background: $sidebarBg;
    border: 1px solid $sidebarBorder;
    border-radius: 20px;
}
QFrame#card {
    background: $cardBg;
    border: 1px solid $cardBorder;
    border-radius: 18px;
}
QFrame#pathRow {
    background: $pathRowBg;
    border: 1px solid $cardBorder;
    border-radius: 12px;
}
QFrame#searchPill {
    background: $fieldBg;
    border: 1px solid $fieldBorder;
    border-radius: 19px;
}
QFrame#taskCard {
    background: $taskBg;
    border: 1px solid $taskBorder;
    border-radius: 12px;
}
QFrame#metric {
    background: $metricBg;
    border: 1px solid $cardBorder;
    border-radius: 10px;
}
QFrame#header { background: transparent; }

QPushButton {
    background: $buttonBg; color: $text;
    border: 1px solid $fieldBorder; border-radius: 10px; padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover { background: $buttonHoverBg; border-color: $accentSoft; }
QPushButton:pressed { background: $selection; }
QPushButton:disabled { color: $faint; background: transparent; border-color: $grid; }
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 $accentSoft, stop:1 $accentDeep);
    color: #ffffff; border: none; font-weight: 700; padding: 11px 18px;
}
QPushButton#primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #60a5fa, stop:1 #4f46e5);
}
QPushButton#primary:disabled { background: $grid; color: $faint; }
QPushButton#nav, QPushButton#navSecondary {
    background: transparent; border: none; border-radius: 12px;
    padding: 9px 12px; text-align: left; color: $muted; font-weight: 600;
}
QPushButton#navSecondary { font-weight: 500; }
QPushButton#nav:hover, QPushButton#navSecondary:hover {
    background: $navHover; color: $text;
}
QPushButton#nav:checked, QPushButton#navSecondary:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 $accentSoft, stop:1 $accentDeep);
    color: #ffffff;
}
QPushButton#nav:disabled { color: $faint; }
QPushButton#browse { padding: 6px 12px; border-radius: 9px; font-size: 12px; }
QPushButton#link {
    background: transparent; border: none; color: $accent;
    padding: 3px 2px; font-weight: 700; font-size: 12px;
}
QPushButton#link:hover { color: $accentSoft; }
QPushButton#iconButton {
    background: $buttonBg; border: 1px solid $fieldBorder;
    border-radius: 19px; padding: 0;
}
QPushButton#iconButton:hover { background: $buttonHoverBg; }
QPushButton#chip {
    background: $buttonBg; border: 1px solid $fieldBorder;
    border-radius: 9px; padding: 6px 10px; font-size: 12px;
}
QPushButton#chip:hover { background: $buttonHoverBg; }
QPushButton#outline {
    background: $buttonBg; border: 1px solid $fieldBorder;
    border-radius: 10px; padding: 7px 11px; font-size: 12px;
}
QPushButton#outline:hover { background: $buttonHoverBg; border-color: $accentSoft; }
QPushButton#iconSmall {
    background: transparent; border: 1px solid $fieldBorder;
    border-radius: 8px; padding: 5px;
}
QPushButton#iconSmall:hover { background: $buttonHoverBg; }
QPushButton#trafficRed { background: #ff5f57; border: none; border-radius: 6px; padding: 0; }
QPushButton#trafficYellow { background: #febc2e; border: none; border-radius: 6px; padding: 0; }
QPushButton#trafficGreen { background: #28c840; border: none; border-radius: 6px; padding: 0; }
QPushButton#trafficRed:hover { background: #ff7b75; }
QPushButton#trafficYellow:hover { background: #ffd05c; }
QPushButton#trafficGreen:hover { background: #55d96b; }

QLineEdit, QComboBox {
    background: $fieldBg; color: $text;
    border: 1px solid $fieldBorder; border-radius: 9px; padding: 7px 10px;
    selection-background-color: $selection;
}
QLineEdit:focus, QComboBox:focus { border-color: $accentSoft; }
QLineEdit:disabled, QComboBox:disabled { color: $faint; }
QLineEdit#pathValue, QLabel#pathValue {
    background: transparent; border: none; padding: 0;
    font-size: 12px; font-weight: 600;
}
QLineEdit#searchInput {
    background: transparent; border: none; padding: 0;
}
QComboBox { min-height: 22px; }
QComboBox#versionCombo, QComboBox#levelFilter, QComboBox#themeCombo { padding-right: 30px; }
QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView {
    background: $menuBg; color: $text;
    border: 1px solid $fieldBorder; border-radius: 9px;
    padding: 4px; outline: none;
    selection-background-color: $selection;
}

QTreeWidget {
    background: transparent; color: $text;
    border: none; outline: none;
    alternate-background-color: $rowAlt;
}
QTreeWidget::item { border: none; padding: 0; }
QTreeWidget::item:hover { background: $rowHover; }
QTreeWidget::item:selected { background: $selection; color: $text; }
QHeaderView { background: transparent; }
QHeaderView::section {
    background: transparent; color: $muted;
    border: none; border-bottom: 1px solid $grid;
    padding: 7px 8px; font-size: 11px; font-weight: 700;
}

QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { background: transparent; border: none; padding: 0; }
QListWidget::item:selected { background: transparent; }

QProgressBar {
    background: $groove; border: none; border-radius: 6px;
    text-align: center; color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 $accentSoft, stop:1 $accentDeep);
    border-radius: 6px;
}
QProgressBar#taskBar { border-radius: 4px; }
QProgressBar#taskBar::chunk { border-radius: 4px; }

QPlainTextEdit#logView {
    background: $logBg; color: $logFg;
    border: 1px solid $logBorder; border-radius: 11px;
    padding: 8px 10px;
    font-family: "DejaVu Sans Mono", "Menlo", "Consolas", monospace;
    font-size: 11px;
    selection-background-color: $logSelection;
}

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle { background: $scrollHandle; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QToolTip {
    background: $menuBg; color: $text;
    border: 1px solid $fieldBorder; border-radius: 6px; padding: 5px 8px;
}
""")


def stylesheet(palette: dict) -> str:
    """Render the shared sheet against one palette.

    ``$name`` substitution rather than ``str.format`` because every rule below is
    wrapped in literal braces.
    """
    return _QSS.safe_substitute(palette)


_RGBA = re.compile(r"rgba?\(\s*([^)]+?)\s*\)\Z")


def qcolor(value: str) -> QColor:
    """A palette value as a painter colour.

    QSS understands ``rgba(...)``; ``QColor`` does not, so the delegate and the
    backdrop would both paint black from a string the stylesheet renders correctly.
    """
    match = _RGBA.match(str(value).strip())
    if not match:
        return QColor(value)
    parts = [part.strip() for part in match.group(1).split(",")]
    if len(parts) < 3:
        return QColor(value)
    red, green, blue = (int(part) for part in parts[:3])
    alpha = 255
    if len(parts) > 3:
        raw = float(parts[3])
        alpha = round(raw * 255) if raw <= 1 else int(raw)
    return QColor(red, green, blue, max(0, min(255, alpha)))
