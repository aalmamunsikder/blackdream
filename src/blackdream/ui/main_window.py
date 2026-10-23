"""The main window: a glass dashboard over the engine's compatibility work.

Upstream's equivalent was a numbered text menu, and a menu is the wrong control for
this job: compatibility verdicts for a dozen devices do not fit in a scrollback,
"which macOS can this machine run" is not a typing task, and a build that takes four
minutes with no output looks like a hang. The dashboard shows engine state as it
happens, and the only things a user can type are file paths -- which are picked.

The fourth table column is the one piece of judgement this layer adds. It is not a
second opinion: ``verdicts.target_status`` answers one narrow question the engine's
own tuples already contain -- does this device work on the release the user picked?
A device native through Sequoia and dropped in Tahoe is "Supported" for one selection
and "Not supported" for the next, which is the answer a build needs.

Presentation follows three rules that outrank the layout:

* No engine work runs on the GUI thread, and nothing here touches a widget from a
  worker. Events arrive through :class:`EngineBridge` and are drained on a timer.
* The error card sits above the page stack, so no view change can hide a failure.
* One log widget. The Logs view moves it, never duplicates it; two views of one ring
  buffer drift apart the first time a line is dropped.

Scope of this slice, stated plainly: v1 emits an EFI folder. It never mounts, writes
to, or repairs an EFI partition.
"""

from __future__ import annotations

import copy
import html
import os
import platform
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import (
    QPointF, QRectF, QSettings, QSize, Qt, QTimer, QUrl)
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QDesktopServices, QDragEnterEvent, QDropEvent,
    QFont, QFontMetrics, QGuiApplication, QIcon, QKeySequence, QLinearGradient,
    QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QShortcut)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QBoxLayout, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QProxyStyle, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ocengine import paths
from ocengine import runtime
from ocengine.fatal import EngineError

from blackdream import RELEASE_LABEL, __version__, hardware
from blackdream.core import config_diff
from blackdream.core import config_editor
from blackdream.core import config_presets
from blackdream.core import crash_log
from blackdream.core import diagnostics
from blackdream.core import efi_manifest
from blackdream.core import efi_preflight
from blackdream.core import installer as installer_core
from blackdream.core import validation_assistant
from blackdream.core import verdicts
from blackdream.core.job_runner import (
    CANCELLED, DONE, Job, JobRunner, Outcome, UnexpectedEngineFailure)
from blackdream.core.pipeline import (
    OUTPUT_MARKER, BuildNotReady, Pipeline, _STEPS)
from blackdream.ui import icons
from blackdream.ui.bridge import EngineBridge, JobSignals
from blackdream.ui.theme import DARK, LIGHT, qcolor, qpalette, stylesheet

_LEVEL_COLOR = {"debug": "#8a8f98", "info": "#d8dbe4", "warning": "#e5c07b",
                "error": "#e06c75"}
_LEVEL_TAG = {"debug": "DEBUG", "info": "INFO", "warning": "WARN", "error": "ERROR"}
_LOG_TIME = "#7d8496"
_LOG_TEXT = "#d8dbe4"

#: Icon names, not glyphs: a text tick cannot carry the theme colour or the DPI scale.
_FIELD_STATE = {"empty": "dot", "ok": "check-circle", "warn": "alert-circle",
                "error": "x-circle"}
_STAGE_ICON = {"done": "check-circle", "running": "spinner", "pending": "dot",
               "failed": "x-circle", "cancelled": "minus"}
_STAGE_STATES = ("done", "running", "pending", "failed", "cancelled")
_STATUS_TONE = {"supported": "ok", "limited": "warn", "unsupported": "fail",
                "unknown": "unknown"}
_STATUS_ICON = {"ok": "check-circle", "warn": "alert-circle",
                "fail": "x-circle", "unknown": "dot"}
_CLASS_ICON = {
    "CPU": "cpu", "GPU": "gpu", "Audio": "speaker", "Ethernet": "globe",
    "Wi-Fi": "wifi", "Storage": "drive", "USB": "usb", "Bluetooth": "bluetooth",
    "SD card": "sd", "Display": "monitor", "Biometric": "fingerprint",
}
_NAV_ICON = {
    "Installer": "download", "Build EFI": "build", "Configure EFI": "sliders",
    "Compatibility": "pulse", "Logs": "logs",
    "Settings": "gear", "Help": "help", "Donate": "heart",
}
#: Top-level config.plist sections get a stable glyph in the section rail.
_CONFIG_SECTION_ICON = {
    "ACPI": "pulse", "Booter": "play", "DeviceProperties": "sliders",
    "Kernel": "layers", "Misc": "gear", "NVRAM": "drive",
    "PlatformInfo": "fingerprint", "UEFI": "shield",
}
_CONFIG_TYPE_ICON = {
    "boolean": "check-circle", "integer": "gauge", "real": "gauge",
    "string": "file", "data": "pulse", "dictionary": "layers",
    "array": "logs", "date": "clock",
}
_SECTIONS = ("Installer", "Build EFI", "Configure EFI")
_BUILD_VIEWS = ("Compatibility", "Build EFI", "Logs")
_SECONDARY_VIEWS = ("Settings", "Help", "Donate")
_VIEWS = ("Installer",) + _BUILD_VIEWS + ("Configure EFI",) + _SECONDARY_VIEWS
_PAGE_COPY = {
    "Installer": (
        "Make a macOS Installer",
        "Download Apple's recovery image and write it to a USB drive."),
    "Compatibility": (
        "Hardware Compatibility",
        "Review what macOS can run on this machine, then build the EFI folder."),
    "Build EFI": (
        "Build EFI Folder",
        "Watch the engine work and open the folder when it is done."),
    "Logs": (
        "Engine Log",
        "Every message the engine reported, in order."),
    "Configure EFI": (
        "Configure EFI",
        "Edit the built config.plist, check it with ocvalidate, and generate "
        "SMBIOS serials."),
    "Settings": (
        "Settings",
        "Appearance, storage and the rules this app works under."),
    "Help": (
        "Help",
        "How the workflow fits together, and what to do when a check fails."),
    "Donate": (
        "Support BlackDream",
        "Ways to help that do not cost anything."),
}

# The Help card renders these verbatim. Keeping both keycap tables literal means
# the mockup allowlist can be checked against the source instead of a format
# string that never appears on screen.
_SHORTCUTS_CTRL = (
    ("Search devices", "Ctrl K"),
    ("Open a report", "Ctrl O"),
    ("Installer", "Ctrl 1"),
    ("Build EFI", "Ctrl 2"),
    ("Configure EFI", "Ctrl 3"),
    ("Compatibility", "Ctrl Shift 1"),
    ("Build", "Ctrl Shift 2"),
    ("Logs", "Ctrl Shift 3"),
    ("Settings", "Ctrl ,"),
    ("Help", "F1"),
    ("Quit", "Ctrl Q"),
)
_SHORTCUTS_MAC = (
    ("Search devices", "\u2318 K"),
    ("Open a report", "\u2318 O"),
    ("Installer", "\u2318 1"),
    ("Build EFI", "\u2318 2"),
    ("Configure EFI", "\u2318 3"),
    ("Compatibility", "\u2318 Shift 1"),
    ("Build", "\u2318 Shift 2"),
    ("Logs", "\u2318 Shift 3"),
    ("Settings", "\u2318 ,"),
    ("Help", "F1"),
    ("Quit", "\u2318 Q"),
)
# One row per step of the three-section workflow, in workflow order.
_QUICK_START = (
    ("Make the installer",
     "Pick a macOS release, download Apple's recovery image, and write it to a FAT32 USB drive. A dropped connection resumes.",
     "download"),
    ("Load a report",
     "Collect hardware on Linux or Windows, or drop a Report.json exported by Hardware Sniffer anywhere in this window.",
     "file"),
    ("Choose a release",
     "The version picker marks the engine's suggestion, and any release that needs OpenCore Legacy Patcher.",
     "monitor"),
    ("Check compatibility",
     "Every device is graded, and the Status column answers for the release you picked.",
     "pulse"),
    ("Build the folder",
     "Pick an output folder and build. The EFI folder is written; nothing is mounted or written to a disk.",
     "build"),
    ("Configure the EFI",
     "Edit the built config.plist here, validate it with OpenCore's own checker, and save it back.",
     "sliders"),
)
_BUILD_JOBS = frozenset({"Selecting patches and kexts", "Downloading OpenCore and kexts",
                         "Writing the EFI folder"})
_FILTERS = ("Info and above", "Warnings and above", "Everything")
_THEME_MODES = ("system", "light", "dark")


@dataclass(frozen=True)
class _Step:
    """One GUI-thread step of a chained job, and what to render when it lands."""

    name: str
    body: Callable
    on_done: Callable[[Outcome], None] | None = None
    timeout: float | None = None


def _format_elapsed(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return "{:.1f} s".format(seconds)
    minutes, rest = divmod(int(seconds), 60)
    if minutes < 60:
        return "{}:{:02d}".format(minutes, rest)
    hours, minutes = divmod(minutes, 60)
    return "{}:{:02d}:{:02d}".format(hours, minutes, rest)


def _format_size(size: float) -> str:
    size = max(0.0, float(size))
    if size < 1024:
        return "{:.0f} B".format(size)
    if size < 1024 ** 2:
        return "{:.0f} KB".format(size / 1024)
    if size < 1024 ** 3:
        return "{:.1f} MB".format(size / 1024 ** 2)
    return "{:.2f} GB".format(size / 1024 ** 3)


def _format_rate(rate: float) -> str:
    if not rate or rate <= 0:
        return "\u2014"
    if rate >= 1024 ** 2:
        return "{:.1f} MB/s".format(rate / 1024 ** 2)
    return "{:.0f} KB/s".format(rate / 1024)


def _report_hint() -> str:
    """How this host gets a report: a local scan, or an export from the target PC.

    A report is the only input every host shares. Saying so explicitly matters on
    macOS, where no scan exists and a missing button otherwise looks like a bug.
    """
    if sys.platform == "win32":
        return "Load a Report.json, or scan this machine with Hardware Sniffer."
    if hardware.collect_supported():
        return "Load a Report.json, or collect hardware from this machine."
    return "Load a Report.json exported by Hardware Sniffer on the target PC."


class _ComboPopupStyle(QProxyStyle):
    """Make a non-editable combo drop its list below the field.

    Fusion answers SH_ComboBox_Popup for non-editable combos, which is the macOS
    menu behaviour: the list is positioned so the selected row sits over the field.
    On Windows and Linux that reads as a popup opening on top of its own button, so
    the selected value is hidden the moment the list appears. macOS keeps its native
    popup because the overlap is the expected platform behaviour there.
    """

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ComboBox_Popup and sys.platform != "darwin":
            return 0
        return super().styleHint(hint, option, widget, returnData)


def install_dropdown_style() -> None:
    application = QApplication.instance()
    if application is None or sys.platform == "darwin":
        return
    if isinstance(application.style(), _ComboPopupStyle):
        return
    application.setStyle(_ComboPopupStyle(application.style().objectName() or "Fusion"))


class _Wallpaper(QWidget):
    """The window's interior: blue silk behind the glass, painted not shipped.

    The platform still draws the frame and the menu bar; this widget owns only the
    client area inside them. It is rendered once per size, theme and device-pixel
    ratio -- repainting five cubic ribbons for every log line would cost more than
    the flat canvas it replaces.
    """

    def __init__(self) -> None:
        super().__init__()
        self._palette = LIGHT
        self._cache: QPixmap | None = None
        self._cache_key: tuple | None = None
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def set_palette(self, palette: dict) -> None:
        self._palette = palette
        self._cache = None
        self.update()

    def resizeEvent(self, event) -> None:
        self._cache = None
        super().resizeEvent(event)

    def paintEvent(self, _event) -> None:
        width = max(1, self.width())
        height = max(1, self.height())
        ratio = self.devicePixelRatioF()
        key = (width, height, ratio)
        if self._cache is None or self._cache_key != key:
            self._cache = self._render(width, height, ratio)
            self._cache_key = key
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cache)
        painter.end()

    def _render(self, width: int, height: int, ratio: float) -> QPixmap:
        pixmap = QPixmap(max(1, round(width * ratio)),
                         max(1, round(height * ratio)))
        painter = QPainter(pixmap)
        painter.scale(ratio, ratio)
        painter.setRenderHint(QPainter.Antialiasing)

        palette = self._palette
        sky = QLinearGradient(0.0, 0.0, width, height)
        sky.setColorAt(0.0, qcolor(palette["wallTop"]))
        sky.setColorAt(0.5, qcolor(palette["wallMid"]))
        sky.setColorAt(1.0, qcolor(palette["wallBottom"]))
        painter.fillRect(QRectF(0, 0, width, height), sky)

        glow = QRadialGradient(QPointF(width * 0.58, height * 0.32),
                               max(width, height) * 0.85)
        core = qcolor(palette["wallGlow"])
        core.setAlpha(150)
        middle = qcolor(palette["wallGlow"])
        middle.setAlpha(58)
        edge = qcolor(palette["wallGlow"])
        edge.setAlpha(0)
        glow.setColorAt(0.0, core)
        glow.setColorAt(0.35, middle)
        glow.setColorAt(1.0, edge)
        painter.fillRect(QRectF(0, 0, width, height), glow)

        painter.setBrush(Qt.NoBrush)
        for (start_y, c1x, c1y, c2x, c2y, end_y,
             thickness, colour, alpha) in palette["wallRibbons"]:
            path = QPainterPath(QPointF(-0.15 * width, start_y * height))
            path.cubicTo(QPointF(c1x * width, c1y * height),
                         QPointF(c2x * width, c2y * height),
                         QPointF(width * 1.15, end_y * height))
            stroke = max(4.0, height * thickness)
            for scale, factor in ((1.0, 0.34), (0.55, 1.0)):
                tone = qcolor(colour)
                tone.setAlpha(int(alpha * factor))
                pen = QPen(tone, stroke * scale)
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                painter.drawPath(path)

        vignette = QRadialGradient(QPointF(width * 0.5, height * 0.46),
                                   max(width, height) * 0.8)
        clear = qcolor(palette["wallShade"])
        clear.setAlpha(0)
        dark = qcolor(palette["wallShade"])
        dark.setAlpha(120)
        vignette.setColorAt(0.55, clear)
        vignette.setColorAt(1.0, dark)
        painter.fillRect(QRectF(0, 0, width, height), vignette)

        painter.end()
        pixmap.setDevicePixelRatio(ratio)
        return pixmap


