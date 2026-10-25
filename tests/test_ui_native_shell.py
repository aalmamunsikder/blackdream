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
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QBoxLayout, QLabel, QPushButton, QWidget)

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


def test_no_button_is_narrower_than_its_own_label(make_window, qapp):
    """The Configure toolbar held eight buttons in one row, and at the window's own
    minimum width the row squeezed them until `Changes…` drew as `hanges`. Every frame
    in ``docs/screenshots`` is 1536 px wide, so not one of them could show it — the
    measurement has to happen at ``minimumSize()``, the smallest window a user can
    drag this one to."""
    window = make_window()
    window.resize(window.minimumSize())
    window.show()
    for _ in range(4):
        qapp.processEvents()

    clipped = []
    for name in _VIEWS:
        window._show_view(name)
        for _ in range(4):
            qapp.processEvents()
        for button in window.findChildren(QPushButton):
            if not button.isVisible() or not button.text().strip():
                continue
            if button.width() < button.sizeHint().width():
                clipped.append("{}: {} {!r} squeezed into {} px".format(
                    name, button.objectName() or "button", button.text(),
                    button.width()))
    assert clipped == []

    # The rail is 200 px at the reference font, but on a runner whose font is
    # wider it grows by the few pixels the tagline needs (the next test), so the
    # assertion is against the rail that was actually laid out.
    hint = window.findChild(QLabel, "brandHint")
    assert hint.sizeHint().width() <= hint.width(), \
        "{!r} needs {} px in {} px".format(hint.text(), hint.sizeHint().width(),
                                           hint.width())


def test_a_wider_platform_font_wraps_instead_of_losing_letters(make_window, qapp):
    """The fonts on CI are not this machine's font.

    The first run of the button sweep above went green here and red on both CI
    legs: on ubuntu-22.04 the tagline needed 124 px in 121, and on Windows
    ``Configure EFI`` was squeezed into 173 px while the Configure actions lost
    width in the header and the Keys toolbar. A platform font is a few per cent
    wider than the one the geometry was measured with, so the fix cannot be a
    set of wider constants -- the rail grows past its 200 px reference and the
    action rows take a second line. This test manufactures that difference with
    letter spacing, which reaches even the sizes the stylesheet pins, and checks
    the two promises: every label keeps its whole width, and every wrapped line
    is inside the row's own height.
    """
    base = QFont(qapp.font())
    wide = QFont(base)
    wide.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
    qapp.setFont(wide)
    try:
        window = make_window()
        window.resize(window.minimumSize())
        window.show()
        for _ in range(6):
            qapp.processEvents()

        assert window._rail.width() >= 200
        hint = window.findChild(QLabel, "brandHint")
        assert hint.sizeHint().width() <= hint.width(), \
            "{!r} needs {} px in {} px".format(hint.text(),
                                               hint.sizeHint().width(),
                                               hint.width())

        wrapped = 0
        # Findings are collected rather than asserted on sight, so one run
        # names every squeezed label on a platform instead of the first one:
        # the first version of this sweep died at `Generate serials` and never
        # reached the three views after it.
        offenders = []
        for name in _VIEWS:
            window._show_view(name)
            for _ in range(4):
                qapp.processEvents()
            for button in window.findChildren(QPushButton):
                if not button.isVisible() or not button.text().strip():
                    continue
                if button.width() < button.sizeHint().width():
                    offenders.append("{}: {!r} squeezed into {} px".format(
                        name, button.text(), button.width()))
            for row in window.findChildren(ui._WrapRow):
                if not row.isVisible():
                    continue
                if row.height() != row.heightForWidth(row.width()):
                    offenders.append("{}: row is {} px tall but its lines "
                                     "need {}".format(name, row.height(),
                                                      row.heightForWidth(
                                                          row.width())))
                shown = [child for child in row._children if child.isVisible()]
                if len(row._lines(row.width())) > 1:
                    wrapped += 1
                for index, child in enumerate(shown):
                    geometry = child.geometry()
                    label = (child.text() if hasattr(child, "text")
                             else child.objectName())
                    # A search field scrolls its text and the Keys card between
                    # its fixed-width neighbours is narrower than the field's
                    # maximum, so the field is entitled to min(hint, max, row).
                    # A button or label is entitled to its whole hint.
                    entitled = child.sizeHint().width()
                    if row._flexible(child):
                        entitled = min(entitled, child.maximumWidth(),
                                       row.width())
                    if geometry.width() < entitled:
                        offenders.append("{}: {!r} is {} px in a {} px "
                                         "geometry".format(
                                             name, label, entitled,
                                             geometry.width()))
                    if geometry.right() > row.width():
                        offenders.append("{}: {!r} runs past the row".format(
                            name, label))
                    if geometry.bottom() > row.height():
                        offenders.append("{}: {!r} is drawn below the row"
                                         .format(name, label))
                    for other in shown[index + 1:]:
                        if geometry.intersects(other.geometry()):
                            offenders.append("{}: {!r} overlaps {!r}".format(
                                name, label,
                                other.text() if hasattr(other, "text")
                                else other.objectName()))
        assert offenders == [], "a wider font squeezed {} of them: {}".format(
            len(offenders), "; ".join(offenders))
        assert wrapped > 0, "no row wrapped, so the font was not wider"
    finally:
        qapp.setFont(base)


