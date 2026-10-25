"""The BlackDream desktop palette, in two themes.

The platform owns the frame and menu bar; inside that client area the window
paints its own blue-silk backdrop. The frosted 200 px sidebar and the translucent
content veil sit over it, and the glass cards sit over those -- the wallpaper is
inside the app, never behind the desktop window.

Every colour used by QSS lives here as a finished QSS value (``rgba(...)`` included),
so a palette can be handed to a painter as well as to a stylesheet, and
:func:`qpalette` can hand the same palette to native dialogs and menus.
"""

from __future__ import annotations

import re
from string import Template

from PySide6.QtGui import QColor, QPalette

#: (start y, c1 x/y, c2 x/y, end y, thickness, colour, alpha) in window fractions.
#: Cubic strokes painted once into the cached backdrop; they are the mockup's blue
#: silk, not a texture asset.
_LIGHT_RIBBONS = (
    (0.94, 0.32, 0.52, 0.58, 0.96, 0.16, 0.22, "#a9d2ff", 78),
    (0.52, 0.08, 0.24, 0.54, 0.42, 0.08, 0.13, "#eef7ff", 92),
    (-0.06, 0.22, 0.20, 0.72, 0.56, 0.54, 0.30, "#0c3fb4", 58),
    (1.04, 0.42, 0.42, 0.62, 0.72, 0.86, 0.18, "#ffffff", 52),
    (1.02, 0.18, 0.28, 0.56, 0.84, 0.68, 0.34, "#0a2f94", 46),
)

_DARK_RIBBONS = (
    (0.94, 0.32, 0.52, 0.58, 0.96, 0.16, 0.22, "#2f6bd8", 62),
    (0.52, 0.08, 0.24, 0.54, 0.42, 0.08, 0.13, "#5f93e8", 46),
    (-0.06, 0.22, 0.20, 0.72, 0.56, 0.54, 0.30, "#020817", 120),
    (1.04, 0.42, 0.42, 0.62, 0.72, 0.86, 0.18, "#8fb6ff", 34),
    (1.02, 0.18, 0.28, 0.56, 0.84, 0.68, 0.34, "#01040d", 110),
)

_LIGHT_TINTS = {
    "CPU": ("#1f6bff", "rgba(31,107,255,28)"),
    "GPU": ("#e2447a", "rgba(226,68,122,26)"),
    "Audio": ("#dd7a24", "rgba(221,122,36,28)"),
    "Ethernet": ("#1296b8", "rgba(18,150,184,26)"),
    "Wi-Fi": ("#b8890b", "rgba(184,137,11,30)"),
    "Storage": ("#1f9a5b", "rgba(31,154,91,26)"),
    "USB": ("#3f7fe0", "rgba(63,127,224,26)"),
    "Bluetooth": ("#4b6bdd", "rgba(75,107,221,26)"),
    "SD card": ("#c95f38", "rgba(201,95,56,26)"),
    "Display": ("#5a63d6", "rgba(90,99,214,26)"),
    "Biometric": ("#a84bb8", "rgba(168,75,184,26)"),
}

_DARK_TINTS = {
    "CPU": ("#8fb5ff", "rgba(100,150,255,42)"),
    "GPU": ("#ff9cc7", "rgba(255,120,170,38)"),
    "Audio": ("#ffc07a", "rgba(255,170,90,38)"),
    "Ethernet": ("#7fdbe8", "rgba(90,215,230,36)"),
    "Wi-Fi": ("#f2cf6a", "rgba(240,200,90,38)"),
    "Storage": ("#86dfae", "rgba(90,220,150,36)"),
    "USB": ("#93c9f5", "rgba(100,180,240,38)"),
    "Bluetooth": ("#a9b8ff", "rgba(130,150,255,38)"),
    "SD card": ("#ffab8c", "rgba(255,140,100,38)"),
    "Display": ("#b3b8ff", "rgba(140,145,255,40)"),
    "Biometric": ("#e29ce8", "rgba(210,120,220,38)"),
}

