"""Reading ocvalidate's lines: a key path when it is unambiguous, raw text when not.

The mapping is the feature, so these tests are about the boundary between "this line
names one place" and "this line could name two". A jump to the wrong key is worse than
no jump: it looks authoritative and sends the user to edit something unrelated.
"""

from __future__ import annotations

import copy

import pytest

from blackdream.core import validation_assistant as assistant


def _config():
    return {
        "ACPI": {"Add": []},
        "Kernel": {"Quirks": {"DisableIoMapper": True, "PanicNoKextDump": True}},
        "UEFI": {
            "Quirks": {"ResizeGpuBars": -1, "ClearTaskSwitchBit": False},
            "Drivers": ["OpenRuntime.efi", {"Path": "HfsPlus.efi", "Enabled": True}],
        },
        "PlatformInfo": {"Generic": {"SystemProductName": "iMac19,1"}},
    }


def test_a_unique_unknown_key_maps_to_its_path():
    line = "OCS: No schema for ClearTaskSwitchBit at 2 index, context <Quirks>!"
    explanation = assistant.explain(line, _config())

    assert explanation.path == ("UEFI", "Quirks", "ClearTaskSwitchBit")
    assert explanation.navigable
    assert explanation.kind == "unknown-key"
    assert "ClearTaskSwitchBit" in explanation.message
    assert "UEFI's schema" not in explanation.message, "the section is named, not guessed"
    assert explanation.raw == line


def test_two_contexts_with_the_same_name_need_the_index_to_separate_them():
    data = {
        "Kernel": {"Quirks": {"A": 1, "Mystery": True}},
        "UEFI": {"Quirks": {"B": 2, "Mystery": True}},
    }
    # Mystery sits at the same position in both, so the message cannot say which.
    line = "OCS: No schema for Mystery at 1 index, context <Quirks>!"
    assert assistant.explain(line, data).path is None


def test_the_index_separates_two_contexts_when_the_positions_differ():
    data = {
        "Kernel": {"Quirks": {"Mystery": True, "A": 1}},
        "UEFI": {"Quirks": {"B": 2, "C": 3, "Mystery": True}},
    }
    line = "OCS: No schema for Mystery at 2 index, context <Quirks>!"
    assert assistant.explain(line, data).path == (
        "UEFI", "Quirks", "Mystery")


def test_a_missing_key_maps_to_the_dictionary_it_belongs_in():
    line = "OCS: Missing key ResizeGpuBars, context <Quirks>!"
    data = {"UEFI": {"Quirks": {"ResizeAppleGpuBars": -1}}}

    explanation = assistant.explain(line, data)

    assert explanation.path == ("UEFI", "Quirks")
    assert explanation.kind == "missing-key"
    assert "ResizeGpuBars" in explanation.message


def test_a_missing_key_in_two_contexts_is_not_guessed():
    data = {"Kernel": {"Quirks": {}}, "UEFI": {"Quirks": {}}}
    line = "OCS: Missing key PanicNoKextDump, context <Quirks>!"
    assert assistant.explain(line, data).path is None


def test_a_context_inside_an_array_carries_the_index():
    data = {"UEFI": {"Drivers": [{"Arguments": ""},
                                 {"Path": "HfsPlus.efi", "Mystery": 1}]}}
    line = "OCS: No schema for Mystery at 1 index, context <Path>!"
    # "Path" is a key here, not a dictionary, so there is nothing to navigate to.
    assert assistant.explain(line, data).path is None

    line = "OCS: No schema for Mystery at 1 index, context <Drivers>!"
    assert assistant.explain(line, data).path == (
        "UEFI", "Drivers", 1, "Mystery")


def test_an_unknown_key_in_a_nested_array_item_maps_through_the_index():
    data = {"Kernel": {"Add": [
        {"BundlePath": "A.kext"},
        {"BundlePath": "B.kext", "Surprise": True},
    ]}}
    line = "OCS: No schema for Surprise at 1 index, context <Add>!"
    assert assistant.explain(line, data).path == (
        "Kernel", "Add", 1, "Surprise")


def test_a_serialisation_failure_is_explained_without_a_path():
    explanation = assistant.explain("Serialisation returns 2 errors!", _config())
    assert explanation.path is None
    assert explanation.kind == "serialisation"
    assert "could not serialise" in explanation.message


def test_an_unmapped_validator_line_keeps_the_raw_text_and_does_not_guess():
    line = "OCV: PickerMode: invalid value (99)!"
    explanation = assistant.explain(line, _config())
    assert explanation.path is None
    assert explanation.raw == line
    assert explanation.message


def test_a_non_validator_line_has_no_invented_explanation():
    explanation = assistant.explain("ocvalidate exited with status 3.", None)
    assert explanation.path is None
    assert explanation.message is None
    assert explanation.kind == "other"


def test_annotate_keeps_order_and_reads_the_document_once():
    issues = (
        "OCS: No schema for ClearTaskSwitchBit at 2 index, context <Quirks>!",
        "Serialisation returns 1 errors!",
    )
    data = _config()
    before = copy.deepcopy(data)

    explanations = assistant.annotate(issues, data)

    assert [item.raw for item in explanations] == list(issues)
    assert explanations[0].path == ("UEFI", "Quirks", "ClearTaskSwitchBit")
    assert explanations[1].path is None
    assert data == before, "reading the document must not change it"


def test_without_a_document_a_line_is_still_explained_but_not_located():
    line = "OCS: No schema for Something at 0 index, context <Quirks>!"
    explanation = assistant.explain(line, None)
    assert explanation.path is None
    assert explanation.message


@pytest.mark.parametrize("line", [
    "OCS: Missing key Foo, context <Bar>",
    " OCS: No schema for Mismatch at 3 index, context <Add>! ",
])
def test_whitespace_and_the_trailing_mark_do_not_change_the_reading(line):
    explanation = assistant.explain(line)
    assert explanation.raw == line.strip()
    assert explanation.kind in ("unknown-key", "missing-key")
