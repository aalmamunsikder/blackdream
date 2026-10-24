"""The schema preview is a reading, never a migration.

These tests pin the three claims it makes: what the pinned sample declares and this
file lacks, what this file has that the sample does not, and where a shared path
has a different plist type. They also pin the boundary: non-empty sample tables are
reported but never copied into the projection, no input is mutated, and the report
says that nothing was applied.
"""

from __future__ import annotations

import copy

from blackdream.core import config_editor
from blackdream.core import schema_preview as preview

CLOSING = "This preview changes nothing. A migration would need a review and a save."
CAVEAT = ("A key that is missing from this config may be optional or unnecessary "
          "for this machine.")


def _run(document, sample, version="1.0.8"):
    return preview.compare(document, sample, version)


def _pairs(result):
    return [(item.kind, item.label) for item in result.findings]


def test_identical_documents_report_nothing():
    document = {"A": 1, "B": {"C": "x"}}
    sample = copy.deepcopy(document)

    result = _run(document, sample)

    assert result.empty
    assert result.findings == ()
    assert result.missing == () and result.extra == () and result.types == ()
    assert result.projected == document


def test_a_missing_scalar_is_reported_and_added_to_the_projection():
    document = {"Keep": 1}
    sample = {"Keep": 1, "Name": "hello", "Flag": True, "ROM": b"\x01\x02"}

    result = _run(document, sample)

    assert [item.path for item in result.missing] == [
        ("Flag",), ("Name",), ("ROM",)]
    name = next(item for item in result.missing if item.path == ("Name",))
    assert name.schema == "hello"
    assert name.current == ""
    assert name.label == "Name"
    assert result.projected == {
        "Keep": 1, "Name": "hello", "Flag": True, "ROM": b"\x01\x02"}


def test_a_missing_kext_table_is_reported_but_never_projected():
    document = {"Kernel": {}}
    sample = {"Kernel": {"Add": [{"BundlePath": "Lilu.kext", "Enabled": True}]}}

    result = _run(document, sample)

    assert [item.path for item in result.missing] == [("Kernel", "Add")]
    assert result.missing[0].schema == "1 item"
    assert result.projected == {"Kernel": {}}
    assert "Kernel > Add" in preview.to_text(result)


def test_a_missing_section_dictionary_is_reported_but_never_projected():
    document = {}
    sample = {"DeviceProperties": {"Add": {"PciRoot(0x0)": {"layout-id": 1}}}}

    result = _run(document, sample)

    assert [item.path for item in result.missing] == [("DeviceProperties",)]
    assert result.missing[0].schema == "1 key"
    assert result.projected == {}


def test_a_missing_empty_list_is_added_to_the_projection():
    document = {"ACPI": {"Quirks": {"FadtEnableReset": False}}}
    sample = {"ACPI": {"Add": [], "Quirks": {"FadtEnableReset": True}}}

    result = _run(document, sample)

    assert [item.path for item in result.missing] == [("ACPI", "Add")]
    assert result.missing[0].schema == "0 items"
    assert result.projected == {
        "ACPI": {"Quirks": {"FadtEnableReset": False}, "Add": []}}


def test_an_extra_key_is_reported_and_kept_in_the_projection():
    document = {"A": 1, "Custom": {"Mine": True}}
    sample = {"A": 1}

    result = _run(document, sample)

    assert [(item.kind, item.path) for item in result.extra] == [
        ("extra", ("Custom",))]
    assert result.extra[0].schema == ""
    assert result.extra[0].current == "1 key"
    assert result.projected == document


def test_an_extra_nested_key_is_reported_at_its_full_path():
    document = {"Booter": {"Quirks": {"AvoidRuntimeDefrag": True, "Mine": 1}}}
    sample = {"Booter": {"Quirks": {"AvoidRuntimeDefrag": True}}}

    result = _run(document, sample)

    assert [item.path for item in result.extra] == [
        ("Booter", "Quirks", "Mine")]
    assert result.extra[0].label == "Booter > Quirks > Mine"


def test_one_is_an_integer_and_true_is_a_boolean():
    document = {"A": 1, "B": False}
    sample = {"A": True, "B": 0}

    result = _run(document, sample)

    assert len(result.types) == 2
    first = result.types[0]
    assert first.path == ("A",)
    assert first.current == "1" and first.schema == "true"
    assert first.current_type == "integer" and first.schema_type == "boolean"
    second = result.types[1]
    assert second.path == ("B",)
    assert second.current == "false" and second.schema == "0"
    assert second.current_type == "boolean" and second.schema_type == "integer"
    # A type finding is a report, not a replacement.
    assert result.projected == document


