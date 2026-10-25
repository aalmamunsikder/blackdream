"""The Installer and Configure EFI sections, driven offscreen.

The backend tests prove the protocol and the copy semantics. These tests prove the
two pages say what the spec says and that the destructive action stays disabled
until every precondition is real: a verified image, a complete EFI folder and a
drive the user chose. No network and no host drive is touched.

The Configure page is also the app's own config.plist editor now. Its tests drive
the real tree and the real document, stubbing only the modal dialogs and the two
jobs that would otherwise reach ocvalidate/macserial.
"""

from __future__ import annotations

import os
import plistlib
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QPushButton, QStyle, QStyleOptionButton,
    QStyleOptionViewItem)

from ocengine import runtime  # noqa: E402

from blackdream.core import config_editor  # noqa: E402
from blackdream.core import config_presets  # noqa: E402
from blackdream.core import installer as installer_core  # noqa: E402
from blackdream.core.job_runner import CANCELLED, DONE, FAILED, Outcome  # noqa: E402
from blackdream.ui import main_window as ui  # noqa: E402
from blackdream.ui.main_window import MainWindow  # noqa: E402


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
    monkeypatch.setattr(installer_core, "cached_recovery",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer_core, "list_usb_volumes", lambda: [])

    def build(store=None):
        settings = _MemorySettings(store or {})
        monkeypatch.setattr(ui, "QSettings",
                            lambda *_args, **_kwargs: settings)
        window = MainWindow()
        qapp.processEvents()
        created.append(window)
        return window

    yield build

    for window in created:
        window._ticker.stop()
        for runner in (window.runner, window._installer_runner,
                       window._usb_runner, window._config_runner):
            runner.cancel()
        try:
            window._style_hints.colorSchemeChanged.disconnect(
                window._on_color_scheme)
        except (RuntimeError, TypeError):
            pass
        window.close()
        window.deleteLater()
    runtime.set_sink(previous_sink)
    qapp.processEvents()


