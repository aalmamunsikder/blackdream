"""Dropdown behaviour: the popup drops below the field, and never lies about state.

Fusion reads a non-editable combo as a macOS menu and positions its popup so the
selected row covers the field. On Windows and Linux that hides the current value
exactly when the user opens the list, so the window installs a proxy style that
restores an ordinary drop-down. These tests also pin the filter's initial choice
and the empty version state -- both used to render a blank field with no selection.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QStyle, QStyleOptionComboBox, QVBoxLayout, QWidget)

from ocengine import runtime  # noqa: E402

from blackdream.ui import main_window as ui  # noqa: E402
from blackdream.ui.main_window import MainWindow, _Combo, install_dropdown_style  # noqa: E402
from blackdream.ui.theme import LIGHT  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _MemorySettings:
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
        monkeypatch.setattr(ui, "QSettings",
                            lambda *_args, **_kwargs: _MemorySettings(seed or {}))
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


def test_non_editable_combos_drop_below_the_field(qapp, make_window):
    """The popup must start at or below the field's bottom edge."""
    window = make_window()
    window.resize(1240, 760)
    # Switch before show: offscreen defers the hidden page's layout until the
    # window is shown, and a popup opened before that pass anchors to the old
    # geometry. A real click can only arrive after layout has settled.
    window._show_view("Compatibility")
    qapp.processEvents()
    window.show()
    qapp.processEvents()

    combo = window.version_combo
    combo.clear()
    combo.addItems(["One", "Two", "Three"])
    combo.showPopup()
    qapp.processEvents()

    popup = combo.view().window()
    combo_bottom = combo.mapToGlobal(combo.rect().bottomLeft()).y()
    assert popup.geometry().top() >= combo_bottom - 1, (
        "the popup covers the field again; SH_ComboBox_Popup is back")
    combo.hidePopup()


def test_the_popup_style_is_overridden_on_this_platform(qapp):
    install_dropdown_style()
    if sys.platform == "darwin":
        pytest.skip("macOS keeps the native menu-style popup")
    option = QStyleOptionComboBox()
    assert qapp.style().styleHint(QStyle.SH_ComboBox_Popup, option) == 0
    assert isinstance(qapp.style(), ui._ComboPopupStyle)


def test_the_log_filter_starts_with_a_selection(qapp, make_window):
    """A placeholder text on a combo clears currentIndex; the filter must not inherit that."""
    window = make_window()
    assert window.level_filter.currentIndex() == 0
    assert window.level_filter.currentText() == "Info and above"
    assert window.theme_combo.currentIndex() >= 0


def test_the_version_field_is_disabled_and_explains_itself_until_a_report_loads(
        qapp, make_window):
    window = make_window()
    assert window.version_combo.count() == 0
    assert not window.version_combo.isEnabled()
    assert "report" in window.version_combo.placeholderText().lower()


def test_a_combo_without_items_does_not_report_a_selection(qapp):
    """setPlaceholderText is what clears currentIndex; keep the behaviour explicit."""
    combo = QComboBox()
    combo.setPlaceholderText("none")
    combo.addItems(["One", "Two"])
    assert combo.currentIndex() == -1

    local = _Combo(LIGHT)
    local.addItems(["One", "Two"])
    assert local.currentIndex() == 0
    assert local.placeholderText() == ""
