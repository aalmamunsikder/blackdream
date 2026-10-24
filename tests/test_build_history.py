"""Build history is append-only, bounded, and honest about vanished folders."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ocengine.paths import EnginePaths

from blackdream.core import build_history as history
from blackdream.core.build_history import Entry


def _entry(at="2026-10-24T00:00:00+00:00", status="succeeded", **changes):
    values = dict(at=at, status=status, release="24.99.99", output="",
                  manifest="", detail="")
    values.update(changes)
    return Entry(**values)


def _moment(minutes):
    return (datetime(2026, 10, 24, tzinfo=timezone.utc)
            + timedelta(minutes=minutes)).isoformat()


# -- Entry and read -----------------------------------------------------------


def test_an_entry_round_trips_and_malformed_records_are_rejected():
    entry = _entry(output="/builds/EFI", manifest=".blackdream-manifest.json",
                   detail="validation failed")

    assert Entry.from_dict(entry.to_dict()) == entry
    assert Entry.from_dict({}) is None
    assert Entry.from_dict([]) is None
    assert Entry.from_dict({"at": "", "status": "succeeded"}) is None
    assert Entry.from_dict({"at": "now", "status": "almost"}) is None
    assert Entry.from_dict({"at": "now", "status": "succeeded",
                            "detail": 3}) is None


def test_read_returns_newest_first_and_skips_malformed_lines(tmp_path):
    path = tmp_path / "build-history.jsonl"
    path.write_text("\n".join([
        json.dumps(_entry(at=_moment(0), status="failed").to_dict()),
        "",
        "{not json",
        "[]",
        json.dumps({"at": _moment(1), "status": "unknown"}),
        json.dumps(_entry(at=_moment(2), status="cancelled").to_dict()),
    ]) + "\n", encoding="utf-8")

    loaded = history.read(path)

    assert [entry.at for entry in loaded] == [_moment(2), _moment(0)]
    assert loaded[0].status == "cancelled"


def test_a_missing_file_reads_as_empty(tmp_path):
    assert history.read(tmp_path / "absent.jsonl") == []


# -- append -------------------------------------------------------------------


def test_append_keeps_only_the_newest_entries_and_writes_newest_last(tmp_path):
    path = tmp_path / "build-history.jsonl"
    total = history.MAX_ENTRIES + 5

    for index in range(total):
        history.append(_entry(at=_moment(index), detail=str(index)), path)

    loaded = history.read(path)
    lines = path.read_text(encoding="utf-8").splitlines()

    assert len(loaded) == history.MAX_ENTRIES
    assert loaded[0].at == _moment(total - 1)
    assert loaded[-1].at == _moment(total - history.MAX_ENTRIES)
    assert len(lines) == history.MAX_ENTRIES
    assert json.loads(lines[-1])["at"] == _moment(total - 1)
    assert json.loads(lines[0])["at"] == _moment(total - history.MAX_ENTRIES)


def test_append_without_a_path_uses_the_state_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ocengine.paths._current",
        EnginePaths(cache_dir=tmp_path / "cache", tools_dir=tmp_path / "tools",
                    log_dir=tmp_path / "logs"))

    history.append(_entry())

    assert history.read() == [_entry()]
    assert history.default_path() == tmp_path / "build-history.jsonl"


# -- live state of a recorded build -------------------------------------------


def test_folder_state_is_ok_only_while_the_folder_exists(tmp_path):
    folder = tmp_path / "EFI"
    folder.mkdir()
    recorded = _entry(output=str(folder))

    assert history.folder_state(recorded) == "ok"

    folder.rmdir()

    assert history.folder_state(recorded) == "missing"
    assert history.folder_state(_entry(output="")) == "missing"
    assert history.folder_state(_entry(output=str(tmp_path / "deleted"))) == "missing"


def test_folder_state_never_raises_on_a_nonsense_path(tmp_path):
    regular_file = tmp_path / "a-file"
    regular_file.write_text("not a folder", encoding="utf-8")

    assert history.folder_state(_entry(output=str(regular_file))) == "missing"
    assert history.folder_state(_entry(output="\0not a path")) == "missing"


def test_manifest_state_reads_recorded_missing_and_unrecorded(tmp_path):
    folder = tmp_path / "EFI"
    folder.mkdir()
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")

    assert history.manifest_state(
        _entry(output=str(folder), manifest="manifest.json")) == "recorded"
    assert history.manifest_state(_entry(output=str(folder))) == "unrecorded"
    assert history.manifest_state(
        _entry(output=str(folder), manifest="gone.json")) == "missing"
    assert history.manifest_state(
        _entry(manifest="manifest.json")) == "missing"


def test_manifest_state_finds_the_manifest_inside_the_build_root(tmp_path):
    folder = tmp_path / "EFI"
    folder.mkdir()
    (folder / "manifest.json").write_text("{}", encoding="utf-8")

    assert history.manifest_state(
        _entry(output=str(folder), manifest="manifest.json")) == "recorded"


def test_manifest_state_never_raises_when_the_folder_vanished(tmp_path):
    entry = _entry(output=str(tmp_path / "deleted"), manifest="manifest.json")

    assert history.manifest_state(entry) == "missing"
    assert history.folder_state(entry) == "missing"


# -- portable copy ------------------------------------------------------------


def test_the_export_is_tab_separated_and_mentions_a_missing_folder(tmp_path):
    folder = tmp_path / "EFI"
    folder.mkdir()
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    present = _entry(at=_moment(1), output=str(folder), manifest="manifest.json")
    vanished = _entry(at=_moment(0), output=str(tmp_path / "gone" / "EFI"),
                      manifest="manifest.json")

    text = history.to_text([present, vanished])
    lines = text.splitlines()

    assert lines[0] == "BlackDream build history"
    assert len(lines) == 3
    assert lines[1].split("\t") == [
        _moment(1), "succeeded", "24.99.99", str(folder), "ok", "recorded"]
    assert lines[2].split("\t")[4:] == ["missing", "missing"]
    assert "missing" in text
    assert text.endswith("\n") and not text.endswith("\n\n")