LIGHT = {
    "windowBg": "#eef1f6",
    "menuBarFill": "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                   "stop:0 rgba(240,247,255,242), stop:1 rgba(222,237,255,232))",
    "menuBarBorder": "rgba(30,75,160,34)",
    "wallTop": "#1a5be0",
    "wallMid": "#4b90f7",
    "wallBottom": "#0a3aa8",
    "wallGlow": "#d6efff",
    "wallShade": "#041c56",
    "wallRibbons": _LIGHT_RIBBONS,
    "contentVeil": "qlineargradient(x1:0, y1:0, x2:0.85, y2:1, "
                   "stop:0 rgba(248,252,255,188), stop:0.55 rgba(238,247,255,158), "
                   "stop:1 rgba(225,238,255,136))",
    "sidebarFill": "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                   "stop:0 rgba(244,250,255,204), stop:1 rgba(226,240,255,184))",
    "sidebarBg": "rgba(236,245,255,206)",
    "sidebarBorder": "rgba(255,255,255,150)",
    "classTints": _LIGHT_TINTS,
    "cardFill": "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                "stop:0 rgba(255,255,255,196), stop:1 rgba(247,251,255,154))",
    "cardBg": "rgba(255,255,255,178)",
    "cardBorder": "rgba(30,55,95,40)",
    "cardHighlight": "rgba(255,255,255,245)",
    "hairline": "rgba(30,60,110,30)",
    "fieldBg": "rgba(255,255,255,178)",
    "fieldBorder": "rgba(120,150,200,82)",
    "controlBg": "rgba(255,255,255,205)",
    "buttonBg": "rgba(255,255,255,180)",
    "buttonHoverBg": "rgba(255,255,255,240)",
    "menuBg": "#fbfdff",
    "text": "#0c1c33",
    "muted": "#4d5f7a",
    "faint": "#7f8da3",
    "accent": "#1f6bff",
    "accentSoft": "#3f86ff",
    "accentDeep": "#124fd0",
    "onAccent": "#ffffff",
    "primaryTop": "#2f7cff",
    "primaryBottom": "#1d5ef0",
    "primaryEdge": "#1450d8",
    "primaryHoverTop": "#4a8dff",
    "primaryHoverBottom": "#2a6bff",
    "navCheckedTop": "#3f8bff",
    "navCheckedBottom": "#2467f2",
    "navCheckedEdge": "#1b55d0",
    "navHover": "rgba(255,255,255,132)",
    "selection": "rgba(52,110,255,50)",
    "menuHover": "rgba(52,110,255,24)",
    "rowHover": "rgba(255,255,255,150)",
    "rowAlt": "rgba(255,255,255,60)",
    "rowFailBg": "rgba(255,120,120,38)",
    "rowWarnBg": "rgba(255,190,90,36)",
    "grid": "rgba(70,100,150,46)",
    "groove": "rgba(90,120,170,55)",
    "scrollHandle": "rgba(70,90,125,110)",
    "ok": "#178a4c",
    "okBg": "rgba(214,246,226,215)",
    "okBorder": "rgba(31,170,90,90)",
    "warn": "#9a5a06",
    "warnBg": "rgba(252,236,196,210)",
    "warnBorder": "rgba(220,160,40,95)",
    "fail": "#d92d20",
    "failBg": "rgba(255,214,214,190)",
    "failBorder": "rgba(230,80,70,95)",
    "unknown": "#5e6b80",
    "unknownBg": "rgba(120,130,150,26)",
    "unknownBorder": "rgba(120,130,150,70)",
    "tileIcon": "#1f6bff",
    "tileBg": "rgba(31,107,255,30)",
    "taskBg": "rgba(255,255,255,210)",
    "taskBorder": "rgba(255,255,255,220)",
    "metricBg": "rgba(255,255,255,150)",
    "errorBg": "rgba(255,235,236,240)",
    "errorFg": "#8c1d24",
    "errorBorder": "rgba(220,38,38,110)",
    "errorCode": "#9a666c",
    "logBg": "#171a26",
    "logFg": "#dfe3ec",
    "logMuted": "#7d8496",
    "logBorder": "rgba(255,255,255,20)",
    "logSelection": "rgba(96,130,214,120)",
}

