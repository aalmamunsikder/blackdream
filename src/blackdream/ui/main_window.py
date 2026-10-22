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

import html
import os
import platform
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QFontMetrics,
    QIcon, QKeySequence, QLinearGradient, QPainter, QPen, QRadialGradient,
    QShortcut)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizeGrip, QSizePolicy, QStackedWidget, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget)

from ocengine import paths
from ocengine import runtime
from ocengine.fatal import EngineError

from blackdream import __version__, hardware
from blackdream.core import verdicts
from blackdream.core.job_runner import (
    CANCELLED, DONE, Job, JobRunner, Outcome, UnexpectedEngineFailure)
from blackdream.core.pipeline import (
    OUTPUT_MARKER, BuildNotReady, Pipeline, _STEPS)
from blackdream.ui import icons
from blackdream.ui.bridge import EngineBridge, JobSignals
from blackdream.ui.theme import DARK, LIGHT, qcolor, stylesheet

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
    "Compatibility": "pulse", "Build EFI": "build", "Logs": "logs",
    "Settings": "gear", "Help": "help", "Donate": "heart",
}
_PRIMARY_VIEWS = ("Compatibility", "Build EFI", "Logs")
_SECONDARY_VIEWS = ("Settings", "Help", "Donate")
_VIEWS = _PRIMARY_VIEWS + _SECONDARY_VIEWS
_PAGE_COPY = {
    "Compatibility": (
        "Hardware Compatibility",
        "Review what macOS can run on this machine, then build the EFI folder."),
    "Build EFI": (
        "Build EFI Folder",
        "Watch the engine work and open the folder when it is done."),
    "Logs": (
        "Engine Log",
        "Every message the engine reported, in order."),
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
_BUILD_JOBS = frozenset({"Selecting patches and kexts", "Downloading OpenCore and kexts",
                         "Writing the EFI folder"})
_FILTERS = ("Info and above", "Warnings and above", "Everything")


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


class MainWindow(QMainWindow):
    """One window, one engine session. Loading a new report replaces the session."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BlackDream")
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowIcon(QIcon(icons.logo(64)))
        self.resize(1440, 940)
        self.setMinimumSize(1240, 800)
        self.setAcceptDrops(True)

        font = QFont()
        font.setFamilies(["Inter", "SF Pro Text", "Segoe UI", "Noto Sans", "DejaVu Sans"])
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

        self._pipeline: Pipeline | None = None
        self.analysis = None
        self.plan = None
        self._options: list = []
        self._chain: list[_Step] = []
        self._result_dir: Path | None = None
        self._report_path: Path | None = None
        self._settings = QSettings("BlackDream", "BlackDream")
        stored_theme = self._settings.value("appearance/dark", False)
        self._dark = (stored_theme if isinstance(stored_theme, bool)
                      else str(stored_theme).lower() == "true")
        self._last_error_code = ""
        self._view = "Compatibility"
        self._verdicts: list[verdicts.Verdict] = []
        self._items: list[QTreeWidgetItem] = []
        self._current_verdict: verdicts.Verdict | None = None
        self._filter_text = ""
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
        self._apply_theme()
        self._reset_progress()
        self._reset_details()
        self._set_busy(False)
        self._show_error(None)
        self._show_view("Compatibility")
        self._validate_output()
        self._validate_acpi()
        self._install_shortcuts()
        self.statusBar().showMessage("Ready")
        self.statusBar().hide()

        self._ticker = QTimer(self)
        self._ticker.setInterval(60)
        self._ticker.timeout.connect(self._drain)
        self._ticker.start()

    # ---- widget construction ----

    def _build_widgets(self) -> None:
        self._backdrop = _Backdrop(LIGHT)
        self.shell = QFrame()
        self.shell.setObjectName("shell")
        shell_layout = QHBoxLayout(self.shell)
        shell_layout.setContentsMargins(10, 10, 10, 10)
        shell_layout.setSpacing(14)
        shell_layout.addWidget(self._build_sidebar(), 0)
        shell_layout.addWidget(self._build_content(), 1)

        outer = QVBoxLayout(self._backdrop)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(0)
        outer.addWidget(self.shell)
        self.setCentralWidget(self._backdrop)

        self._grip = QSizeGrip(self._backdrop)
        self._grip.setFixedSize(18, 18)
        self._grip.raise_()
        self._position_grip()

    def _build_sidebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(232)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(3)

        dots = QHBoxLayout()
        dots.setContentsMargins(2, 0, 2, 0)
        dots.setSpacing(7)
        for name, tip, slot in (
                ("trafficRed", "Close", self.close),
                ("trafficYellow", "Minimize", self.showMinimized),
                ("trafficGreen", "Zoom", self._toggle_maximized)):
            dot = QPushButton()
            dot.setObjectName(name)
            dot.setFixedSize(12, 12)
            dot.setToolTip(tip)
            dot.clicked.connect(slot)
            dots.addWidget(dot)
        dots.addStretch(1)
        layout.addLayout(dots)
        layout.addSpacing(22)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(icons.logo(36))
        mark.setFixedSize(36, 36)
        names = QVBoxLayout()
        names.setSpacing(0)
        title = QLabel("BlackDream")
        title.setObjectName("brand")
        hint = QLabel("OpenCore EFI builder.")
        hint.setObjectName("brandHint")
        names.addWidget(title)
        names.addWidget(hint)
        brand.addWidget(mark, 0, Qt.AlignVCenter)
        brand.addLayout(names, 1)
        layout.addLayout(brand)
        layout.addSpacing(26)

        self.nav_buttons: list[QPushButton] = []
        for name in _PRIMARY_VIEWS:
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setIconSize(QSize(18, 18))
            button.setMinimumHeight(40)
            button.clicked.connect(lambda _checked, which=name: self._show_view(which))
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
            button.setMinimumHeight(36)
            button.clicked.connect(lambda _checked, which=name: self._show_view(which))
            layout.addWidget(button)
            self.secondary_buttons.append(button)
        self.settings_button = self.secondary_buttons[0]
        self.help_button = self.secondary_buttons[1]
        self.donate_button = self.secondary_buttons[2]
        return bar

    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        header = _DragFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 2, 4, 2)
        header_layout.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.page_title = QLabel("Hardware Compatibility")
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel(
            "Review what macOS can run on this machine, then build the EFI folder.")
        self.page_subtitle.setObjectName("pageSubtitle")
        self.page_subtitle.setWordWrap(True)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header_layout.addLayout(titles, 1)

        self.search = _SearchPill(self._palette_or_light())
        self.search.search_input.textChanged.connect(self._on_search)
        header_layout.addWidget(self.search, 0, Qt.AlignVCenter)

        self.theme_button = QPushButton()
        self.theme_button.setObjectName("iconButton")
        self.theme_button.setFixedSize(38, 38)
        self.theme_button.setIconSize(QSize(18, 18))
        self.theme_button.clicked.connect(self._toggle_theme)
        header_layout.addWidget(self.theme_button, 0, Qt.AlignVCenter)
        layout.addWidget(header)

        self.error_card = QLabel()
        self.error_card.setObjectName("errorCard")
        self.error_card.setWordWrap(True)
        self.error_card.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.error_card.setVisible(False)
        layout.addWidget(self.error_card)

        self._build_cards()

        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(self._scrollable(self._compatibility_page()))
        self.page_stack.addWidget(self._scrollable(self._build_page()))
        self.page_stack.addWidget(self._logs_page())
        self.page_stack.addWidget(self._scrollable(self._settings_page()))
        self.page_stack.addWidget(self._scrollable(self._help_page()))
        self.page_stack.addWidget(self._scrollable(self._donate_page()))
        layout.addWidget(self.page_stack, 1)
        return content

    def _palette_or_light(self) -> dict:
        return DARK if self._dark else LIGHT

    def _build_cards(self) -> None:
        self.files_card = _Card(
            "Select files",
            "Provide your hardware report and any optional ACPI tables.", number=1)
        self.report_field = _PathPicker(
            "Hardware report", "file", self._pick_report, palette=LIGHT)
        self.acpi_field = _PathPicker(
            "ACPI tables (optional)", "layers", self._pick_acpi_dir, palette=LIGHT)
        self.files_card.add(self.report_field)
        self.files_card.add(self.acpi_field)
        machine = QHBoxLayout()
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
        self.files_card.add(machine)
        self.files_card.finish()

        self.version_card = _Card(
            "macOS version", "Choose the macOS version you want to build for.", number=2)
        self.version_combo = _Combo(LIGHT)
        self.version_combo.setObjectName("versionCombo")
        self.version_combo.setMinimumHeight(40)
        self.version_combo.currentIndexChanged.connect(self._on_version_changed)
        self.version_card.add(self.version_combo)
        caption = QLabel("Detected support")
        caption.setObjectName("pathLabel")
        self.version_card.add(caption)
        self.summary = QLabel(_report_hint())
        self.summary.setObjectName("summary")
        self.summary.setWordWrap(True)
        self.summary.setProperty("state", "empty")
        self.summary_note = QLabel(
            "Support ranges come from the report's own compatibility data.")
        self.summary_note.setObjectName("summaryNote")
        self.summary_note.setWordWrap(True)
        self.version_card.add(self.summary)
        self.version_card.add(self.summary_note)
        self.version_card.finish()

        self.actions_card = _Card(
            "Actions", "The EFI is a folder; nothing is mounted or written to a disk.",
            number=3)
        self.output_field = _PathPicker(
            "Output folder", "folder", self._pick_output,
            value=str(self._default_output()), palette=LIGHT)
        self.actions_card.add(self.output_field)
        primary = QHBoxLayout()
        primary.setSpacing(8)
        self.build_button = QPushButton("Build EFI folder")
        self.build_button.setObjectName("primary")
        self.build_button.setMinimumHeight(38)
        self.build_button.clicked.connect(self._on_build)
        self.analyze_button = QPushButton("Check compatibility")
        self.analyze_button.setObjectName("outline")
        self.analyze_button.setMinimumHeight(38)
        self.analyze_button.clicked.connect(self._on_analyze)
        primary.addWidget(self.build_button, 1)
        primary.addWidget(self.analyze_button, 1)
        self.actions_card.add(primary)
        secondary = QHBoxLayout()
        secondary.setSpacing(8)
        self.reveal_button = QPushButton("Open EFI folder")
        self.reveal_button.setObjectName("outline")
        self.reveal_button.clicked.connect(self._reveal_result)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("outline")
        self.cancel_button.clicked.connect(self._on_cancel)
        secondary.addWidget(self.reveal_button)
        secondary.addWidget(self.cancel_button)
        secondary.addStretch(1)
        self.actions_card.add(secondary)
        self.actions_card.finish()

        self.devices_card = _Card(
            "Detected devices", "No report loaded yet.")
        self.view_details_button = QPushButton("View details")
        self.view_details_button.setObjectName("link")
        self.view_details_button.clicked.connect(self._focus_worst_device)
        self.devices_card.set_header_widget(self.view_details_button)
        self.empty_note = QLabel(
            "Load a report to see this machine's devices and what macOS does with them.")
        self.empty_note.setObjectName("emptyNote")
        self.empty_note.setWordWrap(True)
        self.devices_card.add(self.empty_note)
        self._status_delegate = _StatusDelegate(LIGHT)
        self.verdict_tree = QTreeWidget()
        self.verdict_tree.setHeaderLabels(
            ["Device", "Class", "macOS support", "Status"])
        self.verdict_tree.setRootIsDecorated(False)
        self.verdict_tree.setAlternatingRowColors(True)
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
        self.verdict_tree.setColumnWidth(1, 94)
        self.verdict_tree.setColumnWidth(2, 268)
        self.verdict_tree.setColumnWidth(3, 124)
        self.verdict_tree.setMinimumHeight(176)
        self.verdict_tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.verdict_tree.itemSelectionChanged.connect(self._on_device_selected)
        self.devices_card.add(self.verdict_tree, 1)

        self.details_card = _Card("Device details")
        self.detail_badge = QLabel()
        self.detail_badge.setObjectName("badge")
        self.detail_badge.setVisible(False)
        self.details_card.set_header_widget(self.detail_badge)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
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
        self.details_card.finish()

        self.progress_card = _Card(
            "Build progress", "Step, transfer and timing from the engine.")
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
        self.stage_list.setMinimumHeight(120)
        self.stage_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)

        task = QFrame()
        task.setObjectName("taskCard")
        task_layout = QVBoxLayout(task)
        task_layout.setContentsMargins(10, 6, 10, 6)
        task_layout.setSpacing(2)
        task_title = QLabel("CURRENT TASK")
        task_title.setObjectName("taskTitle")
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
        self.transfer_label = QLabel("No transfer in progress.")
        self.transfer_label.setObjectName("taskDetail")
        task_layout.addWidget(task_title)
        task_layout.addWidget(self.task_name)
        task_layout.addWidget(self.task_detail)
        task_layout.addWidget(self.task_progress)
        task_layout.addWidget(self.transfer_label)

        # Checklist and current task share a row: stacking them made the card the
        # tallest thing on the page and pushed the table into a scrollbar.
        task_row = QHBoxLayout()
        task_row.setSpacing(12)
        task_row.addWidget(self.stage_list, 3)
        task_row.addWidget(task, 2)
        self.progress_card.add(task_row, 1)

        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        self.metric_elapsed = _Metric("clock", "Elapsed time")
        self.metric_downloaded = _Metric("download", "Downloaded", "0 B")
        self.metric_speed = _Metric("gauge", "Speed")
        self.metric_step = _Metric("steps", "Step", "0/0")
        for metric in (self.metric_elapsed, self.metric_downloaded,
                       self.metric_speed, self.metric_step):
            metrics.addWidget(metric, 1)
        self.progress_card.add(metrics)

        self.log_card = _Card("Engine log")
        tools = QWidget()
        tool_layout = QHBoxLayout(tools)
        tool_layout.setContentsMargins(0, 0, 0, 0)
        tool_layout.setSpacing(6)
        self.level_filter = _Combo(LIGHT)
        self.level_filter.setObjectName("levelFilter")
        self.level_filter.setFixedWidth(162)
        self.level_filter.addItems(list(_FILTERS))
        self.level_filter.currentIndexChanged.connect(self._rerender_log)
        self.save_log_button = QPushButton("Save log\u2026")
        self.save_log_button.setObjectName("chip")
        self.save_log_button.clicked.connect(self._save_log)
        self.copy_log_button = QPushButton()
        self.copy_log_button.setObjectName("iconSmall")
        self.copy_log_button.setFixedSize(30, 30)
        self.copy_log_button.setIconSize(QSize(15, 15))
        self.copy_log_button.setToolTip("Copy the log")
        self.copy_log_button.clicked.connect(self._copy_log)
        tool_layout.addWidget(self.level_filter)
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

    def _compatibility_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._compat_top = QHBoxLayout()
        self._compat_top.setSpacing(12)
        self._compat_top.addWidget(self.files_card, 4)
        self._compat_top.addWidget(self.version_card, 3)
        layout.addLayout(self._compat_top)

        middle = QHBoxLayout()
        middle.setSpacing(12)
        middle.addWidget(self.devices_card, 3)
        middle.addWidget(self.details_card, 2)
        layout.addLayout(middle, 1)

        self._compat_bottom = QHBoxLayout()
        self._compat_bottom.setSpacing(12)
        self._compat_bottom.setContentsMargins(0, 0, 0, 0)
        # The checklist keeps its natural height; every spare pixel goes to the
        # device table, which is the part that can actually use the room.
        layout.addLayout(self._compat_bottom)
        return page

    def _build_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._build_top = QHBoxLayout()
        self._build_top.setSpacing(12)
        self._build_bottom = QVBoxLayout()
        self._build_bottom.setSpacing(12)
        layout.addLayout(self._build_top)
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
            "The theme applies immediately and is remembered for the next launch.")
        theme_row = QHBoxLayout()
        theme_row.setSpacing(12)
        theme_label = QLabel("Theme")
        theme_label.setObjectName("detailKey")
        self.theme_combo = _Combo(LIGHT)
        self.theme_combo.setObjectName("themeCombo")
        self.theme_combo.setFixedWidth(180)
        self.theme_combo.addItems(["Light", "Dark"])
        self.theme_combo.setCurrentIndex(1 if self._dark else 0)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_choice)
        theme_row.addWidget(theme_label)
        theme_row.addStretch(1)
        theme_row.addWidget(self.theme_combo)
        self.appearance_card.add(theme_row)
        self.appearance_card.finish()

        self.about_card = _Card("About")
        version = QLabel("BlackDream {}".format(__version__))
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
            "Quick start", "Four steps from a report to an EFI folder.")
        for title, copy, icon_name in (
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
                 "build")):
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
            "Copy a short summary for a bug report: app version, platform, theme, "
            "cache paths and the last error code. No report contents are included.")
        diagnostics.setObjectName("rowBody")
        diagnostics.setWordWrap(True)
        self.copy_diagnostics_button = QPushButton("Copy environment info")
        self.copy_diagnostics_button.setObjectName("outline")
        self.copy_diagnostics_button.clicked.connect(self._copy_diagnostics)
        self.diagnostics_note = QLabel("Nothing has been copied.")
        self.diagnostics_note.setObjectName("dialogMuted")
        self.diagnostics_note.setWordWrap(True)
        diagnostics_row = QHBoxLayout()
        diagnostics_row.setSpacing(10)
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
        icons.clear_caches()
        self._backdrop.set_palette(self._palette)
        self._sync_nav_icons()
        self.theme_button.setIcon(icons.icon(
            "sun" if not self._dark else "moon", self._palette["text"], 18))
        self.theme_button.setToolTip(
            "Switch to the light theme" if self._dark else "Switch to the dark theme")
        self.search.apply_palette(self._palette)
        self.report_field.apply_palette(self._palette)
        self.acpi_field.apply_palette(self._palette)
        self.output_field.apply_palette(self._palette)
        self.version_combo.apply_palette(self._palette)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(1 if self._dark else 0)
        self.theme_combo.blockSignals(False)
        self.theme_combo.apply_palette(self._palette)
        self.level_filter.apply_palette(self._palette)
        for metric in (self.metric_elapsed, self.metric_downloaded,
                       self.metric_speed, self.metric_step):
            metric.apply_palette(self._palette)
        for tile in self.findChildren(_InfoTile):
            tile.apply_palette(self._palette)
        self.collect_button.setIcon(
            icons.icon("wave", self._palette["accent"], 14))
        self.acpi_button.setIcon(
            icons.icon("layers", self._palette["accent"], 14))
        self.analyze_button.setIcon(
            icons.icon("pulse", self._palette["text"], 15))
        self.build_button.setIcon(icons.icon("build", "#ffffff", 15))
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
        self._status_delegate.palette = self._palette
        self.verdict_tree.viewport().update()
        if self._last_stages:
            self._render_stages(self._last_stages)
        if self.analysis is not None:
            self._render_verdicts(self._current_verdict.name
                                  if self._current_verdict else None)
        self._rerender_log()

    def _toggle_theme(self) -> None:
        self._set_dark(not self._dark)

    def _on_theme_choice(self, index: int) -> None:
        self._set_dark(index == 1)

    def _set_dark(self, dark: bool) -> None:
        if dark == self._dark:
            return
        self._dark = dark
        self._settings.setValue("appearance/dark", dark)
        self._apply_theme()

    def _sync_nav_icons(self) -> None:
        color = self._palette["muted"]
        for button in self.nav_buttons + self.secondary_buttons:
            icon_color = "#ffffff" if button.text() == self._view else color
            size = 18 if button in self.nav_buttons else 17
            button.setIcon(icons.icon(
                _NAV_ICON.get(button.text(), "dot"), icon_color, size))

    def _show_view(self, name: str) -> None:
        """Switch pages by moving the shared cards, never by copying them.

        The progress card, the action card and the log follow the user between
        views; a second log widget would drift from the ring buffer the moment a
        line was dropped, and two progress bars would disagree within one tick.
        """
        if name not in _VIEWS:
            return
        self._view = name
        self.page_stack.setCurrentIndex(_VIEWS.index(name))
        if name == "Compatibility":
            self._mount(self.actions_card, self._compat_top, 4)
            self._mount(self.progress_card, self._compat_bottom, 3)
            self._mount(self.log_card, self._compat_bottom, 2)
        elif name == "Build EFI":
            self._mount(self.actions_card, self._build_top, 1)
            self._mount(self.progress_card, self._build_top, 2)
            self._mount(self.log_card, self._build_bottom, 1)
        elif name == "Logs":
            self._mount(self.log_card, self._logs_slot, 1)
        self.search.setVisible(name in _PRIMARY_VIEWS)
        title, subtitle = _PAGE_COPY[name]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        for button in self.nav_buttons + self.secondary_buttons:
            button.setChecked(button.text() == name)
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

    # ---- window chrome ----

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _position_grip(self) -> None:
        if hasattr(self, "_grip"):
            self._grip.move(self.width() - 20, self.height() - 20)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_grip()

    def closeEvent(self, event) -> None:
        self._ticker.stop()
        self.runner.cancel()
        super().closeEvent(event)

    def _install_shortcuts(self) -> None:
        self._shortcuts: list[QShortcut] = []

        def add(sequence: str, slot) -> None:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(slot)
            self._shortcuts.append(shortcut)

        add("Ctrl+K", self._focus_search)
        add("Ctrl+O", self._pick_report)
        add("Ctrl+1", lambda: self._show_view("Compatibility"))
        add("Ctrl+2", lambda: self._show_view("Build EFI"))
        add("Ctrl+3", lambda: self._show_view("Logs"))
        add("Ctrl+,", lambda: self._show_view("Settings"))
        add("F1", lambda: self._show_view("Help"))
        add("Ctrl+Q", self.close)

    @staticmethod
    def _shortcut_rows() -> tuple[tuple[str, str], ...]:
        mod = "\u2318" if sys.platform == "darwin" else "Ctrl"
        return (
            ("Search devices", "{} K".format(mod)),
            ("Open a report", "{} O".format(mod)),
            ("Compatibility", "{} 1".format(mod)),
            ("Build EFI", "{} 2".format(mod)),
            ("Logs", "{} 3".format(mod)),
            ("Settings", "{} ,".format(mod)),
            ("Help", "F1"),
            ("Quit", "{} Q".format(mod)),
        )

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
            if option.is_suggested:
                suggested = index
        self.version_combo.setCurrentIndex(suggested)
        self.version_combo.blockSignals(False)
        self._update_summary_note()

    def _on_build(self) -> None:
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
        self.statusBar().showMessage("EFI folder written to {}".format(result))
        self._log_line("info", "Done: {}".format(result))
        self.reveal_button.setEnabled(True)
        self._finish_progress(result)

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
        self.cancel_button.setEnabled(busy)
        self.cancel_button.setVisible(busy)
        self.analyze_button.setEnabled(not busy)
        self.collect_button.setEnabled(not busy)
        self.build_button.setEnabled(not busy and self.analysis is not None)
        self.report_field.setEnabled(not busy)
        self.acpi_field.setEnabled(not busy)
        self.acpi_button.setEnabled(not busy)
        self.output_field.setEnabled(not busy)
        self.version_combo.setEnabled(not busy)
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
        for verdict in self._verdicts:
            item = QTreeWidgetItem([
                verdict.name, verdict.class_label or verdict.section, verdict.text, ""])
            icon_name = _CLASS_ICON.get(verdict.class_label, "layers")
            item.setIcon(0, QIcon(icons.tile(
                icon_name, self._palette["tileIcon"], self._palette["tileBg"], 26)))
            item.setSizeHint(0, QSize(0, 34))
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
        self.summary.setProperty("state", state)
        _repolish(self.summary)

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
        self.metric_step.set("0/0")
        self.task_name.setText("Waiting to start")
        self.task_detail.setText("Nothing is downloading.")
        self._task_stage = ""
        self.task_progress.setValue(0)
        self.transfer_label.setText("No transfer in progress.")
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
        self.stage_list.clear()
        self._stage_widgets = {}
        for name in names:
            # The item's own text is painted under the row widget and would show
            # through it; the name lives in the data role instead.
            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            item.setToolTip(name)
            item.setSizeHint(QSize(0, 24))
            row = _StageRow(name, "pending", "\u2014", self._palette)
            self.stage_list.addItem(item)
            self.stage_list.setItemWidget(item, row)
            self._stage_widgets[name] = row
        self.progress.setRange(0, len(names))
        self.metric_step.set("0/{}".format(len(names)))
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
        self.metric_step.set("{}/{}".format(done, len(stages)))
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

        self.stage_list.clear()
        self._stage_widgets = {}
        for name, _total, state in stages:
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
        self.metric_step.set("{}/{}".format(total, total))
        self.task_progress.setValue(100)
        self.task_name.setText("EFI folder ready")
        self.task_detail.setText(str(result))
        self.transfer_label.setText("Build complete.")
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
        if transfer.total_bytes:
            self.task_detail.setText("{} of {}".format(
                _format_size(transfer.done_bytes), _format_size(transfer.total_bytes)))
        else:
            self.task_detail.setText("{} downloaded".format(
                _format_size(transfer.done_bytes)))
        self.task_progress.setValue(
            round(fraction * 100) if fraction is not None else 0)
        self.transfer_label.setText("{} \u00b7 {} \u00b7 {}".format(
            transfer.product, _format_size(transfer.done_bytes),
            _format_rate(transfer.bytes_per_second)))

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
            self._render_transfer(transfer)
        for level, title, body in events.notifications:
            self._ingest(level, "{}: {}".format(title, body) if body else title)
        self._tick_clock()

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

    def _copy_diagnostics(self) -> None:
        text = "\n".join((
            "BlackDream {}".format(__version__),
            "Platform: {}".format(platform.platform()),
            "Theme: {}".format("Dark" if self._dark else "Light"),
            "Artifact cache: {}".format(paths.current().cache_dir),
            "Runtime tools: {}".format(paths.current().tools_dir),
            "Last error: {}".format(self._last_error_code or "none"),
        ))
        QApplication.clipboard().setText(text)
        self.diagnostics_note.setText("Copied to the clipboard.")

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


class _Backdrop(QWidget):
    """The pastel wallpaper behind the glass shell, painted, not shipped.

    A gradient image would need packaging and a second copy per theme; five radial
    gradients cost one paint at resize and follow the palette dict exactly.
    """

    def __init__(self, palette: dict) -> None:
        super().__init__()
        self._palette = palette

    def set_palette(self, palette: dict) -> None:
        self._palette = palette
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = max(1, self.width()), max(1, self.height())
        sky = QLinearGradient(0, 0, 0, height)
        sky.setColorAt(0.0, qcolor(self._palette["bgTop"]))
        sky.setColorAt(0.55, qcolor(self._palette["bgMid"]))
        sky.setColorAt(1.0, qcolor(self._palette["bgBottom"]))
        painter.fillRect(self.rect(), sky)
        painter.setPen(Qt.NoPen)
        for fx, fy, radius, color, alpha in self._palette["blobs"]:
            centre = QColor(color)
            centre.setAlpha(alpha)
            faded = QColor(color)
            faded.setAlpha(0)
            glow = QRadialGradient(QPointF(width * fx, height * fy),
                                   max(1.0, min(width, height) * radius))
            glow.setColorAt(0.0, centre)
            glow.setColorAt(0.55, centre)
            glow.setColorAt(1.0, faded)
            painter.setBrush(glow)
            painter.drawRect(self.rect())


class _DragFrame(QFrame):
    """A frameless window still has to move."""

    def __init__(self) -> None:
        super().__init__()
        self._drag_offset = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.window().frameGeometry().topLeft())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            toggle = getattr(self.window(), "_toggle_maximized", None)
            if toggle is not None:
                toggle()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _SearchPill(QFrame):
    def __init__(self, palette: dict) -> None:
        super().__init__()
        self.setObjectName("searchPill")
        self.setFixedSize(262, 38)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Search devices\u2026")
        self.search_input.setClearButtonEnabled(True)
        shortcut = QLabel("\u2318 K" if sys.platform == "darwin" else "Ctrl K")
        shortcut.setObjectName("kbd")
        layout.addWidget(self.icon, 0, Qt.AlignVCenter)
        layout.addWidget(self.search_input, 1)
        layout.addWidget(shortcut, 0, Qt.AlignVCenter)
        self.apply_palette(palette)

    def apply_palette(self, palette: dict) -> None:
        self._palette = palette
        self.icon.setPixmap(icons.pixmap("search", palette["muted"], 16))


class _Combo(QComboBox):
    """A combo that draws its own chevron: QSS cannot set an SVG arrow image."""

    def __init__(self, palette: dict) -> None:
        super().__init__()
        self._palette = palette
        self.setMinimumHeight(32)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

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
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(6)
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

    def set_header_widget(self, widget: QWidget) -> None:
        self._header.addWidget(widget, 0, Qt.AlignVCenter)

    def add(self, widget, stretch: int = 0) -> None:
        if isinstance(widget, (QHBoxLayout, QVBoxLayout, QGridLayout)):
            self._layout.addLayout(widget, stretch)
            return
        self._layout.addWidget(widget, stretch)


class _ElidedPath(QLabel):
    """A path that shows both ends instead of clipping mid-character.

    A read-only line edit always shows the start and simply cuts the rest, which
    turned "/home/.../Report.json" into "/home/aalmamun/.local/share/blac".
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
        self.setFixedHeight(46)
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


class _Metric(QFrame):
    def __init__(self, icon_name: str, label: str, value: str = "\u2014") -> None:
        super().__init__()
        self.setObjectName("metric")
        self.setMinimumHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 4, 9, 4)
        layout.setSpacing(7)
        self._icon_name = icon_name
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
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
            self._icon_name, palette["tileIcon"], 16))

    def set(self, text: str) -> None:
        self.value.setText(text)


