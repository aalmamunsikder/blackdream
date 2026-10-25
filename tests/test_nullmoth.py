"""The NullMoth NVIDIA driver is a target-side driver, not an EFI kext.

Apple never shipped a Metal driver for Turing or newer, so every layer has to agree
that the card is reachable *through a driver installed in the target macOS*: the
compatibility checker grades the range from 15.5 instead of rejecting the GPU,
selection keeps WhateverGreen off the card and adds AMFIPass, the config carries the
project's boot arguments, SIP value, SecureBootModel and IONDRVSupport exclude, and
the table says "Limited support" rather than "Supported". These tests pin one layer
each, against the pinned release the build actually names.
"""

from __future__ import annotations

import copy
import plistlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for entry in (str(SRC), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import tests.fixtures as fixtures  # noqa: E402
from blackdream.core import dependency_advisor as advisor  # noqa: E402
from blackdream.core import verdicts  # noqa: E402
from blackdream.core.pipeline import NULLMOTH_HANDOFF, Pipeline  # noqa: E402
from ocengine.compatibility_checker import CompatibilityChecker  # noqa: E402
from ocengine.config_prodigy import ConfigProdigy  # noqa: E402
from ocengine.datasets import gpu_data, kext_data, os_data  # noqa: E402
from ocengine.fatal import GpuUnsupported  # noqa: E402
from ocengine.kext_maestro import KextMaestro  # noqa: E402

TARGET = "25.99.99"
BOOT = advisor.BOOT_SERVICES_GUID
NULLMOTH_ARGS = (
    "nvfb=1 nvaccel=1 nvfbheads=4 -nvkmsnosmooth amfi_get_out_of_my_way=0x1 "
    "amfi=0x80 ipc_control_port_options=0"
)


def _graded(report):
    return CompatibilityChecker().check_compatibility(report)[0]


def _selection(report, target=TARGET):
    maestro = KextMaestro()
    maestro.select_required_kexts(report, target, False, [])
    return maestro, {kext.name for kext in maestro.kexts if kext.checked}


def _boot_args(report, maestro, target=TARGET):
    writer = ConfigProdigy()
    config = {"Booter": {"Quirks": {"ResizeAppleGpuBars": -1}}}
    return writer, writer.boot_args(
        report, target, False, maestro.kexts, config).split()


# --- the pinned release ---------------------------------------------------------------

def test_the_driver_release_and_the_tarball_digest_are_pinned():
    assert gpu_data.NULLMOTH_DRIVER_VERSION == "2.5.4"
    assert gpu_data.NULLMOTH_MIN_DARWIN == "24.5.0"
    assert gpu_data.NULLMOTH_SIP_BITS == 0x0A43
    assert gpu_data.NULLMOTH_RELEASES_URL.endswith("/releases")
    assert re.fullmatch(r"[0-9a-f]{64}", gpu_data.NULLMOTH_TARBALL_SHA256)


def test_every_id_in_the_vendor_table_is_recognised():
    assert len(gpu_data.NULLMOTH_DEVICE_IDS) == 247
    for device_id in gpu_data.NULLMOTH_DEVICE_IDS:
        assert gpu_data.is_nullmoth_device_id("10DE-" + device_id)
    for device_id in ("0193", "0DE1", "1380", "1C82", ""):
        assert not gpu_data.is_nullmoth_device_id("10DE-" + device_id)
    assert not gpu_data.is_nullmoth_device_id("8086-2D05")
    assert not gpu_data.is_nullmoth_device_id(None)


def test_the_fallback_accepts_the_ids_the_vendor_table_does_not_list():
    assert "2D06" not in gpu_data.NULLMOTH_DEVICE_IDS
    assert gpu_data.is_nullmoth_device_id("10DE-2D06")
    assert gpu_data.is_nullmoth_device_id("10de-2d05")


def test_turing_is_the_two_ranges_the_installer_settles():
    for device_id in ("1E02", "1F12", "2182"):
        assert gpu_data.is_turing_device_id("10DE-" + device_id)
    for device_id in ("1DF6", "2204", "2D05"):
        assert not gpu_data.is_turing_device_id("10DE-" + device_id)


# --- grading --------------------------------------------------------------------------

def test_an_rtx_5060_is_graded_sequoia_15_5_to_the_newest_release():
    report = _graded(fixtures.rtx_desktop())
    gpu = next(iter(report["GPU"].values()))

    assert gpu["NullMoth"] is True
    assert gpu["Compatibility"] == (os_data.get_latest_darwin_version(), "24.5.0")
    assert "OCLP Compatibility" not in gpu


def test_an_unlisted_ada_part_still_grades_through_the_fallback():
    report = fixtures.rtx_desktop()
    report["GPU"]["NVIDIA GeForce RTX 5060"]["Device ID"] = "10DE-2D06"
    report["GPU"]["NVIDIA GeForce RTX 5060"]["Codename"] = "Ada Lovelace"

    gpu = next(iter(_graded(report)["GPU"].values()))

    assert gpu["NullMoth"] is True
    assert gpu["Compatibility"][1] == "24.5.0"


def test_a_pre_turing_card_is_still_rejected():
    with pytest.raises(GpuUnsupported):
        CompatibilityChecker().check_compatibility(fixtures.gpu_unsupported())


def test_an_integrated_nvidia_gpu_is_not_handed_to_the_driver():
    report = fixtures.coffee_lake_laptop()
    report["GPU"]["NVIDIA GeForce MX550"] = {
        "Manufacturer": "NVIDIA",
        "Codename": "Turing",
        "Device ID": "10DE-1F12",
        "Device Type": "Integrated GPU",
        "PCI Path": "PciRoot(0x0)/Pci(0x1,0x0)",
    }

    graded = _graded(report)["GPU"]["NVIDIA GeForce MX550"]

    assert "NullMoth" not in graded
    assert graded["Compatibility"] == (None, None)


# --- selection ------------------------------------------------------------------------

def test_selection_hands_the_card_to_nullmoth_and_keeps_whatevergreen_off():
    report = _graded(fixtures.rtx_desktop())
    maestro, names = _selection(report)

    assert {"Lilu", "AMFIPass", "VirtualSMC"} <= names
    assert "WhateverGreen" not in names
    assert "WhateverXe" not in names
    assert maestro.nullmoth_gpu == "NVIDIA GeForce RTX 5060"


def test_a_release_before_the_driver_is_not_handed_over():
    report = _graded(fixtures.rtx_desktop())
    maestro, names = _selection(report, "23.99.99")

    assert maestro.nullmoth_gpu is None
    assert "AMFIPass" not in names


def test_a_whateverxe_build_keeps_its_mod_amfipass_when_a_nullmoth_card_is_present():
    """One EFI can carry one AMFIPass identifier; WhateverXe's Mod build wins."""
    report = _graded(fixtures.tiger_lake_laptop())
    report["GPU"]["NVIDIA GeForce RTX 5060"] = {
        "Manufacturer": "NVIDIA",
        "Codename": "Blackwell",
        "Device ID": "10DE-2D05",
        "Device Type": "Discrete GPU",
        "NullMoth": True,
        "Compatibility": (os_data.get_latest_darwin_version(), "24.5.0"),
    }

    maestro, names = _selection(report)

    assert {"WhateverXe", "AMFIPass-Mod"} <= names
    assert "AMFIPass" not in names
    assert maestro.nullmoth_gpu == "NVIDIA GeForce RTX 5060"


def test_the_driver_kexts_are_never_selected_into_the_efi():
    report = _graded(fixtures.rtx_desktop())
    _maestro, names = _selection(report)

    assert not names & {"NVRM", "NVAccel", "NVRMFB", "NVRMAGDC"}


# --- the config -----------------------------------------------------------------------

def test_the_generated_config_deletes_boot_args_once():
    """ocvalidate rejects a duplicated NVRAM/Delete entry, and the sample already
    deletes boot-args, so the generator must not append it a second time."""
    report = _graded(fixtures.rtx_desktop())
    maestro, _names = _selection(report)
    sample = ROOT / "src" / "blackdream" / "data" / "OpenCore-1.0.8-Sample.plist"
    with sample.open("rb") as handle:
        config = plistlib.load(handle)

    ConfigProdigy().genarate(
        report, {}, "iMacPro1,1", TARGET, False, maestro.kexts, config)

    deletes = config["NVRAM"]["Delete"][BOOT]
    assert deletes.count("boot-args") == 1
    assert deletes.count("csr-active-config") == 1


def test_the_config_carries_the_drivers_arguments_and_the_tested_sip_value():
    report = _graded(fixtures.rtx_desktop())
    maestro, _names = _selection(report)

    writer, args = _boot_args(report, maestro)

    for token in ("nvfb=1", "nvaccel=1", "nvfbheads=4", "-nvkmsnosmooth",
                  "amfi_get_out_of_my_way=0x1", "amfi=0x80",
                  "ipc_control_port_options=0"):
        assert token in args
    assert "nvrmsettle=10000" not in args
    assert "gfxrst=4" not in args
    assert "nv_disable=1" not in args and "-wegnoegpu" not in args
    assert writer.csr_active_config(TARGET, maestro.kexts, nullmoth=True) == "430A0000"


def test_a_turing_card_gets_the_longer_gsp_settle():
    report = fixtures.rtx_desktop()
    gpu = report["GPU"].pop("NVIDIA GeForce RTX 5060")
    gpu.update({"Codename": "Turing", "Device ID": "10DE-1F12"})
    report["GPU"]["NVIDIA GeForce RTX 2060"] = gpu
    report["Monitor"]["LG 27GP850"]["Connected GPU"] = "NVIDIA GeForce RTX 2060"
    report = _graded(report)
    maestro, _names = _selection(report)

    _writer, args = _boot_args(report, maestro)

    assert "nvrmsettle=10000" in args


def test_whatevergreen_keeps_its_boot_screen_fix_when_it_is_selected():
    report = _graded(fixtures.rtx_desktop())
    maestro, _names = _selection(report)
    index = kext_data.kext_index_by_name["WhateverGreen"]
    maestro.kexts[index].checked = True
    try:
        _writer, args = _boot_args(report, maestro)
    finally:
        maestro.kexts[index].checked = False

    assert "gfxrst=4" in args


def test_the_config_excludes_iondrv_support_so_nvrmfb_keeps_display_zero():
    report = _graded(fixtures.rtx_desktop())
    maestro, _names = _selection(report)

    block = ConfigProdigy().block_kext_bundle(maestro.kexts, report, {})

    entry = next(item for item in block
                 if item["Identifier"] == "com.apple.iokit.IONDRVSupport")
    assert entry["Strategy"] == "Exclude"
    assert entry["Enabled"] is True


def test_the_built_in_intel_panel_keeps_iondrv_support():
    report = fixtures.coffee_lake_laptop()
    path = report["GPU"]["Intel UHD Graphics 630"]["PCI Path"]
    writer = ConfigProdigy()

    assert writer._intel_panel_on_firmware_framebuffer(report, {}) is True
    assert writer._intel_panel_on_firmware_framebuffer(
        report, {path: {"disable-gpu": True}}) is False
    assert writer._intel_panel_on_firmware_framebuffer(
        report, {path: {"AAPL,ig-platform-id": b"\x09\x00\x9b\x3e"}}) is False


def test_a_machine_with_both_a_nullmoth_card_and_an_intel_panel_skips_the_block():
    report = fixtures.coffee_lake_laptop()
    report["GPU"]["NVIDIA GeForce RTX 5060"] = {
        "Manufacturer": "NVIDIA",
        "Codename": "Blackwell",
        "Device ID": "10DE-2D05",
        "Device Type": "Discrete GPU",
        "NullMoth": True,
        "Compatibility": (os_data.get_latest_darwin_version(), "24.5.0"),
    }
    maestro, _names = _selection(report)

    block = ConfigProdigy().block_kext_bundle(maestro.kexts, report, {})

    assert not any(item["Identifier"] == "com.apple.iokit.IONDRVSupport"
                   for item in block)


# --- what the user sees ----------------------------------------------------------------

def test_the_table_says_the_card_runs_through_nullmoth():
    report = _graded(fixtures.rtx_desktop())
    gpu = next(row for row in verdicts.rows(report) if row.section == "GPU")

    assert gpu.patch == "NullMoth"
    assert gpu.text == "macOS Sequoia 15.5 to macOS Tahoe 26 with NullMoth"
    assert gpu.compatible is True


def test_the_target_column_is_limited_support_not_supported():
    report = _graded(fixtures.rtx_desktop())
    gpu = next(row for row in verdicts.rows(report) if row.section == "GPU")

    chosen = verdicts.target_status(gpu, TARGET)
    assert chosen.key == "limited"
    assert chosen.label == "Limited support"
    assert "NullMoth" in chosen.detail
    assert "NullMoth NVIDIA driver {}".format(gpu_data.NULLMOTH_DRIVER_VERSION) in (
        chosen.recommendation)

    without_target = verdicts.target_status(gpu, None)
    assert without_target.key == "limited"
    assert "through NullMoth" in without_target.detail


def test_a_release_before_the_driver_is_still_unsupported():
    report = _graded(fixtures.rtx_desktop())
    gpu = next(row for row in verdicts.rows(report) if row.section == "GPU")

    status = verdicts.target_status(gpu, "23.99.99")
    assert status.key == "unsupported"
    assert "15.5" in status.detail


# --- the hand-off -----------------------------------------------------------------------

def _handoff() -> str:
    return NULLMOTH_HANDOFF.format(
        version=gpu_data.NULLMOTH_DRIVER_VERSION,
        releases=gpu_data.NULLMOTH_RELEASES_URL,
        sha256=gpu_data.NULLMOTH_TARBALL_SHA256)


def test_the_handoff_names_the_install_steps_and_the_licence():
    text = _handoff()

    assert "1401-Mac-2.5.4.dmg" in text
    assert "nullmoth-nvidia-2.5.4.tar.gz" in text
    assert gpu_data.NULLMOTH_TARBALL_SHA256 in text
    assert "AuxKC" in text
    assert "Above 4G" in text and "CSM" in text
    assert "Algrey's Fix PAT" in text
    assert "kmutil showloaded" in text
    assert "PolyForm Noncommercial 1.0.0" in text
    assert "RTX 5060" in text
    assert "x86_64" in text


def test_the_handoff_file_is_written_only_when_a_card_was_handed_over(tmp_path):
    pipeline = Pipeline()

    pipeline.kexts.nullmoth_gpu = None
    pipeline._write_nullmoth_handoff(tmp_path)
    assert not (tmp_path / "NullMoth-NVIDIA-Driver.txt").exists()

    pipeline.kexts.nullmoth_gpu = "NVIDIA GeForce RTX 5060"
    pipeline._write_nullmoth_handoff(tmp_path)

    written = (tmp_path / "NullMoth-NVIDIA-Driver.txt").read_text(encoding="utf-8")
    assert written == _handoff()


# --- the dependency advisor -------------------------------------------------------------

IONDRV_BLOCK = {
    "Arch": "Any",
    "Comment": "boot framebuffer IONDRVFramebuffer steals index 0 from NVRMFB",
    "Enabled": True,
    "Identifier": "com.apple.iokit.IONDRVSupport",
    "MaxKernel": "",
    "MinKernel": "",
    "Strategy": "Exclude",
}


def _document() -> dict:
    return {
        "Kernel": {
            "Add": [
                {"BundlePath": "Lilu.kext", "Enabled": True},
                {"BundlePath": "AMFIPass.kext", "Enabled": True},
            ],
            "Block": [dict(IONDRV_BLOCK)],
        },
        "Misc": {"Security": {"SecureBootModel": "Disabled"}},
        "NVRAM": {
            "Add": {BOOT: {"boot-args": NULLMOTH_ARGS,
                           "csr-active-config": bytes.fromhex("430A0000")}},
            "Delete": {BOOT: ["boot-args", "csr-active-config"]},
        },
    }


def _nullmoth_rules(report) -> list[str]:
    return [item.rule for item in report.advisories if item.rule.startswith("nullmoth.")]


def _one(report, rule) -> advisor.Advisory:
    matches = [item for item in report.advisories if item.rule == rule]
    assert len(matches) == 1, "expected one {}, got {!r}".format(
        rule, [item.rule for item in report.advisories])
    return matches[0]


def test_a_complete_nullmoth_config_raises_no_nullmoth_rule():
    report = advisor.advise(_document(), target=TARGET)

    assert _nullmoth_rules(report) == []


def test_missing_driver_arguments_are_named():
    document = _document()
    document["NVRAM"]["Add"][BOOT]["boot-args"] = (
        NULLMOTH_ARGS.replace(" nvfbheads=4", "").replace(" amfi=0x80", ""))

    missing = _one(advisor.advise(document, target=TARGET), "nullmoth.boot_args")

    assert "nvfbheads=4" in missing.trigger and "amfi=0x80" in missing.trigger


def test_the_sip_value_must_contain_the_zero_a43_bits():
    document = _document()
    document["NVRAM"]["Add"][BOOT]["csr-active-config"] = bytes.fromhex("030A0000")

    sip = _one(advisor.advise(document, target=TARGET), "nullmoth.csr")

    assert "030A0000" in sip.trigger
    assert "430A0000" in sip.advice
    assert sip.severity == advisor.WARNING


def test_a_superset_of_the_tested_sip_bits_is_accepted():
    document = _document()
    document["NVRAM"]["Add"][BOOT]["csr-active-config"] = bytes.fromhex("430E0000")

    assert _nullmoth_rules(advisor.advise(document, target=TARGET)) == []


def test_secure_boot_model_must_be_disabled():
    document = _document()
    document["Misc"]["Security"]["SecureBootModel"] = "Default"

    rule = _one(advisor.advise(document, target=TARGET), "nullmoth.secure_boot")

    assert rule.severity == advisor.WARNING
    assert "Default" in rule.trigger


def test_a_config_without_amfipass_is_named():
    document = _document()
    document["Kernel"]["Add"] = [{"BundlePath": "Lilu.kext", "Enabled": True}]

    rule = _one(advisor.advise(document, target=TARGET), "nullmoth.amfipass")

    assert rule.path == ("Kernel", "Add")


def test_the_arguments_that_disable_the_gpu_are_reported_once():
    document = _document()
    document["NVRAM"]["Add"][BOOT]["boot-args"] += " nv_disable=1 -wegnoegpu"

    rule = _one(advisor.advise(document, target=TARGET), "nullmoth.gpu_disabled")

    assert "nv_disable=1" in rule.trigger and "-wegnoegpu" in rule.trigger


@pytest.mark.parametrize("entry", [
    {"BundlePath": "NVRM.kext", "Enabled": True},
    {"BundlePath": "NVRM.kext", "Enabled": True, "Identifier": "com.nullmoth.NVRM"},
    {"BundlePath": "Another.kext", "Enabled": True, "Identifier": "com.nullmoth.NVAccel"},
])
def test_an_efi_copy_of_a_driver_kext_is_reported(entry):
    document = _document()
    document["Kernel"]["Add"].append(entry)

    rule = _one(advisor.advise(document, target=TARGET), "nullmoth.injected_kext")

    assert "Kernel" in rule.path
    assert "NVRM" in rule.trigger or "NVAccel" in rule.trigger


def test_whatevergreen_needs_the_boot_screen_fix():
    document = _document()
    document["Kernel"]["Add"].append(
        {"BundlePath": "WhateverGreen.kext", "Enabled": True})

    rule = _one(advisor.advise(document, target=TARGET), "nullmoth.gfxrst")

    assert "gfxrst=4" in rule.advice


def test_boot_args_must_be_deleted_from_nvram():
    document = _document()
    document["NVRAM"]["Delete"][BOOT] = ["csr-active-config"]

    rule = _one(advisor.advise(document, target=TARGET), "nullmoth.nvram_delete")

    assert rule.severity == advisor.WARNING


def test_the_iondrv_exclude_is_required():
    document = _document()
    document["Kernel"]["Block"] = []

    rule = _one(advisor.advise(document, target=TARGET), "nullmoth.iondrv_block")

    assert rule.path == ("Kernel", "Block")
    assert "no IONDRVSupport Exclude" in rule.evidence


def test_a_disabled_iondrv_exclude_points_at_its_enabled_key():
    document = _document()
    document["Kernel"]["Block"][0]["Enabled"] = False

    rule = _one(advisor.advise(document, target=TARGET), "nullmoth.iondrv_block")

    assert rule.path == ("Kernel", "Block", 0, "Enabled")


def test_without_the_driver_arguments_none_of_its_rules_run():
    document = _document()
    document["NVRAM"]["Add"][BOOT]["boot-args"] = "-v keepsyms=1"
    document["Kernel"]["Block"] = []

    assert _nullmoth_rules(advisor.advise(document, target=TARGET)) == []


def test_whateverxe_accepts_the_value_the_nullmoth_driver_needs():
    """0x0A43 includes WhateverXe's 0x803 bits, so a mixed machine needs one value."""
    document = {
        "Kernel": {"Add": [
            {"BundlePath": "Lilu.kext", "Enabled": True},
            {"BundlePath": "WhateverXe.kext", "Enabled": True},
            {"BundlePath": "AMFIPass.kext", "Enabled": True},
        ]},
        "NVRAM": {"Add": {BOOT: {
            "boot-args": "-v -allow3d -disablegfxfirmware",
            "csr-active-config": bytes.fromhex("430A0000"),
        }}},
    }

    report = advisor.advise(document, target=TARGET)

    assert [item.rule for item in report.advisories
            if item.rule.startswith("whateverxe.")] == []


@pytest.mark.parametrize("source, token", [
    ("ocengine/config_prodigy.py:626", "uses_nullmoth"),
    ("ocengine/config_prodigy.py:719", "NullMoth"),
    ("ocengine/config_prodigy.py:846", "boot-args"),
    ("ocengine/kext_maestro.py:718", "nullmoth_gpu"),
    ("blackdream/core/pipeline.py:162", "NVRM"),
])
def test_a_citation_lands_on_the_line_the_rule_claims(source, token):
    path, coordinates = source.split(":", 1)
    number = int(re.match(r"\d+", coordinates).group(0))
    lines = (SRC / path).read_text(encoding="utf-8").splitlines()
    window = "\n".join(lines[number - 1:number + 2])
    assert token in window, "{} expected near {}:{}".format(token, path, number)


def test_every_nullmoth_citation_names_lines_that_exist():
    document = _document()
    document["Kernel"]["Block"] = []
    document["Kernel"]["Add"].append({"BundlePath": "NVRM.kext", "Enabled": True})
    document["NVRAM"]["Add"][BOOT]["boot-args"] = (
        NULLMOTH_ARGS + " nv_disable=1")
    document["NVRAM"]["Add"][BOOT]["csr-active-config"] = bytes.fromhex("030A0000")
    document["NVRAM"]["Delete"][BOOT] = []
    document["Misc"]["Security"]["SecureBootModel"] = "Default"
    document["Kernel"]["Add"] = [
        entry for entry in document["Kernel"]["Add"]
        if entry["BundlePath"] != "AMFIPass.kext"
    ]

    report = advisor.advise(document, target=TARGET)
    founded = [item for item in report.advisories
               if item.rule.startswith("nullmoth.")]
    assert len(founded) >= 7

    for item in founded:
        match = re.match(r"^([\w/.-]+\.py):(.*)$", item.source)
        assert match, "source is not a file:line citation: {!r}".format(item.source)
        path, coordinates = match.group(1), match.group(2)
        target_file = SRC / path
        assert target_file.is_file(), "cited file is not in this repo: {}".format(path)
        lines = target_file.read_text(encoding="utf-8").splitlines()
        numbers = [int(number) for number in re.findall(r"\d+", coordinates)]
        assert numbers
        for number in numbers:
            assert number <= len(lines), "{}:{} is past the end".format(path, number)