DARK = {
    "windowBg": "#12161d",
    "menuBarFill": "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                   "stop:0 rgba(15,24,42,242), stop:1 rgba(9,15,27,232))",
    "menuBarBorder": "rgba(255,255,255,26)",
    "wallTop": "#0a1c40",
    "wallMid": "#123a72",
    "wallBottom": "#050d20",
    "wallGlow": "#2f6bd8",
    "wallShade": "#00060f",
    "wallRibbons": _DARK_RIBBONS,
    "contentVeil": "qlineargradient(x1:0, y1:0, x2:0.85, y2:1, "
                   "stop:0 rgba(16,25,43,168), stop:0.55 rgba(10,17,30,146), "
                   "stop:1 rgba(6,11,21,132))",
    "sidebarFill": "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                   "stop:0 rgba(13,20,34,208), stop:1 rgba(6,10,18,192))",
    "sidebarBg": "rgba(9,12,17,190)",
    "sidebarBorder": "rgba(255,255,255,30)",
    "classTints": _DARK_TINTS,
    "cardFill": "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                "stop:0 rgba(42,51,71,220), stop:1 rgba(28,35,50,194))",
    "cardBg": "rgba(35,42,58,205)",
    "cardBorder": "rgba(255,255,255,40)",
    "cardHighlight": "rgba(255,255,255,58)",
    "hairline": "rgba(255,255,255,20)",
    "fieldBg": "rgba(255,255,255,16)",
    "fieldBorder": "rgba(255,255,255,46)",
    "controlBg": "rgba(255,255,255,26)",
    "buttonBg": "rgba(255,255,255,22)",
    "buttonHoverBg": "rgba(255,255,255,40)",
    "menuBg": "#1c2230",
    "text": "#eef2fa",
    "muted": "#a6b2c7",
    "faint": "#79869b",
    "accent": "#6fa4ff",
    "accentSoft": "#4f8dff",
    "accentDeep": "#2f63d0",
    "onAccent": "#12161d",
    "primaryTop": "#3f86ff",
    "primaryBottom": "#2564f0",
    "primaryEdge": "#1f52c8",
    "primaryHoverTop": "#5f9bff",
    "primaryHoverBottom": "#3575ff",
    "navCheckedTop": "#3f7dff",
    "navCheckedBottom": "#265fe8",
    "navCheckedEdge": "#1d4ec0",
    "navHover": "rgba(255,255,255,28)",
    "selection": "rgba(80,130,255,90)",
    "menuHover": "rgba(80,130,255,34)",
    "rowHover": "rgba(255,255,255,16)",
    "rowAlt": "rgba(255,255,255,6)",
    "rowFailBg": "rgba(220,70,80,70)",
    "rowWarnBg": "rgba(220,160,50,58)",
    "grid": "rgba(255,255,255,26)",
    "groove": "rgba(255,255,255,24)",
    "scrollHandle": "rgba(255,255,255,46)",
    "ok": "#86d9a5",
    "okBg": "rgba(34,92,60,192)",
    "okBorder": "rgba(90,190,125,80)",
    "warn": "#f0c274",
    "warnBg": "rgba(110,78,24,180)",
    "warnBorder": "rgba(235,180,90,80)",
    "fail": "#f2a0a8",
    "failBg": "rgba(110,36,44,180)",
    "failBorder": "rgba(240,120,132,90)",
    "unknown": "#a3a9b8",
    "unknownBg": "rgba(255,255,255,22)",
    "unknownBorder": "rgba(255,255,255,40)",
    "tileIcon": "#8fb5ff",
    "tileBg": "rgba(100,150,255,45)",
    "taskBg": "rgba(255,255,255,14)",
    "taskBorder": "rgba(255,255,255,30)",
    "metricBg": "rgba(255,255,255,10)",
    "errorBg": "rgba(74,28,34,220)",
    "errorFg": "#f2b0b6",
    "errorBorder": "rgba(240,120,132,90)",
    "errorCode": "#c88a90",
    "logBg": "#0e1117",
    "logFg": "#d7dae1",
    "logMuted": "#7d8496",
    "logBorder": "rgba(255,255,255,20)",
    "logSelection": "rgba(96,130,214,110)",
}

