"""Comparing two reports separates hardware facts from recorded engine output.

A changed compatibility tuple is not a changed machine: the only safe statement
the diff can make is that the two files disagree. These tests pin that boundary.

They also pin the naming. A report keys each device by its own printable name, and
so does the Compatibility table; a comparison that renamed devices could not be
read against the table the user just looked at.
"""

from __future__ import annotations

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import tests.fixtures as fixtures  # noqa: E402

from blackdream.core import report_compare as compared  # noqa: E402
from blackdream.core import verdicts  # noqa: E402

COMPAT = ("22.99.99", "17.99.99")


def _report():
    """A partly graded coffee-lake laptop, with the GPU left ungraded.

    Only CPU, Network and Sound carry a recorded verdict, the way a report graded
    by an older engine would: the comparison must still see the other devices.
    """
    report = copy.deepcopy(fixtures.coffee_lake_laptop())
    report["CPU"]["Compatibility"] = list(COMPAT)
    for section in ("Network", "Sound"):
        for device in report[section].values():
            device["Compatibility"] = list(COMPAT)
    return report


def test_identical_reports_have_no_changes_and_an_empty_export():
    before = _report()

    result = compared.compare(before, copy.deepcopy(before))
    text = compared.to_text(result)

    assert result.empty
    assert result.changes == ()
    assert result.devices_before == result.devices_after == 12
    assert result.unchanged == 12
    assert text.startswith("BlackDream report comparison\n")
    assert "No differences." in text


def test_devices_are_named_from_the_report_key_the_table_uses():
    report = _report()

    found = compared.devices(report)
    graded = [(verdict.section, verdict.name) for verdict in verdicts.rows(report)]

    assert list(found) == [
        ("CPU", "Intel Core i7-8550U"),
        ("GPU", "Intel UHD Graphics 630"),
        ("Storage Controllers", "Intel Cannon Lake AHCI"),
        ("Network", "Intel I219-V"),
        ("Network", "Intel Wi-Fi 6 AX201"),
        ("Sound", "Intel Cannon Lake-HDMI"),
        ("Sound", "Realtek ALC236"),
        ("USB Controllers", "Intel Cannon Lake USB"),
        ("Bluetooth", "Intel Bluetooth AX201"),
        ("SD Controller", "Realtek Card Reader"),
        ("Monitor", "CMO Integrated Camera"),
        ("Monitor", "Dell USB-C Dock"),
    ]
    # Every device the table shows is here under the same name, in the same order.
    assert graded == [key for key in found if key in graded]


def test_a_device_the_engine_never_graded_is_still_compared():
    report = {"Network": {"Realtek RTL8125": {"Device ID": "10EC-8125"}}}

    assert list(compared.devices(report)) == [("Network", "Realtek RTL8125")]
    assert verdicts.rows(report) == []


def test_a_device_present_only_in_the_later_report_is_added():
    before = _report()
    after = _report()
    after["Network"]["Intel Wi-Fi 7 BE200"] = {
        "Device ID": "8086-00F0", "Compatibility": list(COMPAT)}

    result = compared.compare(before, after)

    assert [(item.kind, item.section, item.name) for item in result.changes] == [
        ("added", "Network", "Intel Wi-Fi 7 BE200")]
    assert result.devices_before == 12
    assert result.devices_after == 13
    assert result.unchanged == 12


def test_a_device_present_only_in_the_earlier_report_is_removed():
    before = _report()
    after = _report()
    del after["Sound"]["Realtek ALC236"]

    result = compared.compare(before, after)

    assert [(item.kind, item.section, item.name) for item in result.changes] == [
        ("removed", "Sound", "Realtek ALC236")]
    assert result.devices_before == 12
    assert result.devices_after == 11
    assert result.unchanged == 11


def test_a_changed_device_id_is_a_hardware_change_and_fields_join_with_semicolons():
    before = {"Network": {"Ethernet": {
        "Manufacturer": "Intel", "Device ID": "0x1234",
        "Compatibility": list(COMPAT)}}}
    after = copy.deepcopy(before)
    after["Network"]["Ethernet"]["Manufacturer"] = "AMD"
    after["Network"]["Ethernet"]["Device ID"] = "0x5678"

    result = compared.compare(before, after)

    assert len(result.changes) == 1
    change = result.changes[0]
    assert (change.kind, change.section, change.name) == (
        "hardware", "Network", "Ethernet")
    assert change.detail == (
        "Manufacturer: Intel -> AMD; Device ID: 0x1234 -> 0x5678")
    assert result.unchanged == 0


def test_a_recorded_compatibility_change_alone_is_a_reading_change():
    before = _report()
    after = _report()
    after["Network"]["Intel I219-V"]["Compatibility"] = ["23.99.99", "17.99.99"]

    result = compared.compare(before, after)

    assert len(result.changes) == 1
    change = result.changes[0]
    assert (change.kind, change.section, change.name) == (
        "reading", "Network", "Intel I219-V")
    assert change.detail == (
        "Compatibility: (22.99.99, 17.99.99) -> (23.99.99, 17.99.99)")
    assert result.unchanged == 11


