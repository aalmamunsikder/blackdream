"""GUI slice: the window drives the engine and survives everything it returns.

Every test here runs the real pipeline on a real worker thread with PySide6's
offscreen platform, because the failures this layer exists to prevent -- a widget
touched from a worker thread, an engine error that closes the app, a remote string
that formats the window instead of naming itself -- only show up when the threading
and the rendering are real.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import tests.fixtures as fixtures  # noqa: E402
from ocengine import compatibility_checker  # noqa: E402
from ocengine import runtime  # noqa: E402
from ocengine.fatal import EngineError  # noqa: E402
from ocengine.utils import Utils  # noqa: E402
from ocengine.runtime import set_sink  # noqa: E402

from blackdream.core.job_runner import Job  # noqa: E402
from blackdream.core.pipeline import Pipeline  # noqa: E402
from blackdream.ui.main_window import MainWindow, _Step, _dropped_json  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    previous = runtime.current_sink()
    win = MainWindow()
    qapp.processEvents()
    try:
        yield win
    finally:
        win.runner.cancel()
        win._ticker.stop()
        set_sink(previous)


def _load(win, directory, name, data):
    """Point the window at a report and wait for the engine to answer."""
    win.set_report(fixtures.write_report(str(directory), name, data))
    return _settle(win)


def _settle(win, timeout=120.0):
    """Pump the GUI loop until the engine has answered, or fail loudly.

    ``runner.busy`` goes False a frame before the outcome is emitted, so the chain
    and ``delivered`` together are what says the window is done talking.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if win.runner.delivered and not win._chain:
            for _ in range(4):
                QApplication.processEvents()
            return
        time.sleep(0.005)
    raise AssertionError("window never went idle: chain={}".format(
        [step.name for step in win._chain]))


def _rows(win):
    return [win.verdict_tree.topLevelItem(i) for i in range(win.verdict_tree.topLevelItemCount())]


def test_fresh_window_is_idle_and_asks_for_a_report(window):
    assert window.runner.busy is False
    assert window.build_button.isEnabled() is False
    assert window.analyze_button.isEnabled() is True
    assert window.error_card.text() == ""
    assert "Report.json" in window.summary.text()


def test_the_window_is_its_own_engine_sink(qapp):
    """Engine events must reach the window that owns the bridge.

    They used to be installed by app.main() only, so a window constructed any other
    way (tests, a future driver) rendered its own log lines while every engine stage,
    transfer and message went to NullSink -- a successful build showed an empty step
    list and 0%.
    """
    previous = runtime.current_sink()
    try:
        win = MainWindow()
        assert runtime.current_sink() is win.bridge
        Utils().progress_bar("Building OpenCore EFI", ["one", "two"], 1)

        win._drain()
        assert [win.stage_list.item(i).data(Qt.UserRole)
                for i in range(win.stage_list.count())] == ["one", "two"]
        assert win.stage_list.itemWidget(win.stage_list.item(0)) is not None
        assert win.progress.value() == 1 and win.progress.maximum() == 2
        assert win.step_label.text() == "Step 2 of 2"
        # The bar's own text is off: one colour cannot stay legible on both the
        # empty groove and the filled chunk, so the percentage is drawn beside it.
        assert win.progress.isTextVisible() is False
        assert win.progress_label.text() == "50%"
    finally:
        set_sink(previous)


def test_a_valid_report_populates_verdicts_and_versions(window, tmp_path):
    _load(window, tmp_path, "alder", fixtures.alder_lake_desktop())

    rows = _rows(window)
    assert rows, "the engine graded devices but none reached the table"
    assert ("Intel Core i5-12600K", "CPU") in {(r.text(0), r.text(1)) for r in rows}
    assert all(r.text(2) for r in rows)

    assert "Native support: macOS Monterey 12" in window.summary.text()
    assert window.build_button.isEnabled() is True

    labels = [window.version_combo.itemText(i) for i in range(window.version_combo.count())]
    assert any("suggested" in label for label in labels), labels
    assert "suggested" in window.version_combo.currentText()
    assert window.version_combo.currentData() == "25.99.99"


def test_engine_activity_is_captured_without_touching_stdout(window, tmp_path, capsys):
    _load(window, tmp_path, "coffee", fixtures.coffee_lake_laptop())

    tail = window.bridge.tail()
    assert tail, "engine activity produced no log events"
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
    assert not any("\x1b[" in message for _level, message in tail)


