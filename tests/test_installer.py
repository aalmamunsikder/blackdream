"""The installer backend: Apple's signature, chunk checks, and USB writes.

The USB tests use an ordinary temporary directory as a stand-in for a mounted
FAT32 volume. That is deliberate: ``write_installer`` is file-level copying, and
the only thing that makes the directory a "USB drive" is the identity check, which
is patched here to return the stand-in.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from blackdream.core import installer  # noqa: E402
from blackdream.core.pipeline import Cancelled, CancelToken  # noqa: E402

CHUNKLIST = Path(__file__).parent / "data" / "BaseSystem.chunklist"


def make_efi(root: Path) -> Path:
    efi = root / "EFI"
    (efi / "BOOT").mkdir(parents=True)
    (efi / "OC").mkdir()
    (efi / "BOOT" / "BOOTx64.efi").write_bytes(b"MZ" + b"\0" * 128)
    (efi / "OC" / "OpenCore.efi").write_bytes(b"\0" * (65 * 1024))
    (efi / "OC" / "config.plist").write_text("<plist/>", encoding="utf-8")
    return efi


def make_recovery(root: Path, payload: bytes = b"recovery-bytes" * 512):
    image = root / "BaseSystem.dmg"
    image.write_bytes(payload)
    chunklist = root / "BaseSystem.chunklist"
    chunklist.write_bytes(b"signed-list")
    return installer.RecoveryDownload(
        image=image, chunklist=chunklist,
        sha256=hashlib.sha256(payload).hexdigest(), size=len(payload),
        product="Test macOS")


def make_volume(mount: Path, identity: str = "test:identity"):
    usage = shutil.disk_usage(mount)
    return installer.UsbVolume(
        label="TESTUSB", mount=mount, device="/dev/fake1", filesystem="VFAT",
        size=usage.total, free=usage.free, identity=identity)


# ---- Apple's signed chunklist -------------------------------------------


def test_the_real_apple_chunklist_verifies():
    chunks = installer.parse_chunklist(CHUNKLIST.read_bytes())
    assert len(chunks) == 85
    assert chunks[0][0] == 10 * 1024 * 1024
    assert sum(size for size, _digest in chunks) > 800 * 1024 * 1024
    assert all(len(digest) == 32 for _size, digest in chunks)


def test_a_chunklist_with_a_flipped_byte_is_refused():
    data = bytearray(CHUNKLIST.read_bytes())
    data[installer._CHUNK_LIST_HEADER_SIZE + 4] ^= 0x01
    with pytest.raises(installer.ChunklistInvalid):
        installer.parse_chunklist(bytes(data))


def test_a_chunklist_with_a_broken_signature_is_refused():
    data = bytearray(CHUNKLIST.read_bytes())
    data[-1] ^= 0xFF
    with pytest.raises(installer.ChunklistInvalid):
        installer.parse_chunklist(bytes(data))


def test_an_unsigned_chunklist_is_refused():
    data = bytearray(CHUNKLIST.read_bytes())
    data[10] = 0  # signature method
    with pytest.raises(installer.ChunklistInvalid):
        installer.parse_chunklist(bytes(data))


def test_a_truncated_chunklist_is_refused():
    with pytest.raises(installer.ChunklistInvalid):
        installer.parse_chunklist(CHUNKLIST.read_bytes()[:100])


# ---- image verification --------------------------------------------------


def test_verify_image_accepts_every_chunk_and_reports_the_file_digest(tmp_path):
    payload = b"aaaa" + b"bbbbbb" + b"cc"
    image = tmp_path / "image.bin"
    image.write_bytes(payload)
    chunks = [(4, hashlib.sha256(b"aaaa").digest()),
              (6, hashlib.sha256(b"bbbbbb").digest()),
              (2, hashlib.sha256(b"cc").digest())]
    assert installer.verify_image(image, chunks) == hashlib.sha256(payload).hexdigest()


def test_verify_image_refuses_a_flipped_byte(tmp_path):
    image = tmp_path / "image.bin"
    image.write_bytes(b"wrong")
    with pytest.raises(installer.RecoveryImageCorrupt):
        installer.verify_image(image, [(5, hashlib.sha256(b"right").digest())])


def test_verify_image_refuses_a_short_or_long_file(tmp_path):
    short = tmp_path / "short.bin"
    short.write_bytes(b"ab")
    with pytest.raises(installer.RecoveryImageCorrupt):
        installer.verify_image(short, [(3, hashlib.sha256(b"abc").digest())])
    long = tmp_path / "long.bin"
    long.write_bytes(b"abcd")
    with pytest.raises(installer.RecoveryImageCorrupt):
        installer.verify_image(long, [(3, hashlib.sha256(b"abc").digest())])


# ---- release catalogue ---------------------------------------------------


def test_the_release_catalogue_covers_every_supported_macos():
    assert [release.version for release in installer.RECOVERY_RELEASES] == [
        "10.13", "10.14", "10.15", "11", "12", "13", "14", "15", "26"]
    assert installer.DEFAULT_RELEASE is installer.RECOVERY_RELEASES[-1]
    assert installer.DEFAULT_RELEASE.latest
    assert all(release.board_id.startswith("Mac-")
               for release in installer.RECOVERY_RELEASES)
    assert all(release.mlb for release in installer.RECOVERY_RELEASES)


def test_a_stored_version_finds_its_release_and_an_unknown_one_does_not():
    assert installer.release_for("14").name == "Sonoma"
    assert installer.release_for("99") is None


def test_every_release_has_its_own_cache():
    directories = [installer._cache_dir(release)
                   for release in installer.RECOVERY_RELEASES]
    assert len(set(directories)) == len(directories)


def test_the_default_release_keeps_the_legacy_cache_path():
    """Tahoe's image was cached under the board-only path before this picker."""
    assert installer._cache_dir(installer.DEFAULT_RELEASE).name == (
        installer.RECOVERY_BOARD_ID)


