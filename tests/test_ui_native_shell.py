"""The native window: platform chrome, an inside canvas, cheap redraws.

2.6 keeps the platform frame and visible menu bar, but paints the mockup's
blue-silk wallpaper inside the client area: the frost rail and the content veil
sit over it, and the glass cards sit over those. Nothing is painted behind the
window, inset from it, or around its edges. These tests pin the parts a
screenshot cannot: the native frame, the cached wallpaper, the visible menu
driving the same six views, the device search only where the table exists, the
dashboard reflow, stage-row reuse, and the idle ticker.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("PySide6")

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QBoxLayout, QWidget)

from ocengine import runtime  # noqa: E402

from blackdream.core.pipeline import _STEPS  # noqa: E402
from blackdream.ui import main_window as ui  # noqa: E402
from blackdream.ui.main_window import (  # noqa: E402
    MainWindow, _BUILD_VIEWS, _SECTIONS, _SECONDARY_VIEWS, _VIEWS)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _MemorySettings:
    """QSettings writes to the real user profile; tests must not change it."""

    def __init__(self, store):
        self._store = store

    def value(self, key, default=None):
        return self._store.get(key, default)

    def setValue(self, key, value):
        self._store[key] = value


@pytest.fixture
def make_window(qapp, monkeypatch):
    previous_sink = runtime.current_sink()
    created = []

    def build(seed=None):
        store = {} if seed is None else seed
        monkeypatch.setattr(ui, "QSettings",
                            lambda *_args, **_kwargs: _MemorySettings(store))
        window = MainWindow()
        qapp.processEvents()
        created.append(window)
        return window

    yield build

    for window in created:
        window._ticker.stop()
        window.runner.cancel()
        try:
            window._style_hints.colorSchemeChanged.disconnect(
                window._on_color_scheme)
        except (RuntimeError, TypeError):
            pass
        window.close()
        window.deleteLater()
    runtime.set_sink(previous_sink)
    qapp.processEvents()


def test_the_window_uses_the_native_frame(make_window):
    window = make_window()

    assert not (window.windowFlags() & Qt.FramelessWindowHint)
    assert window.windowFlags() & Qt.Window
    assert window.windowTitle() == "BlackDream"
    assert window.minimumSize() == QSize(1160, 700)
    assert window.centralWidget() is window._shell
    assert isinstance(window._shell, ui._Wallpaper)
    assert window._shell.objectName() == "shell"
    assert not hasattr(ui, "_TrafficLight")
    assert not hasattr(ui, "_Root")
    assert window._palette["wallRibbons"]


def test_the_wallpaper_is_painted_inside_and_cached(make_window, qapp):
    """The silk is the window's own backdrop, not a desktop behind it."""
    window = make_window()
    window.resize(1240, 760)
    window.show()
    qapp.processEvents()

    window._shell.repaint()
    first = window._shell._cache
    assert first is not None
    ratio = first.devicePixelRatio()
    assert round(first.width() / ratio) == window._shell.width()
    assert round(first.height() / ratio) == window._shell.height()
    assert window._shell.height() < window.height(), "the menu bar is not wallpaper"

    window._shell.repaint()
    assert window._shell._cache is first, "an unchanged repaint re-rendered the silk"

    window.resize(1280, 760)
    qapp.processEvents()
    window._shell.repaint()
    assert window._shell._cache is not first, "a resize reused the old pixmap"
    assert round(window._shell._cache.width() / ratio) == 1280

    changed = window._shell._cache
    window._set_theme_mode("dark")
    qapp.processEvents()
    window._shell.repaint()
    assert window._shell._cache is not changed, "a theme change reused the old pixmap"


def test_the_menu_bar_is_visible_and_drives_the_views(make_window, qapp):
    window = make_window()

    titles = [action.text().replace("&", "") for action in window.menuBar().actions()]
    assert titles == ["File", "View", "Help"]
    assert not window.menuBar().isHidden()

    view_menu = window.menuBar().actions()[1].menu()
    actions = {action.text(): action for action in view_menu.actions()
               if action.text()}
    assert set(actions) >= (set(_SECTIONS) | set(_SECONDARY_VIEWS)
                            | {"Build", "Toggle Theme"})
    build_menu = actions["Build"].menu()
    build_actions = {action.text(): action for action in build_menu.actions()
                     if action.text()}
    assert set(build_actions) == {"Compatibility", "Build", "Logs"}

    build_actions["Logs"].trigger()
    qapp.processEvents()
    assert window._view == "Logs"
    assert window.page_title.text() == "Engine Log"
    # Logs is a sub-view of Build EFI: the section pill stays lit, and so does
    # the segment tab, because "Logs" is not a top-level destination any more.
    assert any(nav.text() == "Build EFI" and nav.isChecked()
               for nav in window.nav_buttons)
    assert any(tab.text() == "Logs" and tab.isChecked()
               for tab in window.build_buttons)

    actions["Installer"].trigger()
    qapp.processEvents()
    assert window._view == "Installer"
    assert window.page_title.text() == "Make a macOS Installer"
    actions["Build EFI"].trigger()
    qapp.processEvents()
    assert window._view == "Logs", "the section forgot its last sub-view"


