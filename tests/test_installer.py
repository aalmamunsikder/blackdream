"""The installer backend: Apple's signature, chunk checks, and USB writes.

The USB tests use an ordinary temporary directory as a stand-in for a mounted
FAT32 volume. That is deliberate: ``write_installer`` is file-level copying, and
the only thing that makes the directory a "USB drive" is the identity check, which
is patched here to return the stand-in.
"""

from __future__ import annotations

import ast
import collections
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


# ---- re-identifying the target before the first byte ---------------------


#: The shape ``shutil.disk_usage`` answers with; the write path reads ``free``.
_Disk = collections.namedtuple("_Disk", "total used free")


def _prepared(tmp_path):
    """A built folder, a verified recovery and a mounted stand-in volume with one
    file on it that has to survive every refusal below."""
    built = tmp_path / "built"
    make_efi(built)
    mount = tmp_path / "usb"
    mount.mkdir()
    (mount / "keep.txt").write_text("keep", encoding="utf-8")
    return built, make_recovery(tmp_path), mount


def test_a_drive_swapped_behind_the_confirmation_is_refused(tmp_path, monkeypatch):
    """The list the user chose from was true a moment ago. ``_assert_target`` runs
    again inside the write, so the drive that answers now has to be the drive that
    was named -- not a smaller one that happened to get the same mount point."""
    built, recovery, mount = _prepared(tmp_path)
    volume = make_volume(mount, identity="usb:1")
    monkeypatch.setattr(installer, "list_usb_volumes",
                        lambda: [make_volume(mount, identity="usb:2")])

    with pytest.raises(installer.UsbVolumeRefused) as caught:
        installer.write_installer(volume, built, recovery)

    assert "no longer present" in caught.value.detail
    assert (mount / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not list(mount.glob(".blackdream-stage-*"))


def test_the_system_volume_is_refused_even_when_a_scan_offers_it(tmp_path, monkeypatch):
    """A volume list is produced by scanning, and a scan can be wrong. The system
    disk is refused by name as well, because the one write this app cannot take
    back is the one to the volume this machine boots from."""
    built, recovery, mount = _prepared(tmp_path)
    volume = make_volume(mount, identity="usb:1")
    monkeypatch.setattr(installer, "list_usb_volumes", lambda: [volume])
    monkeypatch.setattr(installer, "_system_mounts", lambda: {str(mount)})

    with pytest.raises(installer.UsbVolumeRefused) as caught:
        installer.write_installer(volume, built, recovery)

    assert "system volume" in caught.value.detail
    assert not (mount / "EFI").exists()


def test_a_drive_without_room_is_refused_before_anything_is_copied(tmp_path,
                                                                  monkeypatch):
    """Half of a multi-gigabyte copy onto a full stick is worse than none of it:
    the previous installer has gone and the new one does not fit."""
    built, recovery, mount = _prepared(tmp_path)
    volume = make_volume(mount, identity="usb:1")
    monkeypatch.setattr(installer, "list_usb_volumes", lambda: [volume])
    monkeypatch.setattr(installer.shutil, "disk_usage",
                        lambda path: _Disk(64 * 2**30, 0, 1024))

    with pytest.raises(installer.InstallerCopyFailed) as caught:
        installer.write_installer(volume, built, recovery)

    assert "MiB free" in caught.value.detail
    assert (mount / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not list(mount.glob(".blackdream-stage-*"))


# ---- resuming a half-downloaded image -----------------------------------


class _StreamResponse:
    """The three members of a ``urlopen`` result that ``_stream`` actually uses."""

    def __init__(self, code, body):
        self._code = code
        self._body = body
        self._pos = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def getcode(self):
        return self._code

    def read(self, _size):
        piece = self._body[self._pos:self._pos + 64]
        self._pos += len(piece)
        return piece


class _FakeCdn:
    """Answers ``_stream``'s opener from a scripted list of ``(code, body)`` per
    attempt, and keeps every request's headers so a range request can be told
    apart from a fresh one."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.headers = []

    def open(self, request, timeout=None):
        self.headers.append(dict(request.header_items()))
        code, body = self._answers.pop(0)
        return _StreamResponse(code, body)


BODY = bytes(range(256)) * 2


def _stream_through(monkeypatch, cdn, destination):
    monkeypatch.setattr(installer, "build_opener", lambda *args: cdn)
    return installer._stream("http://oscdn.example.test/BaseSystem.dmg", "token",
                             destination, "Test macOS", len(BODY), None)


def test_a_partial_image_resumes_where_it_stopped(tmp_path, monkeypatch):
    """A 7 GB image interrupted at a third of the way is the normal case for this
    download, not the exception. Re-asking for the whole thing would make it never
    finish on a machine with a short-lived connection."""
    destination = tmp_path / "BaseSystem.dmg"
    staging = destination.with_name(destination.name + ".part")
    staging.write_bytes(BODY[:len(BODY) // 2])

    cdn = _FakeCdn([(206, BODY[len(BODY) // 2:])])
    result = _stream_through(monkeypatch, cdn, destination)

    assert cdn.headers[0].get("Range") == "bytes={}-".format(len(BODY) // 2)
    assert result.read_bytes() == BODY
    assert not destination.exists()  # the caller promotes it only once verified


def test_a_server_that_ignores_the_range_restates_the_whole_image(tmp_path,
                                                                 monkeypatch):
    """Appending a full 200 body to a half file gives an image that is neither the
    old download nor the new one. Chunk verification catches that before a USB
    drive sees it, so the cost of getting this wrong is a download that never
    completes rather than a corrupt installer -- which is why it is still checked.
    """
    destination = tmp_path / "BaseSystem.dmg"
    staging = destination.with_name(destination.name + ".part")
    staging.write_bytes(BODY[:len(BODY) // 2])

    cdn = _FakeCdn([(200, BODY)])
    result = _stream_through(monkeypatch, cdn, destination)

    assert cdn.headers[0].get("Range")  # it did ask to resume
    assert result.read_bytes() == BODY


#: The commands that would take a drive apart. Reading a mount table and copying
#: files onto a volume is what the installer does; formatting, mounting,
#: partitioning or opening the whole device is how a tester loses the machine they
#: booted from. The notes promise that never happens, so it is enforced here on the
#: syntax tree rather than repeated as a sentence.
DISK_COMMANDS = {
    "diskutil": frozenset({"list", "info", "enumerate"}),
    "mount": frozenset(), "umount": frozenset(),
    "mkfs": frozenset(), "newfs": frozenset(),
    "fdisk": frozenset(), "sfdisk": frozenset(), "parted": frozenset(),
    "dd": frozenset(), "mdadm": frozenset(), "blkdiscard": frozenset(),
    "Format-Volume": frozenset(), "Set-Partition": frozenset(),
    "Clear-Disk": frozenset(),
}

APP_SOURCE = Path(__file__).resolve().parents[1] / "src" / "blackdream"


def _command_tokens(call) -> tuple:
    """The words of a command literal, in order, or () when it is not a literal.

    Only a constant command can be judged: a path built from a variable is the
    business of the behaviour tests, not of this sweep.
    """
    if not call.args:
        return ()
    first = call.args[0]
    if isinstance(first, ast.List):
        return tuple(getattr(element, "value", None) for element in first.elts)
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return tuple(first.value.split())
    return ()


def test_the_app_never_formats_mounts_or_opens_a_disk():
    offenders = []
    for path in sorted(APP_SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (node.func.id if isinstance(node.func, ast.Name)
                    else getattr(node.func, "attr", ""))
            if name in {"run", "Popen", "call", "check_output", "check_call",
                        "system", "popen"}:
                tokens = _command_tokens(node)
                for index, token in enumerate(tokens):
                    if not isinstance(token, str):
                        continue
                    program = token.strip().replace("\\", "/").rsplit("/", 1)[-1]
                    allowed = DISK_COMMANDS.get(program)
                    if allowed is None and program.startswith(("mkfs", "newfs")):
                        allowed = frozenset()
                    if allowed is None:
                        continue
                    following = tokens[index + 1] if index + 1 < len(tokens) else ""
                    if following not in allowed:
                        offenders.append("{}:{}: would run {}".format(
                            path.name, node.lineno, " ".join(
                                str(item) for item in tokens[index:index + 2])))
            elif name == "open" and node.args:
                target = getattr(node.args[0], "value", None)
                if isinstance(target, str) and (
                        target.startswith("/dev") or "PhysicalDrive" in target
                        or "/rdisk" in target):
                    offenders.append("{}:{}: would open {}".format(
                        path.name, node.lineno, target))

    assert offenders == []
