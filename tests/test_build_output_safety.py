"""Build output safety: only BlackDream-owned folders are replaced.

The build used to ``rmtree`` the user's chosen output unconditionally, so a path
pointing at a mounted ESP's EFI folder would delete a working bootloader. These
tests pin the marker rule and the path-form-aware pruning that keeps nested
drivers, tools and picker variants on Windows, where the filesystem listing uses
backslashes and config.plist uses forward slashes.
"""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import blackdream.core.pipeline as pipeline  # noqa: E402
from blackdream.core.pipeline import (  # noqa: E402
    OUTPUT_MARKER,
    BuildNotReady,
    BuildVerificationFailed,
    Pipeline,
)


def test_a_foreign_non_empty_folder_is_refused_and_left_intact(tmp_path):
    target = tmp_path / "EFI"
    (target / "EFI" / "OC").mkdir(parents=True)
    boss = target / "EFI" / "OC" / "BOOTx64.efi"
    boss.write_bytes(b"someone else's bootloader")

    with pytest.raises(BuildNotReady) as raised:
        Pipeline._create_output_dir(target)

    assert "not created by BlackDream" in raised.value.detail
    assert boss.read_bytes() == b"someone else's bootloader"


def test_an_existing_empty_folder_is_adopted(tmp_path):
    target = tmp_path / "EFI"
    target.mkdir()

    Pipeline._create_output_dir(target)

    assert (target / OUTPUT_MARKER).is_file()


def test_a_previous_blackdream_build_is_replaced(tmp_path):
    target = tmp_path / "EFI"
    Pipeline._create_output_dir(target)
    (target / "stale.txt").write_text("old")

    Pipeline._create_output_dir(target)

    assert not (target / "stale.txt").exists()
    assert (target / OUTPUT_MARKER).is_file()


def _fake_listing(entries):
    def listing(directory, extension_filter=None, type_filter=None):
        return entries.get(Path(directory).name, [])
    return listing


def test_prune_keeps_config_references_written_with_forward_slashes(tmp_path, monkeypatch):
    result = tmp_path / "EFI"
    oc = result / "EFI" / "OC"
    drivers = oc / "Drivers"
    tools = oc / "Tools"
    image = oc / "Resources" / "Image"
    audio = oc / "Resources" / "Audio"
    for directory in (drivers, tools, image, audio):
        directory.mkdir(parents=True)

    # A Windows listing spells nested paths with backslashes; a literal name on
    # this filesystem lets the comparison be exercised without Windows.
    (drivers / "OpenRuntime.efi").write_bytes(b"")
    (drivers / "Unused.efi").write_bytes(b"")
    (tools / "memtest86\\BOOTX64.efi").write_bytes(b"")
    (audio / "Sound.wav").write_bytes(b"")
    for variant in ("Acidanthera\\GoldenGate", "Acidanthera\\Chardonnay"):
        (image / variant).mkdir()
        (image / variant / "Background.icns").write_bytes(b"")
    (result / "manifest.json").write_text("{}")

    monkeypatch.setattr(pipeline, "_listing", _fake_listing({
        "Drivers": [("OpenRuntime.efi", "file"), ("Unused.efi", "file")],
        "Tools": [("memtest86\\BOOTX64.efi", "file")],
        "Image": [("Acidanthera", "dir"),
                  ("Acidanthera\\Chardonnay", "dir"),
                  ("Acidanthera\\GoldenGate", "dir")],
    }))

    pipeline.Pipeline._prune(result, {
        "UEFI": {"Drivers": [{"Path": "OpenRuntime.efi"}]},
        "Misc": {
            "Boot": {"PickerVariant": "Auto"},
            "Tools": [{"Path": "memtest86/BOOTX64.efi"}],
        },
    })

    assert (drivers / "OpenRuntime.efi").is_file()
    assert not (drivers / "Unused.efi").exists()
    assert (tools / "memtest86\\BOOTX64.efi").is_file()
    assert not audio.exists()
    assert (image / "Acidanthera\\GoldenGate").is_dir()
    assert not (image / "Acidanthera\\Chardonnay").exists()
    assert not (result / "manifest.json").exists()


