"""Regression: the DSDT pre-patch path must be reachable.

Upstream compared ``_table_signature()`` (which returns ``bytes``) to the ``str``
``"DSDT"``, so that comparison never matched, ``dsdt_list`` was always empty, the
DSDT was never disassembled for pre-patch checks, and ``dsdt_patches`` stayed empty
even when the report folder held a real DSDT. Fixed in ``acpi_guru.py``; this test is
what proves the branch executes rather than being silently skipped.
"""

import struct
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ocengine import runtime
from ocengine.acpi_guru import ACPIGuru


def write_table(directory: Path, name: str, signature: bytes) -> Path:
    header = signature + struct.pack("<I", 36 + 32) + bytes(32)
    path = directory / name
    path.write_bytes(header)
    return path


@pytest.fixture
def acpi_dir(tmp_path):
    folder = tmp_path / "ACPI"
    folder.mkdir()
    write_table(folder, "DSDT.aml", b"DSDT")
    write_table(folder, "SSDT-1.aml", b"SSDT")
    write_table(folder, "APIC.aml", b"APIC")
    return folder


def test_signature_is_bytes_so_only_a_byte_literal_can_match(tmp_path):
    from ocengine.dsdt import DSDT

    probe = DSDT()
    path = write_table(tmp_path, "sig_probe.aml", b"DSDT")
    assert probe._table_signature(str(path)) == b"DSDT"
    assert probe._table_signature(str(path)) != "DSDT"


def test_folder_with_a_dsdt_reaches_the_disassembly_probe(acpi_dir, monkeypatch):
    runtime.set_sink(runtime.NullSink())
    guru = ACPIGuru()

    seen = []

    def fake_load(table_path, *args, **kwargs):
        seen.append(Path(table_path).name)
        # load() returns (disassembled_tables, failed_list). Both must be populated
        # the way a successful run would leave them or the caller takes its
        # failure branch.
        return ({"DefinitionBlock": ""}, [])

    monkeypatch.setattr(guru.acpi, "load", fake_load)

    guru.read_acpi_tables(str(acpi_dir))

    assert "DSDT.aml" in seen, "DSDT was never probed -- the pre-patch path is dead again"


def test_multiple_dsdts_are_rejected(acpi_dir, monkeypatch):
    runtime.set_sink(runtime.NullSink())
    write_table(acpi_dir, "DSDT-2.aml", b"DSDT")
    guru = ACPIGuru()
    monkeypatch.setattr(guru.acpi, "load", lambda *a, **k: ({"DefinitionBlock": ""}, []))

    from ocengine.fatal import EngineError

    with pytest.raises(EngineError) as caught:
        guru.read_acpi_tables(str(acpi_dir))

    assert getattr(caught.value, "code", None) == "acpi.multiple_dsdts"
