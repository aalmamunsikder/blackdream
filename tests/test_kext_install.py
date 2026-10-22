"""Kext installation must fail closed.

Upstream copied checked kexts into the EFI under a broad ``except: continue``:
a selected kext with no cached bundle, or a copy that failed, simply vanished
from the build while config.plist was generated from whatever remained. These
tests pin the replacement contract: every kext checked when installation starts
is either copied or the build raises ``KextInstallIncomplete``.
"""

from __future__ import annotations

import os
import plistlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ocengine.datasets import kext_data  # noqa: E402
from ocengine.kext_maestro import KextInstallIncomplete, KextMaestro  # noqa: E402

DARWIN_25 = "25.99.99"


def _bundle(root, name, identifier=None, inside=None):
    base = root if inside is None else inside
    kext = base / (name + ".kext")
    contents = kext / "Contents"
    contents.mkdir(parents=True)
    executable = contents / "MacOS" / name
    executable.parent.mkdir()
    executable.write_bytes(b"")
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": identifier or "com.test.{}".format(name.lower()),
        "CFBundleExecutable": name,
        "CFBundleVersion": "1.0.0",
    }))
    return kext


def _only(maestro, *names):
    for kext in maestro.kexts:
        kext.checked = kext.name in names


def test_checked_bundle_is_copied(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    _bundle(cache, "Lilu")

    maestro = KextMaestro()
    monkeypatch.setattr(maestro, "ock_files_dir", str(cache))
    _only(maestro, "Lilu")

    kexts_directory = tmp_path / "EFI" / "OC" / "Kexts"
    maestro.install_kexts_to_efi(DARWIN_25, str(kexts_directory))

    assert (kexts_directory / "Lilu.kext" / "Contents" / "Info.plist").is_file()


def test_checked_bundle_without_a_cache_entry_fails_the_build(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()

    maestro = KextMaestro()
    monkeypatch.setattr(maestro, "ock_files_dir", str(cache))
    _only(maestro, "Lilu")

    with pytest.raises(KextInstallIncomplete) as raised:
        maestro.install_kexts_to_efi(DARWIN_25, str(tmp_path / "EFI" / "OC" / "Kexts"))

    assert "Lilu" in raised.value.detail
    assert not (tmp_path / "EFI" / "OC" / "Kexts" / "Lilu.kext").exists()


def test_unchecked_bundle_is_ignored(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    _bundle(cache, "Lilu")
    _bundle(cache, "RestrictEvents")

    maestro = KextMaestro()
    monkeypatch.setattr(maestro, "ock_files_dir", str(cache))
    _only(maestro, "Lilu")

    kexts_directory = tmp_path / "EFI" / "OC" / "Kexts"
    maestro.install_kexts_to_efi(DARWIN_25, str(kexts_directory))

    assert (kexts_directory / "Lilu.kext").is_dir()
    assert not (kexts_directory / "RestrictEvents.kext").exists()


def test_build_time_state_wins_over_planning_time(monkeypatch, tmp_path):
    """BATP re-probes the DSDT during the build and may uncheck ECEnabler.

    The installer must honour that later state instead of demanding a bundle for
    a kext the build deliberately deselected.
    """
    cache = tmp_path / "cache"
    _bundle(cache, "Lilu")

    maestro = KextMaestro()
    monkeypatch.setattr(maestro, "ock_files_dir", str(cache))
    _only(maestro, "Lilu", "ECEnabler")
    maestro.kexts[kext_data.kext_index_by_name["ECEnabler"]].checked = False

    kexts_directory = tmp_path / "EFI" / "OC" / "Kexts"
    maestro.install_kexts_to_efi(DARWIN_25, str(kexts_directory))

    assert (kexts_directory / "Lilu.kext").is_dir()


def test_plugin_under_an_unchecked_parent_is_not_silently_installed(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    product = cache / "IntelBluetoothFirmware"
    parent = _bundle(product, "IntelBluetoothFirmware")
    _bundle(parent / "Contents" / "PlugIns", "IntelBTPatcher")

    maestro = KextMaestro()
    monkeypatch.setattr(maestro, "ock_files_dir", str(cache))
    _only(maestro, "IntelBTPatcher")

    with pytest.raises(KextInstallIncomplete) as raised:
        maestro.install_kexts_to_efi(DARWIN_25, str(tmp_path / "EFI" / "OC" / "Kexts"))

    assert "IntelBTPatcher" in raised.value.detail


def test_unreadable_bundle_is_not_dropped_from_config(monkeypatch, tmp_path):
    kexts_directory = tmp_path / "EFI" / "OC" / "Kexts"
    broken = kexts_directory / "Broken.kext" / "Contents"
    broken.mkdir(parents=True)

    maestro = KextMaestro()
    with pytest.raises(KextInstallIncomplete) as raised:
        maestro.load_kexts({"CPU": {"Core Count": "8"}}, DARWIN_25, str(kexts_directory))

    assert "Broken.kext" in raised.value.detail


def test_readable_bundles_reach_kernel_add(monkeypatch, tmp_path):
    kexts_directory = tmp_path / "EFI" / "OC" / "Kexts"
    _bundle(kexts_directory, "Lilu")

    maestro = KextMaestro()
    entries = maestro.load_kexts({"CPU": {"Core Count": "8"}}, DARWIN_25, str(kexts_directory))

    assert [entry["BundlePath"] for entry in entries] == ["Lilu.kext"]
    assert entries[0]["Enabled"] is True
    assert entries[0]["PlistPath"] == "Contents/Info.plist"
