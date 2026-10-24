"""Profiles are shortcuts, not machine identities, and a bad file is not fatal."""

from __future__ import annotations

import json

from ocengine.paths import EnginePaths

from blackdream.core import machine_profiles as profiles
from blackdream.core import state_store
from blackdream.core.machine_profiles import Profile

FIELDS = {"name", "report", "efi_folder", "release", "updated"}
IDENTITY_KEYS = {"serial", "mlb", "uuid", "rom", "system_uuid", "systemuuid"}


def _profile(name="Studio", report="/reports/studio.txt", **changes):
    values = dict(
        name=name,
        report=report,
        efi_folder="/builds/EFI",
        release="24.99.99",
        updated="2026-10-24T00:00:00+00:00",
    )
    values.update(changes)
    return Profile(**values)


# -- state_store, the helper every record uses ---------------------------------


def test_atomic_write_creates_missing_parents_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "one" / "two" / "file.txt"

    state_store.atomic_write_text(target, "hello")

    assert target.read_text(encoding="utf-8") == "hello"
    assert list(target.parent.iterdir()) == [target]


def test_atomic_write_replaces_an_existing_file(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("old", encoding="utf-8")

    state_store.atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "new"


def test_read_helpers_treat_absence_and_nonsense_as_nothing(tmp_path):
    assert state_store.read_text(tmp_path / "absent") is None
    assert state_store.read_json(tmp_path / "absent") is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert state_store.read_json(broken) is None

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    assert state_store.read_json(array) is None

    directory = tmp_path / "directory"
    directory.mkdir()
    assert state_store.read_text(directory) is None


# -- Profile ------------------------------------------------------------------


def test_a_record_holds_exactly_the_five_local_fields():
    document = _profile().to_dict()

    assert set(document) == FIELDS
    assert IDENTITY_KEYS.isdisjoint(key.casefold() for key in document)


def test_a_name_is_trimmed_and_the_two_required_fields_are_checked():
    assert Profile.from_dict({"name": "  Studio  ", "report": "/r"}).name == "Studio"
    assert Profile.from_dict({"name": "   ", "report": "/r"}) is None
    assert Profile.from_dict({"name": "Studio", "report": "   "}) is None
    assert Profile.from_dict({"name": "Studio"}) is None
    assert Profile.from_dict({"name": "Studio", "report": 3}) is None
    assert Profile.from_dict({"name": "Studio", "report": "/r", "release": 3}) is None
    assert Profile.from_dict([]) is None


def test_missing_optional_fields_default_to_empty_strings():
    profile = Profile.from_dict({"name": "Studio", "report": "/r"})

    assert profile == Profile(name="Studio", report="/r")


# -- save and load ------------------------------------------------------------


def test_profiles_round_trip_through_an_explicit_path(tmp_path):
    path = tmp_path / "profiles.json"
    original = [_profile("workshop"), _profile("Alpha", report="/reports/alpha.txt")]

    written = profiles.save(original, path)
    document = json.loads(path.read_text(encoding="utf-8"))

    assert written == path
    assert document["format"] == profiles.FORMAT
    assert [item["name"] for item in document["profiles"]] == ["Alpha", "workshop"]
    assert profiles.load(path) == [
        _profile("Alpha", report="/reports/alpha.txt"), _profile("workshop")]


def test_malformed_entries_are_skipped_and_a_later_duplicate_wins(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({
        "format": profiles.FORMAT,
        "profiles": [
            _profile("Keep", updated="first").to_dict(),
            "not an object",
            {"name": "", "report": "/nowhere"},
            {"name": "No report"},
            _profile("Keep", updated="last").to_dict(),
        ],
    }), encoding="utf-8")

    loaded = profiles.load(path)

    assert len(loaded) == 1
    assert loaded[0].updated == "last"


def test_a_missing_corrupt_or_future_file_reads_as_empty(tmp_path):
    assert profiles.load(tmp_path / "absent.json") == []

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert profiles.load(corrupt) == []

    future = tmp_path / "future.json"
    future.write_text(json.dumps({"format": 99, "profiles": [
        _profile().to_dict()]}), encoding="utf-8")
    assert profiles.load(future) == []


# -- lookup and editing -------------------------------------------------------


def test_upsert_replaces_a_name_case_insensitively_and_returns_sorted():
    current = [_profile("workshop"), _profile("Studio", report="/old")]
    replacement = _profile("STUDIO", report="/new")

    result = profiles.upsert(current, replacement)

    assert [item.name for item in result] == ["STUDIO", "workshop"]
    assert len(result) == 2
    assert profiles.find(result, "studio").report == "/new"


def test_find_and_remove_ignore_case():
    current = [_profile("Alpha"), _profile("Workshop")]

    assert profiles.find(current, "ALPHA") == current[0]
    assert profiles.find(current, "absent") is None
    assert [item.name for item in profiles.remove(current, "alpha")] == ["Workshop"]


# -- storage location ---------------------------------------------------------


def test_default_path_follows_the_redirected_engine_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ocengine.paths._current",
        EnginePaths(cache_dir=tmp_path / "cache", tools_dir=tmp_path / "tools",
                    log_dir=tmp_path / "logs"))

    assert profiles.default_path() == tmp_path / "profiles.json"