def test_an_ungraded_gpu_is_still_a_device_and_compares_unchanged():
    report = {"GPU": {"Mystery Card": {
        "Manufacturer": "Unknown", "Device ID": "0x1234"}}}

    found = compared.devices(report)
    result = compared.compare(report, copy.deepcopy(report))

    assert list(found) == [("GPU", "Mystery Card")]
    device = found[("GPU", "Mystery Card")]
    assert device.compatibility is None
    assert device.oclp is None
    assert device.fields == (
        ("Manufacturer", "Unknown"), ("Device ID", "0x1234"))
    assert result.empty
    assert result.unchanged == 1


def test_two_different_machines_are_compared_device_by_device():
    result = compared.compare(fixtures.coffee_lake_laptop(),
                              fixtures.alder_lake_desktop())

    kinds = [(item.kind, item.section, item.name) for item in result.changes]
    assert ("removed", "CPU", "Intel Core i7-8550U") in kinds
    assert ("added", "CPU", "Intel Core i5-12600K") in kinds
    assert ("removed", "GPU", "Intel UHD Graphics 630") in kinds
    assert ("added", "GPU", "AMD Radeon RX 6600") in kinds
    assert ("removed", "SD Controller", "Realtek Card Reader") in kinds
    assert not [item for item in kinds if item[0] in ("hardware", "reading")]
    assert result.devices_before == 12
    assert result.devices_after == 9


def test_a_section_level_compatibility_block_is_one_cpu_device():
    report = {"CPU": {
        "Processor Name": "Intel Core i7-8550U",
        "Manufacturer": "Intel",
        "Device ID": "8086-3E9B",
        "Compatibility": list(COMPAT),
        "OCLP Compatibility": ["25.99.99", "21.2.0"],
    }}

    found = compared.devices(report)

    assert list(found) == [("CPU", "Intel Core i7-8550U")]
    device = found[("CPU", "Intel Core i7-8550U")]
    assert device.fields == (
        ("Processor Name", "Intel Core i7-8550U"),
        ("Manufacturer", "Intel"),
        ("Device ID", "8086-3E9B"),
    )
    assert device.compatibility == COMPAT
    assert device.oclp == ("25.99.99", "21.2.0")


def test_only_hardware_keys_are_kept_in_declared_order_and_stringified():
    report = {"Sound": {"Codec": {
        "Device Type": "Audio", "Subsystem": "0x10281234",
        "Vendor": "", "Codename": "ignored", "Device ID": 0x1234,
        "Compatibility": list(COMPAT)}}}

    device = compared.devices(report)[("Sound", "Codec")]

    assert device.fields == (
        ("Device ID", "4660"), ("Subsystem", "0x10281234"),
        ("Device Type", "Audio"))


def test_the_export_labels_every_kind_in_order_and_states_the_boundary():
    before = _report()
    after = _report()
    del after["Sound"]["Realtek ALC236"]
    after["Network"]["New NIC"] = {"Compatibility": list(COMPAT)}
    after["Network"]["Intel I219-V"]["Device ID"] = "8086-FFFF"
    after["Network"]["Intel Wi-Fi 6 AX201"]["Compatibility"] = [
        "23.99.99", "17.99.99"]

    result = compared.compare(before, after)
    text = compared.to_text(result)
    sentence = (
        "A recorded compatibility change can come from a different engine or "
        "database version, not from this machine. Neither side was re-graded.")

    assert "Devices before: 12" in text
    assert "Devices after: 12" in text
    assert "Hardware changes: 1" in text
    assert "Recorded compatibility changes: 1" in text
    assert "Unchanged: 9" in text
    assert "[REMOVED] Sound: Realtek ALC236" in text
    assert "[ADDED] Network: New NIC" in text
    assert "[HARDWARE] Network: Intel I219-V" in text
    assert "Device ID: 8086-15B8 -> 8086-FFFF" in text
    assert "[READING] Network: Intel Wi-Fi 6 AX201" in text
    assert "Compatibility: (22.99.99, 17.99.99) -> (23.99.99, 17.99.99)" in text
    assert (text.index("[REMOVED]") < text.index("[ADDED]")
            < text.index("[HARDWARE]") < text.index("[READING]"))
    assert sentence in text
    assert text.rstrip("\n").endswith(sentence)
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_all_hardware_changes_precede_all_reading_changes():
    before = {"Network": {
        "A": {"Device ID": "1", "Compatibility": list(COMPAT)},
        "B": {"Device ID": "2", "Compatibility": list(COMPAT)},
    }}
    after = copy.deepcopy(before)
    after["Network"]["A"]["Device ID"] = "10"
    after["Network"]["B"]["Device ID"] = "20"
    after["Network"]["A"]["Compatibility"] = ["23.99.99", "17.99.99"]
    after["Network"]["B"]["Compatibility"] = ["24.99.99", "17.99.99"]

    result = compared.compare(before, after)

    assert [item.kind for item in result.changes] == [
        "hardware", "hardware", "reading", "reading"]
    assert [item.name for item in result.changes] == ["A", "B", "A", "B"]
    assert result.unchanged == 0


def test_compare_and_export_do_not_mutate_either_report():
    before = _report()
    after = _report()
    after["Network"]["Intel I219-V"]["Device ID"] = "8086-FFFF"
    after["Network"]["Intel Wi-Fi 6 AX201"]["Compatibility"] = [
        "23.99.99", "17.99.99"]
    before_copy = copy.deepcopy(before)
    after_copy = copy.deepcopy(after)

    result = compared.compare(before, after)
    compared.to_text(result)

    assert before == before_copy
    assert after == after_copy
