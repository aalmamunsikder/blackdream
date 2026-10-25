"""The offline half of the pipeline, across unrelated device archetypes.

One Intel laptop, one Intel desktop with an AMD dGPU and one AMD laptop exercise
every report-driven decision made before a download: verdict rows, the suggested
macOS target, which devices the target disables, the SMBIOS model, and the kexts
the build will need. The reports go through ``Pipeline.load_report`` so the real
validator runs, and no test here touches the network or an ACPI table.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests.fixtures as fixtures  # noqa: E402
from blackdream.core import verdicts  # noqa: E402
from blackdream.core.pipeline import Pipeline  # noqa: E402
from ocengine import resource_fetcher  # noqa: E402
from ocengine.hardware_customizer import HardwareCustomizer  # noqa: E402
from ocengine.kext_maestro import KextMaestro  # noqa: E402
from ocengine.smbios import SMBIOS  # noqa: E402

EXPECTED = {
    "coffee_lake_laptop": {
        "native": ("17.0.0", "25.99.99"),
        "suggested_major": 25,
        "smbios": "MacBookPro15,2",
        "disabled": "Intel Cannon Lake-HDMI",
        "required": {
            "Lilu", "VirtualSMC", "SMCBatteryManager", "SMCDellSensors",
            "SMCProcessor", "SMCSuperIO", "WhateverGreen",
            "AirportItlwm-laobamac", "IntelMausiEthernet", "Sinetek-rtsx",
        },
        "absent": {"NootedRed", "CtlnaAHCIPort", "AppleMCEReporterDisabler"},
    },
    "alder_lake_desktop": {
        "native": ("21.2.0", "25.99.99"),
        "suggested_major": 25,
        "smbios": "MacPro7,1",
        "disabled": None,
        "required": {
            "Lilu", "VirtualSMC", "WhateverGreen", "AppleIGC", "RTL812xLucy",
            "CpuTopologyRebuild",
        },
        "absent": {"SMCBatteryManager", "SMCDellSensors", "NootedRed"},
    },
    "raven_ridge_amd_laptop": {
        "native": ("19.0.0", "25.99.99"),
        # The Vega iGPU caps the native target at Ventura, not the report ceiling.
        "suggested_major": 22,
        "smbios": "MacBookPro16,2",
        "disabled": "Intel Cannon Lake-HDMI",
        "required": {
            "Lilu", "VirtualSMC", "SMCBatteryManager", "NootedRed",
            "AppleMCEReporterDisabler", "CtlnaAHCIPort", "AirportItlwm",
        },
        "absent": {"SMCDellSensors", "AirportItlwm-laobamac"},
    },
    "tiger_lake_laptop": {
        # Apple's drivers stop at Big Sur; WhateverXe is what makes newer targets
        # reachable, so the range starts there and WhateverGreen is never selected.
        "native": ("20.6.0", "25.99.99"),
        "suggested_major": 25,
        "smbios": "MacBookPro16,2",
        "disabled": "Intel Tiger Lake-HDMI",
        "required": {
            "Lilu", "VirtualSMC", "SMCBatteryManager", "WhateverXe", "AMFIPass-Mod",
            "AirportItlwm-laobamac", "IntelMausiEthernet", "Sinetek-rtsx",
        },
        "absent": {"WhateverGreen", "NootedRed", "CtlnaAHCIPort"},
    },
    "rtx_desktop": {
        # Apple has no Metal driver for Turing or newer; the NullMoth driver is what
        # makes 15.5 and newer reachable, so WhateverGreen is never selected for it.
        "native": ("24.5.0", "25.99.99"),
        "suggested_major": 25,
        "smbios": "MacPro7,1",
        "disabled": None,
        "required": {
            "Lilu", "VirtualSMC", "AMFIPass", "AppleIGC", "RTL812xLucy",
            "CpuTopologyRebuild", "RestrictEvents",
        },
        "absent": {"WhateverGreen", "WhateverXe", "NootRX", "NootedRed"},
    },
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Every fetch in the engine funnels through this module's urlopen."""
    def refuse(*args, **kwargs):
        raise AssertionError("offline planning test attempted a network request")

    monkeypatch.setattr(resource_fetcher, "urlopen", refuse)


