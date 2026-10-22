"""Verdict rows: the report the engine graded, shaped for a table."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests.fixtures as fixtures  # noqa: E402
from ocengine.compatibility_checker import CompatibilityChecker  # noqa: E402

from blackdream.core import verdicts  # noqa: E402


def graded(report):
    return CompatibilityChecker().check_compatibility(report)[0]


@pytest.mark.parametrize("builder", ["alder_lake_desktop", "coffee_lake_laptop",
                                      "raven_ridge_amd_laptop"])
def test_every_healthy_report_yields_a_row_per_graded_device(builder):
    rows = verdicts.rows(graded(getattr(fixtures, builder)()))
    assert rows, builder
    assert all(row.text for row in rows)
    assert all(row.section for row in rows)
    cpu = [row for row in rows if row.section == "CPU"]
    assert len(cpu) == 1
    assert cpu[0].compatible is True
    # HDMI audio is "Unsupported" on a healthy laptop report: a red row, not a
    # blocked build. The fatals are raised by the checker, never rendered here.
    assert {row.section for row in rows if row.compatible is False} <= {"Sound"}


def test_an_unsupported_device_is_red_but_not_fatal():
    rows = verdicts.rows({"Sound": {"Intel Cannon Lake-HDMI":
                                    {"Compatibility": [None, None]}}})
    assert rows[0].text == "Unsupported"
    assert rows[0].compatible is False


def test_an_ungraded_gpu_still_gets_a_row_because_absence_is_information():
    rows = verdicts.rows({"GPU": {"Mystery Card": {"Manufacturer": "Unknown"}}})
    assert [row.text for row in rows] == ["Unchecked"]
    assert rows[0].compatible is None
    assert rows[0].name == "Mystery Card"


def test_unsupported_and_unchecked_are_distinguished():
    rows = verdicts.rows({"Network": {"A": {"Compatibility": []}},
                          "Sound": {"B": {"Compatibility": [None, None]}}})
    by_name = {row.name: row for row in rows}
    assert by_name["A"].text == "Unchecked"
    assert by_name["A"].compatible is None
    assert by_name["B"].text == "Unsupported"
    assert by_name["B"].compatible is False


def test_sections_that_are_absent_or_empty_produce_no_rows():
    report = {"Motherboard": {"Name": "X"}, "Bluetooth": {}, "GPU": {}}
    assert verdicts.rows(report) == []


def test_a_report_of_only_unexpected_types_does_not_crash():
    report = {"CPU": "not a dict", "GPU": [1, 2], "Network": {"x": "y"}}
    assert verdicts.rows(report) == []


def test_friendly_range_sorts_regardless_of_which_end_came_first():
    native = verdicts.friendly_range(("21.2.0", "25.99.99"))
    oclp = verdicts.friendly_range(("25.99.99", "21.2.0"))
    assert native == oclp
    assert native.startswith("macOS Monterey 12")
    assert native.endswith("Tahoe 26")


def test_friendly_range_of_nothing_is_nothing():
    assert verdicts.friendly_range(None) == ""