def _settle(app, runner, timeout=5.0):
    """Pump the GUI loop until the runner owes nothing to a slot.

    Waiting on ``busy`` alone returned a frame early: the worker clears that flag
    just before it emits, so the assertions afterwards could read a widget the
    outcome had not reached yet. ``delivered`` is set once the emit has happened,
    which also covers a runner that never took a job.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if runner.delivered:
            for _ in range(4):
                app.processEvents()
            return
        time.sleep(0.01)
    raise AssertionError("job did not settle")


_CONFIG_DATA = {
    "ACPI": {"Add": [], "Quirks": {"FadtEnableReset": False}},
    "Booter": {"Quirks": {"AvoidRuntimeDefrag": True,
                          "ResizeAppleGpuBars": -1}},
    "DeviceProperties": {"Add": {"PciRoot(0x0)": {
        "layout-id": b"\x0b\x00\x00\x00"}}},
    "Kernel": {"Add": [{"BundlePath": "Lilu.kext", "Enabled": True}]},
    "PlatformInfo": {"Automatic": True, "Generic": {
        "SystemProductName": "MacPro7,1",
        "ROM": b"\x11\x22\x33\x44\x55\x66"}},
}


def _efi_folder(root, config=None):
    efi = root / "EFI"
    (efi / "BOOT").mkdir(parents=True)
    (efi / "OC").mkdir()
    (efi / "BOOT" / "BOOTx64.efi").write_bytes(b"boot")
    (efi / "OC" / "OpenCore.efi").write_bytes(b"x" * (64 * 1024))
    (efi / "OC" / "config.plist").write_bytes(plistlib.dumps(
        _CONFIG_DATA if config is None else config, sort_keys=False))
    return efi


def _config_item(window, path):
    item = window._find_config_path(path)
    assert item is not None, "no tree item at {}".format(path)
    return item


def _select(window, path):
    window._select_config_path(path)
    window._update_config_actions()
    return _config_item(window, path)


def _near(colour, wanted, slack=32):
    return (abs(colour.red() - wanted.red()) <= slack
            and abs(colour.green() - wanted.green()) <= slack
            and abs(colour.blue() - wanted.blue()) <= slack)


def _indicator_pixels(window, item, app):
    """Count accent-fill and tick-glyph pixels in one boolean cell."""
    app.processEvents()
    viewport = window.config_tree.viewport()
    index = window.config_tree.indexFromItem(item, 1)
    option = QStyleOptionViewItem()
    option.initFrom(viewport)
    option.rect = window.config_tree.visualRect(index)
    option.widget = window.config_tree
    window.config_tree.itemDelegate().initStyleOption(option, index)
    box = viewport.style().subElementRect(
        QStyle.SubElement.SE_ItemViewItemCheckIndicator, option,
        window.config_tree)
    image = viewport.grab().toImage()
    fill_colour = QColor(window._palette["accent"])
    tick_colour = QColor(window._palette["onAccent"])
    fill = tick = 0
    for y in range(box.top(), box.bottom() + 1):
        for x in range(box.left(), box.right() + 1):
            colour = image.pixelColor(x, y)
            if _near(colour, tick_colour):
                tick += 1
            elif _near(colour, fill_colour):
                fill += 1
    return fill, tick


def _checkbox_tick_pixels(window, checkbox, app):
    """Count tick-glyph pixels inside a QCheckBox indicator."""
    app.processEvents()
    option = QStyleOptionButton()
    option.initFrom(checkbox)
    option.rect = checkbox.rect()
    box = checkbox.style().subElementRect(
        QStyle.SubElement.SE_CheckBoxIndicator, option, checkbox)
    image = checkbox.grab().toImage()
    tick_colour = QColor(window._palette["onAccent"])
    return sum(
        1
        for y in range(box.top(), box.bottom() + 1)
        for x in range(box.left(), box.right() + 1)
        if _near(image.pixelColor(x, y), tick_colour))


def _message_box(monkeypatch, accept=True):
    """Capture one QMessageBox and answer it without showing a native window."""
    captured = {"accept": accept}

    class _Box:
        Warning = "warning"
        Question = "question"
        Information = "information"
        AcceptRole = "accept-role"
        Cancel = "cancel-role"

        def __init__(self, parent=None):
            pass

        def setIcon(self, icon):
            captured["icon"] = icon

        def setWindowTitle(self, title):
            captured["title"] = title

        def setText(self, text):
            captured["text"] = text

        def setInformativeText(self, text):
            captured["informative"] = text

        def setDetailedText(self, text):
            captured["details"] = text

        def addButton(self, label, role=None):
            token = {"label": label, "role": role}
            captured.setdefault("buttons", []).append(token)
            captured["accept_button" if role == _Box.AcceptRole
                    else "cancel_button"] = token
            return token

        def setDefaultButton(self, button):
            captured["default"] = button

        def exec(self):
            captured["shown"] = True

        def clickedButton(self):
            return captured["accept_button" if accept else "cancel_button"]

    monkeypatch.setattr(ui, "QMessageBox", _Box)
    return captured


def _volume(root):
    return installer_core.UsbVolume(
        label="INSTALL", mount=root, device="/dev/sdz1", filesystem="FAT32",
        size=16_000_000_000, free=8_000_000_000, identity="sdz1:{}".format(root))


def _recovery(root):
    return installer_core.RecoveryDownload(
        image=root / "BaseSystem.dmg", chunklist=root / "BaseSystem.chunklist",
        sha256="a" * 64, size=916 * 1024 * 1024, product="macOS 26")


def _card_titles(window):
    page = window.page_stack.currentWidget()
    if hasattr(page, "widget") and page.widget() is not None:
        page = page.widget()
    return {label.text() for label in page.findChildren(QLabel)
            if label.objectName() == "cardTitle"}


def test_the_window_opens_on_the_installer(make_window, qapp):
    window = make_window()

    assert window._view == "Installer"
    assert window.page_title.text() == "Make a macOS Installer"
    assert any(button.text() == "Installer" and button.isChecked()
               for button in window.nav_buttons)


def test_the_installer_starts_idle_and_names_its_two_cards(make_window, qapp):
    window = make_window()
    window._show_view("Installer")
    _settle(qapp, window._usb_runner)

    assert _card_titles(window) == {"macOS installer", "USB drive"}
    assert window.installer_status.text() == "Not downloaded yet."
    assert window.installer_detail.text() == (
        "About 1 GB. A dropped connection resumes where it stopped.")
    assert window.install_download_button.text() == "Download installer"
    assert window.install_download_button.isEnabled()
    assert not window.install_cancel_button.isEnabled()
    assert not window.install_write_button.isEnabled()
    assert window.usb_combo.currentIndex() == -1
    assert window.usb_note.text() == (
        "No FAT32 USB drive is mounted. Plug one in, then choose Refresh.")
    assert window.install_version_combo.currentData() == (
        installer_core.DEFAULT_RELEASE)


def test_a_stored_release_is_restored(make_window):
    window = make_window({"installer/release": "14"})

    assert window._installer_release.version == "14"
    assert window.install_version_combo.currentText() == "macOS Sonoma 14"


def test_the_installer_offers_every_release_newest_first(make_window):
    window = make_window()

    combo = window.install_version_combo
    assert combo.count() == len(installer_core.RECOVERY_RELEASES)
    assert [combo.itemData(index).version for index in range(combo.count())] == [
        release.version for release in reversed(installer_core.RECOVERY_RELEASES)]
    assert combo.currentText() == "macOS Tahoe 26 \u00b7 latest"


def test_choosing_another_release_swaps_the_verified_image(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    window._show_view("Installer")
    tahoe = _recovery(tmp_path)
    window._recovery = tahoe
    window._refresh_installer_state()
    assert window.install_download_button.text() == "Download again"

    cached = {"26": tahoe}
    monkeypatch.setattr(installer_core, "cached_recovery",
                        lambda release: cached.get(release.version))
    combo = window.install_version_combo
    sonoma = next(index for index in range(combo.count())
                  if combo.itemData(index).version == "14")
    newest = next(index for index in range(combo.count())
                  if combo.itemData(index).version == "26")

    combo.setCurrentIndex(sonoma)
    qapp.processEvents()
    assert window._installer_release.version == "14"
    assert window._recovery is None
    assert window.installer_status.text() == "Not downloaded yet."
    assert window.install_download_button.text() == "Download installer"
    assert not window.install_write_button.isEnabled()
    assert window._settings.value("installer/release") == "14"

    cached["14"] = sonoma_image = _recovery(tmp_path)
    combo.setCurrentIndex(newest)
    qapp.processEvents()
    assert window._recovery is tahoe
    assert window.installer_detail.text().startswith("macOS Tahoe 26 \u00b7 ")

    combo.setCurrentIndex(sonoma)
    qapp.processEvents()
    assert window._recovery is sonoma_image
    assert window.installer_detail.text().startswith("macOS Sonoma 14 \u00b7 ")


def test_the_download_requests_the_release_in_the_picker(
        make_window, qapp, tmp_path, monkeypatch):
    requested = []
    fake = _recovery(tmp_path)

    def download(release=None, token=None, use_cache=True):
        requested.append(release)
        return fake

    monkeypatch.setattr(installer_core, "download_recovery", download)
    window = make_window()
    combo = window.install_version_combo
    combo.setCurrentIndex(next(
        index for index in range(combo.count())
        if combo.itemData(index).version == "14"))
    qapp.processEvents()

    window._on_download_installer()
    _settle(qapp, window._installer_runner)

    assert [release.version for release in requested] == ["14"]
    assert window._recovery is fake
    assert window.installer_detail.text().startswith("macOS Sonoma 14 \u00b7 ")


def test_the_view_scans_usb_once_and_never_preselects_a_drive(
        make_window, qapp, monkeypatch, tmp_path):
    calls = []

    def scan():
        calls.append(1)
        return [_volume(tmp_path / "one"), _volume(tmp_path / "two")]

    monkeypatch.setattr(installer_core, "list_usb_volumes", scan)

    window = make_window()
    window._show_view("Installer")
    _settle(qapp, window._usb_runner)
    window._show_view("Compatibility")
    window._show_view("Installer")
    qapp.processEvents()

    assert calls == [1], "re-entering the Installer re-enumerated the host"
    assert window.usb_combo.count() == 2
    assert window.usb_combo.currentIndex() == -1
    assert window.usb_combo.placeholderText() == "Choose a USB drive"
    assert window.usb_note.text() == "Choose a drive."
    assert not window.install_write_button.isEnabled()

    window.usb_combo.setCurrentIndex(0)
    qapp.processEvents()
    assert window.usb_note.text() == "/dev/sdz1 · 8.0 GB free of 16.0 GB"
    assert not window.install_write_button.isEnabled(), "no verified image yet"


def test_the_usb_dropdown_drops_below_the_field(
        make_window, qapp, monkeypatch, tmp_path):
    """The new combo is a real dropdown, not the macOS-style menu popup."""
    if sys.platform == "darwin":
        pytest.skip("macOS keeps the native menu-style popup; the overlap is expected there")
    monkeypatch.setattr(
        installer_core, "list_usb_volumes",
        lambda: [_volume(tmp_path / "one"), _volume(tmp_path / "two")])
    window = make_window()
    window._show_view("Installer")
    _settle(qapp, window._usb_runner)
    window.resize(1240, 760)
    window.show()
    qapp.processEvents()

    combo = window.usb_combo
    combo.showPopup()
    qapp.processEvents()
    popup = combo.view().window()
    combo_bottom = combo.mapToGlobal(combo.rect().bottomLeft()).y()
    assert popup.geometry().top() >= combo_bottom - 1, (
        "the popup covers the field again; SH_ComboBox_Popup is back")
    combo.hidePopup()


def test_write_needs_the_image_the_efi_and_a_chosen_drive(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    window._show_view("Installer")
    qapp.processEvents()

    window._on_write_installer()
    assert window.usb_note.text() == (
        "Choose a drive and a complete EFI folder, and download the installer first.")
    assert not window._installer_runner.busy

    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    window._recovery = _recovery(tmp_path)
    window._refresh_installer_state()
    window._after_usb_scan(Outcome(job="Finding USB drives", status=DONE,
                                   value=[_volume(tmp_path / "usb")]))
    assert not window.install_write_button.isEnabled(), "the user chose no drive"

    window.usb_combo.setCurrentIndex(0)
    qapp.processEvents()
    assert window.install_write_button.isEnabled()


def test_the_write_confirmation_names_the_volume_and_defaults_to_cancel(
        make_window, qapp, tmp_path, monkeypatch):
    captured = {}

    class _Box:
        Warning = object()
        AcceptRole = object()
        Cancel = object()

        def __init__(self, parent=None):
            self._accept = "Write installer"
            self._cancel = "cancel-sentinel"

        def setIcon(self, icon):
            captured["icon"] = icon

        def setWindowTitle(self, title):
            captured["title"] = title

        def setText(self, text):
            captured["text"] = text

        def setInformativeText(self, text):
            captured["informative"] = text

        def addButton(self, label, role=None):
            if role is _Box.AcceptRole:
                captured["accept_label"] = label
                return self._accept
            return self._cancel

        def setDefaultButton(self, button):
            captured["default"] = button

        def exec(self):
            captured["shown"] = True

        def clickedButton(self):
            return self._cancel

    monkeypatch.setattr(ui, "QMessageBox", _Box)
    window = make_window()
    # The page starts a host scan on open; let it finish so its outcome cannot
    # land after the fabricated one and clear the selection.
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    window._recovery = _recovery(tmp_path)
    window._refresh_installer_state()
    window._after_usb_scan(Outcome(job="Finding USB drives", status=DONE,
                                   value=[_volume(tmp_path / "usb")]))
    window.usb_combo.setCurrentIndex(0)
    qapp.processEvents()

    window._on_write_installer()

    assert captured["shown"] is True
    assert captured["title"] == "Write installer?"
    assert captured["text"] == "Write the installer to INSTALL?"
    assert captured["informative"] == (
        "EFI and com.apple.recovery.boot will be replaced. Everything else on the "
        "drive is left alone, and the drive is not formatted.")
    assert captured["accept_label"] == "Write installer"
    assert captured["default"] is _Box.Cancel
    assert not window._installer_runner.busy, "Cancel must not start a write"
    assert window._installer_job == ""


def test_cancel_and_failure_statuses_survive_the_state_refresh(
        make_window, qapp):
    window = make_window()
    window._show_view("Installer")
    qapp.processEvents()

    window._on_installer_outcome(Outcome(job="Writing the installer",
                                         status=CANCELLED))
    assert window.installer_status.text() == "Cancelled."

    window._on_installer_outcome(Outcome(
        job="Downloading macOS recovery", status=FAILED,
        error=installer_core.RecoveryServiceUnavailable(detail="offline")))
    assert window.installer_status.text() == "The installer task failed."
    assert not window.error_card.isHidden()
    assert "offline" in window.error_card.text()


def test_the_configure_page_is_disabled_until_a_config_exists(make_window, qapp):
    window = make_window()
    window._show_view("Configure EFI")
    qapp.processEvents()

    assert _card_titles(window) == {
        "config.plist", "Sections", "Keys", "Selected entry", "Validation"}
    assert not window.page_actions.isHidden()
    assert window.config_validation_chip.text() == "Not validated"
    assert window.config_schema_chip.text() == (
        "OpenCore {}".format(config_editor.OPEN_CORE_VERSION))
    assert window.config_sections.count() == 0
    assert window.config_inspector_title.text() == "Nothing selected"
    assert window.config_validation_status.text() == "Not checked yet."
    assert window.config_status.text() == "No built config.plist yet."
    assert window.config_path.full_text() == (
        "Build an EFI folder in Build EFI, then return here.")
    assert window.config_detail.text() == (
        "Build an EFI folder in Build EFI, or open any OpenCore config.plist.")
    assert window.config_search.placeholderText() == "Search keys\u2026"
    for button in (window.config_save, window.config_validate,
                   window.config_serials, window.config_revert):
        assert not button.isEnabled()
    assert window.config_open.isEnabled()
    assert not window.config_reveal.isEnabled()
    assert window.config_tree.topLevelItemCount() == 1
    assert window.config_tree.topLevelItem(0).text(0) == "No config.plist is open."
    assert window.config_selection.text() == "No config.plist is open."


def test_a_built_config_loads_without_a_click(make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    window._show_view("Configure EFI")
    qapp.processEvents()

    config = folder / "EFI" / "OC" / "config.plist"
    assert window.config_status.text() == "config.plist is open"
    assert window.config_path.full_text() == str(config)
    assert window.config_detail.text() == (
        "Every key is editable, and keys this build does not know are kept.")
    assert window._config_doc.data["PlatformInfo"]["Automatic"] is True
    assert [window.config_tree.topLevelItem(index).text(0)
            for index in range(window.config_tree.topLevelItemCount())] \
        == list(_CONFIG_DATA)
    assert window.config_validate.isEnabled()
    assert window.config_serials.isEnabled()
    assert not window.config_save.isEnabled()
    assert window.config_reveal.isEnabled()
    assert window.config_selection.text() == "ACPI  \u00b7  dictionary  \u00b7  2 keys"


def test_the_section_rail_scopes_the_tree_and_the_inspector_edits(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    window._show_view("Configure EFI")
    qapp.processEvents()

    labels = [window.config_sections.item(index).text()
              for index in range(window.config_sections.count())]
    assert labels == ["All keys"] + list(_CONFIG_DATA)

    for index in range(window.config_sections.count()):
        if window.config_sections.item(index).data(Qt.UserRole) == "Booter":
            window.config_sections.setCurrentRow(index)
            break
    qapp.processEvents()

    assert _config_item(window, ("ACPI",)).isHidden()
    assert not _config_item(window, ("Booter",)).isHidden()
    assert window._config_selected_path() == ("Booter",)

    _select(window, ("Booter", "Quirks", "ResizeAppleGpuBars"))
    assert window.config_inspector_title.text() == "ResizeAppleGpuBars"
    assert window.config_inspector_meta.text() == (
        "Booter > Quirks > ResizeAppleGpuBars")
    assert not window.config_value_edit.isHidden()
    assert window.config_value_edit.text() == "-1"

    window.config_value_edit.setText("0")
    window._apply_config_value()
    qapp.processEvents()

    assert window._config_doc.data["Booter"]["Quirks"][
        "ResizeAppleGpuBars"] == 0
    assert window.config_status.text() == "Unsaved changes"
    assert window.config_inspector_hint.text() == (
        "Apply writes the value into the document, not the file.")

    _select(window, ("Booter", "Quirks", "AvoidRuntimeDefrag"))
    assert not window.config_bool_edit.isHidden()
    assert window.config_bool_edit.isChecked()
    window.config_bool_edit.setChecked(False)
    qapp.processEvents()
    assert window._config_doc.data["Booter"]["Quirks"][
        "AvoidRuntimeDefrag"] is False

    _select(window, ("DeviceProperties", "Add", "PciRoot(0x0)", "layout-id"))
    assert not window.config_edit_value.isHidden()
    assert window.config_value_edit.isHidden()
    assert window.config_inspector_hint.text() == (
        "Data is edited as hexadecimal bytes or printable text.")

    window.config_sections.setCurrentRow(0)
    qapp.processEvents()
    assert not _config_item(window, ("ACPI",)).isHidden()
    assert window._config_selected_path() is not None


def test_an_inline_edit_is_only_saved_when_save_is_pressed(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    efi = _efi_folder(folder)
    window._set_efi_folder(str(folder))
    config = efi / "OC" / "config.plist"
    original = config.read_bytes()

    item = _config_item(window, ("Booter", "Quirks", "ResizeAppleGpuBars"))
    item.setText(1, "0")
    qapp.processEvents()

    assert window._config_doc.data["Booter"]["Quirks"][
        "ResizeAppleGpuBars"] == 0
    assert window.config_status.text() == "Unsaved changes"
    assert window.config_detail.text() == (
        "Unsaved changes are only in memory until you press Save.")
    assert window.config_save.isEnabled()
    assert config.read_bytes() == original, "editing wrote to disk"

    window._on_config_save()
    qapp.processEvents()

    assert plistlib.loads(config.read_bytes())["Booter"]["Quirks"][
        "ResizeAppleGpuBars"] == 0
    assert config.with_name("config.plist.bak").read_bytes() == original
    assert window.config_status.text() == "config.plist is open"
    assert window.config_detail.text() == (
        "Saved. The previous file was kept as config.plist.bak.")
    assert not window.config_save.isEnabled()


def test_a_boolean_cell_is_a_checkbox_that_marks_the_file_dirty(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window.show()
    window._show_section("Configure EFI")
    window._set_efi_folder(str(folder))
    window._select_config_path(
        ("Booter", "Quirks", "AvoidRuntimeDefrag"))

    item = _config_item(window, ("Booter", "Quirks", "AvoidRuntimeDefrag"))
    assert item.checkState(1) == Qt.Checked

    fill, tick = _indicator_pixels(window, item, qapp)
    assert fill > 100, "the checked indicator lost its accent fill"
    assert tick >= 8, "the checked indicator is a bare dot, with no tick"
    window._refresh_config_inspector()
    qapp.processEvents()
    assert window.config_bool_edit.isChecked()
    assert _checkbox_tick_pixels(
        window, window.config_bool_edit, qapp) >= 8, (
        "the inspector checkbox is a bare dot, with no tick")

    item.setCheckState(1, Qt.Unchecked)
    qapp.processEvents()

    assert window._config_doc.data["Booter"]["Quirks"][
        "AvoidRuntimeDefrag"] is False
    assert window.config_status.text() == "Unsaved changes"
    assert window.config_save.isEnabled()


def test_an_external_change_is_reported_and_revert_reloads(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    efi = _efi_folder(folder)
    window._set_efi_folder(str(folder))
    config = efi / "OC" / "config.plist"

    changed = plistlib.loads(plistlib.dumps(_CONFIG_DATA, sort_keys=False))
    changed["PlatformInfo"]["Automatic"] = False
    config.write_bytes(plistlib.dumps(changed, sort_keys=False))
    window._render_config_state()

    assert window.config_status.text() == "Changed on disk."
    assert window.config_detail.text() == (
        "The file changed on disk. Revert to load that version, or save to "
        "replace it.")
    assert window.config_revert.isEnabled()

    window._on_config_revert()
    qapp.processEvents()

    assert window._config_doc.data["PlatformInfo"]["Automatic"] is False
    assert window.config_status.text() == "config.plist is open"
    assert window.config_detail.text() == "Reverted to the file on disk."
    assert not window.config_revert.isEnabled()


def test_saving_over_an_external_change_asks_first(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    efi = _efi_folder(folder)
    window._set_efi_folder(str(folder))
    config = efi / "OC" / "config.plist"

    item = _config_item(window, ("Booter", "Quirks", "ResizeAppleGpuBars"))
    item.setText(1, "0")
    external = plistlib.loads(plistlib.dumps(_CONFIG_DATA, sort_keys=False))
    external["PlatformInfo"]["Automatic"] = False
    config.write_bytes(plistlib.dumps(external, sort_keys=False))

    cancelled = _message_box(monkeypatch, accept=False)
    window._on_config_save()

    assert cancelled["title"] == "Overwrite config.plist?"
    assert cancelled["text"] == (
        "The file changed on disk since it was opened. Overwrite it?")
    assert cancelled["informative"] == (
        "The current version on disk will be kept as config.plist.bak.")
    assert cancelled["buttons"][0]["label"] == "Overwrite"
    assert cancelled["default"] is cancelled["cancel_button"]
    assert window.config_detail.text() == "Save cancelled."
    assert plistlib.loads(config.read_bytes())["PlatformInfo"][
        "Automatic"] is False

    accepted = _message_box(monkeypatch, accept=True)
    window._on_config_save()

    assert accepted["shown"] is True
    assert plistlib.loads(config.read_bytes())["Booter"]["Quirks"][
        "ResizeAppleGpuBars"] == 0
    assert plistlib.loads(
        config.with_name("config.plist.bak").read_bytes())["PlatformInfo"][
            "Automatic"] is False


def test_opening_another_file_is_blocked_while_edits_are_unsaved(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))

    item = _config_item(window, ("Booter", "Quirks", "ResizeAppleGpuBars"))
    item.setText(1, "0")
    monkeypatch.setattr(
        ui.QFileDialog, "getOpenFileName",
        lambda *_args, **_kwargs: pytest.fail("the file dialog opened"))

    window._on_config_open()

    assert window.config_detail.text() == (
        "Save or revert the current file before opening another.")


def test_add_key_suggests_the_sample_below_the_selected_dictionary(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    captured = {}

    class _Dialog:
        def __init__(self, parent, suggestions, existing, palette):
            captured["suggestions"] = dict(suggestions)
            captured["existing"] = set(existing)

        def exec(self):
            return ui.QDialog.Accepted

        def result_value(self):
            return ("ResetLogoStatus", True)

    monkeypatch.setattr(ui, "_AddKeyDialog", _Dialog)
    _select(window, ("ACPI", "Quirks"))

    window._on_config_add_key()
    qapp.processEvents()

    assert captured["existing"] == {"FadtEnableReset"}
    assert captured["suggestions"]["ResetLogoStatus"] is True
    assert window._config_doc.data["ACPI"]["Quirks"]["ResetLogoStatus"] is True
    assert window.config_detail.text() == "Added ResetLogoStatus."
    assert window._config_selected_path() == ("ACPI", "Quirks", "ResetLogoStatus")
    assert window.config_status.text() == "Unsaved changes"


def test_add_key_is_disabled_while_an_array_is_selected(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))

    _select(window, ("Kernel", "Add"))
    assert window.config_add_item.isEnabled()
    assert not window.config_add_key.isEnabled()

    _select(window, ("Kernel", "Add", 0))
    assert window.config_add_item.isEnabled(), "an item can join its array"
    assert window.config_add_key.isEnabled(), "the item is a dictionary"

    _select(window, ("Kernel",))
    assert not window.config_add_item.isEnabled()
    assert window.config_add_key.isEnabled()


def test_add_item_and_move_keep_the_array_consistent(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))

    _select(window, ("Kernel", "Add"))
    window._on_config_add_item()
    qapp.processEvents()

    assert len(window._config_doc.data["Kernel"]["Add"]) == 2
    assert window._config_selected_path() == ("Kernel", "Add", 1)
    assert window.config_detail.text() == "Added item 1."
    assert window.config_up.isEnabled()
    assert not window.config_down.isEnabled()

    window._move_config_item(-1)
    qapp.processEvents()

    assert window._config_selected_path() == ("Kernel", "Add", 0)
    assert window.config_detail.text() == "Moved Kernel > Add > [0]."
    assert not window.config_up.isEnabled()
    assert window.config_down.isEnabled()
    assert window._config_doc.data["Kernel"]["Add"][1]["BundlePath"] == "Lilu.kext"


def test_remove_asks_first_and_names_the_key(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    captured = _message_box(monkeypatch, accept=True)
    _select(window, ("Booter", "Quirks", "ResizeAppleGpuBars"))

    window._on_config_remove()
    qapp.processEvents()

    assert captured["title"] == "Remove from config.plist?"
    assert captured["text"] == (
        "Remove Booter > Quirks > ResizeAppleGpuBars?")
    assert captured["informative"] == (
        "The file is not changed until you press Save.")
    assert captured["buttons"][0]["label"] == "Remove"
    assert captured["default"] is captured["cancel_button"]
    assert "ResizeAppleGpuBars" not in window._config_doc.data["Booter"]["Quirks"]
    assert window.config_detail.text() == (
        "Removed Booter > Quirks > ResizeAppleGpuBars.")
    assert window.config_status.text() == "Unsaved changes"


def test_search_keeps_ancestors_and_hides_the_rest(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    window._show_view("Configure EFI")

    window.config_search.setText("lilu")
    qapp.processEvents()

    assert not _config_item(window, ("Kernel",)).isHidden()
    assert _config_item(window, ("ACPI",)).isHidden()
    assert not _config_item(window, ("Kernel", "Add")).isHidden()

    window.config_search.setText("")
    qapp.processEvents()

    assert not _config_item(window, ("ACPI",)).isHidden()


def test_an_invalid_plist_is_reported_without_a_dialog(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    efi = _efi_folder(folder)
    config = efi / "OC" / "config.plist"
    config.write_bytes(b"<plist/>")

    window._set_efi_folder(str(folder))
    window._show_view("Configure EFI")
    qapp.processEvents()

    assert window.config_status.text() == "The config.plist could not be read."
    assert window.config_path.full_text() == str(config)
    assert window.config_detail.text().startswith("The file could not be read:")
    assert window.error_card.isHidden()
    assert not window.config_validate.isEnabled()
    assert not window.config_save.isEnabled()
    assert window.config_open.isEnabled()
    assert window.config_tree.topLevelItem(0).text(0) == "No config.plist is open."


def test_validate_runs_off_the_ui_thread_and_explains_the_result(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    called = []

    def validate(data):
        called.append(dict(data))
        return config_editor.ValidationResult(
            ok=True, version="", issues=(), output="No issues found.")

    monkeypatch.setattr(config_editor, "validate_document", validate)

    window._on_config_validate()

    assert window.config_detail.text() == (
        "Checking config.plist with ocvalidate\u2026")
    assert window.config_validation_chip.text() == "Checking\u2026"
    assert not window.config_save.isEnabled()

    _settle(qapp, window._config_runner)

    assert len(called) == 1
    assert called[0]["PlatformInfo"]["Automatic"] is True
    assert window.config_validation_status.text() == "No issues found."
    assert window.config_validation_note.text() == (
        "Checked in memory; the copy on disk is unchanged.")
    assert window.config_validation_chip.text() == "Valid"
    assert window.config_issues.isHidden()
    assert window.config_detail.text() == "No issues found."
    assert window.config_validate.isEnabled()
    assert window.config_validate_again.isEnabled()


def test_validation_issues_stay_visible_on_the_page(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))

    def validate(_data):
        return config_editor.ValidationResult(
            ok=False, version="",
            issues=("OCS: No schema for MadeUp at 2 index, context <Quirks>!",
                    "Serialisation returns 1 error!"),
            output="")

    monkeypatch.setattr(config_editor, "validate_document", validate)
    window._on_config_validate()
    _settle(qapp, window._config_runner)

    assert window.config_validation_status.text() == "2 issues found."
    assert window.config_validation_chip.text() == "2 issues"
    assert not window.config_issues.isHidden()
    shown = [window.config_issues.item(i).text()
             for i in range(window.config_issues.count())]
    assert "No schema for MadeUp" in shown[0]
    assert shown[1] == "Serialisation returns 1 error!"

    # A later edit makes the old verdict stale instead of pretending it still
    # describes the document on screen.
    item = _config_item(window, ("Booter", "Quirks", "ResizeAppleGpuBars"))
    item.setText(1, "0")
    qapp.processEvents()
    assert window.config_validation_status.text() == "Not checked yet."
    assert window.config_validation_chip.text() == "Not validated"


def test_generate_serials_confirms_before_touching_the_document(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    monkeypatch.setattr(config_editor, "serial_models", lambda: ["MacPro7,1"])
    requested = []

    def generate(model):
        requested.append(model)
        return {"SystemSerialNumber": "C02TEST", "MLB": "C02TESTMLB",
                "SystemUUID": "00000000-0000-0000-0000-000000000001",
                "ROM": b"\xAA\xBB\xCC\xDD\xEE\xFF"}

    monkeypatch.setattr(config_editor, "generate_serials", generate)
    opened = {}

    class _Dialog:
        def __init__(self, parent, models, current, palette):
            opened["models"] = list(models)
            opened["current"] = current

        def exec(self):
            return ui.QDialog.Accepted

        def selected_model(self):
            return "MacPro7,1"

    monkeypatch.setattr(ui, "_SerialDialog", _Dialog)

    cancelled = _message_box(monkeypatch, accept=False)
    window._on_config_serials()
    _settle(qapp, window._config_runner)

    assert opened == {"models": ["MacPro7,1"], "current": "MacPro7,1"}
    assert requested == ["MacPro7,1"]
    assert cancelled["title"] == "Replace SMBIOS values?"
    assert cancelled["text"] == (
        "Write the new values for MacPro7,1 into config.plist?")
    assert cancelled["informative"] == (
        "Nothing is written until you save. They replace the current serial, "
        "MLB, UUID and ROM.")
    assert cancelled["default"] is cancelled["cancel_button"]
    assert "SystemSerialNumber" not in window._config_doc.data["PlatformInfo"][
        "Generic"]
    assert window.config_detail.text() == "The generated values were not applied."

    accepted = _message_box(monkeypatch, accept=True)
    window._on_config_serials()
    _settle(qapp, window._config_runner)

    assert accepted["shown"] is True
    generic = window._config_doc.data["PlatformInfo"]["Generic"]
    assert generic["SystemSerialNumber"] == "C02TEST"
    assert generic["ROM"] == b"\xAA\xBB\xCC\xDD\xEE\xFF"
    assert window._config_selected_path() == ("PlatformInfo", "Generic")
    assert window.config_detail.text() == (
        "Generated SMBIOS values for MacPro7,1.")
    assert window.config_status.text() == "Unsaved changes"

    # Identity values are one snapshot too; undo puts the old ones back.
    window._on_config_undo()
    qapp.processEvents()
    generic = window._config_doc.data["PlatformInfo"]["Generic"]
    assert "SystemSerialNumber" not in generic
    assert generic["ROM"] == b"\x11\x22\x33\x44\x55\x66"
    window._on_config_redo()
    qapp.processEvents()
    assert window._config_doc.data["PlatformInfo"]["Generic"][
        "SystemSerialNumber"] == "C02TEST"


def test_generated_smbios_values_never_reach_the_engine_log(
        make_window, qapp, tmp_path, monkeypatch):
    """A generated identity is written into the document and nowhere else.

    The log is the file testers attach to a bug report, and the release notes
    promise it holds no serial, MLB, UUID or ROM. This is the only thing that
    keeps that promise honest: the values below are distinctive enough that a
    future line logging an edit, a diff or the document would trip on them.
    """
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    generated = {"SystemSerialNumber": "C02GENERATED",
                 "MLB": "C02GENERATEDMLB",
                 "SystemUUID": "0EAD0000-0000-4000-8000-000000000001",
                 "ROM": b"\x0e\xad\xbe\xef"}

    class _Dialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return ui.QDialog.Accepted

        def selected_model(self):
            return "MacPro7,1"

    monkeypatch.setattr(config_editor, "serial_models", lambda: ["MacPro7,1"])
    monkeypatch.setattr(config_editor, "generate_serials",
                        lambda _model: dict(generated))
    monkeypatch.setattr(ui, "_SerialDialog", _Dialog)
    _message_box(monkeypatch, accept=True)

    window._on_config_serials()
    _settle(qapp, window._config_runner)
    window._on_config_save()
    window._drain()
    qapp.processEvents()

    assert window._config_doc.data["PlatformInfo"]["Generic"][
        "SystemSerialNumber"] == "C02GENERATED"
    written = (folder / "EFI" / "OC" / "config.plist").read_bytes()
    assert written.count(b"C02GENERATEDMLB") == 1, "the value belongs in the file"

    saved_log = "\n".join(
        "[{}] [{}] {}".format(stamp, level, message)
        for level, message, stamp in window._entries)
    shown = "\n".join((window.log_view.toPlainText(), saved_log)).lower()
    for secret in ("c02generated", "c02generatedmlb",
                   "0ead0000-0000-4000-8000-000000000001", "0eadbeef"):
        assert secret not in shown
    assert "saved" in shown, "the log did record the save itself"


def test_a_validation_result_clears_after_every_kind_of_edit(
        make_window, qapp, tmp_path, monkeypatch):
    """A verdict describes one revision of the document, never the next one.

    Leaving "No issues found." on screen above a config the user has since
    changed would report a check that no longer applies to what Save writes.
    """
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    monkeypatch.setattr(
        config_editor, "validate_document",
        lambda _data: config_editor.ValidationResult(
            ok=True, version="", issues=(), output="No issues found."))

    class _Dialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return ui.QDialog.Accepted

        def selected_preset(self):
            return config_presets.preset_by_key("kernel-trim")

        def selected_model(self):
            return "MacPro7,1"

    monkeypatch.setattr(ui, "_PresetDialog", _Dialog)
    monkeypatch.setattr(ui, "_SerialDialog", _Dialog)
    monkeypatch.setattr(config_editor, "serial_models", lambda: ["MacPro7,1"])
    monkeypatch.setattr(config_editor, "generate_serials",
                        lambda _model: {"SystemSerialNumber": "C02STALE"})
    _message_box(monkeypatch, accept=True)

    def check():
        window._on_config_validate()
        _settle(qapp, window._config_runner)
        assert window.config_validation_chip.text() == "Valid"

    def cleared(what):
        qapp.processEvents()
        assert window.config_validation_chip.text() == "Not validated", what
        assert window.config_validation_status.text() == (
            "Not checked yet."), what

    check()
    item = _config_item(window, ("Booter", "Quirks", "ResizeAppleGpuBars"))
    item.setText(1, "0")
    cleared("an inline edit")

    check()
    _select(window, ("Kernel", "Add"))
    window._on_config_add_item()
    cleared("adding an array item")

    check()
    _select(window, ("Kernel", "Add", 1))
    window._move_config_item(-1)
    cleared("moving an item")

    check()
    _select(window, ("Kernel", "Add", 0))
    window._on_config_remove()
    cleared("removing an item")

    check()
    window._on_config_presets()
    cleared("inserting a preset")

    check()
    window._on_config_serials()
    _settle(qapp, window._config_runner)
    cleared("writing generated serials")

    check()
    window._on_config_revert()
    cleared("reverting to the file on disk")


def test_a_data_value_opens_in_the_hex_editor(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    captured = {}

    class _Dialog:
        def __init__(self, parent, title, path, text, monospace):
            captured.update(title=title, path=path, text=text,
                            monospace=monospace)

        def set_parser(self, parser):
            captured["parser"] = parser

        def exec(self):
            return ui.QDialog.Accepted

        def payload(self):
            return b"\xde\xad\xbe\xef"

    monkeypatch.setattr(ui, "_TextDialog", _Dialog)
    item = _config_item(
        window, ("DeviceProperties", "Add", "PciRoot(0x0)", "layout-id"))

    window._on_config_double_clicked(item, 1)
    qapp.processEvents()

    assert captured["title"] == "Edit data"
    assert captured["path"] == (
        "DeviceProperties", "Add", "PciRoot(0x0)", "layout-id")
    assert captured["text"] == "0B 00 00 00"
    assert captured["monospace"] is True
    assert window._config_doc.data["DeviceProperties"]["Add"][
        "PciRoot(0x0)"]["layout-id"] == b"\xde\xad\xbe\xef"
    assert window.config_status.text() == "Unsaved changes"


def test_the_hex_editor_keeps_the_dialog_open_on_bad_input(make_window):
    window = make_window()
    dialog = ui._TextDialog(window, "Edit data", ("X",), "11 22", True)
    dialog.set_parser(config_editor.hex_to_data)

    dialog.edit.setPlainText("not-hex")
    dialog._submit()

    assert dialog.result() != ui.QDialog.Accepted
    assert "even number" in dialog.error.text()
    assert not dialog.error.isHidden()

    dialog.edit.setPlainText("de ad be ef")
    dialog._submit()

    assert dialog.result() == ui.QDialog.Accepted
    assert dialog.payload() == b"\xde\xad\xbe\xef"
    dialog.deleteLater()


def test_the_text_toggle_round_trips_every_byte(make_window):
    raw = b"A\x00\\\n\xff"
    window = make_window()
    dialog = ui._TextDialog(
        window, "Edit data", ("X",), config_editor.data_to_hex(raw), True)
    dialog.set_parser(config_editor.hex_to_data)

    dialog.text_toggle.setChecked(True)
    assert dialog.edit.toPlainText() == config_editor.data_to_text(raw)
    assert dialog.hint.text().startswith("Text view.")

    dialog.text_toggle.setChecked(False)
    assert dialog.edit.toPlainText() == config_editor.data_to_hex(raw)

    dialog.text_toggle.setChecked(True)
    dialog._submit()
    assert dialog.result() == ui.QDialog.Accepted
    assert dialog.payload() == raw
    dialog.deleteLater()


def test_the_text_toggle_reverts_when_the_text_would_change_bytes(make_window):
    window = make_window()
    dialog = ui._TextDialog(window, "Edit data", ("X",), "41 42", True)
    dialog.set_parser(config_editor.hex_to_data)
    dialog.text_toggle.setChecked(True)

    dialog.edit.setPlainText("AB\\q")
    dialog.text_toggle.setChecked(False)

    assert dialog.text_toggle.isChecked()
    assert "Unknown escape" in dialog.error.text()
    assert not dialog.error.isHidden()
    dialog.deleteLater()


def test_presets_need_an_open_document(make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    assert not window.config_presets.isEnabled()

    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))

    assert window.config_presets.isEnabled()
    assert window.config_presets.text() == "Presets\u2026"


def test_inserting_a_preset_appends_the_patch_entry(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    chosen = config_presets.preset_by_key("acpi-osid-xsid")
    opened = {}

    class _Dialog:
        def __init__(self, parent, presets, section, palette):
            opened["presets"] = list(presets)
            opened["section"] = section

        def exec(self):
            return ui.QDialog.Accepted

        def selected_preset(self):
            return chosen

    monkeypatch.setattr(ui, "_PresetDialog", _Dialog)
    window._set_config_section("ACPI")
    window._on_config_presets()
    qapp.processEvents()

    assert opened["presets"] == list(config_presets.PRESETS)
    assert opened["section"] == "ACPI"
    assert len(window._config_doc.data["ACPI"]["Patch"]) == 1
    assert window._config_doc.data["ACPI"]["Patch"][0] == chosen.value
    assert window._config_selected_path() == ("ACPI", "Patch", 0)
    assert window.config_detail.text() == "Inserted {}.".format(chosen.title)
    assert window.config_status.text() == "Unsaved changes"

    # A preset insertion is one snapshot like any other edit, so it walks back.
    assert window.config_undo.isEnabled()
    window._on_config_undo()
    qapp.processEvents()
    assert "Patch" not in window._config_doc.data["ACPI"]


def test_inserting_the_same_preset_again_selects_the_existing_entry(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    chosen = config_presets.preset_by_key("kernel-trim")

    class _Dialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return ui.QDialog.Accepted

        def selected_preset(self):
            return chosen

    monkeypatch.setattr(ui, "_PresetDialog", _Dialog)
    window._on_config_presets()
    window._on_config_presets()
    qapp.processEvents()

    assert len(window._config_doc.data["Kernel"]["Patch"]) == 1
    assert window._config_selected_path() == ("Kernel", "Patch", 0)
    assert window.config_detail.text() == (
        "That preset is already in Kernel > Patch > [0].")


def test_the_preset_dialog_groups_entries_and_previews_their_state(make_window):
    window = make_window()
    dialog = ui._PresetDialog(
        window, config_presets.PRESETS, "Kernel", ui.LIGHT)

    assert dialog.windowTitle() == "Insert a preset"
    groups = [dialog.tree.topLevelItem(index).text(0)
              for index in range(dialog.tree.topLevelItemCount())]
    assert groups == ["ACPI > Patch", "Kernel > Patch"]
    assert dialog.tree.headerItem().text(0) == "Preset"
    assert dialog.selected_preset().target[0] == "Kernel"
    assert dialog.target_label.text() == "Target: Kernel > Patch"
    assert dialog.insert_button.text() == "Insert"

    def find(key):
        for index in range(dialog.tree.topLevelItemCount()):
            group = dialog.tree.topLevelItem(index)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child.data(0, Qt.UserRole) == key:
                    return child

    dialog.tree.setCurrentItem(find("kernel-trim"))
    assert dialog.selected_preset().key == "kernel-trim"
    assert dialog.state_label.text() == (
        "Will be inserted disabled; turn Enabled on to use it.")

    dialog.tree.setCurrentItem(find("acpi-osid-xsid"))
    assert dialog.state_label.text() == "Will be inserted enabled."
    dialog.deleteLater()


# ---- roadmap: history, validator navigation, folder checks, diagnostics ----


def _clean_config():
    return {
        "ACPI": {"Add": [], "Quirks": {}},
        "Booter": {"Quirks": {"ResizeAppleGpuBars": -1}},
        "Kernel": {"Add": [{"BundlePath": "Lilu.kext", "Enabled": True}]},
        "PlatformInfo": {"Automatic": True, "Generic": {
            "SystemProductName": "MacPro7,1",
            "ROM": b"\x11\x22\x33\x44\x55\x66"}},
        "UEFI": {"Drivers": [{"Path": "OpenRuntime.efi", "Enabled": True}]},
    }


def _clean_efi_folder(root):
    efi = _efi_folder(root, _clean_config())
    (efi / "OC" / "Kexts" / "Lilu.kext").mkdir(parents=True)
    (efi / "OC" / "Drivers").mkdir()
    (efi / "OC" / "Drivers" / "OpenRuntime.efi").write_bytes(b"driver")
    return efi


def test_undo_and_redo_walk_snapshots_without_touching_the_file(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    efi = _efi_folder(folder)
    window._set_efi_folder(str(folder))
    original = (efi / "OC" / "config.plist").read_bytes()

    assert not window.config_undo.isEnabled()
    assert not window.config_redo.isEnabled()
    assert window.config_changes.text() == "Changes\u2026"

    item = _config_item(window, ("Booter", "Quirks", "ResizeAppleGpuBars"))
    item.setText(1, "0")
    qapp.processEvents()

    assert window.config_undo.isEnabled()
    assert window.config_undo.toolTip().startswith("Undo ")
    assert window.config_changes.text() == "Changes (1)\u2026"

    window._on_config_undo()
    qapp.processEvents()

    assert window._config_doc.data["Booter"]["Quirks"][
        "ResizeAppleGpuBars"] == -1
    assert (efi / "OC" / "config.plist").read_bytes() == original
    assert window.config_redo.isEnabled()
    assert window.config_detail.text().startswith("Undid ")

    window._on_config_redo()
    qapp.processEvents()

    assert window._config_doc.data["Booter"]["Quirks"][
        "ResizeAppleGpuBars"] == 0
    assert window.config_changes.text() == "Changes (1)\u2026"
    assert (efi / "OC" / "config.plist").read_bytes() == original


def test_a_save_makes_the_saved_bytes_the_new_baseline(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))

    item = _config_item(window, ("Booter", "Quirks", "ResizeAppleGpuBars"))
    item.setText(1, "0")
    qapp.processEvents()
    window._on_config_save()
    qapp.processEvents()

    assert window.config_changes.text() == "Changes\u2026"
    assert not window.config_undo.isEnabled()
    assert not window.config_redo.isEnabled()


def test_the_changes_dialog_lists_each_edit_with_both_values(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))

    _config_item(window, ("Booter", "Quirks", "ResizeAppleGpuBars")
                 ).setText(1, "0")
    qapp.processEvents()
    _config_item(window, ("Booter", "Quirks", "AvoidRuntimeDefrag")
                 ).setCheckState(1, Qt.Unchecked)
    qapp.processEvents()

    dialog = ui._ChangesDialog(
        window, window._config_history.changes(), window._config_doc.path,
        ui.LIGHT)

    assert dialog.windowTitle() == "Changes since the file was opened"
    rows = [[dialog.tree.topLevelItem(index).text(column)
             for column in range(4)]
            for index in range(dialog.tree.topLevelItemCount())]
    assert ("Changed", "Booter > Quirks > ResizeAppleGpuBars",
            "-1", "0") in [tuple(row) for row in rows]
    assert ("Changed", "Booter > Quirks > AvoidRuntimeDefrag",
            "true", "false") in [tuple(row) for row in rows]
    for index in range(dialog.tree.topLevelItemCount()):
        item = dialog.tree.topLevelItem(index)
        assert item.toolTip(1) == item.text(1)
        assert item.toolTip(2) == item.text(2)
        assert item.toolTip(3) == item.text(3)

    empty = ui._ChangesDialog(
        window, [], window._config_doc.path, ui.LIGHT)
    placeholder = empty.tree.topLevelItem(0)
    assert placeholder.text(0) == "No edits since the file was opened."
    assert placeholder.isFirstColumnSpanned()
    dialog.deleteLater()
    empty.deleteLater()


def test_selecting_a_validator_issue_jumps_to_the_key_it_names(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))

    window._render_config_issues((
        "OCS: No schema for ResizeAppleGpuBars at 1 index, context <Quirks>!",
        "The validator stopped here.",
    ))
    qapp.processEvents()

    assert window.config_issue_note.text() == (
        "Select an issue to go to the key it names.")
    first = window.config_issues.item(0)
    assert first.toolTip() == (
        "Go to Booter > Quirks > ResizeAppleGpuBars")

    window.config_issues.setCurrentRow(0)
    qapp.processEvents()

    assert window._config_selected_path() == (
        "Booter", "Quirks", "ResizeAppleGpuBars")
    assert "jumped to Booter > Quirks > ResizeAppleGpuBars" in (
        window.config_issue_note.text())

    window.config_issues.setCurrentRow(1)
    qapp.processEvents()
    assert "does not name one key" in window.config_issue_note.text()


def test_folder_checks_read_the_built_folder_and_never_claim_boot(
        make_window, qapp, tmp_path):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _clean_efi_folder(folder)
    window._set_efi_folder(str(folder))

    assert window.preflight_status.text() == "Not checked yet."
    assert not window.preflight_export.isEnabled()

    window._on_preflight()
    qapp.processEvents()

    assert window._preflight is not None
    assert window.preflight_status.text() == (
        "No issues detected by these checks.")
    assert "do not test firmware, hardware or whether macOS boots" in (
        window.preflight_note.text())
    assert window.preflight_list.isHidden()
    assert window.preflight_export.isEnabled()
    assert "does not prove" not in window.preflight_status.text()

    (folder / "EFI" / "OC" / "Kexts" / "Lilu.kext").rmdir()
    window._on_preflight()
    qapp.processEvents()

    assert "error" in window.preflight_status.text().lower()
    assert not window.preflight_list.isHidden()
    assert "Lilu.kext" in window.preflight_list.item(0).toolTip()
    assert "Next:" in window.preflight_list.item(0).toolTip()


def test_the_manifest_verifies_a_build_and_reports_a_changed_file(
        make_window, qapp, tmp_path):
    from blackdream.core import efi_manifest

    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _clean_efi_folder(folder)
    window._set_efi_folder(str(folder))
    efi_manifest.write(folder)

    window._on_verify_manifest()
    qapp.processEvents()

    assert window.preflight_status.text() == (
        "Every file matches the recorded manifest.")
    assert "does not prove the folder boots" in (
        window.preflight_note.text())
    assert window.preflight_list.isHidden()

    with (folder / "EFI" / "OC" / "OpenCore.efi").open("ab") as handle:
        handle.write(b"tampered")
    window._on_verify_manifest()
    qapp.processEvents()

    assert window.preflight_status.text() == "0 missing, 1 changed, 0 added"
    assert not window.preflight_list.isHidden()
    assert "EFI/OC/OpenCore.efi" in window.preflight_list.item(0).text()


def test_the_folder_report_is_saved_as_text(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _clean_efi_folder(folder)
    window._set_efi_folder(str(folder))
    window._on_preflight()

    target = tmp_path / "checks.txt"
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName",
                        lambda *_args, **_kwargs: (str(target), ""))
    window._on_preflight_export()

    assert target.read_text(encoding="utf-8") == window._preflight_text
    assert "Result: No issues detected by these checks." in (
        target.read_text(encoding="utf-8"))


def test_the_diagnostic_bundle_redacts_identity_values_and_defaults_off_report(
        make_window, qapp, tmp_path, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)
    folder = tmp_path / "build"
    _efi_folder(folder)
    window._set_efi_folder(str(folder))
    window._ingest("info", "ROM 112233445566 at {}".format(Path.home()))

    report = tmp_path / "Report.json"
    report.write_text('{"Hardware": {"CPU": [{"Name": "Test"}]}}',
                      encoding="utf-8")
    window._report_path = report
    captured = {}

    class _StubDialog:
        def __init__(self, parent, bundle, palette):
            captured["bundle"] = bundle
            self.saved_path = ""

        def exec(self):
            return ui.QDialog.Accepted

    monkeypatch.setattr(ui, "_DiagnosticsDialog", _StubDialog)
    window._on_diagnostics_bundle()

    bundle = captured["bundle"]
    names = {entry.name: entry for entry in bundle.entries}
    assert names["environment.txt"].optional is False
    assert names["Report.json"].included is False
    assert names["report-summary.txt"].included is True
    rendered = bundle.render()
    assert "112233445566" not in rendered
    assert "<redacted>" in rendered
    assert "Test" not in names["report-summary.txt"].body


def test_the_diagnostics_copy_scrubs_the_home_folder(
        make_window, qapp, monkeypatch):
    window = make_window()
    _settle(qapp, window._usb_runner)

    window._copy_diagnostics()

    assert window.diagnostics_note.text() == "Copied to the clipboard."
    text = QApplication.clipboard().text()
    assert "BlackDream" in text
    assert str(Path.home()) not in text