def test_a_split_stacks_before_it_clips(qapp):
    first, second = QWidget(), QWidget()
    first.setMinimumWidth(300)
    second.setMinimumWidth(300)
    # A split cannot be resized below its layout minimum (610 here), so the
    # width-vs-minimum fallback is unreachable in practice; the caller's
    # stack_below threshold is the trigger the dashboard relies on.
    split = ui._Split(first, second, spacing=10, stack_below=700)
    split.show()
    split.resize(720, 200)
    qapp.processEvents()
    assert not split._stacked
    assert split._row.direction() == QBoxLayout.Direction.LeftToRight

    split.resize(640, 200)
    qapp.processEvents()
    assert split._stacked
    assert split._row.direction() == QBoxLayout.Direction.TopToBottom


def test_the_status_column_grows_to_fit_its_widest_label(make_window):
    window = make_window()
    tree = window.verdict_tree

    tree.fit_status(40)
    assert tree.columnWidth(3) == tree._STATUS_MIN
    tree.fit_status(140)
    assert tree.columnWidth(3) >= 140


def test_the_device_search_exists_only_where_the_table_does(make_window, qapp):
    """A pill on Build or Logs reordered a table the user could not see."""
    window = make_window()

    for name in _VIEWS:
        window._show_view(name)
        qapp.processEvents()
        assert window.search.isHidden() == (name != "Compatibility"), name


def test_a_stage_event_updates_the_existing_rows(make_window):
    window = make_window()
    window._prime_stages()
    rows = dict(window._stage_widgets)
    first = rows[_STEPS[0]]

    assert list(rows) == list(_STEPS)
    states = ["done", "running"] + ["pending"] * (len(_STEPS) - 2)
    window._render_stages([(name, None, state)
                           for name, state in zip(_STEPS, states)])

    assert window._stage_widgets == rows, "the checklist was rebuilt"
    assert window._stage_widgets[_STEPS[0]] is first
    assert first._state == "done"
    running = rows[_STEPS[1]]
    assert running._state == "running"
    assert running._spinner_timer.isActive(), "a running stage has no spinner"
    assert window.stage_list.count() == len(_STEPS)

    window._render_stages([(name, None, "done") for name in _STEPS])
    assert window._stage_widgets == rows
    assert all(row._state == "done" for row in rows.values())
    assert not running._spinner_timer.isActive()


def test_the_ticker_sleeps_while_idle_and_wakes_for_work(make_window):
    window = make_window()

    # The window opens on the Installer page, which starts its first USB scan while
    # it is built. Whether that scan has finished by the first event-loop pass
    # depends on how long enumerating drives takes on the host, so "idle" is stated
    # here instead of assumed.
    window._set_ticker_interval(False)
    assert window._ticker.interval() == 400
    window._set_ticker_interval(True)
    assert window._ticker.interval() == 60
    window._set_ticker_interval(False)
    assert window._ticker.interval() == 400


def test_system_mode_follows_the_desktop(make_window, monkeypatch):
    observed = {"dark": False}
    monkeypatch.setattr(ui.MainWindow, "_system_dark",
                        staticmethod(lambda: observed["dark"]))
    window = make_window({"appearance/mode": "system"})

    assert window._theme_mode == "system"
    assert window._dark is False
    assert window.theme_combo.currentText() == "System"

    observed["dark"] = True
    window._on_color_scheme(None)
    assert window._dark is True
    assert window.theme_combo.currentText() == "System"

    window._toggle_theme()
    assert window._theme_mode == "light"
    observed["dark"] = True
    window._on_color_scheme(None)
    assert window._dark is False, "an explicit theme must ignore the desktop"


def test_the_old_boolean_appearance_key_still_migrates(make_window):
    window = make_window({"appearance/dark": "true"})

    assert window._theme_mode == "dark"
    assert window._dark is True
    assert window.theme_combo.currentText() == "Dark"


def test_the_theme_button_remembers_an_explicit_choice(make_window, monkeypatch):
    monkeypatch.setattr(ui.MainWindow, "_system_dark", staticmethod(lambda: False))
    store = {"appearance/mode": "system"}
    window = make_window(store)

    window._toggle_theme()

    assert window._theme_mode == "dark"
    assert window._dark is True
    assert store["appearance/mode"] == "dark"
    assert window.theme_combo.currentText() == "Dark"
