"""The section 3 features, driven through the real window offscreen.

Each feature is read-only by design, so these tests check two things: the screen
shows what the core module computed, and nothing here can write a config, write
firmware or boot anything. The engine runs for real on a synthetic report; the
network and the modal dialogs are the only things replaced.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QDialog, QLabel, QPushButton)

import tests.fixtures as fixtures  # noqa: E402
from ocengine import runtime  # noqa: E402
from ocengine.fatal import EngineError  # noqa: E402
from ocengine.paths import EnginePaths  # noqa: E402

from blackdream.core import build_history  # noqa: E402
from blackdream.core import config_diff  # noqa: E402
from blackdream.core import config_editor  # noqa: E402
from blackdream.core import dependency_advisor as advisor  # noqa: E402
from blackdream.core import efi_manifest  # noqa: E402
from blackdream.core import first_boot  # noqa: E402
from blackdream.core import installer as installer_core  # noqa: E402
from blackdream.core import machine_profiles  # noqa: E402
from blackdream.core import release_matrix  # noqa: E402
from blackdream.core import report_compare  # noqa: E402
from blackdream.core.job_runner import CANCELLED, FAILED, Outcome  # noqa: E402
from blackdream.ui import icons  # noqa: E402
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

    def build():
        monkeypatch.setattr(ui, "QSettings",
                            lambda *_args, **_kwargs: _MemorySettings({}))
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


def _state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ocengine.paths._current",
        EnginePaths(cache_dir=tmp_path / "cache", tools_dir=tmp_path / "tools",
                    log_dir=tmp_path / "logs"))


def _settle(window, timeout=120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if window.runner.delivered and not window._chain:
            for _ in range(4):
                QApplication.processEvents()
            return
        time.sleep(0.005)
    raise AssertionError("window never went idle")


def _load(window, directory, name="report", data=None):
    path = fixtures.write_report(
        str(directory), name, data or fixtures.alder_lake_desktop())
    window.set_report(path)
    _settle(window)
    return path


# -- release comparison -------------------------------------------------------


def test_the_compatibility_page_offers_the_links_and_gates_them(make_window):
    window = make_window()

    assert window.profiles_button.isEnabled()
    assert window.history_button.isEnabled()
    assert not window.compare_reports_button.isEnabled()
    assert not window.compare_releases_button.isEnabled()


def test_the_release_matrix_matches_the_table_for_the_selected_release(
        make_window, tmp_path):
    window = make_window()
    _load(window, tmp_path)

    assert window.compare_releases_button.isEnabled()
    matrix = release_matrix.build(
        window._verdicts, window._options, window.analysis.oclp_range)

    selected = window.version_combo.currentIndex()
    for index, verdict in enumerate(window._verdicts):
        assert (matrix.status(index, selected).key
                == window._status_for(verdict).key)

    dialog = ui._ReleaseMatrixDialog(
        window, matrix, window._palette)
    assert dialog.tree.topLevelItemCount() == len(window._verdicts)
    first = dialog.tree.topLevelItem(0)
    assert first.text(2 + selected) == matrix.status(0, selected).label
    tones = [QColor(window._palette[ui._STATUS_TONE.get(status.key, "unknown")])
             for status in matrix.rows[0].cells]
    assert [QColor(first.data(2 + index, Qt.ForegroundRole))
            for index in range(len(tones))] == tones
    # A wash alone is not a verdict: at least one word must be coloured.
    assert any(tone != QColor(window._palette["unknown"]) for tone in tones)
    dialog.close()


# -- report comparison --------------------------------------------------------


def test_compare_reports_reads_both_files_and_keeps_hardware_apart(
        make_window, tmp_path, monkeypatch):
    window = make_window()
    first = _load(window, tmp_path, "first")

    changed = fixtures.alder_lake_desktop()
    changed["GPU"]["AMD Radeon RX 6600"]["Device ID"] = "1002-9999"
    second = fixtures.write_report(str(tmp_path), "second", changed)

    captured = {}

    class _Dialog:
        def __init__(self, parent, comparison, before_name, after_name,
                     palette):
            captured["comparison"] = comparison
            captured["before"] = before_name
            captured["after"] = after_name

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(ui, "_ReportCompareDialog", _Dialog)
    monkeypatch.setattr(
        ui.QFileDialog, "getOpenFileName",
        lambda *_args, **_kwargs: (second, ""))

    window._on_compare_reports()

    comparison = captured["comparison"]
    assert captured["before"] == Path(first).name
    assert captured["after"] == Path(second).name
    assert [change.kind for change in comparison.changes] == ["hardware"]
    assert "1002-73FF -> 1002-9999" in comparison.changes[0].detail


def test_a_report_comparison_dialog_shows_changes_and_the_boundary(make_window):
    before = fixtures.alder_lake_desktop()
    after = fixtures.alder_lake_desktop()
    after["GPU"]["AMD Radeon RX 6600"]["Subsystem ID"] = "0x0000FFFF"
    comparison = report_compare.compare(before, after)

    window = make_window()
    dialog = ui._ReportCompareDialog(
        window, comparison, "before.json", "after.json", window._palette)

    assert dialog.tree.topLevelItemCount() == 1
    assert dialog.tree.topLevelItem(0).text(0) == "Hardware"
    assert dialog.tree.topLevelItem(0).text(2) == "AMD Radeon RX 6600"
    counts = [label.text() for label in dialog.findChildren(QLabel)
              if "unchanged" in label.text()]
    assert counts == [
        "1 hardware change \u00b7 0 recorded compatibility changes \u00b7 8 unchanged"]
    assert "re-graded" in report_compare.BOUNDARY
    dialog.close()


# -- profiles -----------------------------------------------------------------


def test_a_saved_profile_holds_paths_and_never_an_identity(
        make_window, tmp_path, monkeypatch):
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    report = fixtures.write_report(
        str(tmp_path), "profile", fixtures.alder_lake_desktop())
    folder = tmp_path / "EFI"
    folder.mkdir()

    dialog = ui._ProfilesDialog(
        window, [], report=str(report), efi_folder=str(folder),
        release="Tahoe", palette=window._palette)
    monkeypatch.setattr(
        ui.QInputDialog, "getText", lambda *_args, **_kwargs: ("Desk", True))
    dialog._save_profile()

    raw = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))
    assert raw["profiles"][0] == {
        "name": "Desk", "report": str(report), "efi_folder": str(folder),
        "release": "Tahoe", "updated": raw["profiles"][0]["updated"]}
    assert set(raw["profiles"][0]) == {
        "name", "report", "efi_folder", "release", "updated"}
    text = (tmp_path / "profiles.json").read_text(encoding="utf-8")
    for identity in ("SystemSerialNumber", "MLB", "SystemUUID", "ROM"):
        assert identity not in text

    saved = machine_profiles.load()
    using = ui._ProfilesDialog(
        window, saved, report="", efi_folder="", release="",
        palette=window._palette)
    using.tree.setCurrentItem(using.tree.topLevelItem(0))
    using._use()
    assert using.selected_profile() == saved[0]
    assert using.result() == QDialog.Accepted
    dialog.close()
    using.close()


def test_using_a_profile_reloads_its_report_and_selects_its_release(
        make_window, tmp_path, monkeypatch):
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    original = _load(window, tmp_path, "original")
    release = window._options[0].name
    second = fixtures.write_report(
        str(tmp_path), "second", fixtures.alder_lake_desktop())

    profile = machine_profiles.Profile(
        name="Desk", report=second, efi_folder="", release=release)
    window._apply_profile(profile)
    _settle(window)

    assert window._report_path == Path(second)
    assert window.version_combo.currentIndex() == 0
    assert window._current_release_name() == release
    assert Path(original).is_file()


def test_a_profile_with_a_missing_report_is_refused(make_window, tmp_path):
    window = make_window()
    profile = machine_profiles.Profile(
        name="Gone", report=str(tmp_path / "missing.json"))

    window._apply_profile(profile)

    assert window._report_path is None
    assert "report could not be found" in window.error_card.text()


# -- build history ------------------------------------------------------------


def test_a_recorded_build_names_its_release_folder_and_manifest(
        make_window, tmp_path, monkeypatch):
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    folder = tmp_path / "build"
    folder.mkdir()
    (folder / efi_manifest.MANIFEST_NAME).write_text("{}", encoding="utf-8")
    window._build_release = "Tahoe"
    window._build_recorded = False

    window._record_build(
        "succeeded", folder, manifest=efi_manifest.MANIFEST_NAME)

    entries = build_history.read()
    assert len(entries) == 1
    assert entries[0].status == "succeeded"
    assert entries[0].release == "Tahoe"
    assert entries[0].output == str(folder)
    assert build_history.folder_state(entries[0]) == "ok"
    assert build_history.manifest_state(entries[0]) == "recorded"


def test_cancelled_and_failed_builds_are_recorded_once(
        make_window, tmp_path, monkeypatch):
    _state_dir(monkeypatch, tmp_path)
    window = make_window()

    window._build_recorded = False
    window._on_outcome(Outcome(
        job="Downloading OpenCore and kexts", status=CANCELLED))
    window._build_recorded = False
    window._on_outcome(Outcome(
        job="Writing the EFI folder", status=FAILED,
        error=EngineError(detail="disk full")))

    entries = build_history.read()
    assert [entry.status for entry in entries] == ["failed", "cancelled"]
    assert entries[0].detail == "disk full"


def test_the_history_dialog_handles_a_folder_that_is_gone(make_window, tmp_path):
    window = make_window()
    vanished = build_history.Entry(
        at="2026-10-24T10:00:00+00:00", status="succeeded",
        release="Tahoe", output=str(tmp_path / "deleted"),
        manifest=efi_manifest.MANIFEST_NAME)

    dialog = ui._HistoryDialog(window, [vanished], window._palette)

    item = dialog.tree.topLevelItem(0)
    assert item.text(2) == "Succeeded"
    assert item.text(4) == "Folder missing"
    assert item.text(5) == "Missing"
    assert not dialog._open_button.isEnabled()
    dialog.close()


# -- first-boot checklist -----------------------------------------------------


def test_every_checklist_icon_exists_and_the_copy_is_the_export(make_window):
    window = make_window()
    for step in first_boot.STEPS:
        assert not icons.pixmap(step.icon, "#ffffff", 18).isNull()

    window._copy_first_boot()

    assert QApplication.clipboard().text() == first_boot.to_text()
    assert window.first_boot_note.text() == "Copied to the clipboard."
    assert len(first_boot.STEPS) == 6


# -- schema preview -----------------------------------------------------------


def test_the_schema_preview_projects_only_safe_scalar_additions(
        make_window, tmp_path, monkeypatch):
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    sample = config_editor.sample_plist()
    document = copy.deepcopy(sample)
    del document["Booter"]["Quirks"]["AvoidRuntimeDefrag"]

    monkeypatch.setattr(
        config_editor, "validate_document",
        lambda *_args, **_kwargs: config_editor.ValidationResult(
            ok=True, version="", issues=(), output="No issues found."))

    preview, changes, validation = ui._schema_preview_result(document)

    assert any(finding.label.endswith("AvoidRuntimeDefrag")
               for finding in preview.missing)
    assert any(change.label.endswith("AvoidRuntimeDefrag")
               for change in changes)
    assert validation is not None and validation.ok
    assert preview.projected["Booter"]["Quirks"]["AvoidRuntimeDefrag"] is True
    assert preview.projected is not document

    dialog = ui._SchemaPreviewDialog(
        window, preview, validation, window._palette)
    assert dialog.tree.topLevelItemCount() == len(preview.findings)
    assert "No issues found." in dialog._result.text()
    assert "This preview changes nothing." in dialog._text()
    dialog.close()


def test_the_preview_table_lists_a_missing_container_it_refused_to_invent(
        make_window, tmp_path, monkeypatch):
    """A non-empty sample dict is named, never copied -- and must still be listed.

    The counts line and the table have to agree: a config missing two containers
    shows two rows even though the projection adds nothing and ocvalidate is not
    run.
    """
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    document = copy.deepcopy(config_editor.sample_plist())
    del document["Kernel"]["Emulate"]

    preview, changes, validation = ui._schema_preview_result(document)

    assert [finding.kind for finding in preview.findings] == ["missing"]
    assert changes == [] and validation is None
    dialog = ui._SchemaPreviewDialog(window, preview, validation,
                                     window._palette)
    row = dialog.tree.topLevelItem(0)
    assert [row.text(column) for column in range(4)] == [
        "Missing", "Kernel > Emulate", "",
        "{} keys".format(len(config_editor.sample_plist()["Kernel"]["Emulate"]))]
    assert "Validator not run" in dialog._result.text()
    dialog.close()


def test_a_long_key_path_is_not_elided_in_the_preview(make_window, tmp_path,
                                                      monkeypatch):
    """A preview that truncates the key it is reporting has reported nothing.

    The value columns are hints and the full text is in Copy/Save as text; the
    key is the identity, so it takes the width it needs before the values share
    what is left.
    """
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    document = copy.deepcopy(config_editor.sample_plist())
    del document["Booter"]["Quirks"]["AvoidRuntimeDefrag"]
    monkeypatch.setattr(
        config_editor, "validate_document",
        lambda *_args, **_kwargs: config_editor.ValidationResult(
            ok=True, version="", issues=(), output="No issues found."))

    preview, _changes, validation = ui._schema_preview_result(document)
    dialog = ui._SchemaPreviewDialog(window, preview, validation,
                                     window._palette)
    dialog.show()
    QApplication.processEvents()

    label = dialog.tree.topLevelItem(0).text(1)
    assert label == "Booter > Quirks > AvoidRuntimeDefrag"
    # Host-agnostic on purpose: the platform's own font decides how wide this key
    # is, so the guarantee is that the column honours the content up to the
    # documented cap, not a pixel count measured on one machine.
    needed = QFontMetrics(dialog.tree.font()).horizontalAdvance(label) + 8
    assert dialog.tree.columnWidth(1) >= min(
        needed, ui._SchemaPreviewDialog.KEY_MAX)
    dialog.close()


def test_an_unchanged_document_skips_the_validator(make_window, tmp_path,
                                                   monkeypatch):
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    monkeypatch.setattr(
        config_editor, "validate_document",
        lambda *_args, **_kwargs: pytest.fail("validator should not run"))

    preview, changes, validation = ui._schema_preview_result(
        config_editor.sample_plist())

    assert changes == []
    assert validation is None
    dialog = ui._SchemaPreviewDialog(
        window, preview, validation, window._palette)
    assert "Validator not run" in dialog._result.text()
    dialog.close()


def test_the_schema_preview_button_needs_an_open_document(
        make_window, tmp_path):
    window = make_window()
    assert not window.config_schema_preview.isEnabled()

    target = tmp_path / "config.plist"
    target.write_bytes(config_editor.serialize_document(
        config_editor.sample_plist()))
    window._load_config(target, origin="chosen")
    window._render_config_state()

    assert window.config_schema_preview.isEnabled()




# -- dependency advisor -------------------------------------------------------


def _broken_document() -> dict:
    """A file that disagrees with itself in three different ways.

    Deliberately small: a ``MaxKernel`` that excludes the release being targeted,
    a driver list with no ``OpenRuntime.efi``, and two kexts in the same conflict
    group. That is one error the release choice causes, one error the engine's own
    rules cause, and warnings a reader may reasonably want to dismiss.
    """
    return {
        "Kernel": {"Add": [
            {"BundlePath": "Lilu.kext", "Enabled": True},
            {"BundlePath": "AppleALC.kext", "Enabled": True,
             "MaxKernel": "20.4.0"},
            {"BundlePath": "WhateverGreen.kext", "Enabled": True},
            {"BundlePath": "NootRX.kext", "Enabled": True},
        ]},
        "UEFI": {"Drivers": [{"Path": "HfsPlus.efi", "Enabled": True}]},
        "NVRAM": {"Add": {advisor.BOOT_SERVICES_GUID: {"boot-args": "-v"}}},
    }


def _open_config(window, tmp_path, document=None):
    target = tmp_path / "config.plist"
    target.write_bytes(config_editor.serialize_document(
        document if document is not None else _broken_document()))
    assert window._load_config(target, origin="chosen")
    window._show_view("Configure EFI")
    QApplication.processEvents()
    return target


def _advisor_dialog(window, release="macOS Sonoma 14", keys=()):
    document = copy.deepcopy(window._config_doc.data)
    report = advisor.advise(document, "23.99.99" if release else None)
    dialog = ui._AdvisorDialog(window, report, window._config_doc.path, release,
                               keys, window._palette)
    dialog.show()
    QApplication.processEvents()
    return dialog, report


def test_the_dependency_button_needs_an_open_document(make_window, tmp_path):
    window = make_window()
    assert not window.config_dependencies.isEnabled()
    _open_config(window, tmp_path)
    assert window.config_dependencies.isEnabled()


def test_the_advisor_dialog_shows_the_fields_a_reader_needs(make_window,
                                                           tmp_path):
    """Trigger, evidence, key path, confidence and source on one screen.

    Those five are what turns a warning into something a tester can check, and the
    citation is the point of the last one: an advisory with no source line is a
    guess wearing a badge.
    """
    window = make_window()
    _open_config(window, tmp_path)
    dialog, report = _advisor_dialog(window)
    try:
        assert [dialog.tree.headerItem().text(column)
                for column in range(3)] == ["Severity", "Where", "Trigger"]
        assert dialog.hint.text() == advisor.BOUNDARY
        assert dialog.summary.text() == report.summary
        assert dialog.target_note.text() == "Checked against macOS Sonoma 14."
        assert len(dialog._rows) == len(report.advisories) > 0
        for index in range(len(dialog._rows)):
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(index))
            item = dialog._rows[index]
            assert dialog._values["Trigger"].text() == item.trigger
            assert dialog._values["Evidence"].text() == item.evidence
            assert dialog._values["Confidence"].text() == item.confidence.capitalize()
            assert dialog._values["Advice"].text() == item.advice
            assert dialog._values["Rule"].text() == item.rule
            assert dialog._values["Source"].text() == item.source
            # Spelled the way the Changes… dialog spells it, so the two surfaces
            # cannot name one key in two shapes -- indices as ``[1]``, not ``1``.
            assert dialog._values["Key path"].text() == \
                config_diff.path_label(item.path)
    finally:
        dialog.close()


def test_the_advisor_dialog_offers_no_way_to_change_the_config(make_window,
                                                              tmp_path,
                                                              monkeypatch):
    """"Do not automatically reorder kexts or alter kernel quirks", in widget form.

    The claim is about the whole surface, so it is checked against every button in
    it -- including the ones a design tool would happily invent -- and against the
    file, which is read back after the dismiss and the restore.
    """
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    target = _open_config(window, tmp_path)
    before = target.read_bytes()
    dialog, _report = _advisor_dialog(window)
    try:
        texts = {button.text() for button in dialog.findChildren(QPushButton)}
        assert not texts & {"Fix", "Apply", "Reorder", "Migrate", "Save",
                            "Auto-fix"}
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
        dialog._dismiss()
        dialog._restore()
        assert target.read_bytes() == before
        assert not window._config_doc.is_dirty()
    finally:
        dialog.close()


def test_dismissing_writes_the_record_file_and_nothing_else(make_window,
                                                           tmp_path,
                                                           monkeypatch):
    """One key in ``advisor-dismissals.json``, and the row comes back on Restore.

    The dismissal is the only write this feature makes, so the test names the file,
    the ruleset inside it and the sentence the dialog prints about it.
    """
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    target = _open_config(window, tmp_path)
    before = target.read_bytes()
    dialog, report = _advisor_dialog(window)
    try:
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
        hidden = dialog._rows[0]
        dialog._dismiss()

        record = tmp_path / "advisor-dismissals.json"
        assert record.is_file()
        stored = json.loads(record.read_text(encoding="utf-8"))
        assert stored["ruleset"] == advisor.RULESET
        assert stored["dismissed"] == [hidden.dismissal_key]
        assert target.read_bytes() == before
        assert hidden not in dialog._rows
        assert len(dialog._rows) == len(report.advisories) - 1
        assert dialog.show_dismissed.isEnabled()
        assert dialog.show_dismissed.text() == "Show dismissed (1)"
        assert dialog.status.text() == (
            "Kept in advisor-dismissals.json, not in config.plist.")

        dialog.show_dismissed.setChecked(True)
        assert hidden in dialog._rows
        dialog.tree.setCurrentItem(dialog._row_for(hidden))
        dialog._restore()
        assert json.loads(record.read_text(encoding="utf-8"))["dismissed"] == []
        assert hidden in dialog._rows
        assert dialog.show_dismissed.text() == "Show dismissed"
        assert not dialog.show_dismissed.isEnabled()
    finally:
        dialog.close()


def test_a_reopened_dialog_still_honours_a_dismissal(make_window, tmp_path,
                                                    monkeypatch):
    """The window loads the record, so a second opening cannot forget it.

    A dismissal that only lasts until the dialog closes is a filter, not a
    preference, and the roadmap asked for the preference.
    """
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    _open_config(window, tmp_path)
    dialog, report = _advisor_dialog(window)
    try:
        dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
        hidden = dialog._rows[0]
        dialog._dismiss()
    finally:
        dialog.close()

    again, _second = _advisor_dialog(window, keys=advisor.load_dismissals())
    try:
        assert hidden not in again._rows
        assert len(again._rows) == len(report.advisories) - 1
        assert not again.show_dismissed.isChecked()
        again.show_dismissed.setChecked(True)
        assert hidden in again._rows
    finally:
        again.close()


def test_go_to_key_selects_the_path_the_advisory_named(make_window, tmp_path):
    """A jump that lands on the wrong row is worse than no jump at all."""
    window = make_window()
    _open_config(window, tmp_path)
    dialog, report = _advisor_dialog(window)
    try:
        item = next(row for row in report.advisories
                    if row.rule == "driver.pairing")
        dialog.tree.setCurrentItem(dialog._row_for(item))
        dialog._go_to_key()
        assert dialog.jump_path == item.path
        selected = window.config_tree.currentItem()
        assert tuple(selected.data(0, Qt.UserRole)) == item.path
    finally:
        dialog.close()


def test_the_button_runs_the_advisor_on_the_selected_release(make_window,
                                                             tmp_path,
                                                             monkeypatch):
    """The version picker is the only thing that can make a ``MaxKernel`` wrong.

    Without a release the window rules are skipped and said to be skipped, so this
    drives the real handler after a real analysis and reads the report it handed the
    dialog -- including the copy boundary: the editor's own document is untouched.
    """
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    _load(window, tmp_path)
    release = window.version_combo.currentText()
    assert window.version_combo.currentData(), "the report left no release"
    _open_config(window, tmp_path)

    opened = {}

    def capture(self, *_args):
        opened["dialog"] = self
        return 0

    monkeypatch.setattr(ui._AdvisorDialog, "exec", capture)
    window._on_config_dependencies()

    dialog = opened["dialog"]
    assert dialog.target_note.text() == "Checked against {}.".format(release)
    assert {row.rule for row in dialog._report.advisories} >= {
        "window.excludes_target", "driver.pairing", "conflict.group"}
    assert window._config_note == (
        "Dependencies checked. Nothing was written to config.plist.")
    assert dialog._report.entries == len(_broken_document()["Kernel"]["Add"])


def test_a_config_without_a_release_says_what_it_did_not_check(make_window,
                                                               tmp_path,
                                                               monkeypatch):
    """A skipped rule is reported as skipped, never as a clean bill."""
    _state_dir(monkeypatch, tmp_path)
    window = make_window()
    _open_config(window, tmp_path)
    opened = {}

    def capture(self, *_args):
        opened["dialog"] = self
        return 0

    monkeypatch.setattr(ui._AdvisorDialog, "exec", capture)
    window._on_config_dependencies()

    dialog = opened["dialog"]
    assert dialog.target_note.text() == "Checked without a macOS release."
    assert dialog._report.skipped
    assert "Not checked: {}".format(dialog._report.skipped[0]) in dialog._text()
    assert "window.excludes_target" not in {row.rule for row in dialog._rows}


def test_the_export_is_the_dialogs_own_words(make_window, tmp_path):
    """Copy, Save as text… and the screen must not disagree about a rule."""
    window = make_window()
    _open_config(window, tmp_path)
    dialog, report = _advisor_dialog(window)
    try:
        text = dialog._text()
        assert text == advisor.to_text(report)
        assert text.startswith("BlackDream dependency advisory")
        assert advisor.BOUNDARY in text
        for item in report.advisories:
            assert item.source in text
            assert item.trigger in text
            assert item.advice in text
    finally:
        dialog.close()