def test_each_release_requests_its_own_board_serial_and_os(
        tmp_path, monkeypatch):
    requested = []

    class Captured(Exception):
        pass

    def fetch(**kwargs):
        requested.append(kwargs)
        raise Captured()

    monkeypatch.setattr(installer, "fetch_recovery_asset", fetch)
    monkeypatch.setattr(installer, "_cache_dir",
                        lambda release: tmp_path / release.version)
    for release in installer.RECOVERY_RELEASES:
        with pytest.raises(Captured):
            installer.download_recovery(release=release, use_cache=False)
    assert requested == [
        {"board_id": release.board_id, "mlb": release.mlb,
         "os_type": release.os_type}
        for release in installer.RECOVERY_RELEASES]


def test_cached_recovery_is_scoped_to_the_release(tmp_path, monkeypatch):
    directories = {release.version: tmp_path / release.version
                   for release in installer.RECOVERY_RELEASES}
    for directory in directories.values():
        directory.mkdir()
    tahoe = directories[installer.DEFAULT_RELEASE.version]
    (tahoe / "BaseSystem.dmg").write_bytes(b"abc")
    (tahoe / "BaseSystem.chunklist").write_bytes(b"list")
    (tahoe / "verified.json").write_text(json.dumps({
        "release": "macOS Tahoe 26", "sha256": hashlib.sha256(b"abc").hexdigest(),
        "size": 3, "product": "140-93589"}), encoding="utf-8")
    monkeypatch.setattr(installer, "_cache_dir",
                        lambda release: directories[release.version])

    found = installer.cached_recovery(installer.DEFAULT_RELEASE)
    assert found is not None and found.release == "macOS Tahoe 26"
    assert installer.cached_recovery(installer.release_for("14")) is None


def test_cached_recovery_refuses_a_manifest_for_another_release(
        tmp_path, monkeypatch):
    directory = tmp_path / "cache"
    directory.mkdir()
    (directory / "BaseSystem.dmg").write_bytes(b"abc")
    (directory / "BaseSystem.chunklist").write_bytes(b"list")
    (directory / "verified.json").write_text(json.dumps({
        "release": "macOS Sonoma 14", "sha256": hashlib.sha256(b"abc").hexdigest(),
        "size": 3, "product": "696-08090"}), encoding="utf-8")
    monkeypatch.setattr(installer, "_cache_dir", lambda release: directory)

    assert installer.cached_recovery(installer.DEFAULT_RELEASE) is None


def test_cached_recovery_ignores_a_size_mismatch(tmp_path, monkeypatch):
    directory = tmp_path / "cache"
    directory.mkdir()
    image = directory / "BaseSystem.dmg"
    image.write_bytes(b"abc")
    (directory / "BaseSystem.chunklist").write_bytes(b"list")
    (directory / "verified.json").write_text(json.dumps({
        "sha256": hashlib.sha256(b"abc").hexdigest(), "size": 99,
        "product": "Test"}), encoding="utf-8")
    monkeypatch.setattr(installer, "_cache_dir", lambda board_id: directory)
    assert installer.cached_recovery() is None


# ---- USB discovery details ----------------------------------------------