def _analyse(tmp_path, builder):
    path = fixtures.write_report(str(tmp_path), builder, getattr(fixtures, builder)())
    pipeline = Pipeline()
    return pipeline, pipeline.analyze(pipeline.load_report(path))


def _customize(analysis, target):
    return HardwareCustomizer().hardware_customization(analysis.report, target)


def _kexts(hardware_report, target):
    maestro = KextMaestro()
    maestro.select_required_kexts(hardware_report, target, False, [])
    return {kext.name for kext in maestro.kexts if kext.checked}


@pytest.mark.parametrize("builder", sorted(EXPECTED))
def test_a_report_drives_every_decision_before_the_build(builder, tmp_path):
    expected = EXPECTED[builder]
    pipeline, analysis = _analyse(tmp_path, builder)

    assert analysis.native_range == expected["native"]
    assert analysis.oclp_range is None
    assert pipeline.version_choices(analysis)[0].requires_oclp is False

    rows = verdicts.rows(analysis.report)
    assert rows
    cpu = next(row for row in rows if row.section == "CPU")
    gpu = next(row for row in rows if row.section == "GPU")
    assert cpu.compatible is True
    assert gpu.compatible is True

    options = pipeline.version_choices(analysis)
    suggested = next(option for option in options if option.is_suggested)
    assert suggested.darwin_major == expected["suggested_major"]
    assert any(option.darwin_major == suggested.darwin_major for option in options)

    hardware_report, disabled, needs_oclp = _customize(analysis, suggested.value)
    assert needs_oclp is False
    if expected["disabled"] is None:
        assert disabled == {}
    else:
        assert any(expected["disabled"] in name for name in disabled)

    assert SMBIOS().select_smbios_model(hardware_report, suggested.value) == expected["smbios"]

    checked = _kexts(hardware_report, suggested.value)
    assert expected["required"] <= checked
    assert checked & expected["absent"] == set()


def test_the_target_version_changes_the_desktop_smbios_model(tmp_path):
    """The same report is a supported Mac Pro on Tahoe and an iMac Pro before it."""
    _, analysis = _analyse(tmp_path, "alder_lake_desktop")

    ventura_report, _, _ = _customize(analysis, "22.99.99")
    tahoe_report, _, _ = _customize(analysis, "25.99.99")

    assert SMBIOS().select_smbios_model(ventura_report, "22.99.99") == "iMacPro1,1"
    assert SMBIOS().select_smbios_model(tahoe_report, "25.99.99") == "MacPro7,1"


def test_the_target_version_changes_the_audio_kext_choice(tmp_path):
    """Layout injection is a Tahoe-era path; Ventura gets AppleALC alone."""
    _, analysis = _analyse(tmp_path, "coffee_lake_laptop")

    ventura_report, _, _ = _customize(analysis, "22.99.99")
    tahoe_report, _, _ = _customize(analysis, "25.99.99")

    ventura = _kexts(ventura_report, "22.99.99")
    tahoe = _kexts(tahoe_report, "25.99.99")

    assert "AppleALC" in ventura and "SimpleHDA" not in ventura
    assert {"AppleALC", "SimpleHDA"} <= tahoe


def test_two_intel_generations_do_not_share_a_kext_set(tmp_path):
    """The Coffee Lake laptop and the Alder Lake desktop must select differently."""
    laptop_report, _, _ = _customize(_analyse(tmp_path, "coffee_lake_laptop")[1], "25.99.99")
    desktop_report, _, _ = _customize(
        _analyse(tmp_path / "desktop", "alder_lake_desktop")[1], "25.99.99")

    laptop = _kexts(laptop_report, "25.99.99")
    desktop = _kexts(desktop_report, "25.99.99")

    assert "SMCBatteryManager" in laptop and "SMCBatteryManager" not in desktop
    assert "CpuTopologyRebuild" in desktop and "CpuTopologyRebuild" not in laptop