class MainWindow(QMainWindow):
    """One window, one engine session. Loading a new report replaces the session."""

    def __init__(self) -> None:
        super().__init__()
        install_dropdown_style()
        self.setWindowTitle("BlackDream")
        self.setWindowIcon(QIcon(icons.logo(64)))
        self.setMinimumSize(1160, 700)
        self.setAcceptDrops(True)
        self._apply_startup_geometry()

        font = QFont()
        # No family is forced: each platform falls through to the first face it
        # has, so macOS gets SF, Windows gets Segoe UI, Linux gets Inter or Noto.
        font.setFamilies(["SF Pro Text", "SF Pro Display", "Segoe UI Variable Text",
                          "Segoe UI", "Inter", "Noto Sans", "Ubuntu", "DejaVu Sans"])
        font.setPointSize(10)
        self.setFont(font)

        self.bridge = EngineBridge()
        # The window owns the sink. Installing it anywhere else meant a directly
        # constructed window rendered its own log lines but silently dropped every
        # engine event -- stages, transfers and engine text all went to NullSink.
        runtime.set_sink(self.bridge)
        self._signals = JobSignals()
        self.runner = JobRunner(on_outcome=self._signals.finished.emit)
        self._signals.finished.connect(self._on_outcome)

        self._installer_signals = JobSignals()
        self._installer_runner = JobRunner(
            on_outcome=self._installer_signals.finished.emit)
        self._installer_signals.finished.connect(self._on_installer_outcome)
        self._usb_signals = JobSignals()
        self._usb_runner = JobRunner(on_outcome=self._usb_signals.finished.emit)
        self._usb_signals.finished.connect(self._after_usb_scan)
        self._config_signals = JobSignals()
        self._config_runner = JobRunner(
            on_outcome=self._config_signals.finished.emit)
        self._config_signals.finished.connect(self._on_config_outcome)

        self._pipeline: Pipeline | None = None
        self.analysis = None
        self.plan = None
        self._options: list = []
        self._chain: list[_Step] = []
        self._result_dir: Path | None = None
        self._report_path: Path | None = None
        self._settings = QSettings("BlackDream", "BlackDream")
        stored_output = str(self._settings.value("build/last_output", "") or "")
        if stored_output and Path(stored_output).is_dir():
            self._result_dir = Path(stored_output)
        stored_release = str(self._settings.value("installer/release", "") or "")
        self._installer_release = (
            installer_core.release_for(stored_release)
            or installer_core.DEFAULT_RELEASE)
        self._recovery = installer_core.cached_recovery(self._installer_release)
        self._usb_volumes: list[installer_core.UsbVolume] = []
        self._usb_scanned = False
        self._efi_folder: Path | None = None
        self._installer_job = ""
        self._config_doc: config_editor.ConfigDocument | None = None
        self._config_origin = ""
        self._config_job = ""
        self._config_model = ""
        self._config_note = ""
        self._config_loading = False
        self._config_section: str | None = None
        self._config_revision = 0
        self._config_validate_revision = -1
        self._config_validation = None
        self._config_inspector_loading = False
        self._built_config: Path | None = None
        self._config_history: config_diff.History | None = None
        self._preflight: efi_preflight.Report | None = None
        self._theme_mode = self._stored_theme_mode()
        self._dark = (self._system_dark() if self._theme_mode == "system"
                      else self._theme_mode == "dark")
        self._last_error_code = ""
        self._view = "Installer"
        self._build_view = "Compatibility"
        self._verdicts: list[verdicts.Verdict] = []
        self._items: list[QTreeWidgetItem] = []
        self._current_verdict: verdicts.Verdict | None = None
        self._filter_text = ""
        self._details_open = False
        self._entries: deque = deque(maxlen=4000)
        self._stage_names: list[str] = []
        self._stage_started: dict[str, float] = {}
        self._stage_elapsed: dict[str, float] = {}
        self._last_stages: list[tuple[str, int, str]] = []
        self._stage_widgets: dict[str, _StageRow] = {}
        self._build_started: float | None = None
        self._transfer_bytes: dict[str, int] = {}
        self._last_rate = 0.0
        self._last_clock = 0.0
        self._task_stage = ""
        self._placement: dict[QWidget, QVBoxLayout | QHBoxLayout] = {}

        self._build_widgets()
        self._build_menus()
        self._apply_theme()
        self._reset_progress()
        self._reset_details()
        self._set_busy(False)
        self._show_error(None)
        self._show_view("Installer")
        self._validate_output()
        self._validate_acpi()
        self._install_shortcuts()
        self.statusBar().showMessage("Ready")
        self.statusBar().hide()

        # Idle windows have nothing to drain; four ticks a second is enough to pick
        # up the first event of a background job without waking the CPU 17 times a
        # second for the life of the window.
        self._ticker = QTimer(self)
        self._ticker.setInterval(400)
        self._ticker.timeout.connect(self._drain)
        self._ticker.start()

        self._style_hints = QGuiApplication.styleHints()
        self._style_hints.colorSchemeChanged.connect(self._on_color_scheme)

    def _apply_startup_geometry(self) -> None:
        """Open at the design size where it fits, never larger than the screen."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1440, 940)
            return
        available = screen.availableGeometry()
        self.resize(min(1440, max(1160, available.width() - 80)),
                    min(940, max(700, available.height() - 80)))
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _stored_theme_mode(self) -> str:
        """``system``, ``light`` or ``dark``; the old boolean key migrates here."""
        stored = self._settings.value("appearance/mode", "")
        if stored in ("system", "light", "dark"):
            return str(stored)
        legacy = self._settings.value("appearance/dark", None)
        if legacy is None:
            return "system"
        return "dark" if str(legacy).lower() in ("true", "1") else "light"

    @staticmethod
    def _system_dark() -> bool:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark

    # ---- widget construction ----

    def _build_widgets(self) -> None:
        self._shell = _Wallpaper()
        self._shell.setObjectName("shell")
        shell_layout = QHBoxLayout(self._shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self._build_sidebar(), 0)
        shell_layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(self._shell)

    def _build_sidebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(200)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(13, 14, 13, 14)
        layout.setSpacing(3)

        title = QWidget()
        title.setObjectName("brandBar")
        title_layout = QVBoxLayout(title)
        title_layout.setContentsMargins(2, 2, 2, 0)
        title_layout.setSpacing(0)

        brand = QHBoxLayout()
        brand.setContentsMargins(2, 0, 0, 0)
        brand.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(icons.logo(46))
        mark.setFixedSize(46, 46)
        mark.setAttribute(Qt.WA_TransparentForMouseEvents)
        names = QVBoxLayout()
        names.setSpacing(0)
        label = QLabel("BlackDream")
        label.setObjectName("brand")
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        hint = QLabel("OpenCore, made simple.")
        hint.setObjectName("brandHint")
        hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        names.addWidget(label)
        names.addWidget(hint)
        brand.addWidget(mark, 0, Qt.AlignVCenter)
        brand.addLayout(names, 1)
        title_layout.addLayout(brand)
        layout.addWidget(title)
        layout.addSpacing(18)

        self.nav_buttons: list[QPushButton] = []
        workflow = QLabel("WORKFLOW")
        workflow.setObjectName("navSection")
        workflow.setContentsMargins(8, 0, 0, 4)
        layout.addWidget(workflow)
        for name in _SECTIONS:
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setIconSize(QSize(18, 18))
            button.setMinimumHeight(40)
            button.clicked.connect(lambda _checked, which=name: self._show_section(which))
            layout.addWidget(button)
            self.nav_buttons.append(button)

        layout.addStretch(1)

        self.secondary_buttons: list[QPushButton] = []
        for name in _SECONDARY_VIEWS:
            button = QPushButton(name)
            button.setObjectName("navSecondary")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setIconSize(QSize(17, 17))
            button.setMinimumHeight(34)
            button.clicked.connect(lambda _checked, which=name: self._show_view(which))
            layout.addWidget(button)
            self.secondary_buttons.append(button)
        self.settings_button = self.secondary_buttons[0]
        self.help_button = self.secondary_buttons[1]
        self.donate_button = self.secondary_buttons[2]
        return bar

    def _build_content(self) -> QWidget:
        content = QFrame()
        content.setObjectName("content")
        content.setFrameShape(QFrame.NoFrame)
        content.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 16, 22, 18)
        layout.setSpacing(12)

        header = QWidget()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(2, 0, 2, 0)
        header_layout.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.page_title = QLabel("Hardware Compatibility")
        self.page_title.setObjectName("pageTitle")
        self.page_title.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.page_subtitle = QLabel(
            "Review what macOS can run on this machine, then build the EFI folder.")
        self.page_subtitle.setObjectName("pageSubtitle")
        self.page_subtitle.setWordWrap(True)
        self.page_subtitle.setAttribute(Qt.WA_TransparentForMouseEvents)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header_layout.addLayout(titles, 1)

        # The Configure page owns the header's action slot; every other page
        # leaves it empty so the subtitle keeps the full width.
        self.page_actions = QWidget()
        self.page_actions.setObjectName("pageActions")
        self.page_actions_layout = QHBoxLayout(self.page_actions)
        self.page_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.page_actions_layout.setSpacing(6)
        self.page_actions.setVisible(False)
        header_layout.addWidget(self.page_actions, 0, Qt.AlignVCenter)
        layout.addWidget(header)

        self.error_card = QLabel()
        self.error_card.setObjectName("errorCard")
        self.error_card.setWordWrap(True)
        self.error_card.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.error_card.setVisible(False)
        layout.addWidget(self.error_card)

        self._build_cards()

        self.page_stack = QStackedWidget()
        self._section_pages: dict[str, QWidget] = {
            "Installer": self._scrollable(self._installer_page()),
            "Build EFI": self._build_section(),
            "Configure EFI": self._configure_page(),
            "Settings": self._scrollable(self._settings_page()),
            "Help": self._scrollable(self._help_page()),
            "Donate": self._scrollable(self._donate_page()),
        }
        for name in ("Installer", "Build EFI", "Configure EFI",
                     "Settings", "Help", "Donate"):
            self.page_stack.addWidget(self._section_pages[name])
        layout.addWidget(self.page_stack, 1)
        return content

    def _build_section(self) -> QWidget:
        """The Build EFI section: three sub-views over one shared set of cards."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        tabs = QWidget()
        tabs.setObjectName("sectionTabs")
        row = QHBoxLayout(tabs)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.build_buttons: list[QPushButton] = []
        for name, label in (("Compatibility", "Compatibility"),
                            ("Build EFI", "Build"), ("Logs", "Logs")):
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.clicked.connect(
                lambda _checked=False, which=name: self._show_view(which))
            row.addWidget(button)
            self.build_buttons.append(button)
        row.addStretch(1)
        layout.addWidget(tabs)

        self.build_stack = QStackedWidget()
        self.build_stack.addWidget(self._scrollable(self._compatibility_page()))
        self.build_stack.addWidget(self._scrollable(self._build_page()))
        self.build_stack.addWidget(self._logs_page())
        layout.addWidget(self.build_stack, 1)
        return page

    def _build_menus(self) -> None:
        """Native menus for the actions that already have shortcuts.

        The sidebar stays the primary navigation; the menu bar is what a desktop
        user reaches for with Alt, so every platform gets the same four commands.
        On macOS Qt moves it into the system menu bar.
        """
        bar = self.menuBar()
        self._view_actions: dict[str, QAction] = {}

        file_menu = bar.addMenu("&File")
        open_report = QAction("Open Report\u2026", self)
        open_report.setShortcut(QKeySequence.StandardKey.Open)
        open_report.triggered.connect(self._pick_report)
        open_acpi = QAction("Open ACPI Folder\u2026", self)
        open_acpi.triggered.connect(self._pick_acpi_dir)
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(open_report)
        file_menu.addAction(open_acpi)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        view_menu = bar.addMenu("&View")
        group = QActionGroup(self)
        group.setExclusive(True)
        shortcuts = {"Installer": "Ctrl+1", "Build EFI": "Ctrl+2",
                     "Configure EFI": "Ctrl+3", "Settings": "Ctrl+,", "Help": "F1"}
        for name in _SECTIONS + _SECONDARY_VIEWS:
            action = QAction(name, self)
            action.setCheckable(True)
            if name in shortcuts:
                action.setShortcut(QKeySequence(shortcuts[name]))
            if name in _SECTIONS:
                action.triggered.connect(
                    lambda _checked=False, which=name: self._show_section(which))
            else:
                action.triggered.connect(
                    lambda _checked=False, which=name: self._show_view(which))
            group.addAction(action)
            view_menu.addAction(action)
            self._view_actions[name] = action
        view_menu.addSeparator()
        build_menu = view_menu.addMenu("Build")
        build_shortcuts = {"Compatibility": "Ctrl+Shift+1",
                           "Build EFI": "Ctrl+Shift+2", "Logs": "Ctrl+Shift+3"}
        for name in _BUILD_VIEWS:
            action = QAction("Build" if name == "Build EFI" else name, self)
            action.setShortcut(QKeySequence(build_shortcuts[name]))
            action.triggered.connect(
                lambda _checked=False, which=name: self._show_view(which))
            build_menu.addAction(action)
        view_menu.addSeparator()
        theme_action = QAction("Toggle Theme", self)
        theme_action.triggered.connect(self._toggle_theme)
        view_menu.addAction(theme_action)

        help_menu = bar.addMenu("&Help")
        shortcuts_action = QAction("Keyboard Shortcuts", self)
        shortcuts_action.triggered.connect(lambda: self._show_view("Help"))
        about_action = QAction("About BlackDream", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(lambda: self._show_view("Settings"))
        help_menu.addAction(shortcuts_action)
        help_menu.addAction(about_action)

    def _palette_or_light(self) -> dict:
        return DARK if self._dark else LIGHT

    def _build_cards(self) -> None:
        self.files_card = QFrame()
        self.files_card.setObjectName("groupCard")
        files = QVBoxLayout(self.files_card)
        files.setContentsMargins(10, 10, 10, 10)
        files.setSpacing(9)
        self.report_field = _PathPicker(
            "Hardware report (Report.json)", "file", self._pick_report, palette=LIGHT)
        self.acpi_field = _PathPicker(
            "ACPI tables folder", "layers", self._pick_acpi_dir, palette=LIGHT)
        self.output_field = _PathPicker(
            "Output folder", "folder", self._pick_output,
            value=str(self._default_output()), palette=LIGHT)
        for field in (self.report_field, self.acpi_field, self.output_field):
            field.setFixedHeight(52)
            files.addWidget(field)
        machine = QHBoxLayout()
        machine.setContentsMargins(4, 0, 0, 0)
        machine.setSpacing(14)
        self.collect_button = QPushButton("Collect hardware")
        self.collect_button.setObjectName("link")
        self.collect_button.setToolTip(
            "Scan this machine with Hardware Sniffer; downloads and runs the verified tool"
            if sys.platform == "win32"
            else "Scan this machine and write a Report.json")
        self.collect_button.setVisible(hardware.collect_supported())
        self.collect_button.clicked.connect(self._on_collect)
        self.acpi_button = QPushButton("Read ACPI tables")
        self.acpi_button.setObjectName("link")
        self.acpi_button.setToolTip(
            "Read the firmware tables from this machine; asks for administrator rights")
        self.acpi_button.setVisible(hardware.acpi_supported())
        self.acpi_button.clicked.connect(self._on_dump_acpi)
        machine.addWidget(self.collect_button)
        machine.addWidget(self.acpi_button)
        machine.addStretch(1)
        files.addLayout(machine)

        self.version_card = QFrame()
        self.version_card.setObjectName("groupCard")
        version = QVBoxLayout(self.version_card)
        version.setContentsMargins(12, 10, 12, 11)
        version.setSpacing(8)
        version_title = QLabel("macOS version")
        version_title.setObjectName("cardTitle")
        version.addWidget(version_title)
        version_row = QHBoxLayout()
        version_row.setSpacing(10)
        self.version_icon = QLabel()
        self.version_icon.setFixedSize(30, 30)
        self.version_icon.setPixmap(icons.tile(
            "monitor", LIGHT["tileIcon"], LIGHT["tileBg"], 30))
        self.version_combo = _Combo(LIGHT)
        self.version_combo.setObjectName("versionCombo")
        self.version_combo.setMinimumHeight(34)
        self.version_combo.setPlaceholderText("Load a report to choose a version")
        self.version_combo.setEnabled(False)
        self.version_combo.currentIndexChanged.connect(self._on_version_changed)
        version_row.addWidget(self.version_icon, 0, Qt.AlignVCenter)
        version_row.addWidget(self.version_combo, 1)
        version.addLayout(version_row)

        self.summary_frame = QFrame()
        self.summary_frame.setObjectName("summaryCard")
        self.summary_frame.setProperty("state", "empty")
        summary_layout = QHBoxLayout(self.summary_frame)
        summary_layout.setContentsMargins(10, 8, 10, 8)
        summary_layout.setSpacing(9)
        self.summary_icon = QLabel()
        self.summary_icon.setFixedSize(20, 20)
        self.summary_icon.setAlignment(Qt.AlignCenter)
        summary_copy = QVBoxLayout()
        summary_copy.setSpacing(1)
        self.summary = QLabel(_report_hint())
        self.summary.setObjectName("summary")
        self.summary.setWordWrap(True)
        self.summary_note = QLabel(
            "Support ranges come from the report's own compatibility data.")
        self.summary_note.setObjectName("summaryNote")
        self.summary_note.setWordWrap(True)
        summary_copy.addWidget(self.summary)
        summary_copy.addWidget(self.summary_note)
        summary_layout.addWidget(self.summary_icon, 0, Qt.AlignTop)
        summary_layout.addLayout(summary_copy, 1)
        version.addWidget(self.summary_frame)
        self._set_summary_icon("empty")

        self.actions_card = QFrame()
        self.actions_card.setObjectName("groupCard")
        actions = QGridLayout(self.actions_card)
        actions.setContentsMargins(11, 11, 11, 11)
        actions.setHorizontalSpacing(9)
        actions.setVerticalSpacing(9)
        self.analyze_button = QPushButton("Check compatibility")
        self.analyze_button.setObjectName("primary")
        self.analyze_button.setMinimumHeight(42)
        self.analyze_button.setIconSize(QSize(16, 16))
        self.analyze_button.clicked.connect(self._on_analyze)
        self.build_button = QPushButton("Build EFI folder")
        self.build_button.setObjectName("outline")
        self.build_button.setMinimumHeight(42)
        self.build_button.setIconSize(QSize(16, 16))
        self.build_button.clicked.connect(self._on_build)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("outline")
        self.cancel_button.setMinimumHeight(42)
        self.cancel_button.clicked.connect(self._on_cancel)
        self.reveal_button = QPushButton("Open EFI folder")
        self.reveal_button.setObjectName("outline")
        self.reveal_button.setMinimumHeight(42)
        self.reveal_button.setIconSize(QSize(15, 15))
        self.reveal_button.clicked.connect(self._reveal_result)
        for column, button in enumerate((self.analyze_button, self.build_button,
                                         self.cancel_button, self.reveal_button)):
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            actions.addWidget(button, column // 2, column % 2)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        self.actions_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.preflight_card = _Card(
            "Folder checks",
            "Read the built folder before you try to boot it.")
        preflight_actions = QWidget()
        preflight_actions_layout = QHBoxLayout(preflight_actions)
        preflight_actions_layout.setContentsMargins(0, 0, 0, 0)
        preflight_actions_layout.setSpacing(6)
        self.preflight_button = QPushButton("Run checks")
        self.preflight_button.setObjectName("outline")
        self.preflight_button.setMinimumHeight(28)
        self.preflight_button.setToolTip(
            "Check required files and every path config.plist references")
        self.preflight_button.clicked.connect(lambda: self._on_preflight())
        self.preflight_verify = QPushButton("Verify manifest")
        self.preflight_verify.setObjectName("outline")
        self.preflight_verify.setMinimumHeight(28)
        self.preflight_verify.setToolTip(
            "Compare the folder with the manifest written at build time")
        self.preflight_verify.clicked.connect(self._on_verify_manifest)
        self.preflight_export = QPushButton("Save report\u2026")
        self.preflight_export.setObjectName("outline")
        self.preflight_export.setMinimumHeight(28)
        self.preflight_export.setEnabled(False)
        self.preflight_export.clicked.connect(self._on_preflight_export)
        for button in (self.preflight_button, self.preflight_verify,
                       self.preflight_export):
            preflight_actions_layout.addWidget(button)
        self.preflight_card.set_header_widget(preflight_actions)
        self.preflight_status = QLabel("Not checked yet.")
        self.preflight_status.setObjectName("rowTitle")
        self.preflight_card.add(self.preflight_status)
        self.preflight_note = QLabel(
            "These checks read the folder. They do not test firmware, hardware "
            "or whether macOS boots.")
        self.preflight_note.setObjectName("rowBody")
        self.preflight_note.setWordWrap(True)
        self.preflight_card.add(self.preflight_note)
        self.preflight_list = QListWidget()
        self.preflight_list.setObjectName("configIssues")
        self.preflight_list.setMaximumHeight(112)
        self.preflight_list.setVisible(False)
        self.preflight_card.add(self.preflight_list)
        self._preflight_text = ""

        self.devices_card = _Card(
            "Detected devices", "No report loaded yet.")
        self.search = _SearchPill(self._palette_or_light(), compact=True)
        self.search.search_input.textChanged.connect(self._on_search)
        self.devices_card.set_header_widget(self.search)
        self.view_details_button = QPushButton("View details")
        self.view_details_button.setObjectName("chip")
        self.view_details_button.clicked.connect(self._toggle_details)
        self.devices_card.set_header_widget(self.view_details_button)
        self.empty_note = QLabel(
            "Load a report to see this machine's devices and what macOS does with them.")
        self.empty_note.setObjectName("emptyNote")
        self.empty_note.setWordWrap(True)
        self.devices_card.add(self.empty_note)
        self._status_delegate = _StatusDelegate(LIGHT)
        self.verdict_tree = _VerdictTree()
        self.verdict_tree.setHeaderLabels(
            ["Device", "Class", "macOS support", "Status"])
        self.verdict_tree.setRootIsDecorated(False)
        self.verdict_tree.setAlternatingRowColors(False)
        self.verdict_tree.setIndentation(0)
        self.verdict_tree.setUniformRowHeights(True)
        self.verdict_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.verdict_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verdict_tree.setItemDelegateForColumn(3, self._status_delegate)
        header = self.verdict_tree.header()
        header.setStretchLastSection(False)
        header.setSectionsClickable(False)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.verdict_tree.setColumnWidth(1, 72)
        self.verdict_tree.setColumnWidth(2, 266)
        self.verdict_tree.setColumnWidth(3, 100)
        self.verdict_tree.setMinimumHeight(150)
        self.verdict_tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.verdict_tree.itemSelectionChanged.connect(self._on_device_selected)
        self.devices_card.add(self.verdict_tree, 1)

        self.details_card = _Card("Device details")
        self.detail_badge = QLabel()
        self.detail_badge.setObjectName("badge")
        self.detail_badge.setVisible(False)
        self.details_card.set_header_widget(self.detail_badge)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        self.detail_values: dict[str, QLabel] = {}
        for row, key in enumerate(("Device", "Class", "macOS support", "Vendor",
                                   "Device ID", "Subsystem", "Current status")):
            caption = QLabel(key)
            caption.setObjectName("detailKey")
            caption.setFixedWidth(102)
            value = QLabel("\u2014")
            value.setObjectName("detailValue")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(caption, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1)
            self.detail_values[key] = value
        recommendation_key = QLabel("Recommendation")
        recommendation_key.setObjectName("detailKey")
        recommendation_key.setFixedWidth(102)
        self.detail_recommendation = QLabel(
            "Select a device to see the engine's verdict for it.")
        self.detail_recommendation.setObjectName("detailRecommendation")
        self.detail_recommendation.setWordWrap(True)
        grid.addWidget(recommendation_key, 7, 0, Qt.AlignTop)
        grid.addWidget(self.detail_recommendation, 7, 1)
        self.details_card.add(grid)
        detail_buttons = QHBoxLayout()
        detail_buttons.setSpacing(8)
        self.copy_details_button = QPushButton("Copy details")
        self.copy_details_button.setObjectName("outline")
        self.copy_details_button.clicked.connect(self._copy_details)
        self.why_button = QPushButton("Show engine verdict")
        self.why_button.setObjectName("outline")
        self.why_button.clicked.connect(self._show_why)
        detail_buttons.addWidget(self.copy_details_button)
        detail_buttons.addWidget(self.why_button)
        detail_buttons.addStretch(1)
        self.details_card.add(detail_buttons)
        # The details card shares the right column with the table, so every row
        # it saves is one more device visible above the fold.
        self.details_card.layout().setSpacing(4)
        self.details_card.finish()
        self.details_card.setVisible(False)

        self.progress_card = _Card(
            "Build progress", "Step, transfer and timing from the engine.")
        self.progress_card.hint_label().setObjectName("progressHint")
        self.step_label = QLabel("Not started")
        self.step_label.setObjectName("stepLabel")
        self.progress_card.set_header_widget(self.step_label)
        bar_row = QHBoxLayout()
        bar_row.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setRange(0, 5)
        self.progress.setValue(0)
        # Qt paints this text in one colour wherever it sits, so a value legible on
        # the empty groove turns into grey-on-blue halfway through. The percentage
        # is drawn beside the bar instead, where it never shares a background.
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(9)
        self.progress_label = QLabel("0%")
        self.progress_label.setObjectName("percent")
        bar_row.addWidget(self.progress, 1)
        bar_row.addWidget(self.progress_label, 0, Qt.AlignRight)
        self.progress_card.add(bar_row)

        self.stage_list = QListWidget()
        self.stage_list.setObjectName("stageList")
        self.stage_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.stage_list.setFocusPolicy(Qt.NoFocus)
        self.stage_list.setMinimumHeight(122)
        self.stage_list.setMinimumWidth(220)
        self.stage_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)

        task = QFrame()
        task.setObjectName("taskCard")
        task_layout = QVBoxLayout(task)
        task_layout.setContentsMargins(11, 8, 11, 8)
        task_layout.setSpacing(3)
        self.task_name = QLabel("Waiting to start")
        self.task_name.setObjectName("taskName")
        self.task_detail = QLabel("Nothing is downloading.")
        self.task_detail.setObjectName("taskDetail")
        self.task_progress = QProgressBar()
        self.task_progress.setObjectName("taskBar")
        self.task_progress.setRange(0, 100)
        self.task_progress.setValue(0)
        self.task_progress.setTextVisible(False)
        self.task_progress.setFixedHeight(5)
        task_layout.addWidget(self.task_name)
        task_layout.addWidget(self.task_detail)
        task_layout.addWidget(self.task_progress)
        task_layout.addSpacing(2)

        metrics = QHBoxLayout()
        metrics.setSpacing(6)
        self.metric_elapsed = _Metric("clock", "Elapsed time", compact=True)
        self.metric_downloaded = _Metric("download", "Downloaded", "0 B", compact=True)
        self.metric_speed = _Metric("gauge", "Speed", compact=True)
        for metric in (self.metric_elapsed, self.metric_downloaded,
                       self.metric_speed):
            metrics.addWidget(metric, 1)
        task_layout.addLayout(metrics)

        # Checklist and current task share a row: stacking them made the card the
        # tallest thing on the page and pushed the table into a scrollbar.
        task_row = _Split(self.stage_list, task, spacing=12, stretch=(3, 2),
                          stack_stretch=(1, 0))
        self.progress_card.add(task_row, 1)

        self.log_card = _Card("Engine log")
        tools = QWidget()
        tool_layout = QHBoxLayout(tools)
        tool_layout.setContentsMargins(0, 0, 0, 0)
        tool_layout.setSpacing(6)
        self.level_filter = _Combo(LIGHT)
        self.level_filter.setObjectName("levelFilter")
        self.level_filter.setFixedWidth(162)
        self.level_filter.addItems(list(_FILTERS))
        self.level_filter.setCurrentIndex(0)
        self.level_filter.currentIndexChanged.connect(self._rerender_log)
        self.log_card.add_header_widget(self.level_filter)
        self.save_log_button = QPushButton("Save log\u2026")
        self.save_log_button.setObjectName("chip")
        self.save_log_button.clicked.connect(self._save_log)
        self.copy_log_button = QPushButton()
        self.copy_log_button.setObjectName("iconSmall")
        self.copy_log_button.setFixedSize(30, 30)
        self.copy_log_button.setIconSize(QSize(15, 15))
        self.copy_log_button.setToolTip("Copy the log")
        self.copy_log_button.clicked.connect(self._copy_log)
        tool_layout.addWidget(self.save_log_button)
        tool_layout.addWidget(self.copy_log_button)
        self.log_card.set_header_widget(tools)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("logView")
        self.log_view.setMaximumBlockCount(4000)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setMinimumHeight(150)
        self.log_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.log_card.add(self.log_view, 1)

    def _installer_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.installer_card = _Card(
            "macOS installer",
            "Apple's recovery image for the release you pick, verified chunk by "
            "chunk against Apple's signed chunklist.")
        release_row = QHBoxLayout()
        release_row.setSpacing(10)
        self.install_version_icon = QLabel()
        self.install_version_icon.setFixedSize(30, 30)
        self.install_version_combo = _Combo(LIGHT)
        self.install_version_combo.setObjectName("versionCombo")
        self.install_version_combo.setMinimumHeight(36)
        self.install_version_combo.setPlaceholderText("Choose a macOS version")
        self.install_version_combo.currentIndexChanged.connect(
            self._on_installer_version_changed)
        release_row.addWidget(self.install_version_icon, 0, Qt.AlignVCenter)
        release_row.addWidget(self.install_version_combo, 1)
        self.installer_card.add(release_row)

        # Newest first, and no signals until the stored choice is in place: the
        # first addItem would otherwise select Tahoe and overwrite that choice.
        self.install_version_combo.blockSignals(True)
        for release in reversed(installer_core.RECOVERY_RELEASES):
            label = release.label + (" \u00b7 latest" if release.latest else "")
            self.install_version_combo.addItem(label, release)
            self.install_version_combo.setItemData(
                self.install_version_combo.count() - 1, label, Qt.ToolTipRole)
        selected = next(
            (index for index in range(self.install_version_combo.count())
             if self.install_version_combo.itemData(index) == self._installer_release),
            0)
        self.install_version_combo.setCurrentIndex(selected)
        self.install_version_combo.blockSignals(False)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.installer_icon = QLabel()
        self.installer_icon.setFixedSize(30, 30)
        status_copy = QVBoxLayout()
        status_copy.setSpacing(1)
        self.installer_status = QLabel("Not downloaded yet.")
        self.installer_status.setObjectName("rowTitle")
        self.installer_detail = QLabel()
        self.installer_detail.setObjectName("rowBody")
        self.installer_detail.setWordWrap(True)
        status_copy.addWidget(self.installer_status)
        status_copy.addWidget(self.installer_detail)
        status_row.addWidget(self.installer_icon, 0, Qt.AlignTop)
        status_row.addLayout(status_copy, 1)
        self.installer_card.add(status_row)

        self.installer_progress = QProgressBar()
        self.installer_progress.setObjectName("taskBar")
        self.installer_progress.setRange(0, 100)
        self.installer_progress.setValue(0)
        self.installer_progress.setTextVisible(False)
        self.installer_progress.setFixedHeight(5)
        self.installer_progress.setVisible(False)
        self.installer_card.add(self.installer_progress)

        installer_actions = QHBoxLayout()
        installer_actions.setSpacing(8)
        self.install_download_button = QPushButton("Download installer")
        self.install_download_button.setObjectName("primary")
        self.install_download_button.setMinimumHeight(38)
        self.install_download_button.setIconSize(QSize(15, 15))
        self.install_download_button.clicked.connect(self._on_download_installer)
        self.install_cancel_button = QPushButton("Cancel")
        self.install_cancel_button.setObjectName("outline")
        self.install_cancel_button.setMinimumHeight(38)
        self.install_cancel_button.setIconSize(QSize(14, 14))
        self.install_cancel_button.setEnabled(False)
        self.install_cancel_button.clicked.connect(self._on_installer_cancel)
        installer_actions.addWidget(self.install_download_button)
        installer_actions.addWidget(self.install_cancel_button)
        installer_actions.addStretch(1)
        self.installer_card.add(installer_actions)
        layout.addWidget(self.installer_card)

        self.usb_card = _Card(
            "USB drive",
            "A mounted FAT32 volume on a USB bus. BlackDream copies files; it "
            "never formats the drive.")
        volume_row = QHBoxLayout()
        volume_row.setSpacing(10)
        self.usb_icon = QLabel()
        self.usb_icon.setFixedSize(30, 30)
        self.usb_combo = _Combo(LIGHT)
        self.usb_combo.setMinimumHeight(36)
        self.usb_combo.setPlaceholderText("Plug in a FAT32 USB drive, then refresh")
        self.usb_combo.currentIndexChanged.connect(self._on_usb_selected)
        self.usb_refresh = QPushButton("Refresh")
        self.usb_refresh.setObjectName("outline")
        self.usb_refresh.setMinimumHeight(36)
        self.usb_refresh.clicked.connect(self._refresh_usb)
        volume_row.addWidget(self.usb_icon, 0, Qt.AlignVCenter)
        volume_row.addWidget(self.usb_combo, 1)
        volume_row.addWidget(self.usb_refresh, 0)
        self.usb_card.add(volume_row)

        self.usb_note = QLabel("No drive selected.")
        self.usb_note.setObjectName("rowBody")
        self.usb_note.setWordWrap(True)
        self.usb_card.add(self.usb_note)

        stored_efi = str(self._settings.value("installer/efi_folder", "") or "")
        if not stored_efi and self._result_dir is not None:
            stored_efi = str(self._result_dir)
        self.efi_field = _PathPicker(
            "EFI folder", "folder", self._pick_efi_folder, value=stored_efi,
            palette=LIGHT)
        self.efi_field.setFixedHeight(52)
        self.usb_card.add(self.efi_field)
        self._validate_efi_field()

        replace_note = QLabel(
            "EFI and com.apple.recovery.boot on the drive will be replaced. "
            "Everything else on it is left alone.")
        replace_note.setObjectName("rowBody")
        replace_note.setWordWrap(True)
        self.usb_card.add(replace_note)

        write_row = QHBoxLayout()
        self.install_write_button = QPushButton("Write installer")
        self.install_write_button.setObjectName("primary")
        self.install_write_button.setMinimumHeight(40)
        self.install_write_button.setIconSize(QSize(15, 15))
        self.install_write_button.clicked.connect(self._on_write_installer)
        write_row.addWidget(self.install_write_button)
        write_row.addStretch(1)
        self.usb_card.add(write_row)
        layout.addWidget(self.usb_card)
        layout.addStretch(1)

        self._refresh_installer_state()
        self._update_usb_detail()
        return page

    def _configure_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Header slot: validation state, the pinned schema, then the three file
        # actions. The save action is primary and only lights up when dirty.
        self.config_validation_chip = QLabel("Not validated")
        self.config_validation_chip.setObjectName("configChip")
        self.config_schema_chip = QLabel(
            "OpenCore {}".format(config_editor.OPEN_CORE_VERSION))
        self.config_schema_chip.setObjectName("configChip")
        self.page_actions_layout.addWidget(self.config_validation_chip)
        self.page_actions_layout.addWidget(self.config_schema_chip)
        self.page_actions_layout.addSpacing(4)

        self.config_open = QPushButton("Open config\u2026")
        self.config_open.setObjectName("outline")
        self.config_open.setMinimumHeight(36)
        self.config_open.setIconSize(QSize(14, 14))
        self.config_open.clicked.connect(self._on_config_open)
        self.config_validate = QPushButton("Validate")
        self.config_validate.setObjectName("outline")
        self.config_validate.setMinimumHeight(36)
        self.config_validate.setIconSize(QSize(14, 14))
        self.config_validate.clicked.connect(self._on_config_validate)
        self.config_save = QPushButton("Save")
        self.config_save.setObjectName("primary")
        self.config_save.setMinimumHeight(36)
        self.config_save.setIconSize(QSize(15, 15))
        self.config_save.clicked.connect(self._on_config_save)
        for button in (self.config_open, self.config_validate,
                       self.config_save):
            self.page_actions_layout.addWidget(button)

        self.configure_card = _Card(
            "config.plist",
            "Edit the file this app built. Nothing is written until you save.")
        config_row = QHBoxLayout()
        config_row.setSpacing(10)
        self.config_icon = QLabel()
        self.config_icon.setFixedSize(30, 30)
        config_copy = QVBoxLayout()
        config_copy.setSpacing(1)
        self.config_status = QLabel("No built config.plist yet.")
        self.config_status.setObjectName("rowTitle")
        self.config_path = _ElidedPath()
        config_copy.addWidget(self.config_status)
        config_copy.addWidget(self.config_path)
        config_row.addWidget(self.config_icon, 0, Qt.AlignTop)
        config_row.addLayout(config_copy, 1)
        self.config_serials = QPushButton("Generate serials")
        self.config_serials.setObjectName("outline")
        self.config_serials.setMinimumHeight(32)
        self.config_serials.setIconSize(QSize(14, 14))
        self.config_serials.clicked.connect(self._on_config_serials)
        self.config_revert = QPushButton("Revert")
        self.config_revert.setObjectName("outline")
        self.config_revert.setMinimumHeight(32)
        self.config_revert.clicked.connect(self._on_config_revert)
        self.config_reveal = QPushButton("Show folder")
        self.config_reveal.setObjectName("outline")
        self.config_reveal.setMinimumHeight(32)
        self.config_reveal.setIconSize(QSize(14, 14))
        self.config_reveal.clicked.connect(self._reveal_config)
        for button in (self.config_serials, self.config_revert,
                       self.config_reveal):
            config_row.addWidget(button, 0, Qt.AlignVCenter)
        self.configure_card.add(config_row)

        self.config_progress = QProgressBar()
        self.config_progress.setObjectName("taskBar")
        self.config_progress.setRange(0, 100)
        self.config_progress.setValue(0)
        self.config_progress.setTextVisible(False)
        self.config_progress.setFixedHeight(5)
        self.config_progress.setVisible(False)
        self.configure_card.add(self.config_progress)

        self.config_detail = QLabel()
        self.config_detail.setObjectName("rowBody")
        self.config_detail.setWordWrap(True)
        self.configure_card.add(self.config_detail)
        layout.addWidget(self.configure_card)

        self.sections_card = _Card("Sections")
        self.sections_card.setFixedWidth(206)
        self.config_sections = QListWidget()
        self.config_sections.setObjectName("configSections")
        self.config_sections.setFrameShape(QFrame.NoFrame)
        self.config_sections.setUniformItemSizes(True)
        self.config_sections.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.config_sections.currentItemChanged.connect(
            self._on_config_section_changed)
        self.sections_card.add(self.config_sections, 1)

        self.keys_card = _Card(
            "Keys",
            "Select a value to edit it. Keys this build does not know are kept "
            "as they are.")
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.config_undo = QPushButton("Undo")
        self.config_undo.setObjectName("outline")
        self.config_undo.setMinimumHeight(30)
        self.config_undo.setToolTip("Undo the last edit in memory")
        self.config_undo.clicked.connect(self._on_config_undo)
        self.config_redo = QPushButton("Redo")
        self.config_redo.setObjectName("outline")
        self.config_redo.setMinimumHeight(30)
        self.config_redo.setToolTip("Redo the last undone edit")
        self.config_redo.clicked.connect(self._on_config_redo)
        self.config_changes = QPushButton("Changes\u2026")
        self.config_changes.setObjectName("outline")
        self.config_changes.setMinimumHeight(30)
        self.config_changes.setToolTip(
            "Review every edit made since the file was opened")
        self.config_changes.clicked.connect(self._on_config_changes)
        self.config_add_key = QPushButton("Add key")
        self.config_add_key.setObjectName("outline")
        self.config_add_key.setMinimumHeight(30)
        self.config_add_key.clicked.connect(self._on_config_add_key)
        self.config_add_item = QPushButton("Add item")
        self.config_add_item.setObjectName("outline")
        self.config_add_item.setMinimumHeight(30)
        self.config_add_item.clicked.connect(self._on_config_add_item)
        self.config_remove = QPushButton("Remove")
        self.config_remove.setObjectName("outline")
        self.config_remove.setMinimumHeight(30)
        self.config_remove.clicked.connect(self._on_config_remove)
        self.config_up = QPushButton("Up")
        self.config_up.setObjectName("outline")
        self.config_up.setMinimumHeight(30)
        self.config_up.clicked.connect(lambda: self._move_config_item(-1))
        self.config_down = QPushButton("Down")
        self.config_down.setObjectName("outline")
        self.config_down.setMinimumHeight(30)
        self.config_down.clicked.connect(lambda: self._move_config_item(1))
        for button in (self.config_undo, self.config_redo, self.config_changes,
                       self.config_add_key, self.config_add_item,
                       self.config_remove, self.config_up, self.config_down):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.config_search = QLineEdit()
        self.config_search.setObjectName("configSearch")
        self.config_search.setPlaceholderText("Search keys\u2026")
        self.config_search.setClearButtonEnabled(True)
        self.config_search.setMinimumWidth(150)
        self.config_search.setMaximumWidth(190)
        self.config_search.textChanged.connect(self._apply_config_filters)
        self.config_presets = QPushButton("Presets\u2026")
        self.config_presets.setObjectName("outline")
        self.config_presets.setMinimumHeight(30)
        self.config_presets.setIconSize(QSize(14, 14))
        self.config_presets.setToolTip("Insert a ready-made OpenCore patch.")
        self.config_presets.setAccessibleName("Insert a preset")
        self.config_presets.clicked.connect(self._on_config_presets)
        header_widgets = QWidget()
        header_layout = QHBoxLayout(header_widgets)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        header_layout.addWidget(self.config_search)
        header_layout.addWidget(self.config_presets)
        self.keys_card.set_header_widget(header_widgets)
        self.keys_card.add(toolbar)

        self.config_tree = QTreeWidget()
        self.config_tree.setObjectName("configTree")
        self.config_tree.setHeaderLabels(["Key", "Value", "Type"])
        self.config_tree.setRootIsDecorated(True)
        self.config_tree.setIndentation(16)
        self.config_tree.setAllColumnsShowFocus(True)
        self.config_tree.setUniformRowHeights(True)
        self.config_tree.setAlternatingRowColors(False)
        self.config_tree.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.config_tree.setItemDelegateForColumn(1, _ConfigValueDelegate(self))
        self.config_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.config_tree.customContextMenuRequested.connect(self._config_menu)
        self.config_tree.itemChanged.connect(self._on_config_item_changed)
        self.config_tree.itemDoubleClicked.connect(
            self._on_config_double_clicked)
        self.config_tree.itemSelectionChanged.connect(self._update_config_actions)
        header = self.config_tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setStretchLastSection(False)
        self.config_tree.setColumnWidth(2, 88)
        self.keys_card.add(self.config_tree, 1)

        self.config_selection = QLabel("Select a key to edit it.")
        self.config_selection.setObjectName("rowBody")
        self.config_selection.setWordWrap(True)
        self.keys_card.add(self.config_selection)

        self.inspector_card = _Card("Selected entry")
        self.inspector_card.setFixedWidth(268)
        inspector_head = QHBoxLayout()
        inspector_head.setSpacing(8)
        self.config_inspector_icon = QLabel()
        self.config_inspector_icon.setFixedSize(28, 28)
        inspector_titles = QVBoxLayout()
        inspector_titles.setSpacing(1)
        self.config_inspector_title = QLabel("Nothing selected")
        self.config_inspector_title.setObjectName("rowTitle")
        self.config_inspector_title.setWordWrap(True)
        self.config_inspector_meta = QLabel()
        self.config_inspector_meta.setObjectName("rowBody")
        self.config_inspector_meta.setWordWrap(True)
        inspector_titles.addWidget(self.config_inspector_title)
        inspector_titles.addWidget(self.config_inspector_meta)
        inspector_head.addWidget(self.config_inspector_icon, 0, Qt.AlignTop)
        inspector_head.addLayout(inspector_titles, 1)
        self.inspector_card.add(inspector_head)

        inspector_value = QHBoxLayout()
        inspector_value.setSpacing(6)
        self.config_value_edit = QLineEdit()
        self.config_value_edit.setObjectName("configValueEdit")
        self.config_value_edit.setPlaceholderText("Value")
        self.config_value_edit.returnPressed.connect(self._apply_config_value)
        self.config_apply_value = QPushButton("Apply")
        self.config_apply_value.setObjectName("outline")
        self.config_apply_value.setMinimumHeight(30)
        self.config_apply_value.clicked.connect(self._apply_config_value)
        inspector_value.addWidget(self.config_value_edit, 1)
        inspector_value.addWidget(self.config_apply_value, 0)
        self.inspector_card.add(inspector_value)
        self.config_bool_edit = QCheckBox("On")
        self.config_bool_edit.setObjectName("configBoolEdit")
        self.config_bool_edit.toggled.connect(self._on_config_bool_toggled)
        self.inspector_card.add(self.config_bool_edit)
        self.config_edit_value = QPushButton("Edit\u2026")
        self.config_edit_value.setObjectName("outline")
        self.config_edit_value.setMinimumHeight(30)
        self.config_edit_value.clicked.connect(self._on_config_edit_value)
        self.inspector_card.add(self.config_edit_value)
        self.config_inspector_hint = QLabel("Select a key to inspect it.")
        self.config_inspector_hint.setObjectName("rowBody")
        self.config_inspector_hint.setWordWrap(True)
        self.inspector_card.add(self.config_inspector_hint)
        self.inspector_card.finish()

        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self.sections_card, 0)
        body.addWidget(self.keys_card, 1)
        body.addWidget(self.inspector_card, 0)
        layout.addLayout(body, 1)

        self.validation_card = _Card("Validation")
        self.config_validate_again = QPushButton("Validate again")
        self.config_validate_again.setObjectName("outline")
        self.config_validate_again.setMinimumHeight(28)
        self.config_validate_again.setIconSize(QSize(13, 13))
        self.config_validate_again.clicked.connect(self._on_config_validate)
        self.validation_card.set_header_widget(self.config_validate_again)
        validation_row = QHBoxLayout()
        validation_row.setSpacing(8)
        self.config_validation_icon = QLabel()
        self.config_validation_icon.setFixedSize(18, 18)
        self.config_validation_status = QLabel("Not checked yet.")
        self.config_validation_status.setObjectName("rowTitle")
        self.config_validation_note = QLabel(
            "Run Validate to check the in-memory config with ocvalidate.")
        self.config_validation_note.setObjectName("rowBody")
        self.config_validation_note.setWordWrap(True)
        validation_row.addWidget(self.config_validation_icon, 0, Qt.AlignTop)
        validation_row.addWidget(self.config_validation_status, 0, Qt.AlignTop)
        validation_row.addWidget(self.config_validation_note, 1)
        self.validation_card.add(validation_row)
        self.config_issues = QListWidget()
        self.config_issues.setObjectName("configIssues")
        self.config_issues.setMaximumHeight(76)
        self.config_issues.setVisible(False)
        self.config_issues.setSelectionMode(QAbstractItemView.SingleSelection)
        self.config_issues.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.config_issues.currentItemChanged.connect(
            self._on_config_issue_selected)
        self.validation_card.add(self.config_issues)
        self.config_issue_note = QLabel()
        self.config_issue_note.setObjectName("rowBody")
        self.config_issue_note.setWordWrap(True)
        self.config_issue_note.setVisible(False)
        self.validation_card.add(self.config_issue_note)
        layout.addWidget(self.validation_card)

        self._rebuild_config_tree()
        self._refresh_configure()
        return page

    def _compatibility_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        left_host = QWidget()
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(12)
        left.addWidget(self.files_card)
        left.addWidget(self.version_card)
        self._compat_actions = QVBoxLayout()
        self._compat_actions.setContentsMargins(0, 0, 0, 0)
        self._compat_actions.setSpacing(0)
        left.addLayout(self._compat_actions)
        left.addStretch(1)

        right_host = QWidget()
        right = QVBoxLayout(right_host)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(12)
        right.addWidget(self.devices_card, 1)
        self._compat_progress = QVBoxLayout()
        self._compat_progress.setContentsMargins(0, 0, 0, 0)
        self._compat_progress.setSpacing(0)
        right.addLayout(self._compat_progress)

        columns = _Split(left_host, right_host, spacing=16, stretch=(43, 57),
                         stack_below=800)
        layout.addWidget(columns, 1)

        self._compat_log = QVBoxLayout()
        self._compat_log.setContentsMargins(0, 0, 0, 0)
        self._compat_log.setSpacing(0)
        layout.addLayout(self._compat_log)
        return page

    def _build_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self._build_actions_slot = QWidget()
        self._build_actions_layout = QVBoxLayout(self._build_actions_slot)
        self._build_actions_layout.setContentsMargins(0, 0, 0, 0)
        self._build_actions_layout.setSpacing(0)
        self._build_progress_slot = QWidget()
        self._build_progress_layout = QVBoxLayout(self._build_progress_slot)
        self._build_progress_layout.setContentsMargins(0, 0, 0, 0)
        self._build_progress_layout.setSpacing(0)
        self._build_top = _Split(self._build_actions_slot, self._build_progress_slot,
                                 spacing=14, stretch=(0, 1), stack_below=900)
        self._build_bottom = QVBoxLayout()
        self._build_bottom.setSpacing(12)
        layout.addWidget(self._build_top)
        layout.addLayout(self._build_bottom, 1)
        return page

    def _logs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._logs_slot = QVBoxLayout()
        self._logs_slot.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._logs_slot, 1)
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.appearance_card = _Card(
            "Appearance",
            "Follows the system by default. Changes apply immediately.")
        theme_row = QHBoxLayout()
        theme_row.setSpacing(12)
        theme_label = QLabel("Theme")
        theme_label.setObjectName("detailKey")
        self.theme_combo = _Combo(LIGHT)
        self.theme_combo.setObjectName("themeCombo")
        self.theme_combo.setFixedWidth(180)
        self.theme_combo.addItems(["System", "Light", "Dark"])
        self.theme_combo.setCurrentIndex(_THEME_MODES.index(self._theme_mode))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_choice)
        theme_row.addWidget(theme_label)
        theme_row.addStretch(1)
        theme_row.addWidget(self.theme_combo)
        self.appearance_card.add(theme_row)
        self.appearance_card.finish()

        self.about_card = _Card("About")
        version = QLabel("BlackDream {}".format(RELEASE_LABEL))
        version.setObjectName("aboutVersion")
        body = QLabel(
            "An OpenCore EFI builder with a graphical front end. Compatibility "
            "checking, kext selection, and ACPI patching come from the BSD-3 "
            "licensed OpCore Simplify engine.")
        body.setObjectName("rowBody")
        body.setWordWrap(True)
        license_note = QLabel(
            "BlackDream is MIT licensed. The vendored engine keeps its BSD-3-Clause license.")
        license_note.setObjectName("rowBody")
        license_note.setWordWrap(True)
        privacy = QLabel(
            "No report is uploaded; the engine only downloads the artifacts a build needs.")
        privacy.setObjectName("rowBody")
        privacy.setWordWrap(True)
        self.about_card.add(version)
        self.about_card.add(body)
        self.about_card.add(license_note)
        self.about_card.add(privacy)
        self.about_card.finish()
        top.addWidget(self.appearance_card, 2)
        top.addWidget(self.about_card, 3)
        layout.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.storage_card = _Card(
            "Storage", "Where downloads and the tools that read firmware live.")
        for caption, path, icon_name in (
                ("Artifact cache", paths.current().cache_dir, "folder"),
                ("Runtime tools", paths.current().tools_dir, "layers")):
            self.storage_card.add(_InfoRow(
                caption, str(path), LIGHT, icon_name=icon_name, selectable=True))
        self.storage_card.finish()

        self.safety_card = _Card("Downloads and safety")
        for title, copy, icon_name in (
                ("Pinned SHA-256",
                 "Downloads are verified against pinned SHA-256 digests before the engine uses them.",
                 "shield"),
                ("Folder only",
                 "BlackDream writes an EFI folder. It never mounts, writes to, or repairs an EFI partition.",
                 "folder"),
                ("No account",
                 "No account, no telemetry, and no update check runs in the background.",
                 "fingerprint")):
            self.safety_card.add(_InfoRow(title, copy, LIGHT, icon_name=icon_name))
        self.safety_card.finish()
        bottom.addWidget(self.storage_card, 3)
        bottom.addWidget(self.safety_card, 3)
        layout.addLayout(bottom)
        layout.addStretch(1)
        return page

    def _help_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.quick_start_card = _Card(
            "Quick start", "Six steps across the three sections in the sidebar.")
        for title, copy, icon_name in _QUICK_START:
            self.quick_start_card.add(_InfoRow(title, copy, LIGHT, icon_name=icon_name))
        self.quick_start_card.finish()

        self.shortcuts_card = _Card("Keyboard shortcuts")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        for row, (action, keys) in enumerate(self._shortcut_rows()):
            label = QLabel(action)
            label.setObjectName("rowTitle")
            keycap = QLabel(keys)
            keycap.setObjectName("kbd")
            keycap.setAlignment(Qt.AlignCenter)
            keycap.setMinimumWidth(52)
            grid.addWidget(label, row, 0)
            grid.addWidget(keycap, row, 1, Qt.AlignRight)
        self.shortcuts_card.add(grid)
        self.shortcuts_card.finish()
        top.addWidget(self.quick_start_card, 3)
        top.addWidget(self.shortcuts_card, 2)
        layout.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.troubleshooting_card = _Card("Troubleshooting")
        for title, copy, icon_name in (
                ("Read the red card first",
                 "It names the failure and ends with a code such as acpi.refused. The log keeps the full sequence.",
                 "alert-triangle"),
                ("A refused ACPI read is not a fault",
                 "Nothing was read or written. Try again and accept the system authentication window.",
                 "shield"),
                ("A rejected report clears the page",
                 "Choose another Report.json; the previous machine's devices are removed on purpose.",
                 "info"),
                ("Save the log before reporting a problem",
                 "Save log\u2026 writes it to a file, and the copy button puts it on the clipboard.",
                 "save")):
            self.troubleshooting_card.add(_InfoRow(title, copy, LIGHT, icon_name=icon_name))
        self.troubleshooting_card.finish()

        self.diagnostics_card = _Card("Diagnostics")
        diagnostics = QLabel(
            "Copy a short summary for a bug report, or build a bundle you can "
            "read before you send it: app version, platform, theme, the session "
            "log, the crash report and the last validation result. Nothing is "
            "uploaded, and serial, MLB, UUID and ROM values are redacted.")
        diagnostics.setObjectName("rowBody")
        diagnostics.setWordWrap(True)
        self.copy_diagnostics_button = QPushButton("Copy environment info")
        self.copy_diagnostics_button.setObjectName("outline")
        self.copy_diagnostics_button.clicked.connect(self._copy_diagnostics)
        self.diagnostics_bundle_button = QPushButton("Save diagnostic bundle\u2026")
        self.diagnostics_bundle_button.setObjectName("outline")
        self.diagnostics_bundle_button.clicked.connect(self._on_diagnostics_bundle)
        self.diagnostics_note = QLabel("Nothing has been copied or saved.")
        self.diagnostics_note.setObjectName("dialogMuted")
        self.diagnostics_note.setWordWrap(True)
        diagnostics_row = QHBoxLayout()
        diagnostics_row.setSpacing(10)
        diagnostics_row.addWidget(self.diagnostics_bundle_button)
        diagnostics_row.addWidget(self.copy_diagnostics_button)
        diagnostics_row.addWidget(self.diagnostics_note, 1)
        self.diagnostics_card.add(diagnostics)
        self.diagnostics_card.add(diagnostics_row)
        self.diagnostics_card.finish()
        bottom.addWidget(self.troubleshooting_card, 3)
        bottom.addWidget(self.diagnostics_card, 2)
        layout.addLayout(bottom)
        layout.addStretch(1)
        return page

    def _donate_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        summary = _Card("Support the project")
        summary_copy = QLabel(
            "BlackDream is free and MIT licensed. It has no account, no telemetry and no ads.")
        summary_copy.setObjectName("rowBody")
        summary_copy.setWordWrap(True)
        summary.add(summary_copy)
        summary.finish()
        layout.addWidget(summary)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for index, (title, copy, icon_name) in enumerate((
                ("Test on real hardware",
                 "Run the check on a machine you own, then build to a spare disk. Real reports expose firmware the test suite cannot.",
                 "monitor"),
                ("Send a compatibility report",
                 "If a verdict looks wrong, include the engine log and the environment info from Help when you report it.",
                 "file"),
                ("Share the app",
                 "Pass it to someone with the same hardware. A second report on the same model is how device gaps get found.",
                 "share"),
                ("Funding",
                 "Donation links are not open yet. No payment button is shown until there is a page behind it.",
                 "heart"))):
            card = _Card(title)
            card.set_header_widget(_InfoTile(icon_name, LIGHT, 28))
            note = QLabel(copy)
            note.setObjectName("rowBody")
            note.setWordWrap(True)
            card.add(note)
            card.finish()
            grid.addWidget(card, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        return page

    @staticmethod
    def _scrollable(page: QWidget) -> QScrollArea:
        """Cards keep their own height and the page scrolls when they do not fit."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setWidget(page)
        return area

    # ---- theme ----

    def _apply_theme(self) -> None:
        self._palette = DARK if self._dark else LIGHT
        self.setStyleSheet(stylesheet(self._palette))
        self._shell.set_palette(self._palette)
        icons.clear_caches()
        application = QApplication.instance()
        if application is not None:
            # Native dialogs and menus read the application palette, not this
            # window's stylesheet.
            application.setPalette(qpalette(self._palette))
        self._sync_nav_icons()
        self.search.apply_palette(self._palette)
        self.version_icon.setPixmap(icons.tile(
            "monitor", self._palette["tileIcon"], self._palette["tileBg"], 30))
        self.report_field.apply_palette(self._palette)
        self.acpi_field.apply_palette(self._palette)
        self.output_field.apply_palette(self._palette)
        self.version_combo.apply_palette(self._palette)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(_THEME_MODES.index(self._theme_mode))
        self.theme_combo.blockSignals(False)
        self.theme_combo.apply_palette(self._palette)
        self.level_filter.apply_palette(self._palette)
        for metric in (self.metric_elapsed, self.metric_downloaded,
                       self.metric_speed):
            metric.apply_palette(self._palette)
        self._set_summary_icon(self._summary_state)
        for tile in self.findChildren(_InfoTile):
            tile.apply_palette(self._palette)
        self.collect_button.setIcon(
            icons.icon("wave", self._palette["accent"], 14))
        self.acpi_button.setIcon(
            icons.icon("layers", self._palette["accent"], 14))
        self.analyze_button.setIcon(
            icons.icon("play", "#ffffff", 15))
        self.build_button.setIcon(
            icons.icon("build", self._palette["text"], 15))
        self.cancel_button.setIcon(
            icons.icon("x", self._palette["text"], 14))
        self.reveal_button.setIcon(
            icons.icon("folder", self._palette["text"], 14))
        self.save_log_button.setIcon(
            icons.icon("save", self._palette["text"], 14))
        self.copy_log_button.setIcon(
            icons.icon("copy", self._palette["text"], 15))
        self.copy_details_button.setIcon(
            icons.icon("copy", self._palette["text"], 14))
        self.copy_diagnostics_button.setIcon(
            icons.icon("copy", self._palette["text"], 14))
        self.why_button.setIcon(
            icons.icon("info", self._palette["text"], 14))
        self.usb_combo.apply_palette(self._palette)
        self.install_version_combo.apply_palette(self._palette)
        self.efi_field.apply_palette(self._palette)
        self._refresh_installer_state()
        self._refresh_configure()
        self._status_delegate.palette = self._palette
        self.verdict_tree.viewport().update()
        for row in self._stage_widgets.values():
            row.set_palette(self._palette)
        if self._last_stages:
            self._render_stages(self._last_stages)
        if self.analysis is not None:
            self._render_verdicts(self._current_verdict.name
                                  if self._current_verdict else None)
        self._rerender_log()

    def _toggle_theme(self) -> None:
        self._set_theme_mode("light" if self._dark else "dark")

    def _on_theme_choice(self, index: int) -> None:
        if 0 <= index < len(_THEME_MODES):
            self._set_theme_mode(_THEME_MODES[index])

    def _set_theme_mode(self, mode: str) -> None:
        if mode not in _THEME_MODES:
            return
        self._theme_mode = mode
        self._settings.setValue("appearance/mode", mode)
        self._dark = self._system_dark() if mode == "system" else mode == "dark"
        self._apply_theme()

    def _on_color_scheme(self, _scheme=None) -> None:
        if self._theme_mode != "system":
            return
        dark = self._system_dark()
        if dark != self._dark:
            self._dark = dark
            self._apply_theme()

    def _sync_nav_icons(self) -> None:
        color = self._palette["muted"]
        active = self._active_section()
        for button in self.nav_buttons:
            selected = button.text() == active
            icon_color = "#ffffff" if selected else color
            button.setIcon(icons.icon(
                _NAV_ICON.get(button.text(), "dot"), icon_color, 17))
        for button in self.secondary_buttons:
            selected = button.text() == self._view
            icon_color = "#ffffff" if selected else color
            button.setIcon(icons.icon(
                _NAV_ICON.get(button.text(), "dot"), icon_color, 16))

    def _active_section(self) -> str:
        return "Build EFI" if self._view in _BUILD_VIEWS else self._view

    def _show_section(self, name: str) -> None:
        """Enter a top-level section; Build EFI remembers its last sub-view."""
        if name == "Build EFI":
            self._show_view(self._build_view)
        else:
            self._show_view(name)

    def _show_view(self, name: str) -> None:
        """Switch pages by moving the shared cards, never by copying them.

        The progress card, the action card and the log follow the user between
        views; a second log widget would drift from the ring buffer the moment a
        line was dropped, and two progress bars would disagree within one tick.
        """
        if name not in _VIEWS:
            return
        self._view = name
        if name in _BUILD_VIEWS:
            self._build_view = name
            self.build_stack.setCurrentIndex(_BUILD_VIEWS.index(name))
            self.page_stack.setCurrentWidget(self._section_pages["Build EFI"])
            for button in self.build_buttons:
                button.setChecked(
                    button.text() == ("Build" if name == "Build EFI" else name))
        else:
            self.page_stack.setCurrentWidget(self._section_pages[name])
        if name == "Compatibility":
            self._mount(self.actions_card, self._compat_actions, 0)
            if self._details_open:
                self.progress_card.setVisible(False)
                self._mount(self.details_card, self._compat_progress, 0)
                self.details_card.setVisible(True)
            else:
                self.details_card.setVisible(False)
                self._mount(self.progress_card, self._compat_progress, 0)
                self.progress_card.setVisible(True)
            self._mount(self.log_card, self._compat_log, 0)
        elif name == "Build EFI":
            self.details_card.setVisible(False)
            self.progress_card.setVisible(True)
            self._mount(self.actions_card, self._build_actions_layout, 0)
            self._build_actions_layout.setAlignment(self.actions_card, Qt.AlignTop)
            self._mount(self.progress_card, self._build_progress_layout, 0)
            self._mount(self.preflight_card, self._build_bottom, 0)
            self._mount(self.log_card, self._build_bottom, 1)
        elif name == "Logs":
            self.details_card.setVisible(False)
            self._mount(self.log_card, self._logs_slot, 1)
        # The search filters the device table, which only exists on Compatibility.
        # Leaving it on Build and Logs made typing there silently reorder a table
        # the user could not see.
        self.search.setVisible(name == "Compatibility")
        self.page_actions.setVisible(name == "Configure EFI")
        title, subtitle = _PAGE_COPY[name]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        active = self._active_section()
        for button in self.nav_buttons:
            button.setChecked(button.text() == active)
        for button in self.secondary_buttons:
            button.setChecked(button.text() == name)
        for action_name, action in self._view_actions.items():
            action.setChecked(action_name == active)
        if name == "Installer":
            self._refresh_installer_state()
            self._update_usb_detail()
            if not self._usb_scanned:
                self._usb_scanned = True
                self._refresh_usb()
        elif name == "Configure EFI":
            self._refresh_configure()
        self._sync_nav_icons()

    def _mount(self, widget: QWidget, layout, stretch: int = 0) -> None:
        current = self._placement.get(widget)
        if current is layout:
            layout.setStretch(layout.indexOf(widget), stretch)
            return
        if current is not None:
            current.removeWidget(widget)
        layout.addWidget(widget, stretch)
        self._placement[widget] = layout

    # ---- window state ----

    def closeEvent(self, event) -> None:
        self._ticker.stop()
        for runner in (self.runner, self._installer_runner, self._usb_runner,
                       self._config_runner):
            runner.cancel()
        super().closeEvent(event)

    def _install_shortcuts(self) -> None:
        self._shortcuts: list[QShortcut] = []

        def add(sequence: str, slot) -> None:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(slot)
            self._shortcuts.append(shortcut)

        # Everything else lives on a menu action, so its shortcut stays visible
        # in the menu and cannot be registered twice.
        add("Ctrl+K", self._focus_search)

    @staticmethod
    def _shortcut_rows() -> tuple[tuple[str, str], ...]:
        return _SHORTCUTS_MAC if sys.platform == "darwin" else _SHORTCUTS_CTRL

    def _focus_search(self) -> None:
        self._show_view("Compatibility")
        self.search.search_input.setFocus()
        self.search.search_input.selectAll()

    # ---- paths and drag/drop ----

    @staticmethod
    def _default_output() -> Path:
        return paths.current().cache_dir.parent / "builds" / time.strftime("%Y%m%d-%H%M")

    def _pick_report(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Hardware report", str(Path.home()),
            "Hardware reports (Report.json *.json);;All files (*)")
        if path:
            self.set_report(path)

    def _pick_acpi_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "ACPI tables folder", str(Path.home()))
        if path:
            self.set_acpi_dir(path)

    def _pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Output folder", str(Path.home()))
        if path:
            self.set_output_dir(str(Path(path) / "EFI"))

    def set_acpi_dir(self, path: str) -> None:
        self.acpi_field.set_value(path)
        self._validate_acpi()

    def set_output_dir(self, path: str) -> None:
        self.output_field.set_value(path)
        self._validate_output()

    def _validate_acpi(self) -> None:
        """A fact about the folder, not a promise about the build."""
        folder = self.acpi_field.value()
        if not folder:
            self.acpi_field.set_state("empty", "No folder chosen")
            return
        count = _aml_tables(folder)
        if count < 0:
            self.acpi_field.set_state("error", "Folder does not exist")
        elif count == 0:
            self.acpi_field.set_state("warn", "No .aml files here")
        else:
            self.acpi_field.set_state("ok", "{} .aml file(s) found".format(count))

    def _validate_output(self) -> None:
        """Judge the nearest folder that exists, not the leaf the build will create."""
        folder = self.output_field.value()
        if not folder:
            self.output_field.set_state("empty", "No folder chosen")
            return
        path = Path(folder)
        existing = path.parent
        while existing != existing.parent and not existing.exists():
            existing = existing.parent
        if not os.access(str(existing), os.W_OK | os.X_OK):
            self.output_field.set_state("error", "Not writable")
        elif path.exists():
            if (path / OUTPUT_MARKER).is_file():
                self.output_field.set_state("ok", "Replaces a previous BlackDream build")
            else:
                try:
                    is_empty = not any(path.iterdir())
                except OSError:
                    is_empty = False
                if is_empty:
                    self.output_field.set_state("ok", "Exists and is writable")
                else:
                    self.output_field.set_state("error", "Folder is not empty")
        else:
            self.output_field.set_state("ok", "Will be created")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if not self._chain and _dropped_json(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        path = _dropped_json(event)
        if path:
            self.set_report(path)
            event.acceptProposedAction()

    def set_report(self, path: str | Path) -> None:
        """Loading a report starts a fresh session: an engine run mutates its own
        kext and ACPI copies, so a second report must not inherit the first.

        A running chain owns the pipeline. Replacing it now would leave the next
        step building from a different session than the one that selected its
        kexts, so the report is refused until the step stops.
        """
        if self._chain:
            self._show_error(EngineError(detail=(
                "A step is still running. Let it finish or cancel it before "
                "opening another report.")))
            return
        self._report_path = Path(path)
        self.report_field.set_value(str(self._report_path))
        self.report_field.set_state("warn", "Checking\u2026")
        self._pipeline = None
        self._clear_analysis()
        self._summarise("Checking {}\u2026".format(self._report_path.name), "empty")
        self.summary_note.setText(
            "Support ranges come from the report's own compatibility data.")
        self._filter_text = ""
        self.search.search_input.clear()
        self._result_dir = None
        self.reveal_button.setEnabled(False)
        self._show_view("Compatibility")
        self._on_analyze()

    def _clear_analysis(self, rejected: bool = False) -> None:
        """Forget the graded report and every widget that was showing it.

        A rejected report must not inherit the previous report's devices,
        versions or task text: the error card would describe one machine while
        the rest of the page still described another.
        """
        self.analysis = None
        self.plan = None
        self._options = []
        self._verdicts = []
        self._items = []
        self.verdict_tree.clear()
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.blockSignals(False)
        self._reset_details()
        self.empty_note.setVisible(True)
        if rejected:
            self.devices_card.set_hint("No devices were graded from this report.")
            self.empty_note.setText(
                "The engine rejected this report before grading any device.")
        else:
            self.devices_card.set_hint("No report loaded yet.")
            self.empty_note.setText(
                "Load a report to see this machine's devices and what macOS does "
                "with them.")
        self.build_button.setEnabled(False)

    # ---- jobs ----

    def _ensure_pipeline(self) -> Pipeline:
        if self._pipeline is None:
            self._pipeline = Pipeline()
        return self._pipeline

    def _start(self, steps: list[_Step]) -> None:
        self._chain = list(steps)
        self._show_error(None)
        self._run_next()

    def _run_next(self) -> None:
        step = self._chain[0]
        self._set_ticker_interval(True)
        self._set_busy(True, step.name)
        self._log_line("info", "== {} ==".format(step.name))
        if not self.runner.start(Job(name=step.name, body=step.body, timeout=step.timeout)):
            self._chain = []
            self._set_busy(False)
            self._show_error(EngineError(detail=(
                "The previous step is still finishing. Its engine objects are in use, "
                "so starting another now would corrupt this session.")))

    def _on_collect(self) -> None:
        """Scan this machine, rather than asking for a file someone else generated.

        ``collect_hardware`` owns the platform choice: the built-in scan on Linux,
        the verified Hardware Sniffer CLI on Windows. Both return a Collected, and
        the timeout covers the Windows tool's download as well as its scan.
        """
        target = self._scan_dir()

        def body(token):
            return hardware.collect_hardware(
                target, is_cancelled=lambda: token.cancelled)

        self._start([_Step("Collecting hardware", body, self._after_collect,
                           timeout=hardware.collect_timeout())])

    def _after_collect(self, outcome: Outcome) -> None:
        collected = outcome.value
        self._log_line("info", "{} hardware sections written to {}".format(
            len(collected.report), collected.report_path))
        if collected.acpi_dir is not None:
            tables = len(list(collected.acpi_dir.glob("*.aml")))
            self._log_line("info", "{} ACPI tables exported with the report".format(tables))
            self.set_acpi_dir(str(collected.acpi_dir))
        # set_report starts its own chain, and this callback runs while _on_outcome is
        # still holding the finished step. Starting from here would run the next step
        # twice, so it goes on the event loop instead.
        QTimer.singleShot(0, lambda: self.set_report(collected.report_path))

    @staticmethod
    def _scan_dir() -> Path:
        return paths.current().cache_dir.parent / "reports" / time.strftime("%Y%m%d-%H%M")

    def _on_dump_acpi(self) -> None:
        """Make the ACPI folder the build needs, from the firmware in front of us."""
        target = self._report_path.parent if self._report_path else self._scan_dir()

        def body(token):
            return hardware.AcpiDumper().dump(target, is_cancelled=lambda: token.cancelled)

        self._start([_Step("Reading ACPI tables", body, self._after_dump_acpi, timeout=260)])

    def _after_dump_acpi(self, outcome: Outcome) -> None:
        dumped = outcome.value
        self._log_line("info", "{} ACPI tables read from firmware".format(len(dumped.tables)))
        self.set_acpi_dir(str(dumped.acpi_dir))

    def _on_analyze(self) -> None:
        if not self._report_path:
            self._show_error(EngineError(detail=(
                "Choose a Report.json first. You can drop the file anywhere in this window.")))
            return
        report = str(self._report_path)

        def body(token):
            pipeline = self._ensure_pipeline()
            data = pipeline.load_report(report)
            token.check()
            analysis = pipeline.analyze(data)
            token.check()
            return analysis, pipeline.version_choices(analysis)

        self._start([_Step("Checking compatibility", body, self._after_analyze, timeout=180)])

    def _after_analyze(self, outcome: Outcome) -> None:
        analysis, options = outcome.value
        self.analysis = analysis
        self.report_field.set_state("ok", "Graded")
        self._populate_versions(options)
        self._render_verdicts()
        summary = "Native support: {}".format(
            verdicts.friendly_range(analysis.native_range))
        if analysis.oclp_range:
            summary += "\nWith OpenCore Legacy Patcher: {}".format(
                verdicts.friendly_range(analysis.oclp_range))
        self._summarise(summary, "ok")
        self._update_summary_note()
        self._log_line("info", "Graded {} devices".format(len(self._verdicts)))
        self._task_stage = ""
        self.task_name.setText("Ready to build")
        self.task_detail.setText("Choose a macOS version, then build the EFI folder.")

    def _populate_versions(self, options) -> None:
        self._options = list(options)
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        suggested = 0
        for index, option in enumerate(self._options):
            badges = []
            if option.is_suggested:
                badges.append("suggested")
            if option.requires_oclp:
                badges.append("needs OCLP")
            label = "{}  \u00b7  {}".format(option.name, ", ".join(badges)) if badges \
                else option.name
            self.version_combo.addItem(label, option.value)
            self.version_combo.setItemData(index, label, Qt.ToolTipRole)
            if option.is_suggested:
                suggested = index
        self.version_combo.setPlaceholderText(
            "Load a report to choose a version" if not self._options else "")
        self.version_combo.setCurrentIndex(suggested)
        self.version_combo.setEnabled(bool(self._options) and not self.runner.busy)
        self.version_combo.blockSignals(False)
        self._update_summary_note()

    def _on_build(self) -> None:
        if self._installer_runner.busy or self._config_runner.busy:
            self._show_error(BuildNotReady(
                detail="The installer is still working.",
                remediation=("Wait for it to finish, or cancel it on the "
                             "Installer page.",)))
            return
        if self.analysis is None or self.version_combo.currentData() is None:
            return
        output = self.output_field.value()
        if not output:
            self._show_error(EngineError(detail="Choose an output folder for the EFI build."))
            return
        # The pipeline refuses a foreign non-empty folder without touching it, but
        # that failure would only surface after the download stage has run.
        self._validate_output()
        if self.output_field.state_key == "error":
            self._show_error(BuildNotReady(
                detail="The output folder cannot be used: {}.".format(
                    self.output_field.note.rstrip(".").lower()),
                remediation=("Choose a different output folder, or empty that one "
                             "yourself first.",)))
            return
        version = str(self.version_combo.currentData())
        acpi_dir = self.acpi_field.value() or None
        result_dir = Path(output)
        analysis = self.analysis
        self._result_dir = result_dir
        self._build_started = time.monotonic()
        self._transfer_bytes.clear()
        self._last_rate = 0.0
        self._reset_progress()
        self._build_started = time.monotonic()

        def configure(token):
            token.check()
            return self._ensure_pipeline().configure(analysis, version, acpi_dir=acpi_dir)

        def gather(token):
            return self._ensure_pipeline().gather_artifacts(self.plan, token=token)

        def emit(token):
            return self._ensure_pipeline().build(self.plan, result_dir, token=token)

        self.reveal_button.setEnabled(False)
        self._start([
            _Step("Selecting patches and kexts", configure, self._after_configure, timeout=300),
            _Step("Downloading OpenCore and kexts", gather, None, timeout=1800),
            _Step("Writing the EFI folder", emit, self._after_build, timeout=900),
        ])

    def _after_configure(self, outcome: Outcome) -> None:
        self.plan = outcome.value
        self._log_line("info", "SMBIOS model: {}".format(self.plan.smbios_model))

    def _after_build(self, outcome: Outcome) -> None:
        result = Path(outcome.value)
        self._result_dir = result
        self._settings.setValue("build/last_output", str(result))
        self._set_efi_folder(str(result), persist=True)
        self.statusBar().showMessage("EFI folder written to {}".format(result))
        self._log_line("info", "Done: {}".format(result))
        self.reveal_button.setEnabled(True)
        self._finish_progress(result)
        self._write_manifest(result)
        self._on_preflight(result)

    # ---- folder checks ----

    def _manifest_metadata(self) -> dict:
        return {
            "version": __version__,
            "release_label": RELEASE_LABEL,
            "macos": str(self.version_combo.currentData() or ""),
            "smbios_model": str(getattr(self.plan, "smbios_model", "") or ""),
            "validator": "ocvalidate {}".format(config_editor.OPEN_CORE_VERSION),
        }

    def _write_manifest(self, folder: Path) -> None:
        try:
            path = efi_manifest.write(
                folder, build=self._manifest_metadata(),
                validation={"ocvalidate": "not run during build"})
        except (OSError, efi_manifest.ManifestError) as exc:
            self._log_line("warning", "The manifest could not be written: {}".format(exc))
            return
        self._log_line("info", "Manifest written: {}".format(path.name))

    @staticmethod
    def _folder_root(folder) -> Path | None:
        """The folder that contains EFI; accepts the EFI folder itself too."""
        path = Path(folder)
        if (path / "EFI" / "OC" / "config.plist").is_file():
            return path
        if (path.name.casefold() == "efi"
                and (path / "OC" / "config.plist").is_file()):
            return path.parent
        return None

    def _preflight_root(self) -> Path | None:
        for folder in (self._efi_folder, self._result_dir):
            if folder is None:
                continue
            root = self._folder_root(folder)
            if root is not None:
                return root
        return None

    def _render_preflight(self, status: str, note: str, rows, text: str) -> None:
        self.preflight_status.setText(status)
        self.preflight_note.setText(note)
        self.preflight_list.clear()
        for label, tooltip in rows:
            item = QListWidgetItem(label)
            item.setToolTip(tooltip)
            self.preflight_list.addItem(item)
        self.preflight_list.setVisible(bool(rows))
        self._preflight_text = text
        self.preflight_export.setEnabled(bool(text))

    def _on_preflight(self, folder=None) -> None:
        root = Path(folder) if folder is not None else self._preflight_root()
        if root is None:
            self._preflight = None
            self._render_preflight(
                "No EFI folder to check.",
                "Build an EFI folder, or choose one on the Installer page.",
                (), "")
            return
        try:
            report = efi_preflight.analyse(root)
        except efi_preflight.PreflightError as exc:
            self._preflight = None
            self._render_preflight("This folder cannot be read.", str(exc), (), "")
            return
        self._preflight = report
        rows = [(
            "[{}] {} \u00b7 {}".format(
                finding.severity.upper(), finding.where, finding.message),
            "Evidence: {}\nNext: {}".format(finding.evidence, finding.action),
        ) for finding in report.findings]
        self._render_preflight(
            report.summary,
            "Read {} file{}. These checks do not test firmware, hardware or "
            "whether macOS boots.".format(
                report.files, "" if report.files == 1 else "s"),
            rows, efi_preflight.to_text(report))
        self._log_line(
            "warning" if report.errors else "info",
            "Folder checks: {}".format(report.summary))

    def _on_verify_manifest(self) -> None:
        root = self._preflight_root()
        if root is None:
            self._render_preflight(
                "No EFI folder to check.",
                "Build an EFI folder, or choose one on the Installer page.",
                (), "")
            return
        try:
            result = efi_manifest.verify(root)
        except efi_manifest.ManifestError as exc:
            self._render_preflight(
                "There is no manifest to verify.",
                "{} A manifest is written beside the folder after a build.".format(exc),
                (), "")
            return
        rows = [(
            "[{}] {}".format(item.kind.upper(), item.path),
            "Recorded: {}\nFound: {}".format(
                (item.recorded or "nothing")[:16], (item.found or "nothing")[:16]),
        ) for item in result.differences]
        self._render_preflight(
            result.summary,
            "A match proves these files are the ones recorded at build time. It "
            "does not prove the folder boots.",
            rows, efi_manifest.to_text(result))
        self._log_line(
            "warning" if result.differences else "info",
            "Manifest: {}".format(result.summary))

    def _on_preflight_export(self) -> None:
        if not self._preflight_text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the folder report",
            str(Path.home() / "blackdream-folder-checks.txt"),
            "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            Path(path).write_text(self._preflight_text, encoding="utf-8")
        except OSError as exc:
            self._show_error(EngineError(detail=str(exc)))
            return
        self.statusBar().showMessage("Report saved to {}".format(path))

    # ---- installer section ----

    def _refresh_installer_state(self) -> None:
        if not hasattr(self, "installer_status"):
            return
        palette = getattr(self, "_palette", LIGHT)
        self.install_version_icon.setPixmap(icons.tile(
            "monitor", palette["tileIcon"], palette["tileBg"], 30))
        self.installer_icon.setPixmap(icons.tile(
            "download", palette["tileIcon"], palette["tileBg"], 30))
        self.usb_icon.setPixmap(icons.tile(
            "usb", palette["tileIcon"], palette["tileBg"], 30))
        self.install_download_button.setIcon(
            icons.icon("download", "#ffffff", 15))
        self.install_cancel_button.setIcon(
            icons.icon("x", palette["text"], 14))
        self.install_write_button.setIcon(
            icons.icon("drive", "#ffffff", 15))
        if self._recovery is not None:
            self.installer_status.setText(
                "Verified \u00b7 {}".format(_format_size(self._recovery.size)))
            digest = (self._recovery.sha256 or "")[:12]
            self.installer_detail.setText(
                "{} \u00b7 {} \u00b7 SHA-256 {}\u2026".format(
                    self._installer_release.label,
                    self._recovery.product or "macOS recovery", digest))
        else:
            self.installer_status.setText("Not downloaded yet.")
            self.installer_detail.setText(
                "About 1 GB. A dropped connection resumes where it stopped.")
        if not self._installer_runner.busy:
            self.installer_progress.setVisible(False)
        self.install_download_button.setText(
            "Download again" if self._recovery is not None else "Download installer")
        self._update_installer_ready()

    def _on_installer_version_changed(self, _index: int = -1) -> None:
        release = self.install_version_combo.currentData()
        if release is None or release == self._installer_release:
            return
        self._installer_release = release
        self._settings.setValue("installer/release", release.version)
        # The cached image and the write target follow the selection: an image
        # downloaded for another release must never satisfy this one.
        self._recovery = installer_core.cached_recovery(release)
        self._refresh_installer_state()

    def _update_installer_ready(self) -> None:
        if not hasattr(self, "install_write_button"):
            return
        busy = self._installer_runner.busy
        blocked = busy or self.runner.busy or self._config_runner.busy
        self.install_version_combo.setEnabled(not busy)
        self.install_download_button.setEnabled(not blocked)
        self.install_cancel_button.setEnabled(busy)
        self.install_write_button.setEnabled(
            not blocked and self._recovery is not None
            and self._efi_folder is not None
            and self._selected_volume() is not None)

    def _on_download_installer(self) -> None:
        if self.runner.busy or self._config_runner.busy:
            self.installer_detail.setText(
                "Wait for the other task to finish before downloading.")
            return
        if self._installer_runner.busy:
            return
        self._show_error(None)
        self._installer_job = "download"
        release = self._installer_release
        self.installer_progress.setValue(0)
        self.installer_progress.setVisible(True)
        self.installer_status.setText("Downloading the recovery image\u2026")
        self.installer_detail.setText("Starting\u2026")
        self._installer_runner.start(Job(
            "Downloading macOS recovery",
            lambda token: installer_core.download_recovery(
                release=release, token=token),
            timeout=3600))
        self._update_installer_ready()

    def _on_installer_cancel(self) -> None:
        if self._installer_runner.cancel():
            self.installer_status.setText("Cancelling\u2026")
            self.install_cancel_button.setEnabled(False)

    def _on_write_installer(self) -> None:
        volume = self._selected_volume()
        recovery = self._recovery
        efi = self._efi_folder
        if volume is None or recovery is None or efi is None:
            self.usb_note.setText(
                "Choose a drive and a complete EFI folder, and download the "
                "installer first.")
            return
        if self.runner.busy or self._config_runner.busy or self._installer_runner.busy:
            self.usb_note.setText("Wait for the other task to finish.")
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Write installer?")
        box.setText("Write the installer to {}?".format(
            volume.label or str(volume.mount)))
        box.setInformativeText(
            "EFI and com.apple.recovery.boot will be replaced. Everything else on "
            "the drive is left alone, and the drive is not formatted.")
        confirm = box.addButton("Write installer", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is not confirm:
            return
        self._show_error(None)
        self._installer_job = "write"
        self.installer_progress.setValue(0)
        self.installer_progress.setVisible(True)
        self.installer_status.setText("Writing the installer\u2026")
        self.installer_detail.setText("Starting\u2026")
        self._installer_runner.start(Job(
            "Writing the installer",
            lambda token: installer_core.write_installer(
                volume, efi, recovery, token=token),
            timeout=3600))
        self._update_installer_ready()

    def _on_installer_outcome(self, outcome: Outcome) -> None:
        job, self._installer_job = self._installer_job, ""
        self.installer_progress.setVisible(False)
        if outcome.status == CANCELLED:
            self._log_line("info", "{} cancelled.".format(outcome.job))
        elif outcome.ok:
            if job == "download":
                self._recovery = outcome.value
                self._log_line("info", "Recovery image verified and cached.")
                self.installer_progress.setValue(100)
            else:
                mount = str(outcome.value.get("mount", "")) if isinstance(
                    outcome.value, dict) else ""
                self._log_line("info", "Installer written to {}.".format(mount))
                QMessageBox.information(
                    self, "Installer written",
                    "The installer is on {}.\n\nEject the drive before unplugging "
                    "it.".format(mount))
        else:
            self._show_error(outcome.error)
            self._log_line("error", str(
                outcome.error.detail if outcome.error else outcome.status))
        self._refresh_installer_state()
        # _refresh_installer_state describes what is cached, so terminal messages
        # are applied after it or they are overwritten in the same tick.
        if outcome.status == CANCELLED:
            self.installer_status.setText("Cancelled.")
        elif not outcome.ok:
            self.installer_status.setText("The installer task failed.")
        elif job == "write" and isinstance(outcome.value, dict):
            self.installer_status.setText(
                "Installer written to {}.".format(outcome.value.get("mount", "")))

    def _render_installer_transfer(self, transfer) -> None:
        fraction = transfer.fraction
        if fraction is not None:
            self.installer_progress.setValue(round(fraction * 100))
        self.installer_progress.setVisible(True)
        self.installer_status.setText(transfer.product)
        if transfer.total_bytes:
            self.installer_detail.setText("{} of {}{}".format(
                _format_size(transfer.done_bytes),
                _format_size(transfer.total_bytes),
                "" if fraction is None else " \u00b7 {:.0f}%".format(
                    fraction * 100)))
        else:
            self.installer_detail.setText(
                "{} downloaded".format(_format_size(transfer.done_bytes)))

    def _refresh_usb(self) -> None:
        if self._usb_runner.busy:
            return
        self.usb_refresh.setEnabled(False)
        self.usb_note.setText("Looking for USB drives\u2026")
        self._usb_runner.start(Job(
            "Finding USB drives", lambda token: installer_core.list_usb_volumes(),
            timeout=90))

    def _after_usb_scan(self, outcome: Outcome) -> None:
        self.usb_refresh.setEnabled(True)
        if outcome.ok:
            self._usb_volumes = list(outcome.value or [])
        else:
            self._usb_volumes = []
            self._log_line("warning", "USB scan failed: {}".format(
                outcome.error.detail if outcome.error else outcome.status))
        selected = self.usb_combo.currentData()
        self.usb_combo.blockSignals(True)
        self.usb_combo.clear()
        for volume in self._usb_volumes:
            self.usb_combo.addItem(volume.display, volume.identity)
        index = self.usb_combo.findData(selected) if selected else -1
        # Adding the first item selects it. A destructive target must be chosen
        # on purpose, so no volume is selected until the user picks one.
        self.usb_combo.setCurrentIndex(index)
        if self._usb_volumes:
            self.usb_combo.setPlaceholderText("Choose a USB drive")
        else:
            self.usb_combo.setPlaceholderText("No FAT32 USB drive found")
        self.usb_combo.blockSignals(False)
        self._update_usb_detail()

    def _selected_volume(self):
        if not hasattr(self, "usb_combo"):
            return None
        identity = self.usb_combo.currentData()
        for volume in self._usb_volumes:
            if volume.identity == identity:
                return volume
        return None

    def _on_usb_selected(self, _index: int = -1) -> None:
        self._update_usb_detail()

    def _update_usb_detail(self) -> None:
        if not hasattr(self, "usb_note"):
            return
        volume = self._selected_volume()
        if volume is not None:
            self.usb_note.setText("{} \u00b7 {:.1f} GB free of {:.1f} GB".format(
                volume.device, volume.free / 1_000_000_000,
                volume.size / 1_000_000_000))
        elif self._usb_volumes:
            self.usb_note.setText("Choose a drive.")
        else:
            self.usb_note.setText(
                "No FAT32 USB drive is mounted. Plug one in, then choose Refresh.")
        self._update_installer_ready()

    def _pick_efi_folder(self) -> None:
        start = self.efi_field.value() if hasattr(self, "efi_field") else ""
        if not start and self._result_dir is not None:
            start = str(self._result_dir)
        path = QFileDialog.getExistingDirectory(
            self, "Choose the built EFI folder", start or str(Path.home()))
        if path:
            self._set_efi_folder(path)

    def _set_efi_folder(self, path: str, persist: bool = True) -> None:
        self.efi_field.set_value(str(path))
        if persist:
            self._settings.setValue("installer/efi_folder", str(path))
        self._validate_efi_field()
        self._refresh_configure()

    def _validate_efi_field(self) -> None:
        if not hasattr(self, "efi_field"):
            return
        value = self.efi_field.value()
        if not value:
            self._efi_folder = None
            self.efi_field.set_state("empty", "Choose the EFI folder this app built.")
        else:
            try:
                self._efi_folder = installer_core.validate_efi_folder(Path(value))
                self.efi_field.set_state(
                    "ok", "A complete OpenCore EFI folder.")
            except (EngineError, OSError) as exc:
                self._efi_folder = None
                self.efi_field.set_state("error", str(
                    getattr(exc, "detail", "") or exc))
        self._update_installer_ready()

    # ---- configure section ----

    def _config_path(self) -> Path | None:
        for folder in (self._efi_folder, self._result_dir):
            if folder is None:
                continue
            try:
                efi = installer_core.validate_efi_folder(Path(folder))
            except (EngineError, OSError):
                continue
            config = efi / "OC" / "config.plist"
            if config.is_file():
                return config
        return None

    def _load_config(self, path, origin: str, quiet: bool = False) -> bool:
        try:
            document = config_editor.ConfigDocument.load(path)
        except config_editor.ConfigEditorError as exc:
            if not quiet:
                self._show_error(exc)
            self._config_note = "The file could not be read: {}".format(
                getattr(exc, "detail", "") or exc)
            self._render_config_state()
            return False
        self._config_doc = document
        self._config_history = config_diff.History(document.data)
        self._config_origin = origin
        self._config_note = ""
        self._config_revision += 1
        self._config_validation = None
        self._config_validate_revision = -1
        self._rebuild_config_tree()
        return True

    def _refresh_configure(self) -> None:
        """Reconcile the editor with the file the build says is current."""
        if not hasattr(self, "config_status"):
            return
        palette = getattr(self, "_palette", LIGHT)
        self.config_icon.setPixmap(icons.tile(
            "file", palette["tileIcon"], palette["tileBg"], 30))
        self.config_save.setIcon(icons.icon("save", "#ffffff", 15))
        self.config_validate.setIcon(icons.icon("check", palette["text"], 14))
        self.config_validate_again.setIcon(
            icons.icon("check", palette["text"], 13))
        self.config_open.setIcon(icons.icon("folder", palette["text"], 14))
        self.config_serials.setIcon(icons.icon("sliders", palette["text"], 14))
        self.config_reveal.setIcon(icons.icon("folder", palette["text"], 14))
        self.config_presets.setIcon(icons.icon("book", palette["text"], 14))
        self._render_config_section_icons()
        target = self._config_path()
        self._built_config = target
        document = self._config_doc
        # A build replaces the file on disk. Reload it only while the editor has
        # nothing to lose: unsaved edits and a file the user opened themselves
        # both outrank a background result.
        if target is not None and (
                document is None
                or (self._config_origin == "built" and document.path != target
                    and not document.is_dirty())):
            self._load_config(target, origin="built", quiet=True)
        self._render_config_state()

    def _render_config_state(self) -> None:
        if not hasattr(self, "config_status"):
            return
        document = self._config_doc
        busy = self._config_runner.busy
        dirty = bool(document is not None and document.is_dirty())
        external = bool(document is not None and document.changed_on_disk())
        built = self._built_config

        if document is None:
            if built is not None:
                status = "The config.plist could not be read."
                self.config_path.set_full_text(str(built))
            else:
                status = "No built config.plist yet."
                self.config_path.set_full_text(
                    "Build an EFI folder in Build EFI, then return here.")
            if self._config_note:
                detail = self._config_note
            elif built is not None:
                detail = ("Open another config.plist, or build the EFI folder "
                          "again.")
            else:
                detail = ("Build an EFI folder in Build EFI, or open any "
                          "OpenCore config.plist.")
        else:
            if external and dirty:
                status = "Changed on disk; unsaved edits here."
            elif external:
                status = "Changed on disk."
            elif dirty:
                status = "Unsaved changes"
            else:
                status = "config.plist is open"
            self.config_path.set_full_text(str(document.path))
            if self._config_note:
                detail = self._config_note
            elif external:
                detail = ("The file changed on disk. Revert to load that "
                          "version, or save to replace it.")
            elif dirty:
                detail = ("Unsaved changes are only in memory until you press "
                          "Save.")
            else:
                detail = ("Every key is editable, and keys this build does not "
                          "know are kept.")
        self.config_status.setText(status)
        self.config_detail.setText(detail)
        self.config_progress.setVisible(busy)
        self.config_save.setEnabled(document is not None and dirty and not busy)
        self.config_validate.setEnabled(document is not None and not busy)
        self.config_serials.setEnabled(document is not None and not busy)
        self.config_open.setEnabled(not busy)
        self.config_revert.setEnabled(
            document is not None and (dirty or external) and not busy)
        self.config_reveal.setEnabled(
            (document is not None or built is not None) and not busy)
        self.config_tree.setEnabled(document is not None and not busy)
        self.config_search.setEnabled(document is not None)
        self.config_sections.setEnabled(document is not None and not busy)
        self.config_validate_again.setEnabled(document is not None and not busy)
        self.config_presets.setEnabled(document is not None and not busy)
        self._render_validation_state()
        self._update_config_actions()

    def _set_config_chip(self, chip: QLabel, text: str, state: str) -> None:
        chip.setText(text)
        if chip.property("state") != state:
            chip.setProperty("state", state)
            chip.style().unpolish(chip)
            chip.style().polish(chip)

    def _render_validation_state(self) -> None:
        if not hasattr(self, "config_validation_status"):
            return
        palette = getattr(self, "_palette", LIGHT)
        result = self._config_validation
        current = (result is not None and self._config_doc is not None
                   and self._config_validate_revision == self._config_revision)
        # The worker can finish before its queued outcome reaches the GUI; keep
        # the card in "checking" until that outcome actually renders.
        busy = self._config_job == "validate"
        lines = ()
        if busy:
            status = "Checking\u2026"
            note = "ocvalidate is checking the in-memory config."
            icon, state, chip = "spinner", "muted", "Checking\u2026"
        elif not current:
            status = "Not checked yet."
            note = "Run Validate to check the in-memory config with ocvalidate."
            icon, state, chip = "pulse", "muted", "Not validated"
        elif result.ok:
            status = result.summary
            note = "Checked in memory; the copy on disk is unchanged."
            icon, state, chip = "check-circle", "ok", "Valid"
        else:
            count = len(result.issues)
            status = result.summary
            note = "Checked in memory; the copy on disk is unchanged."
            icon, state = "alert-triangle", "warn"
            chip = "{} issue{}".format(count, "" if count == 1 else "s")
            lines = result.issues or tuple(
                line for line in (result.output or "").splitlines() if line.strip())
        self.config_validation_status.setText(status)
        self.config_validation_note.setText(note)
        color = {"ok": palette["ok"], "warn": palette["warn"]}.get(
            state, palette["muted"])
        if icon == "spinner":
            self.config_validation_icon.setPixmap(icons.spinner(color, 18, 0))
        else:
            self.config_validation_icon.setPixmap(icons.pixmap(icon, color, 18))
        self._render_config_issues(lines)
        self._set_config_chip(self.config_validation_chip, chip, state)

    def _render_config_issues(self, lines) -> None:
        """One row per validator line, each keeping the message exactly as written."""
        self.config_issues.clear()
        self.config_issue_note.setVisible(bool(lines))
        self.config_issue_note.setText(
            "Select an issue to go to the key it names." if lines else "")
        document = self._config_doc
        if document is None:
            return
        for raw in lines:
            explanation = validation_assistant.explain(raw, document.data)
            item = QListWidgetItem(raw)
            item.setData(Qt.UserRole, explanation.path)
            item.setData(Qt.UserRole + 1, explanation.message)
            if explanation.path is None:
                item.setToolTip(
                    "This line does not name one key. It is shown as ocvalidate "
                    "wrote it.")
            else:
                item.setToolTip("Go to {}".format(
                    config_diff.path_label(explanation.path)))
            self.config_issues.addItem(item)
        self.config_issues.setVisible(bool(lines))

    def _on_config_issue_selected(self, current, _previous=None) -> None:
        if current is None or self._config_doc is None:
            return
        path = current.data(Qt.UserRole)
        explanation = current.data(Qt.UserRole + 1)
        if path:
            self.config_issue_note.setText("{}  \u00b7  jumped to {}".format(
                explanation or current.text(),
                config_diff.path_label(path)))
            self._select_config_path(tuple(path))
        else:
            self.config_issue_note.setText(
                explanation or
                "This line does not name one key; the message is shown as "
                "ocvalidate wrote it.")

    def _config_selected_path(self) -> tuple | None:
        item = self.config_tree.currentItem()
        if item is None:
            return None
        path = item.data(0, Qt.UserRole)
        return tuple(path) if path else None

    def _config_dict_target(self, path):
        """The dictionary a new key would go into for the selected node."""
        if self._config_doc is None or path is None:
            return None
        try:
            value = config_editor.get_at(self._config_doc.data, path)
            parent = config_editor.get_at(self._config_doc.data, path[:-1])
        except (KeyError, IndexError, TypeError):
            return None
        if isinstance(value, dict):
            return path
        if isinstance(value, list):
            return None
        if isinstance(parent, dict):
            return path[:-1]
        return None

    def _config_array_target(self, path):
        """The array a new item would go into for the selected node."""
        if self._config_doc is None or path is None:
            return None
        try:
            value = config_editor.get_at(self._config_doc.data, path)
            parent = config_editor.get_at(self._config_doc.data, path[:-1])
        except (KeyError, IndexError, TypeError):
            return None
        if isinstance(value, list):
            return path
        if isinstance(parent, list):
            return path[:-1]
        return None

    def _update_config_actions(self) -> None:
        if not hasattr(self, "config_tree"):
            return
        document = self._config_doc
        busy = self._config_runner.busy
        ready = document is not None and not busy
        path = self._config_selected_path() if document is not None else None
        self.config_add_key.setEnabled(
            ready and self._config_dict_target(path) is not None)
        self.config_add_item.setEnabled(
            ready and self._config_array_target(path) is not None)
        self.config_remove.setEnabled(ready and path is not None)
        movable = bool(path) and isinstance(path[-1], int)
        position = path[-1] if movable else 0
        self.config_up.setEnabled(ready and movable and position > 0)
        length = 0
        if movable:
            try:
                length = len(config_editor.get_at(document.data, path[:-1]))
            except (KeyError, IndexError, TypeError):
                length = 0
        self.config_down.setEnabled(
            ready and movable and position + 1 < length)
        history = self._config_history
        self.config_undo.setEnabled(ready and bool(history and history.can_undo))
        self.config_redo.setEnabled(ready and bool(history and history.can_redo))
        self.config_changes.setEnabled(ready and history is not None)
        if history is not None and history.can_undo:
            self.config_undo.setToolTip("Undo {}".format(history.undo_label))
        else:
            self.config_undo.setToolTip("Nothing to undo")
        if history is not None and history.can_redo:
            self.config_redo.setToolTip("Redo {}".format(history.redo_label))
        else:
            self.config_redo.setToolTip("Nothing to redo")
        if history is not None:
            count = len(history.changes())
            self.config_changes.setText(
                "Changes ({})\u2026".format(count) if count else "Changes\u2026")
        if path is None:
            self.config_selection.setText(
                "Select a key to edit it." if document is not None
                else "No config.plist is open.")
            self._refresh_config_inspector()
            return
        try:
            value = config_editor.get_at(document.data, path)
        except (KeyError, IndexError, TypeError):
            self.config_selection.setText("Select a key to edit it.")
            self._refresh_config_inspector()
            return
        text = "{}  \u00b7  {}".format(
            _path_label(path), config_editor.type_name(value))
        if isinstance(value, (dict, list)):
            text += "  \u00b7  " + config_editor.format_value(value)
        self.config_selection.setText(text)
        self._refresh_config_inspector()

    def _config_item(self, label: str, value, path: tuple) -> QTreeWidgetItem:
        item = QTreeWidgetItem([
            label, config_editor.format_value(value),
            config_editor.type_name(value)])
        item.setData(0, Qt.UserRole, tuple(path))
        item.setData(1, Qt.UserRole + 1, config_editor.type_name(value))
        item.setToolTip(0, _path_label(path))
        item.setToolTip(1, config_editor.format_value(value, limit=2000))
        if isinstance(value, dict):
            for key, child in value.items():
                item.addChild(self._config_item(str(key), child, path + (key,)))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                item.addChild(self._config_item(
                    "[{}]".format(index), child, path + (index,)))
        if isinstance(value, bool):
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(1, Qt.Checked if value else Qt.Unchecked)
        elif isinstance(value, (int, float, str, datetime)):
            item.setFlags(item.flags() | Qt.ItemIsEditable)
        return item

    def _rebuild_config_tree(self, select: tuple | None = None) -> None:
        if not hasattr(self, "config_tree"):
            return
        self._config_loading = True
        self.config_tree.clear()
        document = self._config_doc
        if document is None:
            placeholder = QTreeWidgetItem(
                ["No config.plist is open.", "", ""])
            placeholder.setFlags(Qt.NoItemFlags)
            self.config_tree.addTopLevelItem(placeholder)
        else:
            for key, value in document.data.items():
                self.config_tree.addTopLevelItem(
                    self._config_item(str(key), value, (key,)))
            if self.config_tree.topLevelItemCount():
                self.config_tree.expandToDepth(0)
        self._config_loading = False
        self._rebuild_config_sections()
        self._apply_config_filters()
        if document is not None:
            if select is None:
                select = self._first_visible_config_path()
            if select is not None:
                self._select_config_path(select)
        self._update_config_actions()

    def _rebuild_config_sections(self) -> None:
        if not hasattr(self, "config_sections"):
            return
        previous = self._config_loading
        self._config_loading = True
        self.config_sections.clear()
        document = self._config_doc
        if document is None:
            self._config_section = None
        else:
            all_keys = QListWidgetItem("All keys")
            all_keys.setData(Qt.UserRole, None)
            all_keys.setData(Qt.UserRole + 1, "layers")
            self.config_sections.addItem(all_keys)
            for key in document.data:
                entry = QListWidgetItem(str(key))
                entry.setData(Qt.UserRole, str(key))
                entry.setData(Qt.UserRole + 1,
                              _CONFIG_SECTION_ICON.get(str(key), "file"))
                self.config_sections.addItem(entry)
            chosen = 0
            if self._config_section is not None:
                for index in range(1, self.config_sections.count()):
                    if (self.config_sections.item(index).data(Qt.UserRole)
                            == self._config_section):
                        chosen = index
                        break
                else:
                    self._config_section = None
            self.config_sections.setCurrentRow(chosen)
        self._config_loading = previous
        self._render_config_section_icons()

    def _render_config_section_icons(self) -> None:
        if not hasattr(self, "config_sections"):
            return
        palette = getattr(self, "_palette", LIGHT)
        for index in range(self.config_sections.count()):
            entry = self.config_sections.item(index)
            name = entry.data(Qt.UserRole + 1) or "file"
            entry.setIcon(icons.icon(name, palette["muted"], 15))
        self._refresh_config_inspector()

    def _on_config_section_changed(self, current, _previous=None) -> None:
        if self._config_loading or not hasattr(self, "config_tree"):
            return
        section = current.data(Qt.UserRole) if current is not None else None
        self._config_section = section or None
        self._apply_config_filters()
        target = (self._config_section,) if self._config_section else (
            self._first_visible_config_path())
        if target is not None:
            self._select_config_path(target)

    def _set_config_section(self, section: str | None) -> None:
        self._config_section = section
        if not hasattr(self, "config_sections"):
            return
        previous = self._config_loading
        self._config_loading = True
        for index in range(self.config_sections.count()):
            if self.config_sections.item(index).data(Qt.UserRole) == section:
                self.config_sections.setCurrentRow(index)
                break
        self._config_loading = previous

    def _first_visible_config_path(self):
        for index in range(self.config_tree.topLevelItemCount()):
            item = self.config_tree.topLevelItem(index)
            if not item.isHidden():
                path = item.data(0, Qt.UserRole)
                return tuple(path) if path else None
        return None

    def _select_config_path(self, path: tuple | None) -> None:
        if not path:
            self.config_tree.setCurrentItem(None)
            return
        top = path[0]
        if (self._config_section is not None and isinstance(top, str)
                and top != self._config_section):
            self._set_config_section(top)
            self._apply_config_filters()
        item = self._find_config_path(path)
        if item is None:
            return
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.config_tree.setCurrentItem(item)
        self.config_tree.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    def _find_config_path(self, path: tuple):
        for index in range(self.config_tree.topLevelItemCount()):
            found = self._find_config_item(
                self.config_tree.topLevelItem(index), path)
            if found is not None:
                return found
        return None

    def _find_config_item(self, item, path: tuple):
        stored = item.data(0, Qt.UserRole)
        if stored is not None and tuple(stored) == tuple(path):
            return item
        for index in range(item.childCount()):
            found = self._find_config_item(item.child(index), path)
            if found is not None:
                return found
        return None

    def _apply_config_filters(self, *_args) -> None:
        if not hasattr(self, "config_tree"):
            return
        query = (self.config_search.text() or "").strip().lower()
        section = self._config_section

        def visit(item, top: bool) -> bool:
            match = bool(query) and any(
                query in item.text(column).lower() for column in range(3))
            child_match = False
            for index in range(item.childCount()):
                child_match = visit(item.child(index), False) or child_match
            in_section = not section or not top or item.text(0) == section
            visible = in_section and (not query or match or child_match)
            item.setHidden(not visible)
            if query and visible:
                item.setExpanded(True)
            return visible

        for index in range(self.config_tree.topLevelItemCount()):
            visit(self.config_tree.topLevelItem(index), True)

    def _refresh_config_inspector(self) -> None:
        if not hasattr(self, "config_inspector_title"):
            return
        palette = getattr(self, "_palette", LIGHT)
        document = self._config_doc
        path = self._config_selected_path() if document is not None else None
        value = None
        if path is not None:
            try:
                value = config_editor.get_at(document.data, path)
            except (KeyError, IndexError, TypeError):
                path = None
        for widget in (self.config_value_edit, self.config_apply_value,
                       self.config_bool_edit, self.config_edit_value):
            widget.setVisible(False)
        if path is None or value is None:
            self.config_inspector_icon.setPixmap(icons.tile(
                "file", palette["tileIcon"], palette["tileBg"], 28))
            self.config_inspector_title.setText("Nothing selected")
            self.config_inspector_meta.setText("")
            self.config_inspector_hint.setText(
                "Select a key to inspect it." if document is not None
                else "No config.plist is open.")
            return
        kind = config_editor.type_name(value)
        self.config_inspector_icon.setPixmap(icons.tile(
            _CONFIG_TYPE_ICON.get(kind, "file"), palette["tileIcon"],
            palette["tileBg"], 28))
        label = ("[{}]".format(path[-1]) if isinstance(path[-1], int)
                 else str(path[-1]))
        self.config_inspector_title.setText(label)
        meta = _path_label(path)
        if isinstance(value, (dict, list)):
            meta += "  \u00b7  " + config_editor.format_value(value)
        self.config_inspector_meta.setText(meta)
        ready = not self._config_runner.busy
        if kind == "boolean":
            self.config_inspector_hint.setText("")
            self._config_inspector_loading = True
            self.config_bool_edit.setChecked(bool(value))
            self._config_inspector_loading = False
            self.config_bool_edit.setEnabled(ready)
            self.config_bool_edit.setVisible(True)
        elif kind == "data":
            self.config_inspector_hint.setText(
                "Data is edited as hexadecimal bytes or printable text.")
            self.config_edit_value.setEnabled(ready)
            self.config_edit_value.setVisible(True)
        elif kind == "string" and "\n" in value:
            self.config_inspector_hint.setText(
                "This value has multiple lines; edit it in the text dialog.")
            self.config_edit_value.setEnabled(ready)
            self.config_edit_value.setVisible(True)
        elif kind in ("dictionary", "array"):
            self.config_inspector_hint.setText(
                "Select a child to edit it, or use the Keys toolbar.")
        else:
            self.config_inspector_hint.setText(
                "Apply writes the value into the document, not the file.")
            self._config_inspector_loading = True
            self.config_value_edit.setText(_editable_text(value, kind))
            self._config_inspector_loading = False
            self.config_value_edit.setEnabled(ready)
            self.config_apply_value.setEnabled(ready)
            self.config_value_edit.setVisible(True)
            self.config_apply_value.setVisible(True)

    def _apply_config_value(self) -> None:
        document = self._config_doc
        path = self._config_selected_path()
        if document is None or path is None or self._config_runner.busy:
            return
        try:
            current = config_editor.get_at(document.data, path)
        except (KeyError, IndexError, TypeError):
            return
        kind = config_editor.type_name(current)
        try:
            value = config_editor.parse_value(kind, self.config_value_edit.text())
        except ValueError as exc:
            self.config_inspector_hint.setText(str(exc))
            return
        if value != current:
            config_editor.set_at(document.data, path, value)
            self._after_config_edit(
                "Change {}".format(config_diff.path_label(path)))
            item = self._find_config_path(path)
            if item is not None:
                self._display_config_item(item, value)
            self._config_note = ""
        self._render_config_state()

    def _on_config_bool_toggled(self, checked: bool) -> None:
        if self._config_inspector_loading or self._config_doc is None:
            return
        path = self._config_selected_path()
        if path is None:
            return
        try:
            current = config_editor.get_at(self._config_doc.data, path)
        except (KeyError, IndexError, TypeError):
            return
        if not isinstance(current, bool) or current == checked:
            return
        config_editor.set_at(self._config_doc.data, path, checked)
        self._after_config_edit(
            "Toggle {}".format(config_diff.path_label(path)))
        item = self._find_config_path(path)
        if item is not None:
            self._display_config_item(item, checked)
        self._config_note = ""
        self._render_config_state()

    def _on_config_edit_value(self) -> None:
        document = self._config_doc
        path = self._config_selected_path()
        if document is None or path is None:
            return
        try:
            value = config_editor.get_at(document.data, path)
        except (KeyError, IndexError, TypeError):
            return
        kind = config_editor.type_name(value)
        if kind == "data":
            self._edit_config_text(
                path, "Edit data",
                config_editor.data_to_hex(bytes(value)), monospace=True,
                parser=config_editor.hex_to_data)
        elif kind == "string" and "\n" in value:
            self._edit_config_text(
                path, "Edit text", value, monospace=False,
                parser=lambda payload: payload)

    def _display_config_item(self, item: QTreeWidgetItem, value) -> None:
        was_loading = self._config_loading
        self._config_loading = True
        item.setText(1, config_editor.format_value(value))
        item.setText(2, config_editor.type_name(value))
        item.setData(1, Qt.UserRole + 1, config_editor.type_name(value))
        item.setToolTip(1, config_editor.format_value(value, limit=2000))
        if isinstance(value, bool):
            item.setCheckState(1, Qt.Checked if value else Qt.Unchecked)
        self._config_loading = was_loading

    def _on_config_item_changed(self, item: QTreeWidgetItem,
                                column: int) -> None:
        if self._config_loading or column != 1 or self._config_doc is None:
            return
        path = item.data(0, Qt.UserRole)
        if not path:
            return
        path = tuple(path)
        try:
            current = config_editor.get_at(self._config_doc.data, path)
        except (KeyError, IndexError, TypeError):
            return
        kind = config_editor.type_name(current)
        try:
            if kind == "boolean":
                value = item.checkState(1) == Qt.Checked
            elif kind in ("integer", "real", "string", "date"):
                value = config_editor.parse_value(kind, item.text(1))
            else:
                return
        except ValueError as exc:
            self._config_note = str(exc)
            self._display_config_item(item, current)
            self._render_config_state()
            return
        if value != current:
            config_editor.set_at(self._config_doc.data, path, value)
            self._after_config_edit(
                "Change {}".format(config_diff.path_label(path)))
            self._config_note = ""
        else:
            self._config_note = ""
        self._display_config_item(item, value)
        self._render_config_state()

    def _on_config_double_clicked(self, item: QTreeWidgetItem,
                                  column: int) -> None:
        if column != 1 or self._config_doc is None:
            return
        path = item.data(0, Qt.UserRole)
        if not path:
            return
        path = tuple(path)
        try:
            value = config_editor.get_at(self._config_doc.data, path)
        except (KeyError, IndexError, TypeError):
            return
        kind = config_editor.type_name(value)
        if kind == "data":
            self._edit_config_text(
                path, "Edit data",
                config_editor.data_to_hex(bytes(value)), monospace=True,
                parser=config_editor.hex_to_data)
        elif kind == "string" and "\n" in value:
            self._edit_config_text(
                path, "Edit text", value, monospace=False,
                parser=lambda payload: payload)

    def _edit_config_text(self, path: tuple, title: str, text: str,
                          monospace: bool, parser) -> None:
        dialog = _TextDialog(self, title, path, text, monospace)
        dialog.set_parser(parser)
        if dialog.exec() != QDialog.Accepted:
            return
        value = dialog.payload()
        config_editor.set_at(self._config_doc.data, path, value)
        self._after_config_edit(
            "Edit {}".format(config_diff.path_label(path)))
        item = self._find_config_path(path)
        if item is not None:
            self._display_config_item(item, value)
        self._config_note = ""
        self._render_config_state()

    def _on_config_presets(self) -> None:
        document = self._config_doc
        if document is None or self._config_runner.busy:
            return
        dialog = _PresetDialog(
            self, config_presets.PRESETS, self._config_section,
            getattr(self, "_palette", LIGHT))
        if dialog.exec() != QDialog.Accepted:
            return
        preset = dialog.selected_preset()
        if preset is None:
            return
        try:
            outcome = config_presets.insert_preset(document.data, preset)
        except ValueError as exc:
            self._config_note = str(exc)
            self._render_config_state()
            return
        if not outcome.inserted:
            self._config_note = "That preset is already in {}.".format(
                _path_label(outcome.path))
            self._rebuild_config_tree(outcome.path)
            self._render_config_state()
            return
        self._after_config_edit("Insert {}".format(preset.title))
        self._config_note = "Inserted {}.".format(preset.title)
        self._rebuild_config_tree(outcome.path)
        self._render_config_state()

    def _on_config_add_key(self) -> None:
        document = self._config_doc
        target = self._config_dict_target(self._config_selected_path())
        if document is None or target is None:
            return
        mapping = config_editor.get_at(document.data, target)
        dialog = _AddKeyDialog(
            self, config_editor.known_children(target), set(mapping),
            getattr(self, "_palette", LIGHT))
        if dialog.exec() != QDialog.Accepted:
            return
        key, value = dialog.result_value()
        try:
            config_editor.add_child(mapping, key, value)
        except ValueError as exc:
            self._config_note = str(exc)
            self._render_config_state()
            return
        self._after_config_edit("Add {}".format(key))
        self._config_note = "Added {}.".format(key)
        self._rebuild_config_tree(tuple(target) + (key,))
        self._render_config_state()

    def _on_config_add_item(self) -> None:
        document = self._config_doc
        target = self._config_array_target(self._config_selected_path())
        if document is None or target is None:
            return
        sequence = config_editor.get_at(document.data, target)
        template = config_editor.array_template(target)
        if template is None and sequence:
            template = copy.deepcopy(sequence[0])
        if template is None:
            template = ""
        config_editor.add_item(sequence, template)
        index = len(sequence) - 1
        self._after_config_edit("Add item to {}".format(
            config_diff.path_label(target)))
        self._config_note = "Added item {}.".format(index)
        self._rebuild_config_tree(tuple(target) + (index,))
        self._render_config_state()

    def _on_config_remove(self) -> None:
        document = self._config_doc
        path = self._config_selected_path()
        if document is None or path is None:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Remove from config.plist?")
        box.setText("Remove {}?".format(_path_label(path)))
        box.setInformativeText(
            "The file is not changed until you press Save.")
        remove_button = box.addButton("Remove", QMessageBox.AcceptRole)
        cancel_button = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(cancel_button)
        box.exec()
        if box.clickedButton() is not remove_button:
            return
        try:
            config_editor.remove_at(document.data, path)
        except (KeyError, IndexError, TypeError) as exc:
            self._config_note = str(exc)
            self._render_config_state()
            return
        self._after_config_edit("Remove {}".format(
            config_diff.path_label(path)))
        self._config_note = "Removed {}.".format(_path_label(path))
        self._rebuild_config_tree(tuple(path[:-1]))
        self._render_config_state()

    def _move_config_item(self, delta: int) -> None:
        document = self._config_doc
        path = self._config_selected_path()
        if document is None or path is None:
            return
        try:
            moved = config_editor.move_item(document.data, path, delta)
        except (ValueError, KeyError, IndexError, TypeError):
            return
        if moved == path:
            return
        self._after_config_edit("Move {}".format(
            config_diff.path_label(moved)))
        self._config_note = "Moved {}.".format(_path_label(moved))
        self._rebuild_config_tree(moved)
        self._render_config_state()

    def _after_config_edit(self, label: str) -> None:
        """Count the revision and keep a snapshot the user can walk back to."""
        if self._config_doc is None:
            return
        self._config_revision += 1
        if self._config_history is None:
            self._config_history = config_diff.History(self._config_doc.data)
        else:
            self._config_history.record(self._config_doc.data, label)

    def _on_config_undo(self) -> None:
        if self._config_history is None or self._config_doc is None:
            return
        label = self._config_history.undo_label
        data = self._config_history.undo()
        if data is None:
            return
        self._apply_config_snapshot(data, "Undid {}".format(label))

    def _on_config_redo(self) -> None:
        if self._config_history is None or self._config_doc is None:
            return
        label = self._config_history.redo_label
        data = self._config_history.redo()
        if data is None:
            return
        self._apply_config_snapshot(data, "Redid {}".format(label))

    def _apply_config_snapshot(self, data: dict, note: str) -> None:
        """Replace the in-memory document with a history state; never saves."""
        if self._config_doc is None:
            return
        self._config_doc.data = data
        self._config_revision += 1
        self._config_note = note
        select = self._config_selected_path()
        self._rebuild_config_tree(select)
        self._render_config_state()

    def _on_config_changes(self) -> None:
        if self._config_history is None or self._config_doc is None:
            return
        dialog = _ChangesDialog(
            self, self._config_history.changes(), self._config_doc.path,
            getattr(self, "_palette", LIGHT))
        dialog.exec()

    def _config_menu(self, position) -> None:
        item = self.config_tree.itemAt(position)
        if item is None or self._config_doc is None:
            return
        self.config_tree.setCurrentItem(item)
        menu = QMenu(self)
        add_key = menu.addAction("Add key")
        add_key.setEnabled(self.config_add_key.isEnabled())
        add_key.triggered.connect(self._on_config_add_key)
        add_item = menu.addAction("Add item")
        add_item.setEnabled(self.config_add_item.isEnabled())
        add_item.triggered.connect(self._on_config_add_item)
        insert_preset = menu.addAction("Insert preset\u2026")
        insert_preset.setEnabled(self.config_presets.isEnabled())
        insert_preset.triggered.connect(self._on_config_presets)
        menu.addSeparator()
        remove = menu.addAction("Remove")
        remove.setEnabled(self.config_remove.isEnabled())
        remove.triggered.connect(self._on_config_remove)
        up = menu.addAction("Move up")
        up.setEnabled(self.config_up.isEnabled())
        up.triggered.connect(lambda: self._move_config_item(-1))
        down = menu.addAction("Move down")
        down.setEnabled(self.config_down.isEnabled())
        down.triggered.connect(lambda: self._move_config_item(1))
        menu.exec(self.config_tree.viewport().mapToGlobal(position))

    def _on_config_save(self) -> None:
        document = self._config_doc
        if document is None or self._config_runner.busy:
            return
        if not document.is_dirty():
            return
        if document.changed_on_disk():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Overwrite config.plist?")
            box.setText(
                "The file changed on disk since it was opened. Overwrite it?")
            box.setInformativeText(
                "The current version on disk will be kept as "
                "config.plist.bak.")
            overwrite = box.addButton("Overwrite", QMessageBox.AcceptRole)
            cancel_button = box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(cancel_button)
            box.exec()
            if box.clickedButton() is not overwrite:
                self._config_note = "Save cancelled."
                self._render_config_state()
                return
        try:
            document.save()
        except config_editor.ConfigEditorError as exc:
            self._show_error(exc)
            self._config_note = "The file could not be saved."
            self._render_config_state()
            return
        self._show_error(None)
        self._log_line("info", "Saved {}.".format(document.path))
        # The disk now holds this state; "changes since opened" starts again
        # from here, and undo stops at the saved file rather than crossing it.
        if self._config_history is not None:
            self._config_history.reset(document.data)
        self._config_note = (
            "Saved. The previous file was kept as config.plist.bak.")
        self._render_config_state()

    def _on_config_revert(self) -> None:
        document = self._config_doc
        if document is None or self._config_runner.busy:
            return
        try:
            reloaded = config_editor.ConfigDocument.load(document.path)
        except config_editor.ConfigEditorError as exc:
            self._show_error(exc)
            self._config_note = "The file could not be read."
            self._render_config_state()
            return
        self._show_error(None)
        self._config_doc = reloaded
        self._config_history = config_diff.History(reloaded.data)
        self._config_origin = (
            "built" if document.path == self._built_config else "chosen")
        self._config_revision += 1
        self._config_validation = None
        self._config_validate_revision = -1
        self._config_note = "Reverted to the file on disk."
        self._rebuild_config_tree()
        self._render_config_state()

    def _on_config_open(self) -> None:
        document = self._config_doc
        if document is not None and document.is_dirty():
            self._config_note = (
                "Save or revert the current file before opening another.")
            self._render_config_state()
            return
        if document is not None:
            start = str(document.path.parent)
        elif self._built_config is not None:
            start = str(self._built_config.parent)
        else:
            start = str(Path.home())
        filename, _filter = QFileDialog.getOpenFileName(
            self, "Open a config.plist", start,
            "Property lists (*.plist);;All files (*)")
        if not filename:
            return
        path = Path(filename)
        origin = "built" if path == self._built_config else "chosen"
        if self._load_config(path, origin=origin):
            self._show_error(None)
            self._config_note = "Opened {}.".format(path.name)
        self._render_config_state()

    def _on_config_validate(self) -> None:
        document = self._config_doc
        if document is None or self._config_runner.busy:
            return
        self._show_error(None)
        self._config_job = "validate"
        self._config_validate_revision = self._config_revision
        self._config_validation = None
        self._config_note = "Checking config.plist with ocvalidate\u2026"
        self.config_progress.setRange(0, 0)
        self.config_progress.setVisible(True)
        self._config_runner.start(Job(
            "Validating config.plist",
            lambda token: config_editor.validate_document(document.data),
            timeout=900))
        self._render_config_state()

    def _on_config_serials(self) -> None:
        document = self._config_doc
        if document is None or self._config_runner.busy:
            return
        models = config_editor.serial_models()
        if not models:
            self._config_note = "No SMBIOS models are available."
            self._render_config_state()
            return
        current = ""
        try:
            current = config_editor.get_at(
                document.data,
                ("PlatformInfo", "Generic", "SystemProductName"))
        except (KeyError, IndexError, TypeError):
            current = ""
        dialog = _SerialDialog(
            self, models, current if isinstance(current, str) else "",
            getattr(self, "_palette", LIGHT))
        if dialog.exec() != QDialog.Accepted:
            return
        model = dialog.selected_model()
        if not model:
            return
        self._show_error(None)
        self._config_job = "serials"
        self._config_model = model
        self._config_note = (
            "Generating SMBIOS serials for {} with macserial\u2026".format(model))
        self.config_progress.setRange(0, 0)
        self.config_progress.setVisible(True)
        self._config_runner.start(Job(
            "Generating SMBIOS serials",
            lambda token: config_editor.generate_serials(model), timeout=300))
        self._render_config_state()

    def _apply_generated_serials(self, values: dict, model: str) -> None:
        document = self._config_doc
        if document is None or not isinstance(values, dict):
            self._config_note = "The generated values could not be applied."
            return
        rom = values.get("ROM", b"")
        rom_text = (config_editor.data_to_hex(rom)
                    if isinstance(rom, (bytes, bytearray)) else str(rom))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Replace SMBIOS values?")
        box.setText(
            "Write the new values for {} into config.plist?".format(model))
        box.setInformativeText(
            "Nothing is written until you save. They replace the current "
            "serial, MLB, UUID and ROM.")
        box.setDetailedText(
            "Serial: {}\nMLB: {}\nUUID: {}\nROM: {}".format(
                values.get("SystemSerialNumber", ""), values.get("MLB", ""),
                values.get("SystemUUID", ""), rom_text))
        replace = box.addButton("Replace", QMessageBox.AcceptRole)
        cancel_button = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(cancel_button)
        box.exec()
        if box.clickedButton() is not replace:
            self._config_note = "The generated values were not applied."
            return
        try:
            config_editor.apply_serials(document.data, values, model)
        except ValueError as exc:
            self._show_error(config_editor.ConfigEditorError(detail=str(exc)))
            self._config_note = "The generated values could not be applied."
            return
        self._after_config_edit("Generate serials for {}".format(model))
        self._config_note = "Generated SMBIOS values for {}.".format(model)
        self._rebuild_config_tree(("PlatformInfo", "Generic"))

    def _on_config_outcome(self, outcome: Outcome) -> None:
        job, self._config_job = self._config_job, ""
        self.config_progress.setVisible(False)
        self.config_progress.setRange(0, 100)
        if outcome.status == CANCELLED:
            self._config_note = "{} cancelled.".format(outcome.job)
        elif not outcome.ok:
            self._show_error(outcome.error)
            self._log_line("error", str(
                outcome.error.detail if outcome.error else outcome.status))
            self._config_note = "The config task failed."
        elif job == "validate":
            result = outcome.value
            self._config_validation = result
            self._log_line("info", "config.plist: {}".format(result.summary))
            self._config_note = result.summary
        elif job == "serials":
            self._apply_generated_serials(
                outcome.value, getattr(self, "_config_model", ""))
            self._config_model = ""
            self._render_config_state()
            return
        else:
            self._config_note = ""
        self._render_config_state()

    def _render_config_transfer(self, transfer) -> None:
        self.config_progress.setRange(0, 100)
        self.config_progress.setVisible(True)
        fraction = transfer.fraction
        if fraction is not None:
            self.config_progress.setValue(round(fraction * 100))
        if transfer.total_bytes:
            self.config_detail.setText(
                "Downloading ocvalidate \u00b7 {} of {}".format(
                    _format_size(transfer.done_bytes),
                    _format_size(transfer.total_bytes)))
        else:
            self.config_detail.setText(
                "Downloading ocvalidate \u00b7 {}".format(
                    _format_size(transfer.done_bytes)))

    def _reveal_config(self) -> None:
        target = (self._config_doc.path if self._config_doc is not None
                  else self._built_config)
        if target is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

    def _on_cancel(self) -> None:
        if self.runner.cancel():
            self.statusBar().showMessage("Cancelling\u2026")
            self.cancel_button.setEnabled(False)
            self.task_detail.setText("Cancelling\u2026")

    def _on_outcome(self, outcome: Outcome) -> None:
        step, self._chain = (self._chain[0], self._chain[1:]) if self._chain else (None, [])
        if outcome.status == DONE:
            self._log_line("info", "{} finished in {:.1f} s".format(
                outcome.job, outcome.elapsed))
            if step is not None and step.on_done is not None:
                # An exception here would otherwise be printed to stderr by Qt and
                # swallowed, leaving a half-painted session that looks fine.
                try:
                    step.on_done(outcome)
                except Exception as exc:
                    self._show_error(UnexpectedEngineFailure(exc))
                    self._set_busy(False)
                    self.statusBar().showMessage(
                        "{} could not be displayed".format(outcome.job))
                    return
            if self._chain:
                self._run_next()
            else:
                self._set_busy(False)
                self._freeze_elapsed()
                self.statusBar().showMessage("Ready")
            return

        self._chain = []
        self._set_busy(False)
        self._freeze_elapsed()
        if outcome.status == CANCELLED:
            self._log_line("warning", "{} cancelled".format(outcome.job))
            self.task_detail.setText("{} cancelled.".format(outcome.job))
            self.statusBar().showMessage("Stopped")
            return
        if outcome.job == "Checking compatibility":
            self.report_field.set_state("error", "Rejected")
            self._clear_analysis(rejected=True)
            self._summarise("Compatibility check failed.", "error")
            self.summary_note.setText(
                "No devices were graded. Choose another Report.json and check it again.")
            self.task_name.setText("Compatibility check failed")
            self.task_detail.setText(str(outcome.error.title))
        if outcome.job in _BUILD_JOBS:
            # The transfer gauge names whichever product it last touched; after a
            # failure that name is not the step that stopped.
            self.task_name.setText(outcome.job)
            self.task_detail.setText("{} failed.".format(outcome.job))
        self._log_line("error", str(outcome.error.detail or outcome.error))
        self._show_error(outcome.error)
        self.statusBar().showMessage("{} failed".format(outcome.job))

    def _set_busy(self, busy: bool, name: str = "") -> None:
        # The mockup keeps all four actions in place; an idle Cancel is disabled,
        # not removed, so the grid never reflows between running and idle.
        self.cancel_button.setEnabled(busy)
        self.analyze_button.setEnabled(not busy)
        self.collect_button.setEnabled(not busy)
        self.build_button.setEnabled(not busy and self.analysis is not None)
        self.report_field.setEnabled(not busy)
        self.acpi_field.setEnabled(not busy)
        self.acpi_button.setEnabled(not busy)
        self.output_field.setEnabled(not busy)
        self.version_combo.setEnabled(not busy and bool(self._options))
        self.reveal_button.setEnabled(
            not busy and self._result_dir is not None and self._result_dir.exists())
        if busy:
            # Follow the work instead of leaving the failure on a page the user has
            # since navigated away from.
            self._show_view("Build EFI" if name in _BUILD_JOBS else "Compatibility")
            if name in _BUILD_JOBS:
                self.progress_card.set_hint("Building your OpenCore EFI folder.")
            if name:
                self.task_name.setText(name)
                self.task_detail.setText("Starting\u2026")
            self.statusBar().showMessage(name or "Working\u2026")
        self._update_installer_ready()
        self._refresh_configure()

    # ---- verdicts and details ----

    def _selected_target(self) -> str | None:
        data = self.version_combo.currentData()
        return str(data) if data else None

    def _status_for(self, verdict: verdicts.Verdict) -> verdicts.Status:
        oclp_range = self.analysis.oclp_range if self.analysis is not None else None
        return verdicts.target_status(verdict, self._selected_target(), oclp_range)

    def _render_verdicts(self, selected_name: str | None = None) -> None:
        if self.analysis is None:
            return
        previous = selected_name or (
            self._current_verdict.name if self._current_verdict else None)
        self.verdict_tree.clear()
        self._verdicts = list(verdicts.rows(self.analysis.report))
        self._items = []
        strong = QFont(self.font())
        strong.setWeight(QFont.Weight.DemiBold)
        for verdict in self._verdicts:
            item = QTreeWidgetItem([
                verdict.name, verdict.class_label or verdict.section, verdict.text, ""])
            icon_name = _CLASS_ICON.get(verdict.class_label, "layers")
            tint, tint_bg = self._palette.get("classTints", {}).get(
                verdict.class_label,
                (self._palette["tileIcon"], self._palette["tileBg"]))
            item.setIcon(0, QIcon(icons.tile(icon_name, tint, tint_bg, 24)))
            item.setFont(0, strong)
            item.setSizeHint(0, QSize(0, 29))
            item.setToolTip(0, verdict.name)
            item.setToolTip(2, verdict.text)
            self.verdict_tree.addTopLevelItem(item)
            self._items.append(item)
        self.empty_note.setVisible(not self._verdicts)
        self.devices_card.set_hint(
            "No report loaded yet." if not self._verdicts else
            "Detected {} devices from your hardware report.".format(len(self._verdicts)))
        if not self._verdicts:
            self._reset_details()
            return
        self._refresh_statuses()
        item = next((row for row, verdict in zip(self._items, self._verdicts)
                     if verdict.name == previous), self._items[0])
        self.verdict_tree.setCurrentItem(item)
        item.setSelected(True)
        self._on_device_selected()

    def _refresh_statuses(self) -> None:
        if self.analysis is None:
            return
        for verdict, item in zip(self._verdicts, self._items):
            status = self._status_for(verdict)
            item.setText(3, status.label)
            item.setData(3, Qt.UserRole, status.key)
            item.setToolTip(3, "{} {}".format(status.detail, status.recommendation))
            tint = {"unsupported": "rowFailBg", "limited": "rowWarnBg"}.get(status.key)
            brush = qcolor(self._palette[tint]) if tint else None
            for column in range(4):
                item.setData(column, Qt.BackgroundRole, brush)
        widest = max((self.verdict_tree.fontMetrics().horizontalAdvance(item.text(3))
                      for item in self._items), default=0)
        self.verdict_tree.fit_status(widest)
        if self._current_verdict in self._verdicts:
            self._show_details(self._current_verdict)
        self.verdict_tree.viewport().update()

    def _on_version_changed(self, _index: int = -1) -> None:
        self._refresh_statuses()
        self._update_summary_note()

    def _update_summary_note(self) -> None:
        if self.analysis is None or not self._options:
            return
        index = self.version_combo.currentIndex()
        if index < 0 or index >= len(self._options):
            return
        selected = self._options[index]
        suggested = next((option for option in self._options if option.is_suggested), None)
        parts = ["Status is computed for {}.".format(selected.name)]
        if suggested is not None and suggested.darwin_major != selected.darwin_major:
            parts.append("The engine suggests {}.".format(suggested.name))
        if selected.requires_oclp:
            parts.append("Needs OpenCore Legacy Patcher.")
        self.summary_note.setText(" ".join(parts))

    def _on_device_selected(self) -> None:
        item = self.verdict_tree.currentItem()
        if item is None or item not in self._items:
            return
        index = self._items.index(item)
        if index >= len(self._verdicts):
            return
        self._current_verdict = self._verdicts[index]
        self._show_details(self._current_verdict)

    def _show_details(self, verdict: verdicts.Verdict) -> None:
        status = self._status_for(verdict)
        fields = dict(verdict.fields)
        values = {
            "Device": verdict.name,
            "Class": verdict.class_label or verdict.section,
            "macOS support": verdict.text,
            "Vendor": fields.get("Vendor", "\u2014"),
            "Device ID": fields.get("Device ID", "\u2014"),
            "Subsystem": fields.get("Subsystem", "\u2014"),
            "Current status": status.detail,
        }
        for key, label in self.detail_values.items():
            label.setText(values.get(key, "\u2014"))
        self.detail_recommendation.setText(status.recommendation)
        self.detail_recommendation.setProperty("state", status.key)
        _repolish(self.detail_recommendation)
        self._set_badge(status.label, status.key)
        self.copy_details_button.setEnabled(True)
        self.why_button.setEnabled(True)

    def _set_badge(self, text: str, state: str) -> None:
        self.detail_badge.setText(text)
        self.detail_badge.setProperty("state", state)
        _repolish(self.detail_badge)
        self.detail_badge.setVisible(bool(text))

    def _reset_details(self) -> None:
        self._current_verdict = None
        for label in self.detail_values.values():
            label.setText("\u2014")
        self.detail_recommendation.setText(
            "Select a device to see the engine's verdict for it.")
        self.detail_recommendation.setProperty("state", "unknown")
        _repolish(self.detail_recommendation)
        self._set_badge("", "unknown")
        self.copy_details_button.setEnabled(False)
        self.why_button.setEnabled(False)

    def _focus_worst_device(self) -> None:
        if not self._verdicts:
            return
        item = next((row for row, verdict in zip(self._items, self._verdicts)
                     if self._status_for(verdict).key == "unsupported"), self._items[0])
        self.verdict_tree.setCurrentItem(item)
        item.setSelected(True)
        self.verdict_tree.scrollToItem(item)
        self._on_device_selected()

    def _toggle_details(self) -> None:
        self._details_open = not self._details_open
        if self._details_open:
            self._focus_worst_device()
        if self._view == "Compatibility":
            # Details takes the slot under the table, where the build progress
            # card sits. Growing the left column instead stretched the table to
            # the page height and pushed the log below the fold.
            self._show_view("Compatibility")
        self.view_details_button.setText(
            "Hide details" if self._details_open else "View details")

    def _copy_details(self) -> None:
        if self._current_verdict is None:
            return
        status = self._status_for(self._current_verdict)
        lines = ["{}: {}".format(key, label.text())
                 for key, label in self.detail_values.items()]
        lines.append("Recommendation: {}".format(status.recommendation))
        QApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage("Device details copied")

    def _show_why(self) -> None:
        if self._current_verdict is None:
            return
        status = self._status_for(self._current_verdict)
        QMessageBox.information(
            self, "Engine verdict",
            "{}\n\nEngine verdict: {}\nStatus: {}\n\n{}\n{}".format(
                self._current_verdict.name, self._current_verdict.text,
                status.label, status.detail, status.recommendation))

    # ---- search and progress ----

    def _on_search(self, text: str) -> None:
        self._filter_text = text.strip().lower()
        self._filter_devices()

    def _filter_devices(self) -> None:
        query = self._filter_text
        for item in self._items:
            haystack = " ".join(item.text(column) for column in range(4)).lower()
            item.setHidden(bool(query) and query not in haystack)

    def _summarise(self, text: str, state: str) -> None:
        self.summary.setText(text)
        for widget in (self.summary_frame, self.summary):
            widget.setProperty("state", state)
            _repolish(widget)
        self._set_summary_icon(state)

    def _set_summary_icon(self, state: str) -> None:
        self._summary_state = state
        palette = self._palette_or_light()
        key = {"ok": "ok", "error": "fail"}.get(state, "unknown")
        icon = {"ok": "check-circle", "error": "x-circle"}.get(state, "info")
        self.summary_icon.setPixmap(icons.pixmap(icon, palette[key], 18))

    def _reset_progress(self) -> None:
        self._stage_names = []
        self._stage_started.clear()
        self._stage_elapsed.clear()
        self._last_stages = []
        self._stage_widgets = {}
        self.stage_list.clear()
        self.progress.setRange(0, 5)
        self.progress.setValue(0)
        self.progress_label.setText("0%")
        self.step_label.setText("Not started")
        self.metric_elapsed.set("\u2014")
        self.metric_downloaded.set("0 B")
        self.metric_speed.set("\u2014")
        self.task_name.setText("Waiting to start")
        self.task_detail.setText("Nothing is downloading.")
        self._task_stage = ""
        self.task_progress.setValue(0)
        self._last_rate = 0.0
        self._build_started = None
        self._transfer_bytes.clear()
        self._prime_stages()

    def _prime_stages(self) -> None:
        """Draw the checklist before the engine has emitted anything.

        An empty list read as a broken card rather than "nothing has run yet"; the
        five stages are fixed, so they can be shown pending from the start.
        """
        names = list(_STEPS)
        self._stage_names = names
        self._last_stages = [(name, None, "pending") for name in names]
        self._rebuild_stage_rows(self._last_stages)
        self.progress.setRange(0, len(names))
        self.progress_card.set_hint("Step, transfer and timing from the engine.")

    def _render_stages(self, stages) -> None:
        stages = list(stages)
        names = [name for name, _total, _state in stages]
        if names != self._stage_names:
            self._stage_names = names
            self._stage_started.clear()
            self._stage_elapsed.clear()
        now = time.monotonic()
        for name, _total, state in stages:
            if state == "running" and name not in self._stage_started:
                self._stage_started[name] = now
            elif state in ("done", "failed", "cancelled") and name in self._stage_started:
                self._stage_elapsed[name] = now - self._stage_started.pop(name)
        self._last_stages = stages

        done = sum(1 for _name, _total, state in stages if state == "done")
        running = next(((index, name) for index, (name, _total, state)
                        in enumerate(stages) if state == "running"), None)
        self.progress.setRange(0, max(1, len(stages)))
        self.progress.setValue(done)
        self.progress_label.setText(
            "{:.0f}%".format(100.0 * done / max(1, len(stages))))
        if running is not None:
            self.step_label.setText(
                "Step {} of {}".format(running[0] + 1, len(stages)))
            if running[1] != self._task_stage:
                self._task_stage = running[1]
                self.task_name.setText(running[1])
                self.task_detail.setText("Running\u2026")
        elif stages and done == len(stages):
            self.step_label.setText("Step {} of {}".format(len(stages), len(stages)))
        elif done:
            self.step_label.setText(
                "Step {} of {}".format(done + 1, len(stages)))
        else:
            self.step_label.setText("Not started")

        self._sync_stage_rows(stages)

    def _sync_stage_rows(self, stages) -> None:
        """Update the checklist in place.

        Rebuilding every row on every stage event reset selection and hover and
        forced a full relayout of the card several times a second while a build
        streamed; the row count is fixed, so only the marks and times change.
        """
        names = [name for name, _total, _state in stages]
        if names != list(self._stage_widgets):
            self._rebuild_stage_rows(stages)
            return
        for name, _total, state in stages:
            row = self._stage_widgets.get(name)
            if row is not None:
                row.set_state(state, self._stage_time(name, state))

    def _rebuild_stage_rows(self, stages) -> None:
        self.stage_list.clear()
        self._stage_widgets = {}
        for name, _total, state in stages:
            # The item's own text is painted under the row widget and would show
            # through it; the name lives in the data role instead.
            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            item.setToolTip(name)
            item.setSizeHint(QSize(0, 24))
            row = _StageRow(name, state, self._stage_time(name, state), self._palette)
            self.stage_list.addItem(item)
            self.stage_list.setItemWidget(item, row)
            self._stage_widgets[name] = row

    def _stage_time(self, name: str, state: str) -> str:
        if name in self._stage_elapsed:
            return _format_elapsed(self._stage_elapsed[name])
        if state == "running" and name in self._stage_started:
            return _format_elapsed(time.monotonic() - self._stage_started[name])
        return "\u2014"

    def _tick_clock(self) -> None:
        now = time.monotonic()
        if now - self._last_clock < 0.25:
            return
        self._last_clock = now
        if self._build_started is not None and self._chain:
            self.metric_elapsed.set(_format_elapsed(now - self._build_started))
        for name, started in self._stage_started.items():
            row = self._stage_widgets.get(name)
            if row is not None:
                row.set_time(_format_elapsed(now - started))

    def _freeze_elapsed(self) -> None:
        if self._build_started is None:
            return
        self.metric_elapsed.set(_format_elapsed(time.monotonic() - self._build_started))
        self._build_started = None

    def _finish_progress(self, result: Path) -> None:
        total = max(1, self.progress.maximum())
        self.progress.setValue(total)
        self.progress_label.setText("100%")
        self.step_label.setText("Step {} of {}".format(total, total))
        self.task_progress.setValue(100)
        self.task_name.setText("EFI folder ready")
        self.task_detail.setText(str(result))
        self.progress_card.set_hint("The EFI folder is ready.")
        self._freeze_elapsed()

    def _render_transfer(self, transfer) -> None:
        previous = self._transfer_bytes.get(transfer.product, 0)
        self._transfer_bytes[transfer.product] = max(previous, transfer.done_bytes)
        total = sum(self._transfer_bytes.values())
        self.metric_downloaded.set(_format_size(total))
        if transfer.bytes_per_second > 0:
            self._last_rate = transfer.bytes_per_second
        self.metric_speed.set(_format_rate(self._last_rate))
        fraction = transfer.fraction
        self.task_name.setText(transfer.product)
        self.task_progress.setValue(
            round(fraction * 100) if fraction is not None else 0)
        if transfer.total_bytes:
            self.task_detail.setText("{} of {}{}".format(
                _format_size(transfer.done_bytes),
                _format_size(transfer.total_bytes),
                "" if fraction is None else " \u00b7 {:.0f}%".format(fraction * 100)))
        else:
            self.task_detail.setText("{} downloaded".format(
                _format_size(transfer.done_bytes)))

    # ---- engine event rendering ----

    def _drain(self) -> None:
        events = self.bridge.drain()
        if events.dropped_logs:
            self._ingest("warning", "{} earlier log lines were dropped".format(
                events.dropped_logs))
        for level, message in events.logs:
            if self._passes_filter(level):
                self._ingest(level, message)
        if events.stages:
            self._render_stages(events.stages)
        for transfer in events.transfers:
            if transfer.product == "ocvalidate":
                self._render_config_transfer(transfer)
            elif transfer.product in ("USB installer", "recovery chunklist") or \
                    transfer.product.startswith("macOS recovery"):
                self._render_installer_transfer(transfer)
            else:
                self._render_transfer(transfer)
        for level, title, body in events.notifications:
            self._ingest(level, "{}: {}".format(title, body) if body else title)
        self._tick_clock()
        self._set_ticker_interval(
            self.runner.busy or self._installer_runner.busy
            or self._config_runner.busy or self._usb_runner.busy
            or bool(self._chain) or bool(self._stage_started))

    def _set_ticker_interval(self, active: bool) -> None:
        if not hasattr(self, "_ticker"):
            return
        interval = 60 if active else 400
        if self._ticker.interval() != interval:
            self._ticker.setInterval(interval)

    def _log_line(self, level: str, message: str) -> None:
        # One channel only: the bridge renders it on the next drain, exactly like
        # an engine message does. Appending here as well drew every GUI-originated
        # line twice.
        self.bridge.log(level, message)

    def _ingest(self, level: str, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._entries.append((level, str(message), stamp))
        if self._passes_filter(level):
            self._append(level, str(message), stamp)

    def _append(self, level: str, message: str, stamp: str | None = None) -> None:
        # Engine text is report content and remote filenames: escape it, or a
        # device called "<b>x</b>" formats the window instead of naming itself.
        tag = _LEVEL_TAG.get(level, "INFO")
        color = _LEVEL_COLOR.get(level, _LEVEL_COLOR["info"])
        body = html.escape(str(message)).replace("\n", "<br/>")
        self.log_view.appendHtml(
            '<span style="color:{time_color}">{stamp}</span>&nbsp;&nbsp;'
            '<span style="color:{color}; font-weight:600">{tag}</span>&nbsp;&nbsp;'
            '<span style="color:{text_color}">{body}</span>'.format(
                time_color=_LOG_TIME, stamp=html.escape(stamp or time.strftime("%H:%M:%S")),
                color=color, tag=tag, text_color=_LOG_TEXT, body=body))

    def _passes_filter(self, level: str) -> bool:
        choice = self.level_filter.currentIndex()
        if choice == 2:
            return True
        if choice == 1:
            return level in ("warning", "error")
        return level in ("info", "warning", "error")

    def _rerender_log(self) -> None:
        self.log_view.clear()
        for level, message, stamp in self._entries:
            if self._passes_filter(level):
                self._append(level, message, stamp)

    def _save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save log", str(Path.home() / "blackdream.log"),
            "Log files (*.log);;All files (*)")
        if not path:
            return
        lines = ["[{}] [{}] {}".format(stamp, level, message)
                 for level, message, stamp in self._entries]
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.statusBar().showMessage("Log saved to {}".format(path))

    def _copy_log(self) -> None:
        QApplication.clipboard().setText(self.log_view.toPlainText())
        self.statusBar().showMessage("Log copied to the clipboard")

    def _environment_text(self) -> str:
        return diagnostics.environment(
            RELEASE_LABEL, platform.platform(),
            theme="Dark" if self._dark else "Light",
            frozen=bool(getattr(sys, "frozen", False)),
            architecture=platform.machine()) + "Last error: {}\n".format(
                self._last_error_code or "none")

    def _copy_diagnostics(self) -> None:
        text = diagnostics.Bundle(home=Path.home()).scrub(self._environment_text())
        QApplication.clipboard().setText(text)
        self.diagnostics_note.setText("Copied to the clipboard.")

    def _newest_crash(self) -> Path | None:
        try:
            reports = sorted(crash_log.report_dir().glob("crash-*.txt"))
        except OSError:
            return None
        return reports[-1] if reports else None

    def _diagnostic_bundle(self) -> diagnostics.Bundle:
        document = self._config_doc
        secrets = (diagnostics.secrets_from_config(document.data)
                   if document is not None else ())
        bundle = diagnostics.Bundle(home=Path.home(), secrets=secrets)
        bundle.add("environment.txt", self._environment_text(), optional=False,
                   note="version, platform, theme and the last error code")
        if self._entries:
            bundle.add("engine.log", "\n".join(
                "[{}] [{}] {}".format(stamp, level, message)
                for level, message, stamp in self._entries),
                note="this session's log")
        crash = self._newest_crash()
        if crash is not None:
            bundle.add("crash-{}.txt".format(crash.stem),
                       diagnostics.log_text(crash),
                       note="the newest crash report")
        if self._config_validation is not None:
            result = self._config_validation
            body = "\n".join((result.summary, "", result.output or "")) + "\n"
            if result.issues:
                body += "\n".join(result.issues) + "\n"
            bundle.add("validation.txt", body,
                       note="the last ocvalidate result")
        if self._preflight is not None:
            bundle.add("preflight.txt", efi_preflight.to_text(self._preflight),
                       note="the last folder check")
        if self._report_path is not None:
            bundle.add("report-summary.txt",
                       diagnostics.report_summary(self._report_path),
                       note="the Report.json key names, not its values")
            try:
                body = self._report_path.read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                body = "Report.json could not be read."
            bundle.add("Report.json", body, included=False,
                       note="contains hardware details; off unless you choose it")
        return bundle

    def _on_diagnostics_bundle(self) -> None:
        dialog = _DiagnosticsDialog(
            self, self._diagnostic_bundle(), getattr(self, "_palette", LIGHT))
        if dialog.exec() == QDialog.Accepted and dialog.saved_path:
            self.diagnostics_note.setText(
                "Saved to {}. Nothing was uploaded.".format(dialog.saved_path))

    # ---- error presentation ----

    def _show_error(self, error: EngineError | None) -> None:
        if error is None:
            self.error_card.setVisible(False)
            self.error_card.setText("")
            return
        self._last_error_code = error.code
        parts = ["<b>{}</b>".format(html.escape(error.title))]
        if error.detail:
            parts.append(html.escape(str(error.detail)))
        if not error.recoverable:
            parts.append("<i>This machine cannot run macOS as configured.</i>")
        if error.remediation:
            parts.append("<ul>" + "".join(
                "<li>{}</li>".format(html.escape(str(item))) for item in error.remediation)
                + "</ul>")
        parts.append("<span style='color:{fg}'>code: {code}</span>".format(
            fg=self._palette["errorCode"], code=html.escape(error.code)))
        self.error_card.setText("<br/>".join(parts))
        self.error_card.setVisible(True)

    def _reveal_result(self) -> None:
        if self._result_dir is not None and self._result_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._result_dir)))

class _InfoTile(QLabel):
    """A small tinted icon used by the utility screens."""

    def __init__(self, name: str, palette: dict, size: int = 28) -> None:
        super().__init__()
        self._name = name
        self._size = size
        self.setFixedSize(size, size)
        self.apply_palette(palette)

    def apply_palette(self, palette: dict) -> None:
        self.setPixmap(icons.tile(
            self._name, palette["tileIcon"], palette["tileBg"], self._size))


class _InfoRow(QWidget):
    """An icon, a title and a wrapped explanation, used by Settings and Help."""

    def __init__(self, title: str, body: str, palette: dict,
                 icon_name: str | None = None, selectable: bool = False) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        if icon_name is not None:
            layout.addWidget(_InfoTile(icon_name, palette, 28), 0, Qt.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(1)
        heading = QLabel(title)
        heading.setObjectName("rowTitle")
        heading.setWordWrap(True)
        copy = QLabel(body)
        copy.setObjectName("rowBody")
        copy.setWordWrap(True)
        if selectable:
            copy.setTextInteractionFlags(Qt.TextSelectableByMouse)
        column.addWidget(heading)
        column.addWidget(copy)
        layout.addLayout(column, 1)
        self.body = copy
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)


class _Split(QWidget):
    """Two panes side by side, stacked once their minimum widths do not fit.

    The dashboard's two columns and the builder's cards both have content that
    cannot shrink past a point. A plain box layout responds by forcing the page
    wider than the viewport, which clips the right edge at the minimum window
    size; this reflows instead and lets the page scroll vertically.
    """

    def __init__(self, first: QWidget, second: QWidget, spacing: int = 12,
                 stretch: tuple[int, int] = (1, 1), stack_below: int = 0,
                 stack_stretch: tuple[int, int] | None = None) -> None:
        super().__init__()
        self._first = first
        self._second = second
        self._spacing = spacing
        self._stretch = stretch
        self._stack_stretch = stack_stretch or (1, 1)
        self._stack_below = stack_below
        self._stacked = False
        self._row = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(spacing)
        self._row.addWidget(first, stretch[0])
        self._row.addWidget(second, stretch[1])

    def _min_width(self, widget: QWidget) -> int:
        return max(widget.minimumSizeHint().width(), widget.minimumWidth())

    def minimumSizeHint(self) -> QSize:
        horizontal = max(self._min_width(self._first), self._min_width(self._second))
        if self._stacked:
            vertical = (self._first.minimumSizeHint().height() + self._spacing
                        + self._second.minimumSizeHint().height())
        else:
            vertical = max(self._first.minimumSizeHint().height(),
                           self._second.minimumSizeHint().height())
        return QSize(horizontal, vertical)

    def sizeHint(self) -> QSize:
        if self._stacked:
            return QSize(
                max(self._first.sizeHint().width(), self._second.sizeHint().width()),
                self._first.sizeHint().height() + self._spacing
                + self._second.sizeHint().height())
        return QSize(
            self._first.sizeHint().width() + self._spacing
            + self._second.sizeHint().width(),
            max(self._first.sizeHint().height(), self._second.sizeHint().height()))

    def resizeEvent(self, event) -> None:
        needed = max(self._stack_below,
                     self._min_width(self._first) + self._spacing
                     + self._min_width(self._second))
        stacked = self.width() < needed
        if stacked != self._stacked:
            self._stacked = stacked
            self._row.setDirection(
                QBoxLayout.Direction.TopToBottom if stacked
                else QBoxLayout.Direction.LeftToRight)
            for index, factor in enumerate(self._stretch):
                self._row.setStretch(
                    index, self._stack_stretch[index] if stacked else factor)
            self.updateGeometry()
        super().resizeEvent(event)


class _SearchPill(QFrame):
    def __init__(self, palette: dict, compact: bool = False) -> None:
        super().__init__()
        self.setObjectName("searchPill")
        self._compact = compact
        self._icon_size = 13 if compact else 15
        self.setFixedHeight(28 if compact else 32)
        # The device card's header must fit beside the table at 1160 px, so the
        # pill gives way instead of forcing the whole dashboard wider.
        self.setMinimumWidth(110 if compact else 200)
        self.setMaximumWidth(204 if compact else 240)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9 if compact else 9, 0, 7, 0)
        layout.setSpacing(6 if compact else 7)
        self.icon = QLabel()
        self.icon.setFixedSize(self._icon_size, self._icon_size)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText(
            "Search" if compact else "Search devices\u2026")
        self.search_input.setClearButtonEnabled(True)
        shortcut = QLabel("\u2318 K" if sys.platform == "darwin" else "Ctrl K")
        shortcut.setObjectName("kbd")
        shortcut.setVisible(not compact)
        layout.addWidget(self.icon, 0, Qt.AlignVCenter)
        layout.addWidget(self.search_input, 1)
        layout.addWidget(shortcut, 0, Qt.AlignVCenter)
        self.apply_palette(palette)

    def sizeHint(self) -> QSize:
        return QSize(204 if self._compact else 240, 28 if self._compact else 32)

    def apply_palette(self, palette: dict) -> None:
        self._palette = palette
        self.icon.setPixmap(icons.pixmap("search", palette["muted"], self._icon_size))


class _Combo(QComboBox):
    """A combo that draws its own chevron: QSS cannot set an SVG arrow image.

    The popup is configured here as well: uniform rows, elided labels with a
    tooltip, and no wheel-driven changes while the combo is not focused. A wheel
    over a closed combo that silently changes the target is a real data-loss
    hazard -- the next Build would use a version nobody picked.
    """

    def __init__(self, palette: dict) -> None:
        super().__init__()
        self._palette = palette
        self.setMinimumHeight(32)
        # A styled combo otherwise reports its longest item as its minimum width;
        # the version list holds long release names, so a theme re-polish made the
        # whole page wider than its viewport. Elide against the field width instead.
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMaxVisibleItems(9)
        view = self.view()
        view.setUniformItemSizes(True)
        view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setTextElideMode(Qt.ElideRight)

    def wheelEvent(self, event) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)

    def apply_palette(self, palette: dict) -> None:
        self._palette = palette
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(self.width() - 24, (self.height() - 16) // 2,
                           icons.pixmap("chevron-down", self._palette["muted"], 16))


class _Card(QFrame):
    """One titled panel. Depth comes from the border and the background step."""

    def __init__(self, title: str, hint: str | None = None,
                 number: int | None = None) -> None:
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(7)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        if number is not None:
            badge = QLabel(str(number))
            badge.setObjectName("numberBadge")
            badge.setFixedSize(20, 20)
            badge.setAlignment(Qt.AlignCenter)
            header.addWidget(badge, 0, Qt.AlignVCenter)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        # A card whose content cannot grow would hand its spare height to the
        # header row, centring the title halfway down the panel.
        heading.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        header.addWidget(heading)
        header.addStretch(1)
        self._header = header
        self._layout = layout
        # Wrapping the row pins it to the top of the card; a bare layout would
        # absorb spare height and centre the title halfway down the panel.
        header_holder = QWidget()
        header_holder.setLayout(header)
        header_holder.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(header_holder)
        self._hint: QLabel | None = None
        if hint:
            self._hint = QLabel(hint)
            self._hint.setObjectName("cardHint")
            self._hint.setWordWrap(True)
            layout.addWidget(self._hint)

    def finish(self) -> None:
        """Pack the content to the top of a card with no growing child."""
        self._layout.addStretch(1)

    def set_hint(self, text: str) -> None:
        if self._hint is not None:
            self._hint.setText(text)

    def hint_label(self) -> QLabel | None:
        return self._hint

    def set_header_widget(self, widget: QWidget) -> None:
        self._header.addWidget(widget, 0, Qt.AlignVCenter)

    def add_header_widget(self, widget: QWidget) -> None:
        """Place a control next to the title, before the header's stretch."""
        self._header.insertWidget(self._header.count() - 1, widget, 0,
                                  Qt.AlignVCenter)

    def add(self, widget, stretch: int = 0) -> None:
        if isinstance(widget, (QHBoxLayout, QVBoxLayout, QGridLayout)):
            self._layout.addLayout(widget, stretch)
            return
        self._layout.addWidget(widget, stretch)


class _ElidedPath(QLabel):
    """A path that shows both ends instead of clipping mid-character.

    A read-only line edit always shows the start and simply cuts the rest, which
    turned "/media/user/My Drive/Report.json" into "/media/user/My Drive/Rep".
    """

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.setObjectName("pathValue")
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._full = text
        self.setToolTip(text)
        self._refresh()

    def full_text(self) -> str:
        return self._full

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(
            self._full, Qt.ElideMiddle, max(0, self.width())))