def test_the_walk_follows_nested_dictionaries():
    document = {"Kernel": {"Quirks": {"PanicNoKextDump": True}}}
    sample = {"Kernel": {"Quirks": {"PanicNoKextDump": True,
                                    "PowerTimeoutKernelPanic": True,
                                    "PanicNoKextDumpType": 1}},
              "Misc": {"Security": {"SecureBootModel": "Default"}}}

    result = _run(document, sample)

    assert [item.path for item in result.missing] == [
        ("Kernel", "Quirks", "PanicNoKextDumpType"),
        ("Kernel", "Quirks", "PowerTimeoutKernelPanic"),
        ("Misc",),
    ]
    assert result.missing[2].schema == "1 key"
    assert result.projected["Kernel"]["Quirks"]["PowerTimeoutKernelPanic"] is True
    assert "Misc" not in result.projected


def test_warning_keys_are_ignored_on_both_sides():
    document = {"A": 1, "#WARNING": "this file's warning"}
    sample = {"A": 1, "#WARNING": "the sample's warning",
              "#WARNING-2": "another sample warning"}

    result = _run(document, sample)

    assert result.empty
    assert result.projected == {"A": 1, "#WARNING": "this file's warning"}


def test_document_order_is_preserved_and_additions_are_appended():
    document = {"Zeta": 1, "Alpha": 2, "Middle": {"Y": 1, "B": 2}}
    sample = {"Zeta": 1, "NewTop": True, "Alpha": 2,
              "Middle": {"Y": 1, "NewNested": False, "B": 2}}

    result = _run(document, sample)

    assert list(result.projected) == ["Zeta", "Alpha", "Middle", "NewTop"]
    assert list(result.projected["Middle"]) == ["Y", "B", "NewNested"]
    assert result.projected["NewTop"] is True
    assert result.projected["Middle"]["NewNested"] is False


def test_findings_are_sorted_by_kind_then_label():
    document = {"Type": 1, "Extra": 2}
    sample = {"Type": True, "Missing": 3}

    result = _run(document, sample)

    assert _pairs(result) == [
        ("missing", "Missing"),
        ("extra", "Extra"),
        ("type", "Type"),
    ]


def test_compare_does_not_mutate_either_input():
    document = {"A": {"B": 1}, "List": [1, 2]}
    sample = {"A": {"B": 1, "C": "new"}, "New": [], "List": [1, 2]}
    document_snapshot = copy.deepcopy(document)
    sample_snapshot = copy.deepcopy(sample)

    _run(document, sample)

    assert document == document_snapshot
    assert sample == sample_snapshot


def test_mutating_the_projection_leaves_the_document_untouched():
    document = {"A": {"B": 1}, "List": [1, 2]}
    sample = {"A": {"B": 1, "C": "new"}, "New": [], "List": [1, 2]}
    result = _run(document, sample)

    result.projected["A"]["B"] = 99
    result.projected["A"]["C"] = 99
    result.projected["New"].append("injected")
    result.projected["List"].append(3)
    result.projected["Top"] = "injected"

    assert document == {"A": {"B": 1}, "List": [1, 2]}


def test_the_text_states_counts_each_finding_and_the_closing_sentences():
    document = {"A": 1, "Extra": True}
    sample = {"A": True, "Missing": "x"}

    text = preview.to_text(_run(document, sample))

    assert text.startswith("BlackDream schema preview\n")
    assert "\nPinned schema: OpenCore 1.0.8\n" in text
    assert "Missing: 1" in text
    assert "Extra: 1" in text
    assert "Different types: 1" in text
    assert "[MISSING] Missing = x\n" in text
    assert "[EXTRA] Extra\n" in text
    assert "[TYPE] A: integer -> boolean\n" in text
    assert CAVEAT + "\n" in text
    assert text.endswith(CLOSING + "\n")
    assert not text.endswith("\n\n")


def test_the_text_says_no_differences_when_there_are_none():
    text = preview.to_text(_run({"A": 1}, {"A": 1}))

    assert "No differences." in text
    assert text.index("No differences.") < text.index(CAVEAT)
    assert CAVEAT + "\n" in text
    assert text.endswith(CLOSING + "\n")


def test_the_pinned_sample_matches_itself():
    sample = config_editor.sample_plist()

    result = preview.compare(sample, config_editor.sample_plist(),
                             config_editor.OPEN_CORE_VERSION)

    assert result.empty
    assert result.projected == sample
