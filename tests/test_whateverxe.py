"""WhateverXe is a third-party graphics path, not a drop-in WhateverGreen.

Apple never shipped a driver for Xe-LP, so every layer has to agree that the part is
reachable *through a patch*: the compatibility checker must grade the range instead of
rejecting the GPU, selection must swap WhateverGreen for WhateverXe plus the Mod
AMFIPass build, the config must carry the project's boot arguments and SIP value, and
the table must say "Limited support" rather than "Supported". These tests pin one
layer each, against the pinned catalogue rows the build actually reads.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for entry in (str(SRC), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import tests.fixtures as fixtures  # noqa: E402
from blackdream.core import verdicts  # noqa: E402
from blackdream.core.pipeline import Pipeline, WHATEVERXE_HANDOFF  # noqa: E402
from ocengine.compatibility_checker import CompatibilityChecker  # noqa: E402
from ocengine.config_prodigy import ConfigProdigy  # noqa: E402
from ocengine.datasets import gpu_data, kext_data, os_data  # noqa: E402
from ocengine.kext_maestro import KextInstallIncomplete, KextMaestro  # noqa: E402

TARGET = "25.99.99"


def _graded(report):
    return CompatibilityChecker().check_compatibility(report)[0]


def _catalogue(name):
    return kext_data.kexts[kext_data.kext_index_by_name[name]]


def _selection(report, target=TARGET):
    maestro = KextMaestro()
    maestro.select_required_kexts(report, target, False, [])
    return maestro, {kext.name for kext in maestro.kexts if kext.checked}


def _bundle(root, name):
    kext = Path(root) / (name + ".kext")
    contents = kext / "Contents"
    contents.mkdir(parents=True)
    executable = contents / "MacOS" / name
    executable.parent.mkdir()
    executable.write_bytes(b"")
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "com.test." + name.lower(),
        "CFBundleExecutable": name,
        "CFBundleVersion": "1.0.0",
    }))
    return kext


# --- the pinned rows -----------------------------------------------------------------

def test_the_catalogue_pins_the_release_and_the_mod_amfipass_build():
    whateverxe = _catalogue("WhateverXe")
    assert whateverxe.download_info["url"] == (
        "https://github.com/b00t0x/WhateverXe/releases/download/0.5.0/"
        "WhateverXe-0.5.0-RELEASE.zip")
    assert whateverxe.download_info["sha256"] == (
        "59cd4b82814b9ae5b5b1029612fc6c7a7ca0a32b7871a7d42e857a6158c3d3ec")
    assert whateverxe.min_darwin_version == "20.6.0"
    assert whateverxe.requires_kexts == ["Lilu"]

    mod = _catalogue("AMFIPass-Mod")
    assert "/3e5ca0385db0db3490e03864fd1f1076fb5a53a2/" in mod.download_info["url"]
    assert mod.download_info["sha256"] == (
        "71f41de42e355d2a83e6f093ef34a5b24d0a9c9a9085830b2317f1b874f56250")
    assert mod.requires_kexts == ["Lilu"]


def test_every_id_in_the_table_is_graded_and_the_neighbours_are_not():
    for device_id in gpu_data.WHATEVERXE_DEVICE_IDS:
        assert gpu_data.is_whateverxe_device_id("8086-" + device_id)
    for device_id in ("3E9B", "9A41", "46D5", "A784", ""):
        assert not gpu_data.is_whateverxe_device_id("8086-" + device_id)


# --- grading -------------------------------------------------------------------------

def test_an_xe_lp_igpu_is_graded_big_sur_11_7_11_to_the_newest_release():
    report = _graded(fixtures.tiger_lake_laptop())
    gpu = next(iter(report["GPU"].values()))

    assert gpu["WhateverXe"] is True
    assert gpu["Compatibility"] == (os_data.get_latest_darwin_version(), "20.6.0")
    assert "OCLP Compatibility" not in gpu


def test_a_low_end_alder_lake_n_is_not_rejected_because_of_its_cpu_name():
    report = fixtures.tiger_lake_laptop()
    report["CPU"]["Processor Name"] = "Intel Celeron N5095"
    report["CPU"]["Codename"] = "Alder Lake-N"
    report["GPU"]["Intel UHD Graphics"] = report["GPU"].pop("Intel Iris Xe Graphics")
    report["GPU"]["Intel UHD Graphics"]["Device ID"] = "8086-46D0"
    report["Monitor"]["BOE 0x095F"]["Connected GPU"] = "Intel UHD Graphics"

    graded = _graded(report)
    gpu = graded["GPU"]["Intel UHD Graphics"]

    assert gpu["WhateverXe"] is True
    assert gpu["Compatibility"] == (os_data.get_latest_darwin_version(), "20.6.0")


def test_a_native_igpu_is_still_graded_natively_and_not_flagged():
    report = _graded(fixtures.coffee_lake_laptop())
    gpu = next(iter(report["GPU"].values()))

    assert "WhateverXe" not in gpu
    assert gpu["Compatibility"] == ("25.99.99", "17.0.0")


# --- selection and configuration ------------------------------------------------------

def test_selection_swaps_whatevergreen_for_whateverxe_and_the_mod_build():
    report = _graded(fixtures.tiger_lake_laptop())
    _maestro, names = _selection(report)

    assert {"WhateverXe", "AMFIPass-Mod", "Lilu"} <= names
    assert "WhateverGreen" not in names
    assert "AMFIPass" not in names


def test_a_navi_22_card_keeps_the_graphics_slot_and_leaves_the_xe_igpu_native():
    report = fixtures.tiger_lake_laptop()
    report["GPU"]["AMD Radeon RX 6700 XT"] = {
        "Manufacturer": "AMD",
        "Codename": "Navi 22",
        "Device ID": "1002-73DF",
        "Device Type": "Discrete GPU",
        "PCI Path": None,
        "ACPI Path": None,
    }
    report = _graded(report)
    _maestro, names = _selection(report)

    assert "NootRX" in names
    assert "WhateverXe" not in names
    # The Mod build must not outlive the kext it was selected for.
    assert "AMFIPass-Mod" not in names


def test_a_native_igpu_keeps_whatevergreen_and_never_selects_whateverxe():
    report = _graded(fixtures.coffee_lake_laptop())
    _maestro, names = _selection(report)

    assert "WhateverGreen" in names
    assert "WhateverXe" not in names
    assert "AMFIPass-Mod" not in names


def test_the_config_carries_the_projects_boot_arguments_and_sip_value():
    report = _graded(fixtures.tiger_lake_laptop())
    maestro, _names = _selection(report)
    config = {"Booter": {"Quirks": {"ResizeAppleGpuBars": -1}}}
    writer = ConfigProdigy()

    args = writer.boot_args(report, TARGET, False, maestro.kexts, config).split()

    assert "-allow3d" in args
    assert "-disablegfxfirmware" in args
    assert writer.csr_active_config(TARGET, maestro.kexts) == "03080000"


def test_a_config_without_whateverxe_keeps_the_ordinary_sip_value():
    report = _graded(fixtures.coffee_lake_laptop())
    maestro, _names = _selection(report)

    assert ConfigProdigy().csr_active_config(TARGET, maestro.kexts) == "030A0000"


def test_the_mod_build_installs_under_the_bundle_name_it_actually_has(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    _bundle(cache / "WhateverXe", "WhateverXe")
    _bundle(cache / "AMFIPass-Mod", "AMFIPass")
    _bundle(cache / "Lilu", "Lilu")

    maestro = KextMaestro()
    monkeypatch.setattr(maestro, "ock_files_dir", str(cache))
    for kext in maestro.kexts:
        kext.checked = kext.name in {"WhateverXe", "AMFIPass-Mod", "Lilu"}

    kexts_directory = tmp_path / "EFI" / "OC" / "Kexts"
    maestro.install_kexts_to_efi(TARGET, str(kexts_directory))

    assert (kexts_directory / "WhateverXe.kext" / "Contents" / "Info.plist").is_file()
    assert (kexts_directory / "AMFIPass.kext" / "Contents" / "Info.plist").is_file()
    assert not (kexts_directory / "AMFIPass-Mod.kext").exists()


def test_the_mod_build_does_not_satisfy_a_selection_that_wanted_upstream_amfipass(
        monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    _bundle(cache / "AMFIPass-Mod", "AMFIPass")
    _bundle(cache / "Lilu", "Lilu")

    maestro = KextMaestro()
    monkeypatch.setattr(maestro, "ock_files_dir", str(cache))
    for kext in maestro.kexts:
        kext.checked = kext.name in {"AMFIPass", "Lilu"}

    with pytest.raises(KextInstallIncomplete):
        maestro.install_kexts_to_efi(TARGET, str(tmp_path / "EFI" / "OC" / "Kexts"))


# --- what the user sees -----------------------------------------------------------------

def test_the_table_says_the_gpu_runs_through_whateverxe():
    report = _graded(fixtures.tiger_lake_laptop())
    gpu = next(row for row in verdicts.rows(report) if row.section == "GPU")

    assert gpu.patch == "WhateverXe"
    assert gpu.text.endswith("with WhateverXe")
    assert gpu.compatible is True


def test_the_target_column_is_limited_support_not_supported():
    report = _graded(fixtures.tiger_lake_laptop())
    gpu = next(row for row in verdicts.rows(report) if row.section == "GPU")

    chosen = verdicts.target_status(gpu, TARGET)
    assert chosen.key == "limited"
    assert chosen.label == "Limited support"
    assert "WhateverXe" in chosen.detail
    assert "WhateverXe Graphics {}".format(gpu_data.WHATEVERXE_GRAPHICS_VERSION) in (
        chosen.recommendation)

    without_target = verdicts.target_status(gpu, None)
    assert without_target.key == "limited"
    assert "through WhateverXe" in without_target.detail


def test_a_release_before_the_patch_is_still_unsupported():
    report = _graded(fixtures.tiger_lake_laptop())
    gpu = next(row for row in verdicts.rows(report) if row.section == "GPU")

    status = verdicts.target_status(gpu, "18.99.99")
    assert status.key == "unsupported"


def test_a_native_igpu_on_the_same_release_still_reads_supported():
    report = _graded(fixtures.coffee_lake_laptop())
    gpu = next(row for row in verdicts.rows(report) if row.section == "GPU")

    assert verdicts.target_status(gpu, TARGET).key == "supported"


def test_the_handoff_names_the_graphics_package_and_the_known_issues():
    text = WHATEVERXE_HANDOFF.format(graphics=gpu_data.WHATEVERXE_GRAPHICS_VERSION)

    assert "WhateverXe Graphics {}".format(gpu_data.WHATEVERXE_GRAPHICS_VERSION) in text
    assert "96 MB" in text
    assert "SSDT-PNLF" in text
    assert "-yTileDisable" in text
    assert "WhateverGreen" in text
    assert "AuxKC" in text or "auxiliary" in text.lower()


def test_the_handoff_file_is_written_only_when_whateverxe_is_selected(tmp_path):
    pipeline = Pipeline()
    index = kext_data.kext_index_by_name["WhateverXe"]

    pipeline.kexts.kexts[index].checked = False
    pipeline._write_whateverxe_handoff(tmp_path)
    assert not (tmp_path / "WhateverXe-Graphics.txt").exists()

    pipeline.kexts.kexts[index].checked = True
    try:
        pipeline._write_whateverxe_handoff(tmp_path)
        written = (tmp_path / "WhateverXe-Graphics.txt").read_text(encoding="utf-8")
    finally:
        pipeline.kexts.kexts[index].checked = False

    assert written == WHATEVERXE_HANDOFF.format(
        graphics=gpu_data.WHATEVERXE_GRAPHICS_VERSION)
