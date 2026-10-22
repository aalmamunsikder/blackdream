"""Windows collection orchestration, driven without a Windows machine.

The executable itself cannot run here, so the parts that matter for correctness are
tested around it: the scan folder starts clean, the tool's exit codes are mapped,
the report is validated by the engine's own schema, and ACPI tables the tool writes
are adopted as the folder the build needs. ``gather`` and ``runner`` are the two
seams that make that possible; the real runner is the same poll-and-kill shape as
the Linux ACPI dumper.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import fixtures
from blackdream.hardware import CollectionRejected, CollectionUnsupported
from blackdream.hardware import windows
from blackdream.hardware.windows import CollectionFailed, WindowsCollector
from ocengine.runtime import RecordingSink, set_sink


def table_bytes(signature: str) -> bytes:
    return signature.encode() + struct.pack("<I", 40) + b"\x00" * 32


@pytest.fixture
def sink():
    recording = RecordingSink()
    set_sink(recording)
    return recording


@pytest.fixture
def supported(monkeypatch):
    monkeypatch.setattr(windows, "supported", lambda: True)


class FakeGather:
    def __init__(self, executable: str = r"C:\tools\Hardware-Sniffer-CLI.exe") -> None:
        self.executable = executable
        self.calls = 0

    def gather_hardware_sniffer(self):
        self.calls += 1
        return self.executable


def writes_report(report: dict | None = None, tables: tuple[str, ...] = ()):
    """A runner that behaves like the real CLI: writes the report, then tables."""
    def runner(argv, is_cancelled):
        out = Path(argv[-1])
        if report is not None:
            (out / "Report.json").write_text(json.dumps(report), encoding="utf-8")
        for signature in tables:
            (out / "ACPI").mkdir(exist_ok=True)
            (out / "ACPI" / "{}.aml".format(signature)).write_bytes(table_bytes(signature))
        return 0, "", ""
    return runner


def test_the_windows_backend_is_gated_by_platform():
    """On this Linux host the production capability is honestly false."""
    assert windows.supported() is (sys.platform == "win32")


def test_collection_on_a_non_windows_host_raises_typed(monkeypatch, sink, tmp_path):
    monkeypatch.setattr(windows, "supported", lambda: False)
    with pytest.raises(CollectionUnsupported):
        WindowsCollector(gather=FakeGather()).collect(tmp_path)


def test_a_scan_returns_the_report_and_the_exported_tables(supported, sink, tmp_path):
    gather = FakeGather()
    runner = writes_report(fixtures.alder_lake_desktop(), tables=("DSDT", "SSDT1"))
    collected = WindowsCollector(gather=gather, runner=runner).collect(tmp_path)

    assert gather.calls == 1
    assert collected.report_path == tmp_path / "Report.json"
    assert collected.report["CPU"]["Processor Name"] == "Intel Core i5-12600K"
    assert collected.acpi_dir == tmp_path / "ACPI"
    assert sorted(p.name for p in collected.acpi_dir.iterdir()) == ["DSDT.aml", "SSDT1.aml"]
    assert ("info", "Hardware report written to {}".format(
        tmp_path / "Report.json")) in sink.logs


def test_a_stale_report_is_not_mistaken_for_this_scans_output(supported, sink, tmp_path):
    (tmp_path / "Report.json").write_text(
        json.dumps(fixtures.coffee_lake_laptop()), encoding="utf-8")
    collector = WindowsCollector(gather=FakeGather(), runner=writes_report())
    with pytest.raises(CollectionFailed):
        collector.collect(tmp_path)


def test_a_failed_acpi_dump_still_accepts_a_complete_report(supported, sink, tmp_path):
    def runner(argv, is_cancelled):
        Path(argv[-1], "Report.json").write_text(
            json.dumps(fixtures.alder_lake_desktop()), encoding="utf-8")
        return 5, "", "firmware tables are unreadable"

    collected = WindowsCollector(gather=FakeGather(), runner=runner).collect(tmp_path)

    assert collected.acpi_dir is None
    assert collected.report["CPU"]["Processor Name"] == "Intel Core i5-12600K"
    assert ("warning", "Hardware Sniffer could not dump the firmware ACPI tables.") in sink.logs


def test_the_documented_exit_codes_become_typed_failures(supported, sink, tmp_path):
    def runner(argv, is_cancelled):
        return 3, "", "could not read SMBIOS"

    with pytest.raises(CollectionFailed) as failure:
        WindowsCollector(gather=FakeGather(), runner=runner).collect(tmp_path)
    assert "collect this machine's hardware" in failure.value.detail
    assert "could not read SMBIOS" in failure.value.detail


def test_an_invalid_report_is_rejected_by_the_engine_schema(supported, sink, tmp_path):
    broken = {"Motherboard": {"Name": "", "Chipset": "", "Platform": "Desktop"}}
    with pytest.raises(CollectionRejected):
        WindowsCollector(gather=FakeGather(), runner=writes_report(broken)).collect(tmp_path)


def test_only_table_named_aml_files_are_adopted(supported, sink, tmp_path):
    def runner(argv, is_cancelled):
        out = Path(argv[-1])
        (out / "Report.json").write_text(json.dumps(fixtures.alder_lake_desktop()),
                                         encoding="utf-8")
        (out / "notes.aml").write_bytes(b"not a table")
        (out / "DSDT.aml").write_bytes(table_bytes("DSDT"))
        return 0, "", ""

    collected = WindowsCollector(gather=FakeGather(), runner=runner).collect(tmp_path)

    assert collected.acpi_dir == tmp_path / "ACPI"
    assert [p.name for p in collected.acpi_dir.iterdir()] == ["DSDT.aml"]