def test_a_fatal_verdict_is_a_screen_not_an_exit(window, tmp_path, qapp):
    _load(window, tmp_path, "no-sse4", fixtures.cpu_without_sse4())

    assert "SSE4" in window.error_card.text()
    assert "code: cpu.no_sse4" in window.error_card.text()
    assert window.build_button.isEnabled() is False
    assert window.analysis is None
    assert window.runner.busy is False
    assert qapp.topLevelWidgets(), "the application lost its window"


def test_an_unsupported_gpu_names_the_device_and_the_code(window, tmp_path):
    _load(window, tmp_path, "gpu", fixtures.gpu_unsupported())

    text = window.error_card.text()
    assert "code: gpu.unsupported" in text
    assert "1F12" in text or "NVIDIA" in text


def test_a_fatal_report_clears_everything_the_previous_one_showed(window, tmp_path):
    """A rejected report used to leave the old devices, versions and task text.

    The error card described the new machine while the table, version picker and
    progress box still described the last report that had succeeded.
    """
    _load(window, tmp_path, "good", fixtures.alder_lake_desktop())
    assert _rows(window)
    assert window.version_combo.count() > 0

    _load(window, tmp_path, "gpu", fixtures.gpu_unsupported())

    assert window.analysis is None
    assert _rows(window) == []
    assert window.version_combo.count() == 0
    assert window.build_button.isEnabled() is False
    assert "Compatibility check failed." in window.summary.text()
    assert window.task_name.text() == "Compatibility check failed"
    assert window.devices_card._hint.text() == "No devices were graded from this report."


def test_a_missing_or_unreadable_report_is_refused_before_grading(window, tmp_path):
    _settle_after(window, str(tmp_path / "nothing.json"))

    assert "code: report.rejected" in window.error_card.text()
    assert window.analysis is None


def _settle_after(win, path):
    win.set_report(path)
    _settle(win)


def test_a_build_with_no_acpi_source_stops_at_an_actionable_error(window, tmp_path):
    """On a machine with no DSDT reachable, the only honest outcome is a refusal.

    Upstream prompted for a folder here; a GUI has to say what is missing and let
    the user point at it instead of blinking a cursor.
    """
    _load(window, tmp_path, "alder", fixtures.alder_lake_desktop())
    window.output_field.set_value(str(tmp_path / "out" / "EFI"))
    window._on_build()
    _settle(window)

    text = window.error_card.text()
    assert "code: pipeline.build_not_ready" in text
    assert "ACPI" in text
    assert window._chain == []
    assert window.plan is None
    assert window.build_button.isEnabled() is True


def test_a_foreign_non_empty_output_folder_is_refused_before_any_work(window, tmp_path):
    """The pipeline would refuse it after the download stage; the window owes the
    user that answer before it spends minutes fetching artifacts. The folder is
    someone's bootloader until proven otherwise, so nothing in it may be touched.
    """
    _load(window, tmp_path, "alder", fixtures.alder_lake_desktop())
    foreign = tmp_path / "ESP" / "EFI"
    (foreign / "BOOT").mkdir(parents=True)
    bootloader = foreign / "BOOT" / "BOOTx64.efi"
    bootloader.write_bytes(b"a working bootloader")
    window.output_field.set_value(str(foreign))

    window._on_build()

    assert "code: pipeline.build_not_ready" in window.error_card.text()
    assert "folder is not empty" in window.error_card.text()
    assert window._chain == []
    assert window.plan is None
    assert bootloader.read_bytes() == b"a working bootloader"


def test_a_failed_build_step_names_the_step_not_the_last_product(window, tmp_path):
    """The gauge names whichever kext was downloading when the step died.

    That name is not the step that stopped, so a failure used to leave the task
    card saying e.g. "OcBinaryData" with a step-level error underneath it.
    """
    _load(window, tmp_path, "alder", fixtures.alder_lake_desktop())

    def fail(token):
        raise EngineError(detail="the download did not finish")

    window._start([_Step(name="Downloading OpenCore and kexts", body=fail)])
    _settle(window)

    assert window.task_name.text() == "Downloading OpenCore and kexts"
    assert window.task_detail.text() == "Downloading OpenCore and kexts failed."
    assert "code: engine.error" in window.error_card.text()


