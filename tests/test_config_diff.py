"""The diff and the history are safety features: every edit must be visible and
every edit must be reversible.

The tests use real plist value kinds -- boolean, integer, real, data, date -- because
the failures that matter here are type confusion (True vs 1), array alignment (a
removed kext must not look like eleven changes) and losing bytes on undo.
"""

from __future__ import annotations

import copy
import datetime

from blackdream.core import config_diff as diff


def _config():
    return {
        "ACPI": {"Add": [
            {"Path": "SSDT-AWAC.aml", "Enabled": True},
            {"Path": "SSDT-PLUG.aml", "Enabled": True},
        ]},
        "Kernel": {"Add": [
            {"BundlePath": "Lilu.kext", "Enabled": True, "Comment": "Lilu"},
            {"BundlePath": "VirtualSMC.kext", "Enabled": True, "Comment": ""},
        ], "Quirks": {"PanicNoKextDump": True, "XhciPortLimit": False}},
        "PlatformInfo": {"Generic": {"SystemProductName": "iMac19,1",
                                     "ROM": b"\xaa\xbb\xcc"}},
        "Future": {"UnknownKey": {"Nested": 1}},
    }


def _by_path(changes):
    return {change.path: change for change in changes}


def test_no_change_is_no_change():
    first = _config()
    second = copy.deepcopy(first)

    assert diff.diff(first, second) == []


def test_a_scalar_change_names_the_path_and_both_values():
    before = _config()
    after = copy.deepcopy(before)
    after["Kernel"]["Quirks"]["XhciPortLimit"] = True

    changes = diff.diff(before, after)

    assert len(changes) == 1
    assert changes[0].kind == diff.CHANGED
    assert changes[0].path == ("Kernel", "Quirks", "XhciPortLimit")
    assert changes[0].before is False
    assert changes[0].after is True


def test_a_boolean_is_not_an_integer():
    assert len(diff.diff({"A": True}, {"A": 1})) == 1
    assert len(diff.diff({"A": 1}, {"A": 1.0})) == 1
    assert len(diff.diff({"A": 0}, {"A": False})) == 1


def test_binary_data_changes_are_not_dropped():
    before = {"PlatformInfo": {"Generic": {"ROM": b"\x00\x01"}}}
    after = {"PlatformInfo": {"Generic": {"ROM": b"\x00\x02"}}}

    changes = diff.diff(before, after)

    assert [item.path for item in changes] == [("PlatformInfo", "Generic", "ROM")]
    assert changes[0].before == b"\x00\x01"
    assert changes[0].after == b"\x00\x02"


def test_a_date_change_is_reported():
    before = {"A": datetime.datetime(2026, 1, 1)}
    after = {"A": datetime.datetime(2026, 10, 23)}

    assert len(diff.diff(before, after)) == 1


def test_an_added_key_keeps_its_document_position_in_the_report():
    before = _config()
    after = copy.deepcopy(before)
    after["ACPI"]["Add"][1]["Comment"] = "plugin type"

    changes = diff.diff(before, after)

    assert [(item.kind, item.path) for item in changes] == [
        (diff.ADDED, ("ACPI", "Add", 1, "Comment"))]
    assert changes[0].before is diff._ABSENT
    assert diff.format_value(changes[0].before) == "nothing"


def test_a_removed_key_is_reported_with_its_old_value():
    before = _config()
    after = copy.deepcopy(before)
    del after["Future"]["UnknownKey"]

    changes = diff.diff(before, after)

    assert [(item.kind, item.path) for item in changes] == [
        (diff.REMOVED, ("Future", "UnknownKey"))]
    assert changes[0].before == {"Nested": 1}


def test_removing_the_first_kext_is_one_removal_not_a_shifted_diff():
    before = _config()
    after = copy.deepcopy(before)
    del after["Kernel"]["Add"][0]

    changes = diff.diff(before, after)

    assert len(changes) == 1
    assert changes[0].kind == diff.REMOVED
    assert changes[0].path == ("Kernel", "Add", 0)
    assert changes[0].before["BundlePath"] == "Lilu.kext"


def test_inserting_a_kext_in_the_middle_is_one_addition():
    before = _config()
    after = copy.deepcopy(before)
    after["Kernel"]["Add"].insert(1, {"BundlePath": "WhateverGreen.kext",
                                      "Enabled": True, "Comment": ""})

    changes = diff.diff(before, after)

    assert len(changes) == 1
    assert changes[0].kind == diff.ADDED
    assert changes[0].path == ("Kernel", "Add", 1)
    assert changes[0].after["BundlePath"] == "WhateverGreen.kext"


def test_moving_an_item_reads_as_a_removal_and_an_addition():
    before = _config()
    after = copy.deepcopy(before)
    after["ACPI"]["Add"].reverse()

    changes = diff.diff(before, after)

    assert sorted(item.kind for item in changes) == [diff.ADDED, diff.REMOVED]
    removed = next(item for item in changes if item.kind == diff.REMOVED)
    added = next(item for item in changes if item.kind == diff.ADDED)
    assert removed.before == added.after
    assert added.after["Path"] in ("SSDT-AWAC.aml", "SSDT-PLUG.aml")


