"""Preflight reads a built folder and reports what it can see.

Every test here is about a boundary the feature promises to keep: the analysis
never writes, never claims more than it checked, and never turns an unexplained
file into noise. A false error costs a user a rebuild; a false clean costs a boot.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import stat

import pytest

from blackdream.core import efi_preflight as preflight


def _write(path, data=b"MZ"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _config(**sections):
    document = {
        "ACPI": {"Add": []},
        "Kernel": {"Add": []},
        "UEFI": {"Drivers": []},
        "Misc": {"Tools": []},
    }
    document.update(sections)
    return document


def _build(root, config=None, *, kexts=(), acpi=(), drivers=(), tools=()):
    _write(root / "EFI/BOOT/BOOTx64.efi")
    _write(root / "EFI/OC/OpenCore.efi")
    for name in acpi:
        _write(root / "EFI/OC/ACPI" / name)
    for name in kexts:
        _write(root / "EFI/OC/Kexts" / name / "Contents/Info.plist", b"plist")
    for name in drivers:
        _write(root / "EFI/OC/Drivers" / name)
    for name in tools:
        _write(root / "EFI/OC/Tools" / name)
    document = _config() if config is None else config
    (root / "EFI/OC").mkdir(parents=True, exist_ok=True)
    (root / "EFI/OC/config.plist").write_bytes(plistlib.dumps(document, fmt=plistlib.FMT_XML))
    return root


def _snapshot(root):
    state = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            info = os.stat(path)
            with open(path, "rb") as handle:
                state[path] = (hashlib.sha256(handle.read()).hexdigest(),
                               info.st_mtime_ns, stat.S_IMODE(info.st_mode))
    return state


def _codes(report):
    return [item.code for item in report.findings]


def test_a_known_good_folder_is_clean_and_says_only_what_it_checked(tmp_path):
    config = _config(
        ACPI={"Add": [{"Path": "SSDT-AWAC.aml", "Enabled": True}]},
        Kernel={"Add": [{"BundlePath": "Lilu.kext", "Enabled": True}]},
        UEFI={"Drivers": ["OpenRuntime.efi"]},
    )
    root = _build(tmp_path / "EFI", config, acpi=["SSDT-AWAC.aml"],
                  kexts=["Lilu.kext"], drivers=["OpenRuntime.efi"])

    report = preflight.analyse(root)

    assert report.findings == ()
    assert report.clean
    assert report.files == 6
    assert report.summary == "No issues detected by these checks."
    assert "boot" not in report.summary.lower()
    text = preflight.to_text(report)
    assert "do not test firmware, hardware or whether macOS boots" in text


def test_analysis_does_not_touch_the_tree(tmp_path):
    config = _config(
        ACPI={"Add": [{"Path": "absent.aml"}]},
        Kernel={"Add": [{"BundlePath": "Absent.kext"}]},
    )
    root = _build(tmp_path / "EFI", config, acpi=["Orphan.aml"])
    before = _snapshot(root)

    preflight.analyse(root)
    preflight.to_text(preflight.analyse(root))

    assert _snapshot(root) == before


def test_a_missing_reference_is_an_error_when_enabled_and_a_warning_when_not(tmp_path):
    config = _config(
        ACPI={"Add": [
            {"Path": "Present.aml", "Enabled": True},
            {"Path": "Gone.aml", "Enabled": True},
            {"Path": "Off.aml", "Enabled": False},
        ]},
    )
    root = _build(tmp_path / "EFI", config, acpi=["Present.aml"])

    report = preflight.analyse(root)
    by_where = {item.where: item for item in report.findings}

    assert by_where["ACPI/Add/1/Path"].severity == preflight.ERROR
    assert by_where["ACPI/Add/2/Path"].severity == preflight.WARNING
    assert "Gone.aml does not exist" in by_where["ACPI/Add/1/Path"].evidence
    assert "EFI/OC/ACPI" in by_where["ACPI/Add/1/Path"].action


def test_a_kext_reference_must_be_a_folder(tmp_path):
    config = _config(Kernel={"Add": [{"BundlePath": "Lilu.kext", "Enabled": True}]})
    root = _build(tmp_path / "EFI", config)
    _write(root / "EFI/OC/Kexts/Lilu.kext", b"not a folder")

    report = preflight.analyse(root)

    assert [(item.code, item.where) for item in report.findings] == [
        ("kext.not_a_folder", "Kernel/Add/0/BundlePath")]


def test_a_duplicate_reference_is_a_warning_once(tmp_path):
    config = _config(
        UEFI={"Drivers": ["OpenRuntime.efi", {"Path": "OpenRuntime.efi"},
                          {"Path": "HfsPlus.efi"}]},
    )
    root = _build(tmp_path / "EFI", config, drivers=["OpenRuntime.efi"])

    report = preflight.analyse(root)
    duplicates = [item for item in report.findings if item.code == "entry.duplicate"]

    assert len(duplicates) == 1
    assert duplicates[0].severity == preflight.WARNING
    assert duplicates[0].where == "UEFI/Drivers"
    assert "OpenRuntime.efi" in duplicates[0].message


def test_a_malformed_plist_is_one_error_not_a_crash(tmp_path):
    root = _build(tmp_path / "EFI")
    (root / "EFI/OC/config.plist").write_bytes(b"<?xml version='1.0'?><plist><dict>")

    report = preflight.analyse(root)

    assert [item.code for item in report.findings] == ["config.unreadable"]
    assert report.errors
    assert not report.clean


def test_a_plist_whose_root_is_not_a_dictionary_is_named(tmp_path):
    root = _build(tmp_path / "EFI")
    (root / "EFI/OC/config.plist").write_bytes(plistlib.dumps(["not", "a", "dict"]))

    report = preflight.analyse(root)

    assert _codes(report) == ["config.root"]


def test_an_additional_unknown_file_is_an_informational_note(tmp_path):
    config = _config(UEFI={"Drivers": ["OpenRuntime.efi"]})
    root = _build(tmp_path / "EFI", config, drivers=["OpenRuntime.efi"],
                  kexts=["Lilu.kext"], acpi=["Spare.aml"])

    report = preflight.analyse(root)
    unreferenced = [item for item in report.findings
                    if item.code == "file.unreferenced"]

    assert {item.where for item in unreferenced} == {
        "EFI/OC/Kexts/Lilu.kext", "EFI/OC/ACPI/Spare.aml"}
    assert all(item.severity == preflight.INFO for item in unreferenced)
    assert report.clean, "an extra file alone must not read as a failure"
    assert "No issues detected by these checks." == report.summary


def test_the_manifest_and_os_noise_are_never_reported(tmp_path):
    config = _config(UEFI={"Drivers": ["OpenRuntime.efi"]})
    root = _build(tmp_path / "EFI", config, drivers=["OpenRuntime.efi"])
    (root / "EFI/OC/Drivers").joinpath(preflight.MANIFEST_NAME).write_text("{}")
    (root / "EFI/OC").joinpath(".DS_Store").write_bytes(b"\0")

    assert preflight.analyse(root).clean


def test_a_reference_that_leaves_the_folder_is_an_error(tmp_path):
    config = _config(
        ACPI={"Add": [
            {"Path": "../../etc/passwd"},
            {"Path": "/etc/passwd"},
            {"Path": "C:\\Windows\\System32\\config"},
        ]},
    )
    root = _build(tmp_path / "EFI", config)

    report = preflight.analyse(root)
    unsafe = [item for item in report.findings if item.code == "path.unsafe"]

    assert len(unsafe) == 3
    assert all(item.severity == preflight.ERROR for item in unsafe)


def test_backslashes_are_read_the_way_the_config_means_them(tmp_path):
    config = _config(
        ACPI={"Add": [{"Path": "Sub\\SSDT.aml", "Enabled": True}]},
        UEFI={"Drivers": ["OpenRuntime.efi"]},
    )
    root = _build(tmp_path / "EFI", config,
                  acpi=["Sub/SSDT.aml"], drivers=["OpenRuntime.efi"])

    assert preflight.analyse(root).clean


def test_disabled_entries_do_not_hide_a_clean_folder(tmp_path):
    config = _config(
        Kernel={"Add": [{"BundlePath": "Lilu.kext", "Enabled": False}]},
        UEFI={"Drivers": ["OpenRuntime.efi"]},
    )
    root = _build(tmp_path / "EFI", config, drivers=["OpenRuntime.efi"])

    report = preflight.analyse(root)
    missing = [item for item in report.findings if item.code == "file.missing"]

    assert missing and missing[0].severity == preflight.WARNING
    assert report.errors == ()


def test_a_folder_with_no_drivers_at_all_does_not_claim_openruntime(tmp_path):
    config = _config(UEFI={"Drivers": []})
    root = _build(tmp_path / "EFI", config)

    report = preflight.analyse(root)

    assert "driver.openruntime" not in _codes(report), (
        "a config that lists no drivers is not the same as one missing OpenRuntime")


def test_a_driver_list_without_openruntime_is_flagged(tmp_path):
    config = _config(UEFI={"Drivers": ["HfsPlus.efi"]})
    root = _build(tmp_path / "EFI", config, drivers=["HfsPlus.efi"])

    report = preflight.analyse(root)
    note = next(item for item in report.findings
                if item.code == "driver.openruntime")

    assert note.severity == preflight.WARNING
    assert "HfsPlus.efi" in note.evidence


def test_a_driver_list_none_of_which_exist_is_flagged_separately(tmp_path):
    config = _config(UEFI={"Drivers": ["HfsPlus.efi", "OpenRuntime.efi"]})
    root = _build(tmp_path / "EFI", config)

    report = preflight.analyse(root)
    notes = [item for item in report.findings if item.code == "driver.openruntime"]

    assert len(notes) == 1
    assert "no driver resolved" in notes[0].evidence


def test_missing_required_files_are_each_one_error(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()

    report = preflight.analyse(root)

    assert {item.where for item in report.findings} == {
        name for name, _why in preflight.REQUIRED}
    assert all(item.severity == preflight.ERROR for item in report.findings)


def test_a_file_is_not_a_folder(tmp_path):
    path = tmp_path / "EFI"
    path.write_text("x")

    with pytest.raises(preflight.PreflightError):
        preflight.analyse(path)


def test_a_mount_point_is_refused_before_it_is_read(tmp_path, monkeypatch):
    root = _build(tmp_path / "EFI")
    monkeypatch.setattr(preflight.os.path, "ismount", lambda path: True)

    with pytest.raises(preflight.PreflightError) as raised:
        preflight.analyse(root)

    assert "mount" in str(raised.value)


def test_findings_are_ordered_by_severity_then_place(tmp_path):
    config = _config(
        ACPI={"Add": [{"Path": "Zeta.aml"}, {"Path": "Alpha.aml"}]},
        Kernel={"Add": [{"BundlePath": "Lilu.kext"}]},
        UEFI={"Drivers": ["OpenRuntime.efi"]},
        Misc={"Tools": [{"Path": "Shell.efi"}]},
    )
    root = _build(tmp_path / "EFI", config, drivers=["OpenRuntime.efi"])

    report = preflight.analyse(root)

    severities = [preflight._SEVERITY_ORDER[item.severity] for item in report.findings]
    assert severities == sorted(severities)
    errors = [item.where for item in report.errors]
    assert errors == sorted(errors, key=str.casefold)


def test_counting_is_reported_and_reflected_in_text(tmp_path):
    config = _config(UEFI={"Drivers": ["OpenRuntime.efi", "HfsPlus.efi"]})
    root = _build(tmp_path / "EFI", config, drivers=["OpenRuntime.efi",
                                                   "HfsPlus.efi",
                                                   "Extra.efi"])

    report = preflight.analyse(root)
    text = preflight.to_text(report)

    assert "Files read: {}".format(report.files) in text
    assert "Result: {}".format(report.summary) in text
    assert "[INFO] EFI/OC/Drivers/Extra.efi" in text
