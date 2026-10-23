"""Built-in hardware report collection for Linux.

The engine consumes a ``Report.json``, and upstream only produced one on Windows:
OpCore Simplify gates its exporter behind ``if os_name != "Windows": return``
(``OpCore-Simplify/Scripts/gathering_files.py:308``) and the tool it calls publishes
only ``.exe`` assets.  This module is the Linux half of closing that gap; Windows uses
``blackdream.hardware.windows`` to run the same verified tool, and macOS has no
collector.  The scanner here is the vendored Linux backend of that same BSD-3 project
(see ``sniffer/VENDOR_NOTICE.txt``), so the identification tables -- the part that is
genuinely hard and genuinely OS-independent -- come from the same source the reference
generator uses.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ocengine import runtime
from ocengine.fatal import EngineError
from ocengine.report_validator import ReportValidator
from ocengine.utils import Utils

REPORT_FILE = "Report.json"


class CollectionUnsupported(EngineError):
    code = "collect.unsupported"
    title = "The built-in scan only runs on Linux"
    remediation = (
        "On Windows, use Collect hardware for the verified Hardware Sniffer scan.",
        "On any host, a Report.json exported by Hardware Sniffer can be loaded instead.",
    )


class CollectionRejected(EngineError):
    code = "collect.rejected"
    title = "The scanned hardware report was not accepted"
    detail = "The scan produced a report, but the engine refused it."
    remediation = ("Scan again, or load a Report.json exported by Hardware Sniffer.",)


def supported() -> bool:
    """Whether a scan can run here at all.

    Linux only, so far.  Windows is better served by the released Hardware Sniffer
    executable, which is why the file picker stays in the UI.  macOS has no backend
    upstream either, and one written against ``ioreg``/``system_profiler`` has not
    been measured on any Apple hardware.
    """
    return sys.platform.startswith("linux")


@dataclass(frozen=True)
class Collected:
    report_path: Path
    report: dict[str, Any]
    resolved: tuple[str, ...] = ()
    """Validator findings the reconciliation pass settled, for the log pane."""
    acpi_dir: Path | None = None
    """Firmware tables the same scan exported, when the collector can read them."""


class ReportCollector:
    def __init__(self, utils: Utils | None = None) -> None:
        self.utils = utils or Utils()

    def collect(self, out_dir: str | Path) -> Collected:
        if not supported():
            raise CollectionUnsupported(
                detail="A built-in scan exists for Linux only; this is {}.".format(sys.platform)
            )

        from .sniffer.linux import LinuxHardwareInfo

        sink = self.utils.sink
        sink.section("Collecting hardware")
        checklist = _Checklist(sink)
        report = LinuxHardwareInfo(progress=checklist.started).hardware_collector()
        checklist.finished()

        directory = Path(self.utils.normalize_path(str(out_dir)))
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / REPORT_FILE
        path.write_text(json.dumps(report, indent=4), encoding="utf-8")

        validator = ReportValidator()
        report, resolved = self._reconcile(validator, path, report)
        for note in resolved:
            sink.log("info", note)
        for section in _absent_sections(validator, report):
            sink.log("info", "No {} found.".format(section.lower()))
        sink.log("info", "Hardware report written to {}".format(path))
        return Collected(report_path=path, report=report, resolved=tuple(resolved))

    def _reconcile(self, validator: ReportValidator, path: Path, raw: dict) -> tuple[dict, list[str]]:
        return reconcile_report(validator, path, raw)


def reconcile_report(validator: ReportValidator, path: Path, raw: dict) -> tuple[dict, list[str]]:
    """Make a collected report one the engine will accept, without guessing.

    The engine's validator is the only authority on the schema, and it already
    returns the report with unknown keys and unparseable values dropped.  Asking
    it, rather than keeping a parallel list of exceptions here, is what stops this
    rotting the next time either side changes.  There was a real case on the first
    machine tried: sysfs reports a thermal zone as ``\\_TZ_.THRM``, which the
    ``acpi_path`` pattern rejects -- and since ``ACPI Path`` is optional, dropping
    that one value is correct, while an allowlist written up front would have had
    to predict it.  Both the Linux and Windows collectors end here, so a report
    rejected on one host is rejected the same way on the other.
    """
    is_valid, errors, notes, cleaned = validator.validate_report(str(path))
    if is_valid and not notes:
        return raw, []

    findings = ["{}: {}".format(kind, item)
                for kind, items in (("error", errors), ("note", notes)) for item in items]

    if cleaned is None:
        raise CollectionRejected(detail="; ".join(errors))

    # A section the scan came back empty for is simply absent from the report, and the
    # engine rejects a report that does not carry its required sections -- so a virtual
    # machine with no GPU, no USB controller and no storage controller produced a report
    # the engine would not read at all. Saying "none found" is not a guess: it is what
    # the scan measured. Sections whose schema requires members are left alone, because
    # there the absence is of a value nobody saw, not of a device nobody found.
    for name, rule in validator.SCHEMA["schema"].items():
        if not rule.get("required", True) or name in cleaned:
            continue
        members = rule.get("schema", {})
        if any(member.get("required", True) for member in members.values()):
            continue
        cleaned[name] = [] if rule.get("type") is list else {}
        findings.append("note: no {} found".format(name.lower()))

    path.write_text(json.dumps(cleaned, indent=4), encoding="utf-8")
    is_valid, errors, notes, _ = validator.validate_report(str(path))
    if not is_valid or errors:
        raise CollectionRejected(detail="; ".join(errors))
    findings += ["note: {}".format(item) for item in notes]
    return cleaned, findings


def _absent_sections(validator: ReportValidator, report: dict) -> list[str]:
    """Schema sections the scan came back empty for, for the log pane.

    Upstream printed these from inside its step loop, which made an empty result a
    stage of its own and pushed the checklist total past the real step count.  Reading
    them off the engine's schema rather than a literal list here keeps the two in step.
    """
    return [name for name in validator.SCHEMA["schema"] if not report.get(name)]


class _Checklist:
    """Turns the collector's per-step callback into the sink's stage contract.

    ``EngineBridge.stage`` rebuilds the list on every ``index == 0`` event because
    ``Utils.progress_bar`` redraws the whole checklist per tick.  Emitting one event
    per step would therefore render a one-item list that replaces itself.
    """

    def __init__(self, sink: runtime.EngineSink) -> None:
        self.sink = sink
        self.names: list[str] = []

    def started(self, name: str, index: int, total: int) -> None:
        self.names.append(name)
        self._emit(total, running=len(self.names) - 1)

    def finished(self) -> None:
        self._emit(len(self.names), running=len(self.names))

    def _emit(self, total: int, running: int) -> None:
        for position, name in enumerate(self.names):
            self.sink.stage(name, position, total, "done" if position < running else "running")