def test_a_changed_key_inside_a_list_item_is_named_notwholesale():
    before = _config()
    after = copy.deepcopy(before)
    after["Kernel"]["Add"][1]["Enabled"] = False

    changes = diff.diff(before, after)

    assert [(item.kind, item.path) for item in changes] == [
        (diff.CHANGED, ("Kernel", "Add", 1, "Enabled"))]


def test_unknown_keys_participate_in_the_diff():
    before = _config()
    after = copy.deepcopy(before)
    after["Future"]["UnknownKey"]["Nested"] = 2

    changes = diff.diff(before, after)

    assert [item.path for item in changes] == [("Future", "UnknownKey", "Nested")]


def test_key_order_is_part_of_what_is_preserved_by_history():
    data = _config()
    history = diff.History(data)

    reordered = copy.deepcopy(data)
    reordered["Future"], reordered["Kernel"] = (
        reordered["Kernel"], reordered["Future"])
    assert history.record(reordered, "Reorder")
    restored = history.undo()
    assert list(restored) == list(data)
    assert history.redo() == reordered


def test_undo_and_redo_walk_the_history_in_order():
    history = diff.History({"A": 0})
    history.record({"A": 1}, "Change A to 1")
    history.record({"A": 2}, "Change A to 2")

    assert history.undo_label == "Change A to 2"
    assert history.undo() == {"A": 1}
    assert history.undo() == {"A": 0}
    assert history.undo() is None
    assert history.can_undo is False
    assert history.redo_label == "Change A to 1"
    assert history.redo() == {"A": 1}
    assert history.redo() == {"A": 2}
    assert history.redo() is None


def test_a_new_change_after_undo_discards_the_redo_branch():
    history = diff.History({"A": 0})
    history.record({"A": 1}, "one")
    history.record({"A": 2}, "two")
    history.undo()

    assert history.can_redo
    history.record({"A": 3}, "three")

    assert not history.can_redo
    assert history.undo() == {"A": 1}


def test_recording_the_same_state_is_a_no_op():
    history = diff.History(_config())

    assert history.record(_config()) is False
    assert not history.can_undo
    assert history.changes() == []


def test_the_history_holds_copies_not_references():
    data = {"A": [1, 2]}
    history = diff.History(data)
    data["A"].append(3)

    assert history.changes() == []
    assert history._current().data == {"A": [1, 2]}


def test_undo_returns_a_copy_the_caller_can_mutate():
    history = diff.History({"A": [1]})
    history.record({"A": [2]}, "two")

    restored = history.undo()
    restored["A"].append(99)

    assert history.undo() is None
    assert history._current().data == {"A": [1]}


def test_binary_values_survive_a_full_undo_redo_cycle():
    original = {"ROM": b"\x00\xff\x10"}
    history = diff.History(original)
    history.record({"ROM": b"\x01"}, "replace ROM")

    assert history.undo() == {"ROM": b"\x00\xff\x10"}
    assert history.redo() == {"ROM": b"\x01"}


def test_the_history_is_bounded_and_keeps_the_newest_changes():
    history = diff.History({"A": 0}, limit=3)
    for value in range(1, 6):
        history.record({"A": value}, "to {}".format(value))

    assert history.undo() == {"A": 4}
    assert history.undo() == {"A": 3}
    assert history.undo() is None, "older states are dropped, not kept forever"


def test_changes_since_open_compare_against_the_opened_document():
    history = diff.History(_config())
    edited = copy.deepcopy(history._current().data)
    edited["Kernel"]["Quirks"]["XhciPortLimit"] = True
    history.record(edited, "toggle")

    assert [item.path for item in history.changes()] == [
        ("Kernel", "Quirks", "XhciPortLimit")]
    history.undo()
    assert history.changes() == []


def test_reset_starts_a_new_baseline():
    history = diff.History({"A": 0})
    history.record({"A": 1}, "one")
    history.reset({"B": True})

    assert not history.can_undo and not history.can_redo
    assert history.changes() == []


def test_the_review_text_names_each_kind_and_its_values():
    before = {"A": 1, "B": True, "C": "keep"}
    after = {"A": 2, "C": "keep", "D": "new"}
    text = diff.to_text(diff.diff(before, after))

    assert "[CHANGED] A" in text
    assert "  before: 1" in text and "  after:  2" in text
    assert "[REMOVED] B" in text
    assert "[ADDED] D" in text
    assert diff.to_text([]) == "No changes since the file was opened.\n"


def test_a_long_value_is_shortened_and_a_multiline_one_is_flattened():
    text = diff.format_value("a" * 200, limit=20)

    assert len(text) == 20 and text.endswith("\u2026")
    assert "\n" not in diff.format_value("line one\nline two")


def test_path_labels_use_the_editor_notation():
    assert diff.path_label(("Kernel", "Add", 0, "Enabled")) == (
        "Kernel > Add > [0] > Enabled")
    assert diff.path_label(()) == "config.plist"


def test_the_absent_marker_reads_as_nothing():
    assert diff.format_value(diff._ABSENT) == "nothing"


def test_diff_does_not_mutate_either_document():
    before = _config()
    after = copy.deepcopy(before)
    after["Kernel"]["Add"].pop()
    snapshot = copy.deepcopy(before), copy.deepcopy(after)

    diff.diff(before, after)

    assert (before, after) == snapshot
