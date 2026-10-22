"""Hardware report collection on Windows, through the tool the engine already runs.

The Linux collector is a built-in scan. Windows has no equivalent here: the
identification tables this project vendors are the ones Hardware Sniffer maintains,
and its CLI is a Windows executable. Rather than reimplementing that catalogue, the
app runs the same tool upstream runs, after the engine's downloader has verified its
release digest -- the executable is never executed from an unverified download.

The tool writes the ``Report.json`` the rest of the pipeline consumes. When it can
read the firmware, it writes the ACPI tables beside it, and those are adopted as the
folder the build's ACPI step needs, so a Windows user does not have to find them
separately.

Nothing in this module runs on another platform: :func:`supported` gates both the
button and :meth:`WindowsCollector.collect`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from ocengine import gathering_files
from ocengine.fatal import EngineError
from ocengine.report_validator import ReportValidator
from ocengine.utils import Utils

from blackdream.core.pipeline import Cancelled

from .collect import (
    REPORT_FILE,
    Collected,
    CollectionUnsupported,
    _absent_sections,
    reconcile_report,
)

#: The Sniffer can take minutes on a large machine; the job wrapper waits longer.
SNIFFER_TIMEOUT = 540.0
POLL_SECONDS = 0.5

# Same grammar as the Linux dumper: firmware tables are plain upper-case names.
_TABLE_FILE = re.compile(r"^(?P<name>[A-Z][A-Za-z0-9]{1,15}(-?[0-9]{1,3})?)\.aml$")

# Documented by Hardware Sniffer's own CLI. Code 5 is special-cased: the report can
# be complete even when the ACPI dump failed, so it is a warning rather than a loss.
_SNIFFER_EXIT = {
    3: "Hardware Sniffer could not collect this machine's hardware.",
    4: "Hardware Sniffer could not write the hardware report.",
    5: "Hardware Sniffer could not dump the firmware ACPI tables.",
}


class CollectionFailed(EngineError):
    code = "collect.failed"
    title = "The hardware scan did not finish"
    remediation = (
        "Run Hardware Sniffer once by hand to see why it stops; its exit codes "
        "distinguish collection, report writing and ACPI failures.",
        "A Report.json exported on this machine can be loaded instead.",
    )


class CollectionTimedOut(EngineError):
    code = "collect.timed_out"
    title = "The hardware scan took too long"
    remediation = ("Close other heavy applications and scan again.",)

    def __init__(self, timeout: float) -> None:
        self.detail = "The scan waited {:g} s and was stopped.".format(timeout)
        super().__init__()


def supported() -> bool:
    """Whether the verified Hardware Sniffer executable can run here."""
    return sys.platform == "win32"


class WindowsCollector:
    """Resolve, run and validate Hardware Sniffer on Windows.

    ``gather`` and ``runner`` are injectable so the orchestration can be tested on
    any host: the real gatherer downloads and verifies the CLI, and the real runner
    starts it without a console window and with a deadline and a cancel check.
    """

    def __init__(self, utils: Utils | None = None, gather=None,
                 runner: Callable | None = None, timeout: float = SNIFFER_TIMEOUT) -> None:
        self.utils = utils or Utils()
        self._gather = gather
        self._runner = runner or self._run_sniffer
        self.timeout = timeout

    def collect(self, out_dir: str | Path,
                is_cancelled: Callable[[], bool] | None = None) -> Collected:
        if not supported():
            raise CollectionUnsupported(detail=(
                "Hardware Sniffer is a Windows executable; this is {}.".format(sys.platform)))

        directory = Path(self.utils.normalize_path(str(out_dir)))
        directory.mkdir(parents=True, exist_ok=True)
        sink = self.utils.sink
        sink.section("Collecting hardware")
        sink.log("info", "Hardware Sniffer will scan this machine and write the report.")

        executable = self._executable()
        report_path = directory / REPORT_FILE
        # A failed scan must not leave a previous run's report looking like this
        # run's output, so the scan folder starts empty of report and tables.
        report_path.unlink(missing_ok=True)
        shutil.rmtree(directory / "ACPI", ignore_errors=True)

        code, out, err = self._runner([executable, "-e", "-o", str(directory)],
                                      is_cancelled)
        acpi_dir = _adopt_tables(directory, sink)

        if not report_path.is_file():
            raise CollectionFailed(detail=_failure_detail(code, err, out))

        try:
            raw = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CollectionFailed(detail=(
                "Hardware Sniffer wrote an unreadable report: {}".format(exc)))

        if code != 0:
            sink.log("warning", _SNIFFER_EXIT.get(
                code, "Hardware Sniffer exited with code {}.".format(code)))

        validator = ReportValidator()
        report, resolved = reconcile_report(validator, report_path, raw)
        for note in resolved:
            sink.log("info", note)
        for section in _absent_sections(validator, report):
            sink.log("info", "No {} found.".format(section.lower()))
        sink.log("info", "Hardware report written to {}".format(report_path))
        return Collected(report_path=report_path, report=report,
                         resolved=tuple(resolved), acpi_dir=acpi_dir)

    def _executable(self) -> str:
        gatherer = self._gather or gathering_files.gatheringFiles()
        return gatherer.gather_hardware_sniffer()

    def _run_sniffer(self, argv: list[str],
                     is_cancelled: Callable[[], bool] | None) -> tuple[int, str, str]:
        try:
            proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            raise CollectionFailed(detail="Could not start Hardware Sniffer: {}".format(exc))

        deadline = time.monotonic() + self.timeout
        while True:
            try:
                out, err = proc.communicate(timeout=POLL_SECONDS)
                return proc.returncode, out, err
            except subprocess.TimeoutExpired:
                if is_cancelled is not None and is_cancelled():
                    _kill(proc)
                    raise Cancelled() from None
                if time.monotonic() >= deadline:
                    _kill(proc)
                    raise CollectionTimedOut(self.timeout) from None


def _adopt_tables(directory: Path, sink) -> Path | None:
    """Move the scan's ACPI tables into one folder, or return None if it wrote none."""
    found: dict[str, Path] = {}
    for path in sorted(directory.rglob("*.aml")):
        if path.is_file() and _TABLE_FILE.match(path.name):
            found.setdefault(path.name, path)
    if not found:
        return None

    target = directory / "ACPI"
    target.mkdir(exist_ok=True)
    for name, path in sorted(found.items()):
        destination = target / name
        if path == destination:
            continue
        destination.unlink(missing_ok=True)
        shutil.move(str(path), str(destination))
    sink.log("info", "{} ACPI tables exported with the report".format(len(found)))
    return target


def _failure_detail(code: int, err: str, out: str) -> str:
    reason = _tail(err) or _tail(out)
    if code in _SNIFFER_EXIT:
        return _SNIFFER_EXIT[code] + ((" {}".format(reason)) if reason else "")
    if reason:
        return reason
    return "Hardware Sniffer exited with code {} without writing {}.".format(code, REPORT_FILE)


def _tail(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _kill(proc: subprocess.Popen) -> None:
    proc.kill()
    try:
        proc.communicate(timeout=POLL_SECONDS)
    except subprocess.TimeoutExpired:
        pass