def test_the_keyboard_reaches_what_the_spec_promises(make_window, qapp):
    """Spec 14 names three keyboard targets: the theme picker, the diagnostics
    buttons and all six sidebar items.

    The rail is one auto-exclusive button group, and Qt gives Tab to only the
    group's first button and moves inside it with the arrow keys. So "reachable"
    has to be walked the way a person drives it -- Tab to the rail, Down through
    all six, Tab into the page -- or the test measures a chain nobody uses.
    """
    window = make_window()
    window.resize(1280, 820)
    window.show()
    for _ in range(6):
        qapp.processEvents()

    def tab_chain(view):
        window._show_view(view)
        for _ in range(6):
            qapp.processEvents()
        if window.focusWidget() is not None:
            window.focusWidget().clearFocus()
        seen = []
        while len(seen) < 60:
            QTest.keyClick(window, Qt.Key_Tab)
            for _ in range(3):
                qapp.processEvents()
            widget = qapp.focusWidget()
            if widget is None or widget is window or widget in seen:
                break
            seen.append(widget)
        return seen

    assert window.theme_combo in tab_chain("Settings")
    help_stops = tab_chain("Help")
    for button in (window.first_boot_copy, window.diagnostics_bundle_button,
                   window.copy_diagnostics_button):
        assert button in help_stops, button.text()

    window._show_view("Installer")
    for _ in range(6):
        qapp.processEvents()
    if window.focusWidget() is not None:
        window.focusWidget().clearFocus()
    QTest.keyClick(window, Qt.Key_Tab)
    for _ in range(3):
        qapp.processEvents()
    rail = window.nav_buttons + window.secondary_buttons
    first = qapp.focusWidget()
    assert first in rail, "Tab landed on {!r}, not the rail".format(first)
    visited = [first]
    for _ in range(len(rail) - 1):
        # The key goes to the focused button, not the window: an exclusive button
        # group handles the arrows in the button's own key handler, and a Down
        # delivered to the window is a different event from one delivered to it.
        QTest.keyClick(visited[-1], Qt.Key_Down)
        for _ in range(3):
            qapp.processEvents()
        visited.append(qapp.focusWidget())
    assert [button.text() for button in visited] == [button.text()
                                                     for button in rail], \
        "the rail hid {} from the keyboard".format(
            [button.text() for button in rail if button not in visited])
    assert window._view == "Donate", "the arrows moved the focus but not the page"


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