class _PathPicker(QFrame):
    """A labelled path in a rounded row, with its state and a Browse button."""

    def __init__(self, label: str, icon_name: str, on_pick: Callable[[], None],
                 value: str = "", palette: dict | None = None) -> None:
        super().__init__()
        self.setObjectName("pathRow")
        self.setFixedHeight(44)
        self._palette = palette or LIGHT
        self._icon_name = icon_name
        self._state_key = "empty"
        self._note = "No path chosen"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(9)
        self.icon = QLabel()
        self.icon.setFixedSize(28, 28)
        column = QVBoxLayout()
        column.setSpacing(0)
        caption = QLabel(label)
        caption.setObjectName("pathLabel")
        self.edit = _ElidedPath(value)
        column.addWidget(caption)
        column.addWidget(self.edit)
        layout.addWidget(self.icon, 0, Qt.AlignVCenter)
        layout.addLayout(column, 1)
        self.state = QLabel()
        self.state.setObjectName("fieldState")
        self.state.setFixedSize(18, 18)
        self.state.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.state, 0, Qt.AlignVCenter)
        button = QPushButton("Browse\u2026")
        button.setObjectName("browse")
        button.clicked.connect(lambda: on_pick())
        layout.addWidget(button, 0, Qt.AlignVCenter)
        self.apply_palette(self._palette)
        self.set_state("empty", "No path chosen")

    def apply_palette(self, palette: dict) -> None:
        self._palette = palette
        self.icon.setPixmap(icons.tile(
            self._icon_name, palette["tileIcon"], palette["tileBg"], 28))
        self.set_state(self._state_key, self._note)

    def set_value(self, path: str) -> None:
        self.edit.set_full_text(path)

    def set_state(self, state: str, note: str = "") -> None:
        """Colour never carries the state alone: the icon and this tooltip say it."""
        self._state_key = state
        self._note = note
        tones = {"empty": self._palette["unknown"], "ok": self._palette["ok"],
                 "warn": self._palette["warn"], "error": self._palette["fail"]}
        self.state.setPixmap(icons.pixmap(
            _FIELD_STATE.get(state, _FIELD_STATE["empty"]),
            tones.get(state, self._palette["unknown"]), 16))
        self.state.setToolTip(note)

    @property
    def state_key(self) -> str:
        return self._state_key

    @property
    def note(self) -> str:
        return self._note

    def value(self) -> str:
        return self.edit.full_text().strip()


