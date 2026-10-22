"""Equivalence between ``blackdream.core.versions`` and the upstream prompt loop.

``upstream_suggest`` below is a verbatim transcription of the suggestion algorithm in
``OpCore-Simplify.py`` ``OCPE.select_macos_version`` (pristine clone, ``f0e1e44``),
stripped of the printing around it. It is run against the pristine ``Scripts`` tree so
that our rewritten module is compared to upstream code and upstream data, not to a
second copy of our own.
"""

import json
import os
import sys
from pathlib import Path
from itertools import product

import pytest

PRISTINE = "/data/BlackDream/OpCore-Simplify"
SRC = Path(__file__).resolve().parents[1] / "src"
for entry in (str(SRC), PRISTINE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures
from blackdream.core import versions
from ocengine.utils import Utils
from ocengine.compatibility_checker import CompatibilityChecker  # noqa: F401

if not os.path.isdir(os.path.join(PRISTINE, "Scripts")):
    pytest.skip("pristine upstream clone not available", allow_module_level=True)

from Scripts.datasets import os_data as pristine_os_data
from Scripts import utils as pristine_utils

_u = Utils()


def upstream_suggest(hardware_report, native_macos_version):
    """Verbatim from OpCore-Simplify.py:select_macos_version."""
    u = pristine_utils.Utils()
    suggested_macos_version = native_macos_version[1]

    for device_type in ("GPU", "Network", "Bluetooth", "SD Controller"):
        if device_type in hardware_report:
            for device_name, device_props in hardware_report[device_type].items():
                if device_props.get("Compatibility", (None, None)) != (None, None):
                    if device_type == "GPU" and device_props.get("Device Type") == "Integrated GPU":
                        device_id = device_props.get("Device ID", ""*8)[5:]

                        if device_props.get("Manufacturer") == "AMD" or device_id.startswith(("59", "87C0")):
                            suggested_macos_version = "22.99.99"
                        elif device_id.startswith(("09", "19")):
                            suggested_macos_version = "21.99.99"

                    if u.parse_darwin_version(suggested_macos_version) > u.parse_darwin_version(device_props.get("Compatibility")[0]):
                        suggested_macos_version = device_props.get("Compatibility")[0]

    while True:
        if "Beta" in pristine_os_data.get_macos_name_by_darwin(suggested_macos_version):
            suggested_macos_version = "{}{}".format(int(suggested_macos_version[:2]) - 1, suggested_macos_version[2:])
        else:
            break

    return suggested_macos_version


GPU_CASES = [
    {},
    {"GPU": {"iGPU": {"Manufacturer": "Intel", "Device Type": "Integrated GPU",
                      "Device ID": "8086-3E9B", "Compatibility": ("25.99.99", "17.0.0")}}},
    {"GPU": {"iGPU": {"Manufacturer": "Intel", "Device Type": "Integrated GPU",
                      "Device ID": "8086-591E", "Compatibility": ("25.99.99", "17.0.0")}}},
    {"GPU": {"iGPU": {"Manufacturer": "Intel", "Device Type": "Integrated GPU",
                      "Device ID": "8086-0910", "Compatibility": ("25.99.99", "17.0.0")}}},
    {"GPU": {"iGPU": {"Manufacturer": "Intel", "Device Type": "Integrated GPU",
                      "Device ID": "8086-191B", "Compatibility": ("21.99.99", "17.0.0")}}},
    {"GPU": {"iGPU": {"Manufacturer": "Intel", "Device Type": "Integrated GPU",
                      "Device ID": "8086-87C0", "Compatibility": ("25.99.99", "21.0.0")}}},
    {"GPU": {"dGPU": {"Manufacturer": "AMD", "Device Type": "Integrated GPU",
                      "Device ID": "1002-15D8", "Compatibility": ("25.99.99", "17.0.0")}}},
    {"GPU": {"dGPU": {"Manufacturer": "NVIDIA", "Device Type": "Discrete GPU",
                      "Device ID": "10DE-128B", "Compatibility": ("17.99.99", "17.0.0")}}},
    {"GPU": {"dGPU": {"Manufacturer": "NVIDIA", "Device Type": "Discrete GPU",
                      "Device ID": "10DE-1F12", "Compatibility": (None, None)}}},
]
AFTERMARKET = [
    {},
    {"Network": {"NIC": {"Compatibility": ("21.99.99", "17.0.0")}}},
    {"Bluetooth": {"BT": {"Compatibility": ("20.99.99", "17.0.0")}}},
    {"SD Controller": {"SD": {"Compatibility": ("19.0.0", "17.0.0")}}},
    {"Network": {"NIC": {"Compatibility": ("25.99.99", "17.0.0")}},
     "Bluetooth": {"BT": {"Compatibility": (None, None)}}},
]
NATIVE = [("17.0.0", "25.99.99"), ("21.2.0", "25.99.99"), ("17.0.0", "17.99.99"),
          ("20.0.0", "20.99.99")]

CASES = [(gpu, after, native)
         for gpu, after, native in product(GPU_CASES, AFTERMARKET, NATIVE)]


@pytest.mark.parametrize("index", range(len(CASES)), ids=[str(i) for i in range(len(CASES))])
def test_suggestion_matches_upstream(index):
    gpu_case, aftermarket, native = CASES[index]
    report = {}
    report.update(gpu_case)
    report.update(aftermarket)

    assert versions.suggest(report, native) == upstream_suggest(report, native)


def test_option_listing_matches_upstream_arithmetic():
    """Upstream listed majors with ``int(version[:2])``; ours parses. The rendered
    major list and the OCLP markers must be identical."""
    oclp = ("25.99.99", "20.0.0")
    native = ("26.0.0", "26.99.99")

    upstream_majors = list(range(min(int(native[0][:2]), int(oclp[-1][:2])),
                                 max(int(native[-1][:2]), int(oclp[0][:2])) + 1))
    listed = versions.options(native, oclp, suggested="25.99.99")

    assert [option.darwin_major for option in listed] == upstream_majors
    assert [option.darwin_major for option in listed if option.requires_oclp] == [
        major for major in upstream_majors if int(oclp[-1][:2]) <= major <= int(oclp[0][:2])]


def test_needs_oclp_only_for_patched_range():
    native = ("22.0.0", "25.99.99")
    oclp = ("25.99.99", "20.0.0")

    assert versions.needs_oclp("20.6.0", oclp, native) is True
    assert versions.needs_oclp("23.0.0", oclp, native) is False
    assert versions.needs_oclp("20.6.0", None, native) is False


def test_graded_fixture_reports_suggest_a_listed_version():
    """End to end: grade a fixture with the converted engine, then suggest from the
    graded report and check the suggestion is one of the options we would render."""
    for name in sorted(fixtures.ALL_HEALTHY):
        graded, native, oclp = CompatibilityChecker().check_compatibility(
            json.loads(json.dumps(getattr(fixtures, name)())))
        suggested = versions.suggest(graded, native)
        listed = versions.options(native, oclp, suggested=suggested)

        assert suggested == upstream_suggest(graded, native)
        assert _u.parse_darwin_version(suggested)[0] in [o.darwin_major for o in listed]
        assert not any(o.name is None for o in listed)
