"""Regression: macserial is provisioned and resolved without touching the package dir.

Closes the defect where ``gathering_files`` moved a binary *whose name came from the
remote archive* into ``src/ocengine/`` (a directory on Python's import path), chmod-ed
it ``+x`` and ``smbios`` later executed it -- letting a download shadow a module or run
tampered bytes. These tests pin the replacement contract:

* construction performs no network I/O and writes nothing into the package directory;
* a candidate inside an import-path directory is refused *even when it exists and its
  bytes match the pin*;
* a tampered binary (right name, wrong bytes) raises a typed error and is never executed;
* resolution honours ``BLACKDREAM_TOOLS_DIR`` ahead of the per-user tools directory;
* ``generate_smbios`` is byte-for-byte unchanged for a stubbed ``macserial`` run;

plus the install step (verified member -> tools dir, unauthenticated bytes never
written or chmod-ed) and the Hardware-Sniffer destination fix.

The real ``macserial`` binaries are ~1 MB each and are not fixtures; the pin tables are
plain data, so the tests re-point them at small synthetic blobs to exercise the exact
name/digest logic that runs against real bytes.
"""

import hashlib
import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
PKG = SRC / "ocengine"

from ocengine import gathering_files, paths, runtime, run, smbios
from ocengine.gathering_files import (
    MacserialUnsupportedPlatform,
    MacserialUnavailable,
    MacserialVerificationFailed,
    gatheringFiles,
)

# Synthetic "binaries". Only their digests matter; the code never inspects the payload.
GOOD_LINUX = b"\x7fELF synthetic macserial.linux payload for tests"
GOOD_SHA = hashlib.sha256(GOOD_LINUX).hexdigest()
TAMPERED = b"\x7fELF trojaned payload that must never run"

# Resolution only looks for the current host's names, so a test that plants a
# binary must plant the one this host would look for.
HOST_PLATFORM = gathering_files.MACSERIAL_PLATFORM_BY_OS[gathering_files.os_name]
HOST_NAME = gathering_files.MACSERIAL_NAMES_BY_OS[gathering_files.os_name][0]


@pytest.fixture(autouse=True)
def _quiet_sink():
    runtime.set_sink(runtime.NullSink())


@pytest.fixture(autouse=True)
def _isolated_tools(tmp_path, monkeypatch):
    """Tests must never resolve a real tool from the checkout or the user profile.

    A developer machine accumulates the real binaries in both ``tools/`` and
    ``~/.local/share/blackdream/tools``; once either exists, a test that pins
    synthetic digests either fails the digest check or silently passes against
    bytes it did not create. Only the fixture's own directories are visible here.
    """
    root = tmp_path / "checkout"
    monkeypatch.setattr(paths, "_SRC_ROOT", root / "src" / "ocengine")
    isolated = paths.EnginePaths(cache_dir=root / "cache",
                                 tools_dir=root / "user-tools")
    monkeypatch.setattr(paths, "current", lambda: isolated)


def _pin_blobs(monkeypatch):
    """Re-point the macserial pin tables at the synthetic blobs (they are data)."""
    other = "0" * 64
    monkeypatch.setattr(gathering_files, "MACSERIAL_PINS_BY_NAME", {
        ("linux", "macserial.linux"): GOOD_SHA,
        ("linux", "macserial"): other,
        ("darwin", "macserial"): other,
        ("win32", "macserial.exe"): other,
        (HOST_PLATFORM, HOST_NAME): GOOD_SHA,
    })
    monkeypatch.setattr(gathering_files, "MACSERIAL_MEMBER_SHA", {
        HOST_NAME: GOOD_SHA,
        "macserial.linux": GOOD_SHA,
        "macserial": other,
        "macserial.exe": other,
    })


def test_construction_does_not_allocate_a_scratch_directory(monkeypatch):
    """A gatherer is constructed by SMBIOS and ConfigProdigy, which never gather.

    Allocating the scratch tree in ``__init__`` left one empty /tmp/ocs_* per
    report even when no download happened.
    """

    def unexpected(self):
        raise AssertionError("scratch directory allocated at construction")

    monkeypatch.setattr(gathering_files.utils.Utils, "get_temporary_dir", unexpected)

    gatheringFiles()


# (a) ---------------------------------------------------------------------
def test_construction_is_side_effect_free_and_leaves_the_package_dir_clean(monkeypatch):
    """Building the gatherer/SMBIOS objects must not touch the network or the package."""

    def _no_network(*args, **kwargs):
        raise AssertionError("network I/O attempted during construction")

    monkeypatch.setattr("ocengine.resource_fetcher.urlopen", _no_network)

    before = set(os.listdir(PKG))
    gatheringFiles()
    smbios.SMBIOS()
    after = set(os.listdir(PKG))

    assert before == after, "construction created or removed a package-dir entry"
    assert not any(name.startswith("macserial") for name in after)