def _path_label(path) -> str:
    if not path:
        return "config.plist"
    parts = []
    for part in path:
        parts.append("[{}]".format(part) if isinstance(part, int)
                     else str(part))
    return " > ".join(parts)


class _ConfigValueDelegate(QStyledItemDelegate):
    """Inline editing only for scalar values, with the untruncated text.

    The tree shows a shortened value so one long string cannot stretch a column;
    handing that shortened text to the editor would silently overwrite the rest
    of the value when the row was left unchanged.
    """

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window

    def _value(self, index):
        document = self._window._config_doc
        source = index.model().index(index.row(), 0, index.parent())
        path = source.data(Qt.UserRole)
        if document is None or not path:
            return None
        try:
            return config_editor.get_at(document.data, tuple(path))
        except (KeyError, IndexError, TypeError):
            return None

    def createEditor(self, parent, option, index):
        if index.column() != 1:
            return None
        value = self._value(index)
        if value is None or isinstance(value, (bool, dict, list, bytes)):
            return None
        if isinstance(value, str) and "\n" in value:
            return None
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index) -> None:
        value = self._value(index)
        if isinstance(editor, QLineEdit) and value is not None:
            if isinstance(value, str):
                editor.setText(value)
            elif isinstance(value, float):
                editor.setText(repr(value))
            else:
                editor.setText(str(value))
            return
        super().setEditorData(editor, index)


