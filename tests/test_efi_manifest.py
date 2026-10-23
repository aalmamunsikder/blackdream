"""The manifest records a tree and later says what changed -- and nothing more.

A hash match is a statement about bytes. These tests pin that statement so the
window can never turn it into "this will boot".
"""

from __future__ import annotations

import json

import pytest

from blackdream.core import efi_manifest as manifest


def _tree(root):
    (root / "EFI/BOOT").mkdir(parents=True)
    (root / "EFI/OC").mkdir(parents=True)
    (root / "EFI/BOOT/BOOTx64.efi").write_bytes(b"boot")
    (root / "EFI/OC/OpenCore.efi").write_bytes(b"core")
    (root / "EFI/OC/config.plist").write_bytes(b"<plist/>")
    return root


def test_a_written_manifest_lists_relative_sorted_paths_and_hashes(tmp_path):
    root = _tree(tmp_path / "EFI")

    path = manifest.write(root, build={"release": "macOS 15.7"},
                          validation={"errors": 0}, now="2026-10-23T00:00:00+00:00")
    document = json.loads(path.read_text())

    assert path.name == manifest.MANIFEST_NAME
    assert path.parent == root
    assert document["tool"] == "BlackDream"
    assert document["format"] == manifest.FORMAT
    assert document["created"] == "2026-10-23T00:00:00+00:00"
    assert document["build"] == {"release": "macOS 15.7"}
    assert document["validation"] == {"errors": 0}
    assert [item["path"] for item in document["files"]] == [
        "EFI/BOOT/BOOTx64.efi", "EFI/OC/OpenCore.efi", "EFI/OC/config.plist"]
    assert all(len(item["sha256"]) == 64 for item in document["files"])
    assert all(item["size"] > 0 for item in document["files"])


def test_the_manifest_does_not_hash_itself(tmp_path):
    root = _tree(tmp_path / "EFI")
    manifest.write(root)
    manifest.write(root)  # a second write must not list the first file

    document = manifest.read(root)

    assert all(item["path"] != manifest.MANIFEST_NAME for item in document["files"])


def test_an_unchanged_folder_verifies_intact(tmp_path):
    root = _tree(tmp_path / "EFI")
    manifest.write(root)

    result = manifest.verify(root)

    assert result.intact
    assert result.unchanged == 3
    assert result.summary == "Every file matches the recorded manifest."


def test_a_modified_file_is_reported_as_changed_with_both_hashes(tmp_path):
    root = _tree(tmp_path / "EFI")
    manifest.write(root)
    (root / "EFI/OC/config.plist").write_bytes(b"<plist>changed</plist>")

    result = manifest.verify(root)
    changed = result.changed

    assert len(changed) == 1
    assert changed[0].path == "EFI/OC/config.plist"
    assert changed[0].recorded != changed[0].found
    assert result.unchanged == 2
    assert not result.intact


def test_a_deleted_file_is_reported_as_missing(tmp_path):
    root = _tree(tmp_path / "EFI")
    manifest.write(root)
    (root / "EFI/BOOT/BOOTx64.efi").unlink()

    result = manifest.verify(root)

    assert [item.path for item in result.missing] == ["EFI/BOOT/BOOTx64.efi"]
    assert result.summary == "1 missing, 0 changed, 0 added"


def test_a_new_file_is_reported_as_added(tmp_path):
    root = _tree(tmp_path / "EFI")
    manifest.write(root)
    (root / "EFI/OC/Drivers").mkdir()
    (root / "EFI/OC/Drivers/OpenRuntime.efi").write_bytes(b"driver")

    result = manifest.verify(root)

    assert [item.path for item in result.added] == ["EFI/OC/Drivers/OpenRuntime.efi"]
    assert result.unchanged == 3


def test_a_renamed_file_reads_as_one_missing_and_one_added(tmp_path):
    root = _tree(tmp_path / "EFI")
    manifest.write(root)
    (root / "EFI/OC/OpenCore.efi").rename(root / "EFI/OC/OpenCore-old.efi")

    result = manifest.verify(root)

    assert [item.path for item in result.missing] == ["EFI/OC/OpenCore.efi"]
    assert [item.path for item in result.added] == ["EFI/OC/OpenCore-old.efi"]


def test_a_moved_folder_still_verifies_because_paths_are_relative(tmp_path):
    original = _tree(tmp_path / "EFI")
    manifest.write(original)
    moved = tmp_path / "elsewhere" / "EFI"
    moved.parent.mkdir()
    original.rename(moved)

    assert manifest.verify(moved).intact


def test_os_noise_is_not_treated_as_a_change(tmp_path):
    root = _tree(tmp_path / "EFI")
    manifest.write(root)
    (root / "EFI/OC/.DS_Store").write_bytes(b"\0")

    assert manifest.verify(root).intact


def test_a_missing_manifest_says_so(tmp_path):
    root = _tree(tmp_path / "EFI")

    with pytest.raises(manifest.ManifestError) as raised:
        manifest.verify(root)

    assert "no .blackdream-manifest.json" in str(raised.value)


@pytest.mark.parametrize("payload", [
    b"{not json",
    b"[]",
    b'{"tool": "BlackDream"}',
    b'{"format": 99, "files": []}',
    b'{"format": 1, "files": [{"path": "a"}]}',
    b'{"format": 1, "files": [{"sha256": "00"}]}',
    b'{"format": 1, "files": ["a"]}',
])
def test_a_malformed_manifest_is_rejected_with_a_reason(tmp_path, payload):
    root = _tree(tmp_path / "EFI")
    (root / manifest.MANIFEST_NAME).write_bytes(payload)

    with pytest.raises(manifest.ManifestError):
        manifest.verify(root)


def test_verification_writes_nothing_and_leaves_the_manifest_alone(tmp_path):
    root = _tree(tmp_path / "EFI")
    path = manifest.write(root)
    before = (path.read_bytes(), path.stat().st_mtime_ns,
              sorted(item.name for item in root.rglob("*")))

    manifest.verify(root)
    manifest.to_text(manifest.verify(root))

    after = (path.read_bytes(), path.stat().st_mtime_ns,
             sorted(item.name for item in root.rglob("*")))
    assert after == before


def test_the_export_states_the_boundary_the_window_states(tmp_path):
    root = _tree(tmp_path / "EFI")
    manifest.write(root)
    text = manifest.to_text(manifest.verify(root))

    assert "does not prove the folder boots" in text
    assert "No differences." in text


def test_the_export_lists_each_difference_with_its_kind(tmp_path):
    root = _tree(tmp_path / "EFI")
    manifest.write(root)
    (root / "EFI/OC/OpenCore.efi").write_bytes(b"new")
    (root / "EFI/BOOT/BOOTx64.efi").unlink()
    (root / "EFI/OC/Extra.efi").write_bytes(b"extra")

    text = manifest.to_text(manifest.verify(root))

    assert "[MISSING] EFI/BOOT/BOOTx64.efi" in text
    assert "[CHANGED] EFI/OC/OpenCore.efi" in text
    assert "[ADDED] EFI/OC/Extra.efi" in text
    assert "recorded " in text and "found    " in text


def test_binary_content_is_hashed_as_bytes_not_text(tmp_path):
    root = _tree(tmp_path / "EFI")
    (root / "EFI/OC/data.bin").write_bytes(bytes(range(256)))
    manifest.write(root)

    assert manifest.verify(root).intact

    (root / "EFI/OC/data.bin").write_bytes(bytes(range(255, -1, -1)))
    assert [item.path for item in manifest.verify(root).changed] == ["EFI/OC/data.bin"]