_QSS = Template("""
QWidget {
    color: $text;
    font-size: 13px;
}
QMainWindow, QDialog { background: $windowBg; }
QFrame#content {
    background: $contentVeil;
    border: none;
}
QWidget#brandBar, QWidget#header { background: transparent; }

#shell {
    background: transparent;
    border: none;
}
QFrame#sidebar {
    background: $sidebarFill;
    border: none;
    border-right: 1px solid $sidebarBorder;
}

QMenuBar {
    background: $menuBarFill;
    color: $text;
    border: none;
    border-bottom: 1px solid $menuBarBorder;
    padding: 3px 8px;
}
QMenuBar::item {
    background: transparent;
    border-radius: 6px;
    padding: 4px 10px;
}
QMenuBar::item:selected { background: $navHover; }
QMenuBar::item:pressed { background: $selection; }
QMenu {
    background: $menuBg;
    color: $text;
    border: 1px solid $cardBorder;
    border-radius: 12px;
    padding: 5px;
}
QMenu::item {
    border-radius: 8px;
    padding: 6px 28px 6px 10px;
}
QMenu::item:selected { background: $selection; }
QMenu::item:disabled { color: $faint; }
QMenu::separator {
    height: 1px;
    background: $hairline;
    margin: 4px 8px;
}

QLabel { color: $text; }
QLabel#pageTitle { font-size: 30px; font-weight: 700; }
QLabel#pageSubtitle { color: $muted; font-size: 13px; }
QLabel#brand { font-size: 16px; font-weight: 700; }
QLabel#brandHint { color: $muted; font-size: 10px; }
QLabel#navSection {
    color: $faint; font-size: 10px; font-weight: 700; letter-spacing: 1px;
}
QLabel#cardTitle { font-size: 16px; font-weight: 700; }
QLabel#cardHint { color: $muted; font-size: 11px; }
QLabel#progressHint { color: $accent; font-size: 12px; }
QLabel#emptyNote { color: $muted; font-size: 12px; }
QLabel#summary { color: $ok; font-size: 12px; font-weight: 600; }
QFrame#summaryCard[state="empty"] QLabel#summary { color: $muted; font-weight: 500; }
QFrame#summaryCard[state="error"] QLabel#summary { color: $errorFg; }
QLabel#summaryNote { color: $muted; font-size: 11px; }
QFrame#summaryCard[state="empty"] QLabel#summaryNote { color: $faint; }
QFrame#summaryCard[state="error"] QLabel#summaryNote { color: $errorFg; }
QLabel#pathLabel { color: $text; font-size: 11px; font-weight: 600; }
QLabel#pathValue { color: $muted; font-size: 11px; font-weight: 500; }
QLabel#numberBadge {
    background: $tileBg; color: $tileIcon; border-radius: 6px;
    font-size: 11px; font-weight: 700;
}
QLabel#dialogTitle { font-size: 18px; font-weight: 700; }
QLabel#dialogBody { color: $text; font-size: 12px; }
QLabel#dialogMuted { color: $muted; font-size: 11px; }
QLabel#aboutVersion { font-size: 16px; font-weight: 700; }
QLabel#rowTitle { font-size: 13px; font-weight: 600; }
QLabel#rowBody { color: $muted; font-size: 12px; }
QLabel#errorCard {
    background: $errorBg; color: $errorFg; border: 1px solid $errorBorder;
    border-radius: 10px; padding: 11px 14px;
}
QLabel#fieldState { background: transparent; }
QLabel#badge {
    border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600;
    background: $unknownBg; color: $unknown; border: 1px solid $unknownBorder;
}
QLabel#badge[state="supported"] { background: $okBg; color: $ok; border-color: $okBorder; }
QLabel#badge[state="limited"] { background: $warnBg; color: $warn; border-color: $warnBorder; }
QLabel#badge[state="unsupported"] { background: $failBg; color: $fail; border-color: $failBorder; }
QLabel#badge[state="unknown"] { background: $unknownBg; color: $unknown; border-color: $unknownBorder; }
QLabel#kbd {
    color: $faint; background: $fieldBg; border: 1px solid $fieldBorder;
    border-radius: 4px; padding: 1px 5px; font-size: 10px;
}
QLabel#configChip {
    background: $fieldBg; color: $muted;
    border: 1px solid $fieldBorder; border-radius: 10px;
    padding: 4px 10px; font-size: 11px; font-weight: 600;
}
QLabel#configChip[state="ok"] {
    background: $okBg; color: $ok; border-color: $okBorder;
}
QLabel#configChip[state="warn"] {
    background: $warnBg; color: $warn; border-color: $warnBorder;
}
QLabel#configChip[state="error"] {
    background: $failBg; color: $fail; border-color: $failBorder;
}
QLabel#stepLabel { color: $muted; font-size: 12px; font-weight: 500; }
QLabel#percent { font-size: 16px; font-weight: 700; }
QLabel#detailKey { color: $muted; font-size: 11px; font-weight: 600; }
QLabel#detailValue { font-size: 12px; font-weight: 500; }
QLabel#detailRecommendation { font-size: 12px; font-weight: 400; }
QLabel#detailRecommendation[state="supported"] { color: $ok; }
QLabel#detailRecommendation[state="limited"] { color: $warn; }
QLabel#detailRecommendation[state="unsupported"] { color: $fail; }
QLabel#taskTitle { color: $muted; font-size: 10px; font-weight: 700; }
QLabel#taskName { font-size: 13px; font-weight: 600; }
QLabel#taskDetail { color: $muted; font-size: 11px; }
QLabel#metricLabel { color: $muted; font-size: 10px; }
QLabel#metricValue { font-size: 13px; font-weight: 600; }
QLabel#stageName { font-size: 12px; font-weight: 400; }
QLabel#stageName[state="pending"] { color: $muted; }
QLabel#stageName[state="running"] { font-weight: 600; }
QLabel#stageName[state="failed"] { color: $fail; }
QLabel#stageName[state="cancelled"] { color: $muted; }
QLabel#stageTime { color: $faint; font-size: 11px; }

QFrame#card, QFrame#groupCard {
    background: $cardFill;
    border: 1px solid $cardBorder;
    border-top-color: $cardHighlight;
    border-radius: 16px;
}
QFrame#summaryCard {
    background: $okBg;
    border: 1px solid $okBorder;
    border-radius: 12px;
}
QFrame#summaryCard[state="empty"] {
    background: $fieldBg;
    border-color: $fieldBorder;
}
QFrame#summaryCard[state="error"] {
    background: $errorBg;
    border-color: $errorBorder;
}
QFrame#pathRow {
    background: $fieldBg;
    border: 1px solid $fieldBorder;
    border-top-color: $cardHighlight;
    border-radius: 13px;
}
QFrame#searchPill {
    background: $controlBg;
    border: 1px solid $fieldBorder;
    border-top-color: $cardHighlight;
    border-radius: 14px;
}
QFrame#taskCard {
    background: $taskBg;
    border: 1px solid $taskBorder;
    border-radius: 12px;
}
QFrame#metric {
    background: $metricBg;
    border: 1px solid $cardBorder;
    border-radius: 9px;
}
QFrame#header { background: transparent; border: none; }

QPushButton {
    background: $buttonBg; color: $text;
    border: 1px solid $fieldBorder; border-top-color: $cardHighlight;
    border-radius: 9px; padding: 6px 13px;
    font-weight: 500;
}
QPushButton:hover {
    background: $buttonHoverBg; border-color: $accentSoft;
    border-top-color: $accentSoft;
}
QPushButton:pressed { background: $selection; }
QPushButton:focus { border-color: $accent; }
QPushButton:disabled {
    color: $faint; background: transparent; border-color: $cardBorder;
}
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 $primaryTop, stop:1 $primaryBottom);
    color: #ffffff;
    border: 1px solid $primaryEdge;
    border-top-color: $primaryTop;
    border-radius: 10px;
    font-weight: 600; padding: 8px 16px;
}
QPushButton#primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 $primaryHoverTop, stop:1 $primaryHoverBottom);
    border-color: $primaryEdge;
    border-top-color: $primaryHoverTop;
}
QPushButton#primary:pressed {
    background: $primaryBottom; border-color: $primaryEdge;
}
QPushButton#primary:focus { border: 2px solid #ffffff; padding: 7px 15px; }
QPushButton#primary:disabled {
    background: $fieldBg; color: $muted; border: 1px solid $fieldBorder;
}
QPushButton#nav, QPushButton#navSecondary {
    background: transparent; border: 1px solid transparent; border-radius: 10px;
    padding: 9px 12px; text-align: left; color: $muted; font-weight: 500;
    font-size: 13px;
}
QPushButton#navSecondary {
    font-weight: 400; font-size: 12px; padding: 6px 10px;
}
QPushButton#nav:hover, QPushButton#navSecondary:hover {
    background: $navHover; color: $text;
}
QPushButton#nav:checked, QPushButton#navSecondary:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 $navCheckedTop, stop:1 $navCheckedBottom);
    border: 1px solid $navCheckedEdge;
    border-top-color: $navCheckedTop;
    color: #ffffff; font-weight: 600;
}
QPushButton#nav:focus, QPushButton#navSecondary:focus { border-color: transparent; }
QPushButton#nav:checked:focus, QPushButton#navSecondary:checked:focus {
    border-color: $navCheckedEdge;
    border-top-color: $navCheckedTop;
}
QPushButton#nav:disabled { color: $faint; }
QWidget#sectionTabs { background: transparent; }
QPushButton#segment {
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 5px 13px; color: $muted; font-size: 12px; font-weight: 600;
    text-align: center;
}
QPushButton#segment:hover { background: $menuHover; color: $text; }
QPushButton#segment:checked {
    background: $controlBg; border-color: $fieldBorder; color: $text;
}
QPushButton#segment:focus { border-color: $accent; }
QPushButton#browse {
    background: $controlBg; border: 1px solid $fieldBorder;
    border-radius: 9px; padding: 5px 11px; font-size: 12px;
}
QPushButton#link {
    background: transparent; border: 1px solid transparent; color: $accent;
    padding: 4px 2px; font-weight: 600; font-size: 12px;
}
QPushButton#link:hover { color: $accentSoft; }
QPushButton#link:focus { border-color: $accent; border-radius: 4px; }
QPushButton#iconButton {
    background: $buttonBg; border: 1px solid $fieldBorder;
    border-top-color: $cardHighlight;
    border-radius: 16px; padding: 0;
}
QPushButton#iconButton:hover { background: $buttonHoverBg; }
QPushButton#chip {
    background: $buttonBg; border: 1px solid $fieldBorder;
    border-top-color: $cardHighlight;
    border-radius: 7px; padding: 5px 10px; font-size: 12px;
}
QPushButton#chip:hover { background: $buttonHoverBg; }
QPushButton#outline {
    background: $buttonBg; border: 1px solid $fieldBorder;
    border-top-color: $cardHighlight;
    border-radius: 8px; padding: 6px 11px; font-size: 12px;
}
QPushButton#outline:hover { background: $buttonHoverBg; border-color: $accentSoft; }
QPushButton#outline:disabled {
    background: $buttonBg; color: $faint; border-color: $fieldBorder;
}
QPushButton#iconSmall {
    background: transparent; border: 1px solid $fieldBorder;
    border-radius: 7px; padding: 4px;
}
QPushButton#iconSmall:hover { background: $buttonHoverBg; }

QLineEdit, QComboBox {
    background: $fieldBg; color: $text;
    border: 1px solid $fieldBorder; border-radius: 9px; padding: 5px 9px;
    selection-background-color: $selection;
}
QLineEdit:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled, QComboBox:disabled { color: $faint; background: $windowBg; }
QLineEdit#pathValue, QLabel#pathValue {
    background: transparent; border: none; padding: 0;
    font-size: 12px; font-weight: 500;
}
QLineEdit#searchInput {
    background: transparent; border: none; padding: 0; font-size: 12px;
}
QComboBox { min-height: 20px; }
QComboBox#versionCombo {
    background: $controlBg; border: 1px solid $fieldBorder;
    border-radius: 11px; padding: 6px 30px 6px 11px; font-size: 13px;
}
QComboBox#levelFilter, QComboBox#themeCombo { padding-right: 28px; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView {
    background: $menuBg; color: $text;
    border: 1px solid $cardBorder; border-radius: 10px;
    padding: 4px; outline: 0;
    selection-background-color: transparent;
}
QFrame#comboPopup { background: transparent; border: none; }
QComboBox QAbstractItemView::item {
    min-height: 28px; padding: 0 8px; border-radius: 6px;
    color: $text;
}
QComboBox QAbstractItemView::item:hover { background: $menuHover; }
QComboBox QAbstractItemView::item:selected {
    background: $selection; color: $text; border: none;
}

QTreeWidget {
    background: transparent; color: $text;
    border: none; outline: none;
    alternate-background-color: $rowAlt;
}
QTreeWidget::item { border: none; padding: 0 2px; }
QTreeWidget::item:hover { background: $rowHover; }
QTreeWidget::item:selected { background: $selection; color: $text; }
QTreeView::indicator, QCheckBox::indicator {
    width: 14px; height: 14px; border-radius: 4px;
    background: $fieldBg; border: 1px solid $fieldBorder;
}
QTreeView::indicator:hover, QCheckBox::indicator:hover {
    border-color: $accent;
}
QTreeView::indicator:checked, QCheckBox::indicator:checked {
    background: $accent; border-color: $accentDeep;
}
QTreeView::indicator:disabled, QCheckBox::indicator:disabled {
    background: $windowBg; border-color: $cardBorder;
}
QHeaderView { background: transparent; }
QHeaderView::section {
    background: transparent; color: $muted;
    border: none; border-bottom: 1px solid $grid;
    border-right: 1px solid $grid;
    padding: 6px 8px; font-size: 11px; font-weight: 600;
}
QHeaderView::section:last { border-right: none; }

QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { background: transparent; border: none; padding: 0; }
QListWidget::item:selected { background: transparent; }
QListWidget#configSections::item {
    color: $text; border-radius: 8px; padding: 7px 8px; font-size: 12px;
}
QListWidget#configSections::item:hover { background: $menuHover; }
QListWidget#configSections::item:selected { background: $selection; }
QListWidget#configSections::item:disabled { color: $faint; }

QLineEdit#configValueEdit { padding: 5px 8px; font-size: 12px; }
QListWidget#configIssues {
    background: $fieldBg; color: $muted;
    border: 1px solid $fieldBorder; border-radius: 8px;
    padding: 2px;
    font-family: "SF Mono", "Menlo", "Cascadia Mono", "Consolas", "DejaVu Sans Mono";
    font-size: 11px;
}
QListWidget#configIssues::item { padding: 3px 6px; border-radius: 5px; }
QListWidget#configIssues::item:hover { background: $menuHover; }
QListWidget#configIssues::item:selected {
    background: $selection; color: $text;
}
QPlainTextEdit#configIssues {
    background: $fieldBg; color: $muted;
    border: 1px solid $fieldBorder; border-radius: 8px;
    padding: 4px 7px; font-size: 11px;
    selection-background-color: $selection;
}

QProgressBar {
    background: $groove; border: none; border-radius: 5px;
    text-align: center; color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 $accentSoft, stop:1 $primaryBottom);
    border-radius: 5px;
}
QProgressBar#taskBar { border-radius: 4px; }
QProgressBar#taskBar::chunk { border-radius: 4px; }

QPlainTextEdit#logView {
    background: $logBg; color: $logFg;
    border: 1px solid $logBorder;
    border-top-color: rgba(255,255,255,24);
    border-radius: 14px;
    padding: 9px 11px;
    font-family: "SF Mono", "Menlo", "Cascadia Mono", "Consolas",
                 "DejaVu Sans Mono", monospace;
    font-size: 12px;
    selection-background-color: $logSelection;
}

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle { background: $scrollHandle; border-radius: 3px; min-height: 28px; }
QScrollBar::handle:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QToolTip {
    background: $menuBg; color: $text;
    border: 1px solid $cardBorder; border-radius: 6px; padding: 4px 7px;
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
    tile renderer would both paint black from a string the stylesheet renders
    correctly.
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


def qpalette(palette: dict) -> QPalette:
    """The same palette for widgets the stylesheet cannot reach.

    Native file dialogs, message boxes and transient popups ignore QSS unless Qt
    falls back to a non-native dialog; handing them the application palette keeps
    them consistent with the window instead of flashing a default light surface in
    the dark theme.
    """
    result = QPalette()
    window = qcolor(palette["windowBg"])
    text = qcolor(palette["text"])
    disabled = qcolor(palette["faint"])
    result.setColor(QPalette.Window, window)
    result.setColor(QPalette.WindowText, text)
    result.setColor(QPalette.Base, qcolor(palette["fieldBg"]))
    result.setColor(QPalette.AlternateBase, qcolor(palette["taskBg"]))
    result.setColor(QPalette.Text, text)
    result.setColor(QPalette.Button, qcolor(palette["buttonBg"]))
    result.setColor(QPalette.ButtonText, text)
    result.setColor(QPalette.Highlight, qcolor(palette["accent"]))
    result.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    result.setColor(QPalette.ToolTipBase, qcolor(palette["menuBg"]))
    result.setColor(QPalette.ToolTipText, text)
    result.setColor(QPalette.PlaceholderText, qcolor(palette["faint"]))
    result.setColor(QPalette.Mid, qcolor(palette["cardBorder"]))
    result.setColor(QPalette.Dark, qcolor(palette["grid"]))
    result.setColor(QPalette.Light, qcolor(palette["cardBg"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        result.setColor(QPalette.Disabled, role, disabled)
    return result
