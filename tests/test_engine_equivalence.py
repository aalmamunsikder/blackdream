"""Differential equivalence between the pristine upstream engine and ours.

Needs the untouched clone (pinned ``f0e1e44``) beside this checkout, or wherever
``BLACKDREAM_PRISTINE`` points; skips when it is not there, so CI on its own still
passes.

Two divergences are deliberate. Upstream grades every Xe-LP iGPU as unsupported, and
ours grades the WhateverXe range instead. Upstream also exits on every NVIDIA dGPU
without an Apple driver, and ours grades Turing-and-later cards through NullMoth.
Those are the only report shapes allowed to differ, and even then the converted engine
must return the range the patch table pins -- a patched device that came back with any
other verdict is a defect, not an accepted difference.
"""

import pytest

from pristine import is_available

if not is_available():
    pytest.skip("pristine upstream clone not available", allow_module_level=True)

import diff_engine
from ocengine.datasets import gpu_data, os_data


def _whateverxe_ids(report):
    return [device.get("Device ID") for device in report.get("GPU", {}).values()
            if gpu_data.is_whateverxe_device_id(device.get("Device ID"))]


def _nullmoth_ids(report):
    """Discrete NullMoth cards: the engine never hands it an integrated GPU."""
    return [device.get("Device ID") for device in report.get("GPU", {}).values()
            if device.get("Device Type") != "Integrated GPU"
            and gpu_data.is_nullmoth_device_id(device.get("Device ID"))]


def test_compatibility_checker_matches_upstream_over_the_branch_space():
    """814 reports that cross every branch-relevant field: Intel/AMD/NVIDIA device
    ids and codenames, CPU name x SIMD set, platform, connector type, network ids.
    Verdict ranges, fatal-vs-exit correspondence, and message text must all agree,
    apart from the Xe-LP devices WhateverXe deliberately makes reachable and the
    Turing-and-later NVIDIA cards NullMoth deliberately makes reachable."""
    mismatches = []
    patched = []
    patched_nullmoth = []
    seen = set()
    for label, report in diff_engine.reports():
        if label in seen:
            continue
        seen.add(label)
        pristine_lines, pristine_outcome = diff_engine.run_pristine(report)
        converted_lines, converted_outcome = diff_engine.run_converted(report)
        reason = diff_engine.compare(pristine_lines, pristine_outcome,
                                     converted_lines, converted_outcome)
        if not reason:
            continue
        if (_whateverxe_ids(report)
                and reason == "upstream exited but ours returned a verdict"
                and converted_outcome[0] == "ok"
                and converted_outcome[1] == ("20.6.0", os_data.get_latest_darwin_version())):
            patched.append(label)
            continue
        if (_nullmoth_ids(report)
                and reason == "upstream exited but ours returned a verdict"
                and converted_outcome[0] == "ok"
                and converted_outcome[1] == (gpu_data.NULLMOTH_MIN_DARWIN,
                                             os_data.get_latest_darwin_version())):
            patched_nullmoth.append(label)
            continue
        mismatches.append("{}: {}".format(label, reason))

    assert patched, "the Xe-LP reports no longer diverge; the patch stopped grading"
    assert patched_nullmoth, "the NVIDIA reports no longer diverge; NullMoth stopped grading"
    assert not mismatches, "{} of {} reports diverge:\n{}".format(
        len(mismatches), len(seen), "\n".join(mismatches[:20]))
