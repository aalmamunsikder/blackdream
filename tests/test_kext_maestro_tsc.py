"""The one observable behavior change in ``kext_maestro.modify_kexts``.

Upstream wrapped a chained ``.get(...).get("itlwm").get("WiFiConfig")`` in a bare
``except``, so for every plist that had no itlwm personality the AttributeError was
swallowed and the ``VoodooTSCSync`` / ``AmdTscSync`` ``IOCPUNumber`` rewrite below it
never executed -- a TSC-sync kext shipped with whatever stub value the kext author
left in it. Removing the itlwm branch (Wi-Fi profiles are now an explicit caller
step) also removes the swallow, which makes those branches live.

These tests pin that: they fail if the branches go dead again.
"""

from __future__ import annotations

import os
import plistlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ocengine.kext_maestro import KextMaestro  # noqa: E402

REPORT = {"CPU": {"Core Count": "8"}}


def _bundle(tmp_path, personality, cpu_number=99):
    kext = tmp_path / "{}.kext".format(personality)
    contents = kext / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    plist = contents / "Info.plist"
    plist.write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "com.test.{}".format(personality),
        "IOKitPersonalities": {
            personality: {"IOPropertyMatch": {"IOCPUNumber": cpu_number}},
        },
    }))
    return str(plist)


@pytest.fixture
def maestro():
    return KextMaestro()


@pytest.mark.parametrize("personality", ["VoodooTSCSync", "AmdTscSync"])
def test_the_tsc_branch_actually_runs_for_a_non_itlwm_plist(maestro, tmp_path, personality):
    plist = _bundle(tmp_path, personality)
    assert maestro.modify_kexts(plist, REPORT, "20.4.0") is True, (
        "the rewrite reported failure -- the branch is dead code again")
    written = plistlib.loads(open(plist, "rb").read())
    assert written["IOKitPersonalities"][personality]["IOPropertyMatch"]["IOCPUNumber"] == 7


@pytest.mark.parametrize("version", ["21.0.0", "22.3.0", "25.99.99"])
def test_macos_12_and_newer_pin_the_cpu_number_to_zero(maestro, tmp_path, version):
    plist = _bundle(tmp_path, "VoodooTSCSync")
    assert maestro.modify_kexts(plist, REPORT, version) is True
    written = plistlib.loads(open(plist, "rb").read())
    assert written["IOKitPersonalities"]["VoodooTSCSync"]["IOPropertyMatch"]["IOCPUNumber"] == 0


def test_an_unrelated_plist_is_left_alone(maestro, tmp_path):
    kext = tmp_path / "Whatever.kext"
    contents = kext / "Contents"
    contents.mkdir(parents=True)
    plist = contents / "Info.plist"
    original = plistlib.dumps({"IOKitPersonalities": {"Unrelated": {"x": 1}}})
    plist.write_bytes(original)

    assert maestro.modify_kexts(str(plist), REPORT, "20.4.0") is False
    assert plist.read_bytes() == original


def test_a_broken_plist_is_reported_not_swallowed(maestro, tmp_path, capsys):
    """The old code hid this behind ``except: pass``-equivalent behaviour.

    It still must not abort a build -- ``load_kexts`` ignores the return value --
    but the failure has to reach the sink, and nothing may reach a terminal.
    """
    plist = tmp_path / "Info.plist"
    plist.write_bytes(b"not a plist at all")

    assert maestro.modify_kexts(str(plist), REPORT, "20.4.0") is False
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_a_missing_ioproperty_match_does_not_raise(maestro, tmp_path):
    """Upstream indexed ``["IOPropertyMatch"]`` directly: a personality without it
    would have raised inside the swallow. It must still raise nothing now."""
    kext = tmp_path / "VoodooTSCSync.kext"
    contents = kext / "Contents"
    contents.mkdir(parents=True)
    plist = contents / "Info.plist"
    plist.write_bytes(plistlib.dumps({"IOKitPersonalities": {"VoodooTSCSync": {}}}))

    assert maestro.modify_kexts(str(plist), REPORT, "20.4.0") is False
