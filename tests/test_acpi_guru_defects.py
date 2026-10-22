"""Regressions for the two latent acpi_guru defects.

1. ``fix_system_clock_awac`` called ``self.hexy(...)``, a helper that lived in
   the pinned SSDTTime original this file was vendored from but was dropped in
   the copy. Every real board with an RTC ``_CRS`` IO gap therefore died inside
   the surrounding bare ``except``: the length rewrite and the ``_CRS to XCRS``
   rename vanished and the build shipped an SSDT-RTCAWAC that does not fix the
   clock - the one bug the patch exists to fix.

2. ``get_lpc_name()`` callers all use the default ``log=False``, so "no
   LPC(B)/SBRG found" was invisible, and a root-level EC device made the
   parent-join return ``""`` as if it were a found name - which fake_ec then
   embedded into ``External (, DeviceObj)``. Missing/empty LPC must now be
   distinguishable and handled at every call site.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ocengine import runtime
from ocengine.acpi_guru import ACPIGuru


@pytest.fixture
def sink():
    previous = runtime.current_sink()
    captured = runtime.RecordingSink()
    runtime.set_sink(captured)
    yield captured
    runtime.set_sink(previous)


@pytest.fixture
def guru(sink):
    return ACPIGuru()


# --------------------------------------------------------------------------
# Defect 1: self.hexy
# --------------------------------------------------------------------------

# The reference is the pinned SSDTTime commit 44aadf0 body, verbatim.
def ssdttime_reference(integer, pad_to=0):
    return "0x" + hex(integer)[2:].upper().rjust(pad_to, "0")


def test_hexy_matches_the_pinned_ssdttime_helper_it_was_copied_without(guru):
    assert hasattr(ACPIGuru, "hexy"), "self.hexy is referenced at fix_system_clock_awac"
    for value, pad in ((0x64, 2), (0x02, 2), (0x04, 2), (0x1234, 4), (0x70, 4), (0, 0), (255, 2)):
        assert guru.hexy(value, pad_to=pad) == ssdttime_reference(value, pad)
    # The exact tokens fix_system_clock_awac replaces inside decompiled _CRS lines.
    assert guru.hexy(0x02, pad_to=2) == "0x02"
    assert guru.hexy(0x04, pad_to=2) == "0x04"


# A decompiled RTC _CRS with the classic AMI gap: IO#1 is 0x0070 len 0x02,
# IO#2 starts at 0x0074 - the previous length must grow to 0x04.
CRS_SCOPE = [
    "                Name (_CRS, ResourceTemplate ()  // _CRS: Current Resource Settings",
    "                {",
    "                    IO (Decode16,",
    "                        0x0070,             // Range Minimum",
    "                        0x0070,             // Range Maximum",
    "                        0x01,               // Alignment",
    "                        0x02,               // Length",
    "                        )",
    "                    IO (Decode16,",
    "                        0x0074,             // Range Minimum",
    "                        0x0074,             // Range Maximum",
    "                        0x01,               // Alignment",
    "                        0x04,               // Length",
    "                        )",
    "                }",
    "            )",
]


def _wire_awac_stubs(guru, monkeypatch, writes):
    rtc = {
        "valid": True, "device": ["_SB.PCI0.LPCB.RTC"], "dev_name": "RTC",
        "dev_hid": "PNP0B00", "has_var": False, "sta": False, "crs": False,
        "patches": [],
    }

    def fake_get_sta_var(var="STAS", dev_hid="ACPI000E", dev_name="AWAC", **kwargs):
        if dev_hid == "ACPI000E":
            return {"valid": False, "patches": [], "dev_name": "AWAC"}
        return dict(rtc, patches=list(rtc["patches"]))

    monkeypatch.setattr(guru, "get_sta_var", fake_get_sta_var)
    monkeypatch.setattr(guru.acpi, "get_method_paths", lambda obj, table=None: [["_SB.PCI0.LPCB.RTC._CRS", 0, "Name"]])
    monkeypatch.setattr(guru.acpi, "get_scope", lambda starting_index=0, add_hex=False, strip_comments=False, table=None: list(CRS_SCOPE))
    monkeypatch.setattr(guru.acpi, "find_next_hex", lambda index=0, table=None: (0, 42))
    monkeypatch.setattr(guru.acpi, "get_shortest_unique_pad", lambda hex_str, index, instance=0, table=None: ("", ""))
    monkeypatch.setattr(guru, "write_ssdt", lambda name, content, compile=True: writes.append((name, content)) or True)


def test_awac_range_rewrite_reaches_the_crs_rename(guru, monkeypatch, sink):
    """The hexy branch now executes: adjusted length lands in the SSDT and the
    _CRS to XCRS rename patch is emitted."""
    writes = []
    _wire_awac_stubs(guru, monkeypatch, writes)

    result = guru.fix_system_clock_awac()

    assert result is not None
    renames = [p for p in result["Patch"] if p["Comment"] == "RTC _CRS to XCRS Rename"]
    assert renames == [{"Comment": "RTC _CRS to XCRS Rename", "Find": "5F435253", "Replace": "58435253"}]
    ssdt = writes[0][1]
    assert "Name (BUFX," in ssdt
    assert "0x04,               // Length" in ssdt, "IO#1 length was not rewritten to close the gap"
    assert "0x02,               // Length" not in ssdt
    assert not sink.messages_at_or_above("warning"), "the rewrite must not take its abandon path"


def test_the_branch_would_have_raised_attributeerror_before(guru, monkeypatch, sink):
    """Pin the pre-fix state: with the helper absent (as the vendored copy had
    it), self.hexy raised AttributeError, the bare except swallowed it, and the
    build silently shipped no range patch at all."""
    writes = []
    _wire_awac_stubs(guru, monkeypatch, writes)

    monkeypatch.delattr(ACPIGuru, "hexy")
    with pytest.raises(AttributeError):
        guru.hexy(0x64, pad_to=2)  # exactly what the old line 1157/1158 hit

    result = guru.fix_system_clock_awac()

    assert result is None, "without hexy the range is abandoned and the whole RTCAWAC output is dropped"
    assert writes == [], "no SSDT may be written from the abandoned branch"
    assert any("range patch abandoned" in m for m in sink.messages_at_or_above("warning"))


# --------------------------------------------------------------------------
# Defect 2: get_lpc_name swallowing a missing LPC
# --------------------------------------------------------------------------

def test_get_lpc_name_returns_none_and_is_never_silent(guru, monkeypatch, sink):
    monkeypatch.setattr(guru.acpi, "acpi_tables", {})

    assert guru.get_lpc_name() is None  # default log=False still distinguishable
    warnings = sink.messages_at_or_above("warning")
    assert any("no LPC(B)/SBRG" in m for m in warnings), "log=False must not swallow the failure"


def test_root_ec_device_yields_not_found_rather_than_empty_name(guru, monkeypatch, sink):
    """An EC path with no parent used to return "" as a found name; callers then
    embedded it into External([[LPCName]]). It must read as "not found"."""
    monkeypatch.setattr(guru.acpi, "acpi_tables", {"DSDT": {"lines": {}, "paths": []}})
    monkeypatch.setattr(guru.acpi, "get_device_paths_with_hid", lambda hid="ACPI000E", table=None: [("EC0", 1)])
    monkeypatch.setattr(guru.acpi, "get_device_paths", lambda obj="HPET", table=None: [])
    monkeypatch.setattr(guru.acpi, "get_path_of_type", lambda obj_type="Name", obj="_ADR", table=None: [])

    assert guru.get_lpc_name() is None


def test_fake_ec_aborts_visibly_and_never_builds_empty_lpc_scope(guru, monkeypatch, sink):
    """Root-level EC => joined parent is "" => the old `is None` checks passed
    it straight into the SSDT. It must abort with a warning and no SSDT."""
    writes = []
    guru.hardware_report = {"Motherboard": {"Platform": "Desktop", "Name": "TEST", "Chipset": "CM246"}}
    monkeypatch.setattr(guru.acpi, "acpi_tables", {"DSDT": {"lines": {}, "paths": []}})
    monkeypatch.setattr(guru.acpi, "get_device_paths_with_hid", lambda hid="ACPI000E", table=None: [("EC0", 1)])
    monkeypatch.setattr(guru.acpi, "get_scope", lambda starting_index=0, add_hex=False, strip_comments=False, table=None:
                        ["Name (_HID, EisaId (\"PNP0C09\"))", "Name (_CRS, ResourceTemplate () {", "Name (_GPE, 0x01)"])
    monkeypatch.setattr(guru.acpi, "get_device_paths", lambda obj="HPET", table=None: [])
    monkeypatch.setattr(guru.acpi, "get_path_of_type", lambda obj_type="Name", obj="_ADR", table=None: [])
    monkeypatch.setattr(guru, "get_sta_var", lambda **kwargs: {"valid": True, "patches": [], "sta": None, "dev_name": "EC0"})
    monkeypatch.setattr(guru, "write_ssdt", lambda name, content, compile=True: writes.append((name, content)) or True)

    assert guru.fake_embedded_controller() is None
    assert writes == [], "SSDT-EC must not be compiled with an empty LPC scope"
    assert not any("External (," in content for _, content in writes)
    assert any("fake_embedded_controller" in m for m in sink.messages_at_or_above("warning"))


def test_fake_ec_falsy_lpc_name_is_handled_at_the_call_site(guru, monkeypatch, sink):
    """Even if discovery ever returns "" again, the caller treats falsy as
    missing: abort, warn, emit nothing."""
    writes = []
    guru.hardware_report = {"Motherboard": {"Platform": "Desktop", "Name": "TEST", "Chipset": "CM246"}}
    monkeypatch.setattr(guru.acpi, "acpi_tables", {})
    monkeypatch.setattr(guru, "get_lpc_name", lambda **kwargs: "")
    monkeypatch.setattr(guru, "write_ssdt", lambda name, content, compile=True: writes.append((name, content)) or True)

    assert guru.fake_embedded_controller() is None
    assert writes == []


def test_awac_missing_lpc_aborts_visibly(guru, monkeypatch, sink):
    """A needed RTC fake with no LPC host used to return with zero output events."""
    writes = []
    monkeypatch.setattr(guru, "get_sta_var", lambda var="STAS", dev_hid="ACPI000E", dev_name="AWAC", **kwargs: {"valid": False, "patches": []})
    monkeypatch.setattr(guru.acpi, "acpi_tables", {})
    monkeypatch.setattr(guru, "write_ssdt", lambda name, content, compile=True: writes.append((name, content)) or True)

    assert guru.fix_system_clock_awac() is None
    assert writes == []
    assert any("fix_system_clock_awac" in m for m in sink.messages_at_or_above("warning"))