class _TextDialog(QDialog):
    """A modal editor for data bytes and multi-line strings."""

    def __init__(self, parent, title: str, path: tuple, text: str,
                 monospace: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(520, 300 if monospace else 260)
        self._parser = None
        self._payload = None
        self._binary = monospace
        self._hex_hint = "Hexadecimal bytes. Spaces are ignored."
        self._text_hint = (
            "Text view. Printable ASCII is shown as text; other bytes as "
            "\\xNN escapes.")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        heading = QLabel(_path_label(path))
        heading.setObjectName("rowTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        if monospace:
            hint_row = QHBoxLayout()
            hint_row.setSpacing(8)
            self.hint = QLabel(self._hex_hint)
            self.hint.setObjectName("rowBody")
            self.hint.setWordWrap(True)
            self.text_toggle = QCheckBox("Show as text")
            self.text_toggle.toggled.connect(self._on_text_toggled)
            hint_row.addWidget(self.hint, 1)
            hint_row.addWidget(self.text_toggle, 0)
            layout.addLayout(hint_row)
        self.edit = QPlainTextEdit()
        self.edit.setPlainText(text)
        if monospace:
            font = QFont("monospace")
            font.setStyleHint(QFont.StyleHint.Monospace)
            self.edit.setFont(font)
            self.edit.setPlaceholderText("00 01 02 \u2026")
        layout.addWidget(self.edit, 1)
        self.error = QLabel()
        self.error.setObjectName("rowBody")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        apply_button = buttons.addButton("Apply", QDialogButtonBox.AcceptRole)
        apply_button.setObjectName("primary")
        buttons.rejected.connect(self.reject)
        apply_button.clicked.connect(self._submit)
        layout.addWidget(buttons)

    def set_parser(self, parser) -> None:
        self._parser = parser

    def _on_text_toggled(self, checked: bool) -> None:
        try:
            if checked:
                raw = self._parser(self.edit.toPlainText())
                self.edit.setPlainText(config_editor.data_to_text(raw))
                self.hint.setText(self._text_hint)
            else:
                raw = config_editor.text_to_data(self.edit.toPlainText())
                self.edit.setPlainText(config_editor.data_to_hex(raw))
                self.hint.setText(self._hex_hint)
        except ValueError as exc:
            self.text_toggle.blockSignals(True)
            self.text_toggle.setChecked(not checked)
            self.text_toggle.blockSignals(False)
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.error.setVisible(False)

    def _submit(self) -> None:
        text = self.edit.toPlainText()
        try:
            if self._binary and self.text_toggle.isChecked():
                self._payload = config_editor.text_to_data(text)
            else:
                self._payload = self._parser(text) if self._parser else text
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.accept()

    def payload(self):
        return self._payload


class _AddKeyDialog(QDialog):
    """Pick a standard child key or name a new one."""

    def __init__(self, parent, suggestions, existing: set,
                 palette: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a key")
        self.setMinimumWidth(420)
        self._suggestions = {key: value for key, value in suggestions}
        self._existing = existing
        self._value = ("", None)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(8)
        self.key_combo = QComboBox()
        self.key_combo.setEditable(True)
        self.key_combo.setInsertPolicy(QComboBox.NoInsert)
        self.key_combo.addItems(list(self._suggestions))
        self.key_combo.currentTextChanged.connect(self._on_key_changed)
        form.addRow("Key", self.key_combo)
        self.type_combo = QComboBox()
        self.type_combo.addItems(config_editor.PLIST_TYPES)
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        form.addRow("Type", self.type_combo)
        self.default_field = QLineEdit()
        self.default_field.setPlaceholderText("Default value")
        form.addRow("Default", self.default_field)
        layout.addLayout(form)
        hint = QLabel(
            "Suggested keys and defaults come from the pinned OpenCore 1.0.8 "
            "sample.")
        hint.setObjectName("rowBody")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.error = QLabel()
        self.error.setObjectName("rowBody")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        add_button = buttons.addButton("Add", QDialogButtonBox.AcceptRole)
        add_button.setObjectName("primary")
        buttons.rejected.connect(self.reject)
        add_button.clicked.connect(self._submit)
        layout.addWidget(buttons)
        if self.key_combo.count():
            self.key_combo.setCurrentIndex(0)
            self._on_key_changed(self.key_combo.currentText())
        self._on_type_changed(self.type_combo.currentText())

    def _on_key_changed(self, text: str) -> None:
        value = self._suggestions.get(text)
        if value is None:
            return
        kind = config_editor.type_name(value)
        self.type_combo.setCurrentText(kind)
        self.default_field.setText(_editable_text(value, kind))

    def _on_type_changed(self, kind: str) -> None:
        composite = kind in ("dictionary", "array")
        self.default_field.setEnabled(not composite)
        if composite:
            self.default_field.clear()

    def _submit(self) -> None:
        key = self.key_combo.currentText().strip()
        if not key:
            self._fail("Enter a key name.")
            return
        if key in self._existing:
            self._fail("That key already exists.")
            return
        kind = self.type_combo.currentText()
        if kind == "dictionary":
            value = {}
        elif kind == "array":
            value = []
        else:
            try:
                value = config_editor.parse_value(
                    kind, self.default_field.text())
            except ValueError as exc:
                self._fail(str(exc))
                return
        self._value = (key, value)
        self.accept()

    def _fail(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(True)

    def result_value(self):
        return self._value


class _PresetDialog(QDialog):
    """Pick a ready-made patch entry for the open document."""

    def __init__(self, parent, presets, section: str | None,
                 palette: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("Insert a preset")
        self.setMinimumSize(600, 460)
        self._presets = list(presets)
        self._selected = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        hint = QLabel(
            "Ready-made entries from the OpenCore Auxiliary Tools preset "
            "library, checked against the pinned OpenCore 1.0.8 schema. "
            "Nothing is written until you save.")
        hint.setObjectName("rowBody")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Preset"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.tree.itemActivated.connect(self._on_activated)
        layout.addWidget(self.tree, 1)
        self.title_label = QLabel("Choose a preset")
        self.title_label.setObjectName("rowTitle")
        self.title_label.setWordWrap(True)
        self.target_label = QLabel()
        self.target_label.setObjectName("rowBody")
        self.target_label.setWordWrap(True)
        self.detail_label = QLabel("Select a preset to see what it changes.")
        self.detail_label.setObjectName("rowBody")
        self.detail_label.setWordWrap(True)
        self.state_label = QLabel()
        self.state_label.setObjectName("rowBody")
        self.state_label.setWordWrap(True)
        for label in (self.title_label, self.target_label,
                      self.detail_label, self.state_label):
            layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.insert_button = buttons.addButton(
            "Insert", QDialogButtonBox.AcceptRole)
        self.insert_button.setObjectName("primary")
        self.insert_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        self.insert_button.clicked.connect(self._accept)
        layout.addWidget(buttons)
        self._populate(section)

    def _populate(self, section: str | None) -> None:
        groups: dict[str, QTreeWidgetItem] = {}
        preferred = None
        for preset in self._presets:
            target = config_presets.path_label(preset.target)
            group = groups.get(target)
            if group is None:
                group = QTreeWidgetItem([target])
                group.setFlags(Qt.ItemIsEnabled)
                self.tree.addTopLevelItem(group)
                groups[target] = group
            child = QTreeWidgetItem([preset.title])
            child.setData(0, Qt.UserRole, preset.key)
            child.setToolTip(0, preset.detail)
            group.addChild(child)
            if preferred is None and section and preset.target[0] == section:
                preferred = child
        self.tree.expandAll()
        first = preferred
        if first is None and self.tree.topLevelItemCount():
            first = self.tree.topLevelItem(0).child(0)
        if first is not None:
            self.tree.setCurrentItem(first)
        self.tree.setFocus()

    def _on_current_changed(self, current, _previous=None) -> None:
        key = current.data(0, Qt.UserRole) if current is not None else None
        preset = config_presets.preset_by_key(key) if key else None
        self._selected = preset
        self.insert_button.setEnabled(preset is not None)
        if preset is None:
            self.title_label.setText("Choose a preset")
            self.target_label.setText("")
            self.detail_label.setText("Select a preset to see what it changes.")
            self.state_label.setText("")
            return
        self.title_label.setText(preset.title)
        self.target_label.setText(
            "Target: {}".format(config_presets.path_label(preset.target)))
        self.detail_label.setText(preset.detail)
        if preset.value.get("Enabled"):
            self.state_label.setText("Will be inserted enabled.")
        else:
            self.state_label.setText(
                "Will be inserted disabled; turn Enabled on to use it.")

    def _on_activated(self, _item, _column) -> None:
        if self.insert_button.isEnabled():
            self._accept()

    def _accept(self) -> None:
        if self._selected is not None:
            self.accept()

    def selected_preset(self):
        return self._selected


class _SerialDialog(QDialog):
    def __init__(self, parent, models, current: str, palette: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate SMBIOS serials")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(8)
        self.model_combo = _Combo(palette)
        self.model_combo.addItems(models)
        if current:
            index = self.model_combo.findText(current)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
        form.addRow("Model", self.model_combo)
        layout.addLayout(form)
        hint = QLabel(
            "Serials come from OpenCore's macserial. They are random, and "
            "nothing is written until you save.")
        hint.setObjectName("rowBody")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        generate = buttons.addButton("Generate", QDialogButtonBox.AcceptRole)
        generate.setObjectName("primary")
        buttons.rejected.connect(self.reject)
        generate.clicked.connect(self.accept)
        layout.addWidget(buttons)

    def selected_model(self) -> str:
        return self.model_combo.currentText()


class _ChangesDialog(QDialog):
    """Every edit since the file was opened, read-only and exportable."""

    def __init__(self, parent, changes, path, palette: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("Changes since the file was opened")
        self.setMinimumSize(760, 420)
        self._changes = list(changes)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        heading = QLabel(str(path))
        heading.setObjectName("rowTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        hint = QLabel(
            "These edits live in memory. Nothing is written until you press "
            "Save, and config.plist.bak is kept when you do.")
        hint.setObjectName("rowBody")
        hint.setWordWrap(True)
        self._hint = hint
        layout.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setObjectName("configTree")
        self.tree.setHeaderLabels(["Change", "Key", "Before", "After"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.tree.setColumnWidth(0, 92)
        for change in self._changes:
            before, after = change.pair
            self.tree.addTopLevelItem(QTreeWidgetItem([
                change.kind.capitalize(), change.label, before, after]))
        if not self._changes:
            empty = QTreeWidgetItem([
                "None", "No edits since the file was opened.", "", ""])
            empty.setFlags(Qt.NoItemFlags)
            self.tree.addTopLevelItem(empty)
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy = buttons.addButton("Copy", QDialogButtonBox.ActionRole)
        save = buttons.addButton("Save as text\u2026", QDialogButtonBox.ActionRole)
        copy.setObjectName("outline")
        save.setObjectName("outline")
        copy.clicked.connect(self._copy)
        save.clicked.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy(self) -> None:
        QApplication.clipboard().setText(config_diff.to_text(self._changes))

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save changes", str(Path.home() / "blackdream-changes.txt"),
            "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            Path(path).write_text(
                config_diff.to_text(self._changes), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "The changes could not be saved", str(exc))
            return
        self._hint.setText("Saved to {}. Nothing was written into the config.".format(
            path))


class _DiagnosticsDialog(QDialog):
    """Choose what goes into a diagnostic bundle, then read it before saving."""

    def __init__(self, parent, bundle: diagnostics.Bundle,
                 palette: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save a diagnostic bundle")
        self.setMinimumSize(720, 520)
        self.bundle = bundle
        self.saved_path = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        heading = QLabel("Choose what to include")
        heading.setObjectName("rowTitle")
        layout.addWidget(heading)
        hint = QLabel(
            "Nothing is uploaded. The bundle is written to the folder you pick, "
            "and you attach it yourself. Serial, MLB, UUID and ROM values are "
            "replaced with <redacted>, and your home folder is shortened to ~.")
        hint.setObjectName("rowBody")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.choices = QListWidget()
        self.choices.setObjectName("configSections")
        self.choices.setMaximumHeight(150)
        for entry in bundle.entries:
            label = entry.name + (" \u00b7 " + entry.note if entry.note else "")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry.name)
            item.setToolTip(entry.note)
            if entry.optional:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if entry.included else Qt.Unchecked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
            self.choices.addItem(item)
        self.choices.itemChanged.connect(self._sync)
        layout.addWidget(self.choices)
        preview_label = QLabel("The text that will be written")
        preview_label.setObjectName("rowTitle")
        layout.addWidget(preview_label)
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("configIssues")
        self.preview.setReadOnly(True)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.preview.setFont(font)
        layout.addWidget(self.preview, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        save = buttons.addButton("Save bundle\u2026",
                                 QDialogButtonBox.AcceptRole)
        save.setObjectName("primary")
        buttons.rejected.connect(self.reject)
        save.clicked.connect(self._save)
        layout.addWidget(buttons)
        self._refresh_preview()

    def _sync(self, item) -> None:
        name = item.data(Qt.UserRole)
        if name is None:
            return
        self.bundle.set_included(name, item.checkState() == Qt.Checked)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self.preview.setPlainText(self.bundle.render())

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the diagnostic bundle",
            str(Path.home() / "blackdream-diagnostics.zip"),
            "Zip archive (*.zip);;Text file (*.txt)")
        if not path:
            return
        try:
            if path.lower().endswith(".txt"):
                self.bundle.write_text(path)
            else:
                self.bundle.write_zip(path)
        except OSError as exc:
            QMessageBox.warning(
                self, "The bundle could not be written", str(exc))
            return
        self.saved_path = path
        self.accept()


def _editable_text(value, kind: str) -> str:
    if kind == "boolean":
        return "true" if value else "false"
    if kind == "real":
        return repr(value)
    if kind == "data":
        return config_editor.data_to_hex(value)
    if kind == "date":
        return value.isoformat()
    if kind in ("dictionary", "array"):
        return ""
    return str(value)


class _Metric(QFrame):
    def __init__(self, icon_name: str, label: str, value: str = "\u2014",
                 compact: bool = False) -> None:
        super().__init__()
        self.setObjectName("metric")
        self._icon_size = 14 if compact else 16
        self.setMinimumHeight(32 if compact else 38)
        layout = QHBoxLayout(self)
        if compact:
            layout.setContentsMargins(7, 2, 7, 2)
        else:
            layout.setContentsMargins(9, 4, 9, 4)
        layout.setSpacing(6 if compact else 7)
        self._icon_name = icon_name
        self.icon = QLabel()
        self.icon.setFixedSize(self._icon_size, self._icon_size)
        column = QVBoxLayout()
        column.setSpacing(0)
        caption = QLabel(label)
        caption.setObjectName("metricLabel")
        self.value = QLabel(value)
        self.value.setObjectName("metricValue")
        column.addWidget(caption)
        column.addWidget(self.value)
        layout.addWidget(self.icon, 0, Qt.AlignVCenter)
        layout.addLayout(column, 1)

    def apply_palette(self, palette: dict) -> None:
        self.icon.setPixmap(icons.pixmap(
            self._icon_name, palette["tileIcon"], self._icon_size))

    def set(self, text: str) -> None:
        self.value.setText(text)


class _StageRow(QWidget):
    _TONES = {"done": "ok", "running": "accentSoft", "pending": "faint",
              "failed": "fail", "cancelled": "muted"}

    def __init__(self, name: str, state: str, elapsed: str, palette: dict) -> None:
        super().__init__()
        self._palette = palette
        self._state = ""
        self._time_text = ""
        self._angle = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 4, 0)
        layout.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        self.name_label = QLabel(name)
        self.name_label.setObjectName("stageName")
        self.time = QLabel(elapsed)
        self.time.setObjectName("stageTime")
        self.time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.icon, 0, Qt.AlignVCenter)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(self.time, 0)
        self.setFixedHeight(26)
        # Only a running stage animates; the row owns the timer so an idle
        # checklist costs nothing.
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(90)
        self._spinner_timer.timeout.connect(self._advance_spinner)
        self.set_state(state, elapsed)

    def set_palette(self, palette: dict) -> None:
        self._palette = palette
        state, self._state = self._state, ""
        self.set_state(state, self._time_text)

    def set_state(self, state: str, elapsed: str) -> None:
        changed = state != self._state
        if not changed and elapsed == self._time_text:
            return
        self._state = state
        self._time_text = elapsed
        self.time.setText(elapsed)
        if changed:
            self.name_label.setProperty("state", state)
            _repolish(self.name_label)
        tone = self._palette[self._TONES.get(state, "faint")]
        if state == "running":
            self._tone = tone
            if not self._spinner_timer.isActive():
                self._spinner_timer.start()
            self._paint_spinner()
        else:
            self._spinner_timer.stop()
            self.icon.setPixmap(
                icons.pixmap(_STAGE_ICON.get(state, "dot"), tone, 16))

    def _paint_spinner(self) -> None:
        self.icon.setPixmap(icons.spinner(self._tone, 16, self._angle))

    def _advance_spinner(self) -> None:
        self._angle = (self._angle + 1) % icons._SPINNER_FRAMES
        self._paint_spinner()

    def set_time(self, text: str) -> None:
        if text == self._time_text:
            return
        self._time_text = text
        self.time.setText(text)


class _VerdictTree(QTreeWidget):
    """The device table, with the Status column kept inside the card.

    Fixed columns do not shrink; when the window reached its minimum width the
    last column fell outside the viewport and every badge was cut in half. The
    support column gives way first, and the detail pane still carries the full
    release range.
    """

    _CLASS_WIDTH = 72
    _STATUS_MIN = 100
    _SUPPORT_MIN = 110
    _SUPPORT_MAX = 266
    # The device name identifies the row; the release range already repeats in
    # the details pane, so it is the column that elides first.
    _DEVICE_MIN = 165

    def __init__(self) -> None:
        super().__init__()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._status_width = self._STATUS_MIN
        # The vertical scrollbar takes width from the viewport; fitting only on
        # resize left the Status column tucked under it.
        self.verticalScrollBar().rangeChanged.connect(self._fit_columns)

    def fit_status(self, widest_text: int) -> None:
        # "Not supported" is wider than the cells the table first shipped with;
        # painting clipped it. The column carries whatever words are on screen.
        width = max(self._STATUS_MIN, widest_text + 40)
        if width != self._status_width:
            self._status_width = width
            self._fit_columns()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_columns()

    def _fit_columns(self, *_args) -> None:
        available = self.viewport().width()
        support = min(self._SUPPORT_MAX,
                      max(self._SUPPORT_MIN,
                          available - self._CLASS_WIDTH - self._status_width
                          - self._DEVICE_MIN))
        if self.columnWidth(2) != support:
            self.setColumnWidth(2, support)
        if self.columnWidth(3) != self._status_width:
            self.setColumnWidth(3, self._status_width)

    def sizeHint(self) -> QSize:
        # The table scrolls its own rows; letting its full preferred height set
        # the page height left the engine log below the fold at 1536x1024.
        hint = super().sizeHint()
        return QSize(hint.width(), min(hint.height(), 172))


class _StatusDelegate(QStyledItemDelegate):
    """Paints the Status column as an icon and coloured word, as the mockup does.

    The item's data stays plain text, so the table still sorts and copies as text.
    """

    def __init__(self, palette: dict) -> None:
        super().__init__()
        self.palette = palette

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(30)
        return size

    def paint(self, painter, option, index) -> None:
        view_option = QStyleOptionViewItem(option)
        self.initStyleOption(view_option, index)
        text = view_option.text
        view_option.text = ""
        widget = view_option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, view_option, painter, widget)
        if not text:
            return
        key = index.data(Qt.UserRole) or "unknown"
        tone = _STATUS_TONE.get(key, "unknown")
        foreground = qcolor(self.palette[tone])
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        icon_size = 15
        left = view_option.rect.left() + 8
        painter.drawPixmap(int(left),
                           int(view_option.rect.center().y() - icon_size / 2),
                           icons.pixmap(_STATUS_ICON.get(tone, "dot"),
                                        self.palette[tone], icon_size))
        painter.setPen(foreground)
        painter.drawText(QRectF(left + icon_size + 6, view_option.rect.top(),
                                view_option.rect.width() - icon_size - 16,
                                view_option.rect.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _aml_tables(folder: str) -> int:
    """How many ACPI tables the engine would consider here, or -1 for no folder.

    Mirrors the two rules ``read_acpi_tables`` applies before it opens a file -- the
    name must not contain "Patched", and a bare report root may hold its tables one
    level down in ``ACPI`` -- and stops there. Whether a table disassembles is the
    engine's answer, not this one.
    """
    root = Path(folder)
    if not root.is_dir():
        return -1
    for candidate in (root, root / "ACPI"):
        try:
            names = [entry.name for entry in candidate.iterdir()]
        except OSError:
            continue
        found = [name for name in names
                 if name.endswith(".aml") and "Patched" not in name]
        if found:
            return len(found)
    return 0


def _dropped_json(event: QDropEvent) -> str:
    """The first dropped path that could be a hardware report, or "".

    Accepts a bare ``Report.json`` or any ``.json``: which one is valid is the
    validator's decision, not the drag handler's.
    """
    data = event.mimeData()
    if not data.hasUrls():
        return ""
    for url in data.urls():
        if url.isLocalFile():
            path = url.toLocalFile()
            if path.endswith(".json") or Path(path).name == "Report.json":
                return path
    return ""
