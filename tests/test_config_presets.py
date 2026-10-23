"""Preset entries: pinned-schema fidelity, insertion, and duplicate detection."""

from __future__ import annotations

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from blackdream.core import config_editor as editor  # noqa: E402
from blackdream.core import config_presets as presets  # noqa: E402


def test_every_preset_fills_the_pinned_schema_exactly():
    for preset in presets.PRESETS:
        sample = editor.schema_at(preset.target)
        assert isinstance(sample, list) and sample, preset.key
        template = sample[0]
        assert set(preset.value) == set(template), preset.key
        for key, value in preset.value.items():
            expected = type(template[key])
            if expected is bytes:
                assert isinstance(value, bytes), (preset.key, key)
            else:
                assert type(value) is expected, (preset.key, key)


def test_preset_keys_and_titles_are_unique_and_targets_are_known():
    assert len(presets.PRESETS) == 12
    assert len({preset.key for preset in presets.PRESETS}) == 12
    assert len({preset.title for preset in presets.PRESETS}) == 12
    assert {preset.target for preset in presets.PRESETS} == {
        ("ACPI", "Patch"), ("Kernel", "Patch")}
    for preset in presets.PRESETS:
        assert presets.preset_by_key(preset.key) is preset
    assert presets.preset_by_key("missing") is None


def test_inserting_a_preset_creates_its_target_and_never_duplicates():
    data = {}
    first = presets.insert_preset(data, presets.PRESETS[-1])
    assert first.inserted is True
    assert first.path == ("Kernel", "Patch", 0)
    assert data["Kernel"]["Patch"][0]["Comment"] == "Enable TRIM for SSD"

    again = presets.insert_preset(data, presets.PRESETS[-1])
    assert again.inserted is False
    assert again.path == first.path
    assert len(data["Kernel"]["Patch"]) == 1


def test_a_preset_matches_an_entry_that_differs_only_in_comment_and_enabled():
    preset = presets.preset_by_key("acpi-osi-xosi")
    existing = copy.deepcopy(preset.value)
    existing["Comment"] = "hand-written rename"
    existing["Enabled"] = False
    data = {"ACPI": {"Patch": [existing]}}

    found = presets.find_preset(data, preset)
    assert found == ("ACPI", "Patch", 0)
    assert presets.insert_preset(data, preset).inserted is False


def test_a_preset_that_does_not_fit_the_document_is_refused():
    data = {"Kernel": {"Patch": {}}}
    with pytest.raises(ValueError, match="not an array"):
        presets.insert_preset(data, presets.PRESETS[-1])

    data = {"Kernel": []}
    with pytest.raises(ValueError, match="not a dictionary"):
        presets.insert_preset(data, presets.PRESETS[-1])


def test_inserting_every_preset_still_validates():
    """Schema fit is checked above; this proves ocvalidate agrees when present."""
    if editor.find_ocvalidate() is None:
        pytest.skip("no verified ocvalidate on this machine")
    data = editor.sample_plist()
    data["ACPI"]["Patch"] = []
    data["Kernel"]["Patch"] = []
    for preset in presets.PRESETS:
        presets.insert_preset(data, preset)
    result = editor.validate_document(data, allow_download=False)
    assert result.ok, result.issues