# (b) ---------------------------------------------------------------------
def test_import_path_candidate_is_refused_even_if_it_exists_and_matches(monkeypatch, tmp_path):
    """A valid, pin-matching macserial that sits on the import path is never returned."""
    _pin_blobs(monkeypatch)
    g = gatheringFiles()

    shadow = tmp_path / "shadow_pkg"
    shadow.mkdir()
    (shadow / "macserial.linux").write_bytes(GOOD_LINUX)

    # Make the directory an import path (exactly like src/ocengine) and the tools dir.
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(shadow))
    monkeypatch.setattr(sys, "path", [str(shadow)] + list(sys.path))

    assert paths.is_on_import_path(str(shadow / "macserial.linux")) is True
    # Refused despite existing and matching its pin.
    assert g.find_macserial() is None


def test_the_real_package_directory_is_never_a_resolution_source(monkeypatch):
    """src/ocengine is on the import path, so a stray macserial there is never run."""
    _pin_blobs(monkeypatch)
    g = gatheringFiles()
    monkeypatch.delenv("BLACKDREAM_TOOLS_DIR", raising=False)

    assert paths.is_on_import_path(str(PKG / "macserial")) is True
    resolved = g.find_macserial()
    assert resolved is None or PKG.resolve() not in Path(resolved).resolve().parents


# (c) ---------------------------------------------------------------------
def test_tampered_binary_is_refused_and_never_executed(monkeypatch, tmp_path):
    """Right name, wrong bytes -> typed error, and Run().run is never invoked."""
    _pin_blobs(monkeypatch)
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / HOST_NAME).write_bytes(TAMPERED)
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(tools))

    executed = []

    def _fake_run(self, command_list, *args, **kwargs):
        executed.append(command_list)
        return ("", "", 0)

    monkeypatch.setattr(run.Run, "run", _fake_run, raising=False)

    s = smbios.SMBIOS()
    with pytest.raises(MacserialVerificationFailed) as caught:
        s.generate_smbios("MacBookPro16,1")

    assert caught.value.code == "engine.macserial_verification_failed"
    assert executed == [], "a pin-mismatched macserial was executed"


# (d) ---------------------------------------------------------------------
def test_resolution_honours_blackdream_tools_dir_first(monkeypatch, tmp_path):
    """BLACKDREAM_TOOLS_DIR wins over the per-user directory; both work alone."""
    _pin_blobs(monkeypatch)
    override = tmp_path / "override"
    user = tmp_path / "user"
    override.mkdir()
    user.mkdir()
    (override / HOST_NAME).write_bytes(GOOD_LINUX)
    (user / HOST_NAME).write_bytes(GOOD_LINUX)

    monkeypatch.setattr(
        paths, "current",
        lambda: paths.EnginePaths(cache_dir=tmp_path / "cache", tools_dir=user),
    )
    g = gatheringFiles()

    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(override))
    chosen = g.find_macserial()
    assert Path(chosen).resolve() == (override / HOST_NAME).resolve()

    monkeypatch.delenv("BLACKDREAM_TOOLS_DIR")
    chosen = g.find_macserial()
    assert Path(chosen).resolve() == (user / HOST_NAME).resolve()


# (e) ---------------------------------------------------------------------
def test_generate_smbios_is_unchanged_for_a_stubbed_macserial_run(monkeypatch):
    s = smbios.SMBIOS()
    monkeypatch.setattr(s, "check_macserial", lambda *a, **k: "/tools/macserial")
    monkeypatch.setattr(smbios.random, "randint", lambda _lo, _hi: 0xAB)

    import uuid as _uuid
    monkeypatch.setattr(smbios.uuid, "uuid4", lambda: _uuid.UUID("11111111-2222-3333-4444-555555555555"))

    canned = ("C02SERIAL1234 | MIDFIELD | C02MLB9876543\n", "", 0)
    monkeypatch.setattr(s, "run", lambda *a, **k: canned)
    ok = s.generate_smbios("MacBookPro16,1")

    # Same slicing the pre-fix code used: serial[0] -> SystemSerialNumber,
    # serial[-1] -> MLB, model name echoed, deterministic ROM/UUID.
    assert ok == {
        "MLB": "C02MLB9876543",
        "ROM": "ABABABABABAB",
        "SystemProductName": "MacBookPro16,1",
        "SystemSerialNumber": "C02SERIAL1234",
        "SystemUUID": "11111111-2222-3333-4444-555555555555",
    }

    # Failure path keeps the documented placeholder serials.
    monkeypatch.setattr(s, "run", lambda *a, **k: ("", "boom", 1))
    fail = s.generate_smbios("MacBookPro16,1")
    assert fail["MLB"] == "A" + "0" * 15 + "Z"
    assert fail["SystemSerialNumber"] == "A" + "0" * 10 + "9"
    assert fail["SystemProductName"] == "MacBookPro16,1"