def test_linux_mount_escapes_are_decoded():
    assert installer._unescape_mount("/media/u/My\\040Drive") == "/media/u/My Drive"
    assert installer._unescape_mount("/media/u/back\\134slash") == "/media/u/back\\slash"


def test_copy_tree_refuses_a_symlink(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    try:
        (source / "target").symlink_to("/etc/hostname")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")
    with pytest.raises(installer.InstallerCopyFailed):
        installer._copy_tree(source, tmp_path / "out")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX-only")
def test_copy_tree_refuses_a_fifo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    os.mkfifo(source / "pipe")
    with pytest.raises(installer.InstallerCopyFailed):
        installer._copy_tree(source, tmp_path / "out")


def test_efi_validation_names_the_missing_piece(tmp_path):
    efi = make_efi(tmp_path)
    (efi / "OC" / "config.plist").unlink()
    with pytest.raises(installer.InstallerCopyFailed) as caught:
        installer.validate_efi_folder(tmp_path)
    assert "config.plist" in caught.value.detail


def test_asset_urls_must_stay_on_apple_cdn():
    with pytest.raises(installer.RecoveryResponseInvalid):
        installer._apple_asset_url("https://example.com/content/downloads/x")
    assert installer._apple_asset_url(
        "https://oscdn.apple.com/content/downloads/x?y=1") == (
            "http://oscdn.apple.com/content/downloads/x?y=1")


# ---- writing to a volume -------------------------------------------------


def test_write_installer_copies_and_preserves_unrelated_files(tmp_path, monkeypatch):
    built = tmp_path / "built"
    make_efi(built)
    recovery = make_recovery(tmp_path)
    mount = tmp_path / "usb"
    mount.mkdir()
    (mount / "keep.txt").write_text("keep", encoding="utf-8")
    old_efi = mount / "EFI"
    old_efi.mkdir()
    (old_efi / "old.txt").write_text("old", encoding="utf-8")
    volume = make_volume(mount, identity="usb:1")
    monkeypatch.setattr(installer, "list_usb_volumes", lambda: [volume])

    result = installer.write_installer(volume, built, recovery)

    assert result["sha256"] == recovery.sha256
    assert (mount / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not (mount / "EFI" / "old.txt").exists()
    assert (mount / "EFI" / "BOOT" / "BOOTx64.efi").read_bytes().startswith(b"MZ")
    assert (mount / "com.apple.recovery.boot" / "BaseSystem.dmg").read_bytes() == (
        recovery.image.read_bytes())
    marker = json.loads((mount / installer.MARKER_NAME).read_text(encoding="utf-8"))
    assert marker["image_sha256"] == recovery.sha256
    assert not list(mount.glob(".blackdream-stage-*"))


def test_write_installer_leaves_the_previous_efi_when_cancelled(tmp_path, monkeypatch):
    built = tmp_path / "built"
    make_efi(built)
    recovery = make_recovery(tmp_path)
    mount = tmp_path / "usb"
    mount.mkdir()
    (mount / "EFI").mkdir()
    (mount / "EFI" / "old.txt").write_text("old", encoding="utf-8")
    volume = make_volume(mount)
    monkeypatch.setattr(installer, "list_usb_volumes", lambda: [volume])
    token = CancelToken()
    token.cancel()

    with pytest.raises(Cancelled):
        installer.write_installer(volume, built, recovery, token=token)

    assert (mount / "EFI" / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (mount / "com.apple.recovery.boot").exists()
    assert not list(mount.glob(".blackdream-stage-*"))


def test_write_installer_rolls_back_when_the_second_swap_fails(tmp_path, monkeypatch):
    built = tmp_path / "built"
    make_efi(built)
    recovery = make_recovery(tmp_path)
    mount = tmp_path / "usb"
    mount.mkdir()
    (mount / "EFI").mkdir()
    (mount / "EFI" / "old.txt").write_text("old", encoding="utf-8")
    volume = make_volume(mount)
    monkeypatch.setattr(installer, "list_usb_volumes", lambda: [volume])

    real_replace = os.replace

    def failing_replace(source, destination):
        if (Path(source).name == "com.apple.recovery.boot"
                and ".blackdream-stage-" in str(source)):
            raise OSError("injected failure")
        return real_replace(source, destination)

    monkeypatch.setattr(installer.os, "replace", failing_replace)

    with pytest.raises(installer.InstallerCopyFailed):
        installer.write_installer(volume, built, recovery)

    assert (mount / "EFI" / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (mount / "EFI" / "BOOT").exists()
    assert not (mount / "com.apple.recovery.boot").exists()
    assert not list(mount.glob(".blackdream-stage-*"))
