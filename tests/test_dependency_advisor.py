"""The dependency advisor explains; it never edits, never guesses, and never cites a
line that is not there.

Three things make an advisory worth showing at all. It must come from a rule the
repository actually contains (so a tester can check the claim), it must survive the
edits a real session makes (so it is not noise), and it must stay silent when the
document does not carry the section the rule needs. Every test here defends one of
those three, plus the no-write boundary the feature promises.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from blackdream.core import config_editor
from blackdream.core import dependency_advisor as advisor

SRC = Path(__file__).resolve().parents[1] / "src"

BOOT_ARGS = ("NVRAM", "Add", advisor.BOOT_SERVICES_GUID, "boot-args")


def _kext(name, **fields) -> dict:
    entry = {"BundlePath": "{}.kext".format(name), "Enabled": True}
    entry.update(fields)
    return entry


def _config(*, add=(), drivers=None, args=None, quirks=None, booter=None,
            platform=None) -> dict:
    """A document with only the sections a rule needs, so a test cannot pass by
    accident on a section it never meant to supply."""
    document: dict = {"Kernel": {"Add": list(add)}}
    if drivers is not None:
        document["UEFI"] = {"Drivers": [{"Path": name, "Enabled": True}
                                        for name in drivers]}
    if args is not None:
        document["NVRAM"] = {"Add": {advisor.BOOT_SERVICES_GUID: {"boot-args": args}}}
    if quirks is not None:
        document["Kernel"]["Quirks"] = dict(quirks)
    if booter is not None:
        document["Booter"] = {"Quirks": dict(booter)}
    if platform is not None:
        document["PlatformInfo"] = dict(platform)
    return document


def _rules(report) -> list[str]:
    return [item.rule for item in report.advisories]


def _one(report, rule) -> advisor.Advisory:
    matches = [item for item in report.advisories if item.rule == rule]
    assert len(matches) == 1, "expected exactly one {}, got {!r}".format(
        rule, _rules(report))
    return matches[0]


# --- the boundary: reading a config must not change it -----------------------------

def test_the_advisor_leaves_the_document_byte_for_byte_as_it_found_it():
    document = config_editor.sample_plist()
    document["Kernel"]["Add"] = [
        _kext("AppleALC"), _kext("SMCBatteryManager"), _kext("WhateverGreen"),
        _kext("WhateverGreen"),
    ]
    document["NVRAM"]["Add"][advisor.BOOT_SERVICES_GUID]["boot-args"] = (
        "-v alcid=11 ctrsmt=full")
    document["Kernel"]["Quirks"]["AppleCpuPmCfgLock"] = True
    document["Kernel"]["Quirks"]["AppleXcpmCfgLock"] = True
    before = copy.deepcopy(document)
    payload = config_editor.serialize_document(document)

    report = advisor.advise(document, target="23.99.99")

    assert report.advisories, "this document should not read as clean"
    assert document == before
    assert config_editor.serialize_document(document) == payload


def test_the_advisor_never_touches_the_engine_s_session_state():
    """``kext_data`` rows carry a mutable ``checked`` flag owned by a build session."""
    from ocengine.datasets import kext_data

    before = {kext.name: (kext.checked, kext.min_darwin_version, kext.max_darwin_version)
              for kext in kext_data.kexts}
    advisor.advise(_config(add=[_kext("AppleALC")]), target="23.99.99")
    assert {kext.name: (kext.checked, kext.min_darwin_version, kext.max_darwin_version)
            for kext in kext_data.kexts} == before


def test_a_document_that_is_not_a_dictionary_is_refused_before_any_rule_runs():
    with pytest.raises(advisor.AdvisorError):
        advisor.advise(["Kernel", "Add"])
    with pytest.raises(advisor.AdvisorError):
        advisor.advise(None)


@pytest.mark.parametrize("broken", [
    {"Kernel": "not a dict", "UEFI": 3, "NVRAM": [], "Booter": None,
     "PlatformInfo": "x"},
    {"Kernel": {"Add": "not a list"}},
    {"Kernel": {"Add": ["", None, 7, {"BundlePath": []}, {"BundlePath": "Lilu"}]}},
    {"NVRAM": {"Add": {advisor.BOOT_SERVICES_GUID: {"boot-args": 42}}}},
])
def test_a_malformed_section_reads_as_nothing_rather_than_as_an_advisory(broken):
    assert advisor.advise(broken, target="23.99.99").advisories == ()


# --- the rules come from this repository -------------------------------------------

def test_every_citation_names_a_file_and_lines_that_exist_here():
    """The roadmap's exit condition - rules are explainable - as a machine check.

    A source string is the only thing between an advisory and a guess, so a citation
    that points past the end of a file, or at a file that is not vendored here, fails.
    """
    document = _config(
        add=[_kext("SMCBatteryManager"), _kext("Lilu"),
             _kext("AppleALC", MaxKernel="20.4.0"), _kext("WhateverGreen"),
             _kext("NootRX"), _kext("Lilu"), _kext("VirtualSMC")],
        drivers=["HfsPlus.efi", "HfsPlusLegacy.efi"],
        args="-v alcid=7 ctrsmt=full agdpmod=pikera",
        quirks={"AppleCpuPmCfgLock": True, "AppleXcpmCfgLock": True,
                "CustomSMBIOSGuid": True},
        booter={"EnableSafeModeSlide": True, "ProvideCustomSlide": False,
                "EnableWriteUnprotector": True, "RebuildAppleMemoryMap": True,
                "ResizeAppleGpuBars": 0},
        platform={"UpdateSMBIOSMode": "Release"})
    document["NVRAM"]["Add"]["00000000-1111-2222-3333-444444444444"] = {"boot-args": "-v"}

    report = advisor.advise(document, target="23.99.99")
    assert report.advisories
    seen = set()
    for item in report.advisories:
        match = re.match(r"^([\w/.-]+\.py):(.*)$", item.source)
        assert match, "source is not a file:line citation: {!r}".format(item.source)
        path, coordinates = match.group(1), match.group(2)
        target_file = SRC / path
        assert target_file.is_file(), "cited file is not in this repo: {}".format(path)
        lines = target_file.read_text(encoding="utf-8").splitlines()
        numbers = [int(number) for number in re.findall(r"\d+", coordinates)]
        assert numbers, "citation carries no line number: {!r}".format(item.source)
        for number in numbers:
            assert number <= len(lines), "{}:{} is past the end ({} lines)".format(
                path, number, len(lines))
        seen.add(item.rule)

    assert seen == {item.rule for item in report.advisories}
    assert len(seen) >= 10, "a kitchen-sink config should exercise most of the ruleset"


@pytest.mark.parametrize("source, token", [
    ("ocengine/datasets/kext_data.py:12", "requires_kexts"),
    ("ocengine/datasets/kext_data.py:13", "conflict_group_id"),
    ("ocengine/kext_maestro.py:1201-1203", "BundleLibraries"),
    ("ocengine/kext_maestro.py:1228-1231", 'bundle["Enabled"] = False'),
    ("ocengine/kext_maestro.py:645-649", "requires_kexts"),
    ("ocengine/config_prodigy.py:645", "OpenRuntime.efi"),
    ("ocengine/config_prodigy.py:710", "AppleXcpmCfgLock"),
    ("ocengine/config_prodigy.py:751", 'UpdateSMBIOSMode"] = "Custom"'),
    ("ocengine/config_prodigy.py:744", "boot-args"),
])
def test_a_citation_lands_on_the_line_the_rule_claims(source, token):
    """Spot-checks that a citation is not merely in range but about the right thing."""
    path, coordinates = source.split(":", 1)
    number = int(re.match(r"\d+", coordinates).group(0))
    lines = (SRC / path).read_text(encoding="utf-8").splitlines()
    window = "\n".join(lines[number - 1:number + 2])
    assert token in window, "{} expected near {}:{}".format(token, path, number)


# --- kext relationships ------------------------------------------------------------

def test_a_plugin_enabled_before_its_parent_is_an_error():
    report = advisor.advise(_config(add=[_kext("VirtualSMC"), _kext("Lilu")]))
    item = _one(report, "order.parent_after_dependent")
    assert item.severity == advisor.ERROR
    assert item.confidence == advisor.HIGH
    assert "Lilu" in item.trigger and "VirtualSMC" in item.trigger


def test_a_dependency_the_config_does_not_contain_at_all_is_named():
    report = advisor.advise(_config(add=[_kext("AppleALC")]))
    item = _one(report, "dependency.missing")
    assert item.trigger == "AppleALC is enabled, but Lilu is not in Kernel/Add."
    assert item.advice.startswith("Add Lilu.kext")


def test_a_dependency_that_is_present_but_disabled_points_at_its_enabled_key():
    document = _config(add=[_kext("AppleALC"), _kext("Lilu", Enabled=False)])
    item = _one(advisor.advise(document), "dependency.disabled")
    assert item.path == ("Kernel", "Add", 1, "Enabled")
    assert "switched off" in item.trigger


def test_the_nested_path_of_a_plugin_resolves_to_the_catalogue_name():
    document = _config(add=[
        {"BundlePath": "VoodooI2C.kext/Contents/PlugIns/VoodooI2CHID.kext",
         "Enabled": True}])
    report = advisor.advise(document)
    item = _one(report, "dependency.missing")
    assert "VoodooI2CHID" in item.trigger and "VoodooI2C" in item.trigger


def test_a_kext_the_catalogue_does_not_know_is_left_alone():
    report = advisor.advise(_config(add=[_kext("SomeBrandNewKext")]))
    assert report.advisories == ()


def test_three_kexts_claiming_the_same_hardware_each_name_the_other_two():
    report = advisor.advise(_config(add=[
        _kext("WhateverGreen"), _kext("NootRX"), _kext("NootedRed")]))
    items = [item for item in report.advisories if item.rule == "conflict.group"]
    assert len(items) == 3
    weg = next(item for item in items if "WhateverGreen" in item.where)
    assert "NootRX" in weg.trigger and "NootedRed" in weg.trigger
    assert "graphics support" in weg.trigger
    assert all(item.severity == advisor.WARNING for item in items)


def test_a_disabled_rival_in_the_same_group_is_not_a_conflict():
    report = advisor.advise(_config(add=[
        _kext("WhateverGreen"), _kext("NootedRed", Enabled=False), _kext("Lilu")]))
    assert "conflict.group" not in _rules(report)


def test_a_repeated_bundle_is_reported_once_and_the_disabled_twin_is_ignored():
    report = advisor.advise(_config(add=[
        _kext("Lilu"), _kext("AppleALC"), _kext("Lilu")]))
    assert _rules(report).count("entry.duplicate") == 1
    only_disabled_twin = advisor.advise(_config(add=[
        _kext("Lilu"), _kext("Lilu", Enabled=False), _kext("AppleALC")]))
    assert "entry.duplicate" not in _rules(only_disabled_twin)


# --- version windows -------------------------------------------------------------

def test_a_window_that_excludes_the_release_is_reported_once_not_twice():
    document = _config(add=[_kext("Lilu"), _kext("AppleALC", MinKernel="",
                                                 MaxKernel="20.4.0")],
                       args="-v")
    report = advisor.advise(document, target="23.99.99")
    assert _rules(report).count("window.excludes_target") == 1
    assert "boot_arg.lilubeta_missing" not in _rules(report)


def test_a_min_kernel_above_the_release_is_the_error_direction():
    document = _config(add=[_kext("Lilu"), _kext("AppleALC", MinKernel="24.0.0",
                                                 MaxKernel="")], args="-v")
    item = _one(advisor.advise(document, target="22.99.99"), "window.excludes_target")
    assert item.path[-1] == "MinKernel"
    assert "24.0.0" in item.evidence


def test_an_empty_window_is_no_window_at_all():
    """The engine writes "" to mean the whole range, so "" must not be a bound."""
    document = _config(add=[_kext("Lilu"), _kext("AppleALC", MinKernel="",
                                                 MaxKernel="")], args="-v")
    assert advisor.advise(document, target="23.99.99").advisories == ()


def test_a_garbage_window_bound_is_not_turned_into_an_advisory():
    document = _config(add=[_kext("Lilu"), _kext("AppleALC", MinKernel="Monterey",
                                                 MaxKernel="22")], args="-v")
    assert "window.excludes_target" not in _rules(advisor.advise(document, target="23"))


def test_without_a_selected_release_the_window_checks_say_what_they_skipped():
    document = _config(add=[_kext("Lilu"), _kext("AppleALC", MaxKernel="20.4.0")])
    report = advisor.advise(document)
    assert report.advisories == ()
    assert "No macOS release was selected" in report.skipped[0]
    assert "Not checked:" in advisor.to_text(report)


def test_the_lilu_beta_flag_is_inferred_from_the_catalogue_when_the_plist_has_no_bound():
    document = _config(add=[_kext("Lilu"), _kext("CryptexFixup")], args="-v")
    report = advisor.advise(document, target="12.99.99")
    item = _one(report, "boot_arg.lilubeta_missing")
    assert item.severity == advisor.WARNING
    assert "-lilubetaall" in item.advice
    still_clean = advisor.advise(_config(add=[_kext("Lilu"), _kext("CryptexFixup")],
                                         args="-v -lilubetaall"), target="12.99.99")
    assert "boot_arg.lilubeta_missing" not in _rules(still_clean)


# --- boot-args -------------------------------------------------------------------

def test_a_boot_arg_whose_kext_is_absent_is_a_warning_about_both():
    report = advisor.advise(_config(add=[_kext("Lilu")], args="-v alcid=11"))
    item = _one(report, "boot_arg.orphan")
    assert item.severity == advisor.WARNING
    assert item.confidence == advisor.MEDIUM
    assert "AppleALC" in item.trigger
    assert item.path == BOOT_ARGS


def test_a_boot_arg_whose_kext_is_present_is_not_an_orphan():
    report = advisor.advise(_config(add=[_kext("Lilu"), _kext("AppleALC")],
                                    args="-v alcid=11"))
    assert "boot_arg.orphan" not in _rules(report)


def test_pikera_without_whatevergreen_is_a_note_rather_than_a_warning():
    report = advisor.advise(_config(add=[_kext("Lilu")], args="-v agdpmod=pikera"))
    item = _one(report, "boot_arg.pikera_without_weg")
    assert item.severity == advisor.INFO


def test_boot_args_under_another_guid_are_inert():
    document = _config(add=[_kext("Lilu")], args="-v")
    document["NVRAM"]["Add"]["4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14"] = {
        "boot-args": "-v alcid=11"}
    report = advisor.advise(document)
    item = _one(report, "boot_args.wrong_guid")
    assert item.severity == advisor.WARNING
    assert "4D1EDE05" in item.where
    assert item.path[2] == "4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14"


def test_an_unreadable_boot_args_value_is_ignored_not_guessed():
    document = _config(add=[_kext("Lilu")])
    document["NVRAM"] = {"Add": {advisor.BOOT_SERVICES_GUID: {"boot-args": None}}}
    assert advisor.advise(document).advisories == ()


# --- drivers ---------------------------------------------------------------------

def test_openruntime_absent_from_a_real_drivers_list_is_an_error():
    report = advisor.advise(_config(drivers=["HfsPlus.efi"]))
    item = _one(report, "driver.pairing")
    assert item.severity == advisor.ERROR
    assert "OpenRuntime.efi" in item.trigger


def test_a_document_without_a_uefi_section_is_not_told_a_driver_is_missing():
    assert advisor.advise({"Kernel": {"Add": []}}).advisories == ()
    assert advisor.advise({"UEFI": "not a dict"}).advisories == ()


def test_both_hfs_variants_together_are_a_pairing_problem():
    report = advisor.advise(_config(drivers=["OpenRuntime.efi", "HfsPlus.efi",
                                             "HfsPlusLegacy.efi"]))
    item = _one(report, "driver.pairing")
    assert "HfsPlusLegacy.efi" in item.trigger


def test_a_tahoe_target_notes_the_apfs_driver_the_engine_would_have_added():
    clean = advisor.advise(_config(drivers=["OpenRuntime.efi"],
                                   args="-v"), target="23.99.99")
    assert clean.advisories == ()
    tahoe = advisor.advise(_config(drivers=["OpenRuntime.efi"], args="-v"),
                           target="25.99.99")
    item = _one(tahoe, "driver.tahoe_apfs")
    assert item.severity == advisor.INFO


# --- quirks ----------------------------------------------------------------------

def test_two_slide_quirks_that_agree_are_not_an_advisory_even_when_both_are_on():
    """The engine derives both from the firmware type, so agreement is the correct
    state - in either direction. A rule that read this the other way round would
    flag every UEFI build the engine makes."""
    for value in (True, False):
        report = advisor.advise(_config(booter={"EnableSafeModeSlide": value,
                                               "ProvideCustomSlide": value}))
        assert "quirk.slide_pair" not in _rules(report), value


def test_two_slide_quirks_that_disagree_are_reported():
    report = advisor.advise(_config(booter={"EnableSafeModeSlide": True,
                                            "ProvideCustomSlide": False}))
    item = _one(report, "quirk.slide_pair")
    assert "EnableSafeModeSlide is on" in item.trigger
    assert "ProvideCustomSlide is off" in item.trigger


def test_both_cfg_locks_off_is_what_the_engine_writes_for_amd():
    report = advisor.advise(_config(quirks={"AppleCpuPmCfgLock": False,
                                           "AppleXcpmCfgLock": False}))
    assert "quirk.cfg_locks" not in _rules(report)


def test_both_cfg_locks_on_is_the_impossible_case():
    report = advisor.advise(_config(quirks={"AppleCpuPmCfgLock": True,
                                           "AppleXcpmCfgLock": True}))
    assert _one(report, "quirk.cfg_locks").severity == advisor.WARNING


def test_a_write_unprotector_and_a_memory_rebuild_both_on_is_reported():
    report = advisor.advise(_config(booter={"EnableWriteUnprotector": True,
                                            "RebuildAppleMemoryMap": True}))
    assert _one(report, "quirk.memory_map").rule == "quirk.memory_map"


def test_a_non_boolean_quirk_value_is_not_reasoned_about():
    report = advisor.advise(_config(booter={"EnableSafeModeSlide": "TRUE",
                                            "ProvideCustomSlide": False}))
    assert "quirk.slide_pair" not in _rules(report)


def test_a_custom_guid_without_a_custom_smbios_mode_is_reported():
    report = advisor.advise(_config(quirks={"CustomSMBIOSGuid": True},
                                    platform={"UpdateSMBIOSMode": "Release"}))
    item = _one(report, "quirk.smbios_guid_mode")
    assert item.path == ("PlatformInfo", "UpdateSMBIOSMode")

    fine = advisor.advise(_config(quirks={"CustomSMBIOSGuid": True},
                                  platform={"UpdateSMBIOSMode": "Custom"}))
    assert fine.advisories == ()
    off = advisor.advise(_config(quirks={"CustomSMBIOSGuid": False},
                                 platform={"UpdateSMBIOSMode": "Release"}))
    assert off.advisories == ()


def test_npci_while_gpu_bars_are_disabled_is_the_pair_the_engine_never_writes():
    report = advisor.advise(_config(booter={"ResizeAppleGpuBars": 0}, args="npci=0x2000"))
    assert _one(report, "quirk.resize_bars_npai").severity == advisor.WARNING

    both_ways = advisor.advise(_config(booter={"ResizeAppleGpuBars": -1},
                                       args="npci=0x2000"))
    assert both_ways.advisories == ()
    no_arg = advisor.advise(_config(booter={"ResizeAppleGpuBars": 0}, args="-v"))
    assert no_arg.advisories == ()


# --- ordering, summaries and export ----------------------------------------------

def test_errors_are_listed_before_notes_and_high_confidence_first():
    document = _config(add=[_kext("AppleALC")], drivers=["HfsPlus.efi"],
                       args="-v ctrsmt=full", booter={"EnableSafeModeSlide": True,
                                                      "ProvideCustomSlide": False})
    severities = [item.severity for item in advisor.advise(document).advisories]
    assert severities == ["error", "error", "warning", "warning"]


def test_the_summary_counts_in_words_and_never_claims_more():
    assert advisor.advise({}).summary == "No dependency issues detected by these checks."
    report = advisor.advise(_config(add=[_kext("AppleALC")], args="-v ctrsmt=full"))
    assert report.summary == "1 error, 1 warning."
    assert advisor.advise(_config(add=[_kext("AppleALC"), _kext("VirtualSMC")],
                                  args="")).summary.startswith("2 errors")
    assert advisor.advise(_config(add=[_kext("Lilu")],
                                  args="-v agdpmod=pikera")).summary == "1 note."


def test_the_export_states_the_boundary_a_reader_might_otherwise_assume():
    report = advisor.advise(_config(add=[_kext("AppleALC")]))
    text = advisor.to_text(report)
    assert "Ruleset: {}".format(report.rules) in text
    assert "do not reorder kexts, do not change any quirk" in text
    assert "whether macOS boots" in text
    assert "dependency.missing" in text
    assert advisor.to_text(advisor.advise({})).endswith("No advisories.\n")


def test_the_advisory_path_resolves_in_the_editor_for_every_rule():
    """A jump-to-key is only a promise if the path addresses a real node."""
    document = _config(
        add=[_kext("AppleALC"), _kext("SMCBatteryManager"), _kext("WhateverGreen"),
             _kext("NootRX")],
        drivers=["HfsPlus.efi", "HfsPlusLegacy.efi"],
        args="-v alcid=7 ctrsmt=full",
        quirks={"AppleCpuPmCfgLock": True, "AppleXcpmCfgLock": True,
                "CustomSMBIOSGuid": True},
        booter={"EnableSafeModeSlide": True, "ProvideCustomSlide": False,
                "EnableWriteUnprotector": True, "RebuildAppleMemoryMap": True,
                "ResizeAppleGpuBars": 0},
        platform={"UpdateSMBIOSMode": "Release"})
    report = advisor.advise(document, target="22.99.99")
    assert len(report.advisories) >= 8
    for item in report.advisories:
        assert item.path, item.rule
        config_editor.get_at(document, item.path)


# --- dismissals -------------------------------------------------------------------

def test_a_dismissed_advisory_disappears_and_comes_back():
    report = advisor.advise(_config(add=[_kext("AppleALC")]))
    item = report.advisories[0]
    keys = advisor.dismiss((), item)
    assert advisor.visible(report, keys) == ()
    assert advisor.visible(report, advisor.restore(keys, item)) == report.advisories


def test_a_dismissal_survives_the_reorder_it_asked_about():
    """The key must not be the row index: an index moves when a neighbour is removed."""
    before = advisor.advise(_config(add=[_kext("AppleALC"), _kext("WhateverGreen")]))
    after = advisor.advise(_config(add=[_kext("AppleALC"), _kext("NullEthernet"),
                                        _kext("WhateverGreen")]))
    keys_before = sorted(item.dismissal_key for item in before.advisories)
    keys_after = sorted(item.dismissal_key for item in after.advisories)
    assert len(keys_before) == 2
    assert keys_before == keys_after
    assert all("/1/" not in key and "/2/" not in key for key in keys_after)


def test_the_dismissal_file_round_trips_and_a_corrupt_one_reads_as_nothing(tmp_path):
    path = tmp_path / "advisor-dismissals.json"
    report = advisor.advise(_config(add=[_kext("AppleALC")]))
    keys = advisor.dismiss((), report.advisories[0])

    assert advisor.save_dismissals(keys, path) == path
    assert advisor.load_dismissals(path) == keys
    assert advisor.load_dismissals(tmp_path / "absent.json") == frozenset()

    path.write_text("{ this is not json", encoding="utf-8")
    assert advisor.load_dismissals(path) == frozenset()
    path.write_text('{"dismissed": ["1|dependency.missing|x"]}', encoding="utf-8")
    assert advisor.load_dismissals(path) == frozenset()


def test_a_dismissal_made_under_an_older_ruleset_stays_hidden_no_longer(tmp_path):
    path = tmp_path / "advisor-dismissals.json"
    advisor.save_dismissals(frozenset({"99|dependency.missing|Kernel/Add/AppleALC/Lilu"}),
                            path)
    report = advisor.advise(_config(add=[_kext("AppleALC")]))
    assert advisor.visible(report, advisor.load_dismissals(path)) == report.advisories


def test_the_default_dismissal_file_lives_in_the_local_state_directory(tmp_path, monkeypatch):
    class _Paths:
        state_dir = tmp_path / "state"

    monkeypatch.setattr(advisor.paths, "current", lambda: _Paths())
    assert advisor.default_dismissal_path() == tmp_path / "state" / "advisor-dismissals.json"