# -- install step: verified member -> tools dir, never the package ----------
def test_install_writes_a_verified_member_to_tools_dir_and_marks_executable(monkeypatch, tmp_path):
    _pin_blobs(monkeypatch)
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(tools))

    extract = tmp_path / "OpenCorePkg" / "Utilities" / "macserial"
    extract.mkdir(parents=True)
    (extract / "macserial.linux").write_bytes(GOOD_LINUX)

    g = gatheringFiles()
    target = g._install_macserial_member(str(extract / "macserial.linux"), "macserial.linux")

    assert target is not None
    assert Path(target).resolve() == (tools / "macserial.linux").resolve()
    assert (tools / "macserial.linux").read_bytes() == GOOD_LINUX
    if os.name != "nt":
        assert os.stat(target).st_mode & 0o111, "verified member was not made executable"
    assert not (PKG / "macserial.linux").exists(), "installed into the package directory"


def test_install_skips_an_unpinned_remote_named_member(monkeypatch, tmp_path):
    _pin_blobs(monkeypatch)
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(tools))

    extract = tmp_path / "OpenCorePkg" / "Utilities" / "macserial"
    extract.mkdir(parents=True)
    sneaky = extract / "macserial.malware"  # name not in the pin table
    sneaky.write_bytes(GOOD_LINUX)

    g = gatheringFiles()
    assert g._install_macserial_member(str(sneaky), "macserial.malware") is None
    assert list(tools.iterdir()) == [], "an unauthenticated remote-named binary was installed"


def test_install_refuses_a_tampered_pinned_member(monkeypatch, tmp_path):
    _pin_blobs(monkeypatch)
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(tools))

    extract = tmp_path / "OpenCorePkg" / "Utilities" / "macserial"
    extract.mkdir(parents=True)
    (extract / "macserial.linux").write_bytes(TAMPERED)

    g = gatheringFiles()
    with pytest.raises(MacserialVerificationFailed):
        g._install_macserial_member(str(extract / "macserial.linux"), "macserial.linux")
    assert list(tools.iterdir()) == [], "a pin-mismatched member was written to the tools dir"


def test_bootloader_install_only_considers_this_hosts_macserial_builds(monkeypatch, tmp_path):
    """A rebuilt foreign member must not gate this host's build.

    OpenCorePkg 1.0.9 (tag 25d02c8) ships a macserial.exe whose bytes differ from
    the previous pin while the Linux members are unchanged. Installing every
    member made a Linux build depend on that Windows pin; only the builds this
    system can run may be considered.
    """
    monkeypatch.setattr(gathering_files, "os_name", "Linux")
    g = gatheringFiles()
    g.temporary_dir = str(tmp_path / "tmp")
    g.ock_files_dir = str(tmp_path / "cache")
    members = tmp_path / "tmp" / "OpenCorePkg" / "Utilities" / "macserial"
    members.mkdir(parents=True)
    for name in ("macserial", "macserial.linux", "macserial.exe"):
        (members / name).write_bytes(GOOD_LINUX)

    installed = []
    monkeypatch.setattr(g, "_install_macserial_member",
                        lambda source, name: installed.append(name))

    assert g.move_bootloader_kexts_to_product_directory("OpenCorePkg") is True
    assert sorted(installed) == ["macserial", "macserial.linux"]


# -- platform boundary ------------------------------------------------------
def test_unknown_platform_raises_typed_error(monkeypatch):
    monkeypatch.setattr(gathering_files, "os_name", "Haiku")
    g = gatheringFiles()
    with pytest.raises(MacserialUnsupportedPlatform) as caught:
        g.find_macserial()
    assert caught.value.code == "engine.macserial_unsupported_platform"


def test_missing_macserial_without_download_raises_unavailable(monkeypatch, tmp_path):
    _pin_blobs(monkeypatch)
    tools = tmp_path / "empty-tools"
    tools.mkdir()
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(tools))
    s = smbios.SMBIOS()
    with pytest.raises(MacserialUnavailable) as caught:
        s.check_macserial(try_downloading=False)
    assert caught.value.code == "engine.macserial_unavailable"


# -- Hardware-Sniffer destination ------------------------------------------
def test_hardware_sniffer_installs_to_tools_dir_not_package(monkeypatch, tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(tools))
    monkeypatch.setattr(gathering_files, "os_name", "Windows")

    g = gatheringFiles()
    published = "a" * 64
    monkeypatch.setattr(g, "_load_download_history", lambda: {})
    monkeypatch.setattr(g, "_save_download_history", lambda *a, **k: None)
    monkeypatch.setattr(g.github, "get_latest_release", lambda *a, **k: {
        "assets": [{
            "product_name": "Hardware-Sniffer-CLI",
            "id": 12345,
            "url": "https://github.example/Hardware-Sniffer-CLI.exe",
            "sha256": published,
        }]
    })

    captured = {}

    def _fake_download(url, destination, sha256_hash=None, product=None):
        captured["destination"] = destination
        Path(destination).write_bytes(b"MZ synthetic sniffer")
        return True

    monkeypatch.setattr(g.fetcher, "download_and_save_file", _fake_download)

    result = g.gather_hardware_sniffer()

    assert Path(result).resolve() == (tools / "Hardware-Sniffer-CLI.exe").resolve()
    assert captured["destination"].startswith(os.path.realpath(str(tools)))
    assert PKG.resolve() not in Path(result).resolve().parents, "sniffer landed in the package dir"