def _tree(tmp_path, additional_kext=None, identifier="com.test.lilu"):
    result = tmp_path / "out"
    efi = result / "EFI"
    oc = efi / "OC"
    (efi / "BOOT").mkdir(parents=True)
    (efi / "BOOT" / "BOOTx64.efi").write_bytes(b"")
    oc.mkdir(parents=True)
    (oc / "OpenCore.efi").write_bytes(b"")
    (oc / "ACPI").mkdir()
    (oc / "ACPI" / "SSDT-Test.aml").write_bytes(b"")
    (oc / "Drivers").mkdir()
    (oc / "Drivers" / "OpenRuntime.efi").write_bytes(b"")
    (oc / "Tools").mkdir()
    kext = oc / "Kexts" / "Lilu.kext" / "Contents"
    kext.mkdir(parents=True)
    (kext / "MacOS").mkdir()
    (kext / "MacOS" / "Lilu").write_bytes(b"")
    (kext / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": identifier,
        "CFBundleExecutable": "Lilu",
    }))
    kernel_add = [{
        "BundlePath": "Lilu.kext",
        "Enabled": True,
        "ExecutablePath": "Contents/MacOS/Lilu",
        "PlistPath": "Contents/Info.plist",
    }]
    if additional_kext is not None:
        name, deps = additional_kext
        extra = oc / "Kexts" / (name + ".kext") / "Contents"
        extra.mkdir(parents=True)
        (extra / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "com.test.{}".format(name),
            "OSBundleLibraries": deps,
        }))
        kernel_add.append({
            "BundlePath": name + ".kext",
            "Enabled": True,
            "ExecutablePath": "",
            "PlistPath": "Contents/Info.plist",
        })
    (oc / "config.plist").write_bytes(plistlib.dumps({
        "ACPI": {"Add": [{"Path": "SSDT-Test.aml"}]},
        "Kernel": {"Add": kernel_add},
        "UEFI": {"Drivers": [{"Path": "OpenRuntime.efi"}]},
        "Misc": {"Tools": []},
    }))
    return result


def test_verification_accepts_a_complete_tree(tmp_path):
    Pipeline._verify_output(_tree(tmp_path))


def test_verification_rejects_a_dangling_acpi_reference(tmp_path):
    result = _tree(tmp_path)
    (result / "EFI" / "OC" / "ACPI" / "SSDT-Test.aml").unlink()

    with pytest.raises(BuildVerificationFailed) as raised:
        Pipeline._verify_output(result)

    assert "SSDT-Test.aml" in raised.value.detail


def test_verification_rejects_a_missing_kext_executable(tmp_path):
    result = _tree(tmp_path)
    (result / "EFI" / "OC" / "Kexts" / "Lilu.kext" / "Contents" / "MacOS" / "Lilu").unlink()

    with pytest.raises(BuildVerificationFailed) as raised:
        Pipeline._verify_output(result)

    assert "Contents/MacOS/Lilu" in raised.value.detail


def test_verification_rejects_duplicate_enabled_identifiers(tmp_path):
    result = _tree(tmp_path, additional_kext=("Twin", {}))
    twin = result / "EFI" / "OC" / "Kexts" / "Twin.kext" / "Contents" / "Info.plist"
    twin.write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.test.lilu"}))

    with pytest.raises(BuildVerificationFailed) as raised:
        Pipeline._verify_output(result)

    assert "duplicate enabled identifier" in raised.value.detail


def test_verification_rejects_a_dependency_loaded_too_late(tmp_path):
    result = _tree(tmp_path, additional_kext=("NeedsLilu", {"com.test.lilu": "1.0"}))
    config_path = result / "EFI" / "OC" / "config.plist"
    config = plistlib.loads(config_path.read_bytes())
    config["Kernel"]["Add"].reverse()
    config_path.write_bytes(plistlib.dumps(config))

    with pytest.raises(BuildVerificationFailed) as raised:
        Pipeline._verify_output(result)

    assert "loads before" in raised.value.detail