class _StageRow(QWidget):
    def __init__(self, name: str, state: str, elapsed: str, palette: dict) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 4, 0)
        layout.setSpacing(8)
        tones = {"done": palette["ok"], "running": palette["accentSoft"],
                 "pending": palette["faint"], "failed": palette["fail"],
                 "cancelled": palette["muted"]}
        icon = QLabel()
        icon.setFixedSize(16, 16)
        icon.setPixmap(icons.pixmap(
            _STAGE_ICON.get(state, "dot"),
            tones.get(state, palette["faint"]), 16))
        name_label = QLabel(name)
        name_label.setObjectName("stageName")
        name_label.setProperty("state", state)
        self.time = QLabel(elapsed)
        self.time.setObjectName("stageTime")
        self.time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(icon, 0, Qt.AlignVCenter)
        layout.addWidget(name_label, 1)
        layout.addWidget(self.time, 0)
        self.setFixedHeight(26)

    def set_time(self, text: str) -> None:
        self.time.setText(text)


class _StatusDelegate(QStyledItemDelegate):
    """Paints the Status column as a pill; the item's data stays plain text."""

    def __init__(self, palette: dict) -> None:
        super().__init__()
        self.palette = palette

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(34)
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
        background = qcolor(self.palette[tone + "Bg"])
        border = qcolor(self.palette[tone + "Border"])
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        metrics = view_option.fontMetrics
        icon_size = 12
        width = icon_size + 5 + metrics.horizontalAdvance(text) + 18
        pill = QRectF(view_option.rect.left() + 8,
                      view_option.rect.center().y() - 10.5, width, 21)
        painter.setPen(QPen(border, 1))
        painter.setBrush(background)
        painter.drawRoundedRect(pill, 10.5, 10.5)
        painter.drawPixmap(int(pill.left() + 7),
                           int(pill.center().y() - icon_size / 2),
                           icons.pixmap(_STATUS_ICON.get(tone, "dot"),
                                        self.palette[tone], icon_size))
        painter.setPen(foreground)
        painter.drawText(QRectF(pill.left() + icon_size + 12, pill.top(),
                                pill.width() - icon_size - 20, pill.height()),
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
