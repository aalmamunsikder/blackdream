"""The in-app ACPI reader for Windows, driven without Windows firmware.

The two Win32 calls cannot run on this host, so the parser, the registry naming and
the file rules are tested through an injected firmware object. One test does call
the real API, and runs only on Windows -- the release workflow's Windows leg is the
machine that proves a non-elevated process gets the DSDT.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from blackdream.core.pipeline import Cancelled
from blackdream.hardware import acpi_windows, TablesDumpFailed, TablesUnsupported
from ocengine.runtime import RecordingSink, set_sink


def table(signature: str, body: bytes = b"payload") -> bytes:
    """A minimal description header with a declared length that fits."""
    total = 36 + len(body)
    return (signature.encode("ascii") + struct.pack("<I", total) + b"\x02\x00"
            + b"BLACKD" + b"TESTTBL " + struct.pack("<I", 1) + b"INTL"
            + struct.pack("<I", 1) + body)


class FakeFirmware:
    """The shape of ``WindowsFirmware`` with the OS taken out."""

    def __init__(self, tables=None, registry=None, advertised=()):
        self.tables = dict(tables or {})
        self.registry = dict(registry or {})
        self.advertised = list(advertised)
        self.fetched: list[str] = []
        self.registry_reads: list[str] = []

    def signatures(self):
        names = list(self.tables) + self.advertised
        return [(name, int.from_bytes(name.encode("ascii"), "little")) for name in names]

    def table(self, signature):
        name = signature.to_bytes(4, "little").decode("ascii")
        self.fetched.append(name)
        return self.tables.get(name)

    def registry_table(self, key):
        self.registry_reads.append(key)
        return self.registry.get(key)


@pytest.fixture
def sink():
    recording = RecordingSink()
    set_sink(recording)
    return recording


@pytest.fixture
def windows_host(monkeypatch):
    monkeypatch.setattr(acpi_windows, "supported", lambda: True)


def read(fake, out_dir, **kwargs):
    return acpi_windows.WindowsAcpiDumper(firmware=fake).dump(out_dir, **kwargs)


def test_a_dump_writes_one_aml_per_table_and_a_dsdt(windows_host, sink, tmp_path):
    fake = FakeFirmware(
        tables={"DSDT": table("DSDT"), "FACP": table("FACP"), "APIC": table("APIC")},
        registry={"SSDT": table("SSDT"), "SSD1": table("SSDT")})

    dumped = read(fake, tmp_path)

    assert dumped.acpi_dir == tmp_path / "ACPI"
    assert sorted(p.name for p in dumped.acpi_dir.iterdir()) == [
        "APIC.aml", "DSDT.aml", "FACP.aml", "SSDT.aml", "SSDT1.aml"]
    assert dumped.acpi_dir.joinpath("DSDT.aml").read_bytes()[:4] == b"DSDT"
    assert dumped.tables == ("DSDT", "SSDT", "SSDT1", "FACP", "APIC")
    assert ("info", "5 ACPI tables read from Windows") in sink.logs


def test_ssdt_instances_come_from_the_registry_not_the_by_signature_call(
        windows_host, sink, tmp_path):
    """``GetSystemFirmwareTable`` returns only the first table with a name, and a
    machine with three SSDTs would lose two of them without the registry copies."""
    fake = FakeFirmware(
        tables={"DSDT": table("DSDT")},
        registry={"SSDT": table("SSDT", b"one"), "SSD1": table("SSDT", b"two"),
                  "SSD2": table("SSDT", b"three")},
        advertised=["SSDT", "SSDT"])

    dumped = read(fake, tmp_path)

    assert "SSDT" not in fake.fetched
    assert [stem for stem in dumped.tables if stem.startswith("SSDT")] == [
        "SSDT", "SSDT1", "SSDT2"]
    assert dumped.acpi_dir.joinpath("SSDT2.aml").read_bytes().endswith(b"three")


def test_the_registry_naming_matches_windows_ssdt_keys():
    """SSDT, SSD1 ... SSD9, SSDA ... SSDS -- the ninth through twenty-eighth keys
    are letters, and reading only the first ten would miss two thirds of them."""
    assert acpi_windows._SSDT_KEYS[0] == "SSDT"
    assert acpi_windows._SSDT_KEYS[9] == "SSD9"
    assert acpi_windows._SSDT_KEYS[10] == "SSDA"
    assert acpi_windows._SSDT_KEYS[-1] == "SSDS"
    assert len(acpi_windows._SSDT_KEYS) == 29


def test_a_machine_without_a_dsdt_is_a_typed_failure(windows_host, sink, tmp_path):
    fake = FakeFirmware(tables={"FACP": table("FACP")})

    with pytest.raises(TablesDumpFailed) as failure:
        read(fake, tmp_path)

    assert "did not return a DSDT" in failure.value.detail
    assert not (tmp_path / "ACPI").exists()


def test_a_malformed_table_is_skipped_rather_than_written(windows_host, sink, tmp_path):
    broken = b"FACP" + struct.pack("<I", 4096) + b"\x00" * 28  # length beyond the bytes
    fake = FakeFirmware(tables={"DSDT": table("DSDT"), "FACP": broken})

    dumped = read(fake, tmp_path)

    assert dumped.tables == ("DSDT",)
    assert not dumped.acpi_dir.joinpath("FACP.aml").exists()


def test_a_repeated_signature_is_fetched_once(windows_host, sink, tmp_path):
    fake = FakeFirmware(tables={"DSDT": table("DSDT"), "FACP": table("FACP")},
                        advertised=["FACP", "FACP"])

    dumped = read(fake, tmp_path)

    assert fake.fetched.count("FACP") == 1
    assert "FACP" in dumped.tables


def test_a_second_dump_replaces_its_own_tables_and_leaves_other_files(
        windows_host, sink, tmp_path):
    """Two DSDTs make the engine refuse the folder outright, so a re-read must not
    merge with the previous dump. Files the app did not write are left alone."""
    fake = FakeFirmware(tables={"DSDT": table("DSDT")})
    first = read(fake, tmp_path)
    first.acpi_dir.joinpath("OLDTB.aml").write_bytes(table("OLDTB"))
    first.acpi_dir.joinpath("notes.txt").write_text("mine", encoding="utf-8")

    second = read(fake, tmp_path)

    assert sorted(p.name for p in second.acpi_dir.iterdir()) == ["DSDT.aml", "notes.txt"]
    assert [p.name for p in second.acpi_dir.iterdir() if p.suffix == ".aml"] == [
        "DSDT.aml"]


def test_the_first_ssdt_still_arrives_when_the_registry_cannot_be_read(
        windows_host, sink, tmp_path):
    fake = FakeFirmware(tables={"DSDT": table("DSDT"), "SSDT": table("SSDT")})

    dumped = read(fake, tmp_path)

    assert "SSDT" in dumped.tables
    assert fake.registry_reads[:1] == ["SSDT"]


def test_a_cancelled_dump_writes_nothing(windows_host, sink, tmp_path):
    fake = FakeFirmware(tables={"DSDT": table("DSDT")})

    with pytest.raises(Cancelled):
        read(fake, tmp_path, is_cancelled=lambda: True)

    assert not (tmp_path / "ACPI").exists()
    assert fake.fetched == []


def test_the_reader_refuses_another_host(monkeypatch, sink, tmp_path):
    monkeypatch.setattr(acpi_windows, "supported", lambda: False)
    with pytest.raises(TablesUnsupported):
        acpi_windows.WindowsAcpiDumper(firmware=FakeFirmware()).dump(tmp_path)


@pytest.mark.skipif(sys.platform != "win32", reason="reads this host's firmware")
def test_a_non_elevated_process_gets_this_machines_dsdt(sink, tmp_path):
    """The point of the whole module: no administrator token, real tables.

    It runs on the release workflow's Windows leg, which is an ordinary user-mode
    process, so a regression to an elevated-only API fails the build.
    """
    dumped = acpi_windows.WindowsAcpiDumper().dump(tmp_path)

    dsdt = dumped.acpi_dir.joinpath("DSDT.aml").read_bytes()
    assert dsdt[:4] == b"DSDT"
    assert 36 <= len(dsdt) <= acpi_windows.MAX_TABLE_BYTES