def test_an_unexpected_engine_bug_is_reported_not_raised(window, tmp_path, monkeypatch):
    def explode(self, report):
        raise IndexError("list index out of range")

    monkeypatch.setattr(Pipeline, "analyze", explode)
    _settle_after(window, fixtures.write_report(str(tmp_path), "boom",
                                                 fixtures.alder_lake_desktop()))

    assert "IndexError: list index out of range" in window.error_card.text()
    assert "code: engine.unexpected" in window.error_card.text()
    assert window.runner.busy is False


def test_a_bare_engine_exception_no_longer_quits_the_app(window, tmp_path, monkeypatch, qapp):
    """What upstream's untyped fatals did before the typed-failure pass: raise a
    bare Exception out of compatibility checking. The window must present it."""
    monkeypatch.setattr(compatibility_checker.CompatibilityChecker, "check_compatibility",
                        lambda self, report: (_ for _ in ()).throw(RuntimeError("boom")))
    _settle_after(window, fixtures.write_report(str(tmp_path), "bare",
                                                 fixtures.alder_lake_desktop()))

    assert "RuntimeError: boom" in window.error_card.text()
    assert window.analyze_button.isEnabled() is True
    assert window.runner.busy is False


def test_report_text_cannot_format_the_window(window):
    marker = "<img src=x onerror=alert(1)>"

    window._append("info", marker)

    # A log pane that interpreted its own input would show an image object here,
    # not the literal text -- so plain text carrying the markup is the proof it was
    # escaped on the way in.
    assert marker in window.log_view.toPlainText()
    assert window.log_view.blockCount() == 1

    error = type("E", (), {"title": marker, "detail": marker, "remediation": (marker,),
                           "code": marker, "recoverable": True})()
    window._show_error(error)
    assert "&lt;img" in window.error_card.text()
    assert "<img" not in window.error_card.text()


def test_a_device_name_is_rendered_as_text_not_markup(window, tmp_path):
    report = fixtures.alder_lake_desktop()
    report["CPU"]["Processor Name"] = "<b>Bold</b> CPU"
    _load(window, tmp_path, "names", report)

    assert _rows(window)[0].text(0) == "<b>Bold</b> CPU"


def test_cancellation_stops_a_running_job_and_releases_the_buttons(window, qapp):
    observed = []

    def body(token):
        observed.append("started")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            token.check()
            time.sleep(0.01)
        observed.append("finished")
        return "never reached"

    window._start([_Step(name="Long job", body=body, timeout=60)])
    assert window.cancel_button.isEnabled() is True
    QApplication.processEvents()
    window._on_cancel()
    _settle(window, timeout=30)

    assert observed == ["started"]
    assert window._chain == []
    assert window.cancel_button.isEnabled() is False
    assert window.analyze_button.isEnabled() is True
    assert window.statusBar().currentMessage() == "Stopped"


def test_a_report_cannot_replace_the_one_a_running_step_is_using(window, tmp_path):
    """Dropping a report mid-build used to reset the pipeline under the chain.

    The next step calls ``_ensure_pipeline()`` again, so it would have gathered
    kexts from a new session while configuring the old plan on another.
    """
    _load(window, tmp_path, "first", fixtures.alder_lake_desktop())
    original = window._report_path

    def body(token):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            token.check()
            time.sleep(0.01)

    window._start([_Step(name="Long job", body=body, timeout=60)])
    assert window._chain

    window.set_report(fixtures.write_report(str(tmp_path), "second",
                                             fixtures.alder_lake_desktop()))

    assert window._report_path == original
    assert window.analysis is not None
    assert "A step is still running" in window.error_card.text()

    window._on_cancel()
    _settle(window, timeout=30)


def test_a_second_job_is_refused_while_the_first_is_running(window):
    ran = []
    window.runner.start(Job(name="holding", body=lambda token: time.sleep(0.5)))

    window._start([_Step(name="second", body=lambda token: ran.append("second"))])
    _settle(window, timeout=30)

    assert ran == [], "the window started a job while engine objects were still in use"
    assert "code: engine.error" in window.error_card.text()


def test_only_json_paths_are_accepted_from_a_drop(qapp):
    def event(path):
        class Url:
            def isLocalFile(self):
                return True

            def toLocalFile(self):
                return path

        class Mime:
            def hasUrls(self):
                return bool(path)

            def urls(self):
                return [Url()] if path else []

        return type("DropEvent", (), {"mimeData": lambda self: Mime()})()

    assert _dropped_json(event("/tmp/Report.json")) == "/tmp/Report.json"
    assert _dropped_json(event("/tmp/report.txt")) == ""
    assert _dropped_json(event("")) == ""
