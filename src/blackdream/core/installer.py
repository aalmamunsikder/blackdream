"""Make a macOS recovery installer on a USB drive.

Apple's recovery service is the only cross-platform source of a macOS installer:
``createinstallmedia`` exists only on macOS and needs a 12 GB Installer app. The
OpenCore project's ``macrecovery`` speaks this service, and this module follows the
same protocol with the same trust model, restated here because the transport alone
does not carry it:

* The session and the payload metadata are fetched over HTTPS from
  ``osrecovery.apple.com`` and the response is refused if a redirect leaves HTTPS.
* The image and its chunklist live on ``oscdn.apple.com``, which serves no
  certificate matching its hostname. TLS verification is **not** weakened to reach
  it. Instead the chunklist is verified against Apple's embedded EFI ROM public key
  -- the same signature check ``macrecovery`` performs -- and every image chunk is
  hashed against the signed chunklist while it is copied. Transport integrity is
  irrelevant because the bytes are authenticated end to end.
* Access tokens in the payload response are credentials for the download session.
  They are kept out of ``repr``, logs and error text.

Writing targets a **mounted FAT32 volume on a USB bus**. Nothing here formats a
disk, opens a block device, or touches the machine's own EFI partition: the copy is
ordinary file I/O into an existing mount, and the caller must have confirmed the
volume with the user first. The volume's identity is re-checked at write time so a
drive swapped behind the confirmation dialog is refused.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import plistlib
import re
import shutil
import ssl
import stat
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, Request, build_opener)

from ocengine import paths as engine_paths
from ocengine import runtime
from ocengine.fatal import EngineError

#: A recent Intel Mac. With an anonymous MLB Apple treats ``os=latest`` as the
#: unified latest release, which is what a PC being prepared for OpenCore wants.
RECOVERY_BOARD_ID = "Mac-27AD2F918AE68F61"
RECOVERY_BOARD_NAME = "MacPro7,1"
MLB_ANONYMOUS = "00000000000000000"


@dataclass(frozen=True)
class RecoveryRelease:
    """One selectable macOS release, and the Mac it is requested as.

    Apple's service has no version parameter. A request names a Mac (board ID)
    and a serial (MLB), and the answer is the newest release that model can run.
    So a release is selected by picking a model pinned to it -- the same mapping
    ``macrecovery`` in OpenCorePkg documents. ``os_type="latest"`` is the one
    exception: it asks for Apple's newest unified release regardless of model.
    """

    name: str
    version: str
    board_id: str
    mlb: str = MLB_ANONYMOUS
    os_type: str = "default"

    @property
    def label(self) -> str:
        return "macOS {} {}".format(self.name, self.version)

    @property
    def latest(self) -> bool:
        return self.os_type == "latest"


#: Every release the build engine grades (10.13 through 26), oldest first. Each
#: board/serial pair was checked against the live recovery service. Tahoe keeps
#: the MacPro7,1 board the installer used before releases were selectable, which
#: is also Apple's unified ``latest`` image.
RECOVERY_RELEASES = (
    RecoveryRelease("High Sierra", "10.13", "Mac-BE088AF8C5EB4FA2",
                    "00000000000J80300"),
    RecoveryRelease("Mojave", "10.14", "Mac-7BA5B2DFE22DDD8C",
                    "00000000000KXPG00"),
    RecoveryRelease("Catalina", "10.15", "Mac-CFF7D910A743CAAF",
                    "00000000000PHCD00"),
    RecoveryRelease("Big Sur", "11", "Mac-2BD1B31983FE1663"),
    RecoveryRelease("Monterey", "12", "Mac-E43C1C25D4880AD6"),
    RecoveryRelease("Ventura", "13", "Mac-B4831CEBD52A0C4C"),
    RecoveryRelease("Sonoma", "14", "Mac-827FAC58A8FDFA22"),
    RecoveryRelease("Sequoia", "15", "Mac-7BA5B2D9E42DDD94"),
    RecoveryRelease("Tahoe", "26", RECOVERY_BOARD_ID, os_type="latest"),
)
DEFAULT_RELEASE = RECOVERY_RELEASES[-1]


def release_for(version: str) -> RecoveryRelease | None:
    """The catalogue entry for a stored version string, if it still exists."""
    return next((release for release in RECOVERY_RELEASES
                 if release.version == version), None)

RECOVERY_ROOT = "https://osrecovery.apple.com/"
RECOVERY_PAYLOAD = "https://osrecovery.apple.com/InstallationPayload/RecoveryImage"
CDN_HOST = "oscdn.apple.com"
CDN_PREFIX = "/content/downloads/"

#: Apple's EFI ROM signing key, as published in OpenCorePkg's macrecovery.py
#: (Copyright (c) 2019, vit9696; BSD-3-Clause). The chunklist signature is the
#: trust anchor for everything that follows it.
APPLE_EFI_ROM_PUBLIC_KEY_1 = int(
    "C3E748CAD9CD384329E10E25A91E43E1A762FF529ADE578C935BDDF9B13F2179D4855E6FC89E9E29CA"
    "12517D17DFA1EDCE0BEBF0EA7B461FFE61D94E2BDF72C196F89ACD3536B644064014DAE25A15DB6BB"
    "0852ECBD120916318D1CCDEA3C84C92ED743FC176D0BACA920D3FCF3158AFF731F88CE0623182A8ED"
    "67E650515F75745909F07D415F55FC15A35654D118C55A462D37A3ACDA08612F3F3F6571761EFCCBC"
    "C299AEE99B3A4FD6212CCFFF5EF37A2C334E871191F7E1C31960E010A54E86FA3F62E6D6905E1CD57"
    "732410A3EB0C6B4DEFDABE9F59BF1618758C751CD56CEF851D1C0EAA1C558E37AC108DA9089863D2"
    "0E2E7E4BF475EC66FE6B3EFDCF", 16)
APPLE_SIGNATURE_EXPONENT = 0x10001

_CHUNK_LIST_HEADER = struct.Struct("<4sIBBBxQQQ")
_CHUNK = struct.Struct("<I32s")
_CHUNK_LIST_HEADER_SIZE = _CHUNK_LIST_HEADER.size
_CHUNK_SIZE = _CHUNK.size

MIB = 1024 * 1024
COPY_MARGIN = 64 * MIB
DOWNLOAD_TIMEOUT = 60
METADATA_TIMEOUT = 30
MAX_ATTEMPTS = 3
MARKER_NAME = ".blackdream-installer.json"


class InstallerError(EngineError):
    code = "installer.error"
    title = "The installer could not be prepared"


class RecoveryServiceUnavailable(InstallerError):
    """The session or the payload request never produced an answer."""

    code = "installer.recovery_service_unavailable"
    title = "Apple's recovery service could not be reached"
    remediation = (
        "Check the network and retry. Nothing was downloaded or written.",
        "The service is region-sensitive; a VPN can make it answer with an error.",
    )


class RecoveryResponseInvalid(InstallerError):
    """The service answered, but not with the fields the protocol needs."""

    code = "installer.recovery_response_invalid"
    title = "Apple's recovery service returned an unexpected answer"
    remediation = (
        "Retry once. If it repeats, the service changed its payload and this build "
        "of BlackDream needs an update.",
    )


class ChunklistInvalid(InstallerError):
    """The chunklist is malformed, truncated, or not signed by Apple."""

    code = "installer.chunklist_invalid"
    title = "The recovery image's chunklist is not authentic"
    remediation = (
        "Nothing from this download was kept. Retry; if it repeats, do not use the "
        "network in between, because the signature is Apple's and cannot change.",
    )
    recoverable = False


class RecoveryDownloadFailed(InstallerError):
    code = "installer.download_failed"
    title = "The macOS recovery image could not be downloaded"
    remediation = (
        "The partial file was kept so the next attempt can resume.",
        "Retry once the connection is stable.",
    )


class RecoveryImageCorrupt(InstallerError):
    code = "installer.image_corrupt"
    title = "The recovery image did not match Apple's signed chunklist"
    remediation = (
        "The image was discarded. Download it again; do not write it to a USB drive.",
    )
    recoverable = False


class NoUsbVolume(InstallerError):
    code = "installer.no_usb_volume"
    title = "No FAT32 USB drive is mounted"
    remediation = (
        "Plug in the USB drive and mount it. The installer needs a FAT32 volume; "
        "OpenCore's UEFI firmware cannot read exFAT or NTFS.",
        "If the drive shows but is not FAT32, format it as FAT32 yourself. "
        "BlackDream never formats a disk.",
    )


class UsbVolumeRefused(InstallerError):
    code = "installer.usb_refused"
    title = "That drive cannot be used for the installer"
    remediation = (
        "Choose a removable FAT32 volume that is not the system disk.",
        "The drive's identity was checked again before writing; reconnect it and "
        "pick it from the list if it was replaced.",
    )


class InstallerCopyFailed(InstallerError):
    code = "installer.copy_failed"
    title = "The installer could not be copied to the USB drive"
    remediation = (
        "The previous EFI folder on the drive was left intact where possible.",
        "Free space on the drive, then retry.",
    )


@dataclass(frozen=True)
class RecoveryAsset:
    """One payload answer. Tokens are credentials and never appear in a repr."""

    product: str
    image_url: str = field(repr=False)
    image_token: str = field(repr=False)
    chunklist_url: str = field(repr=False)
    chunklist_token: str = field(repr=False)


@dataclass(frozen=True)
class RecoveryDownload:
    """A verified image on disk, plus the digest later copy steps re-check."""

    image: Path
    chunklist: Path
    sha256: str
    size: int
    product: str
    release: str = ""


@dataclass(frozen=True)
class UsbVolume:
    """A mounted, writable FAT32 volume on a USB bus."""

    label: str
    mount: Path
    device: str
    filesystem: str
    size: int
    free: int
    identity: str = field(repr=False, default="")

    @property
    def display(self) -> str:
        return "{} · {} · {:.1f} GB".format(
            self.label or self.mount.name or self.device,
            self.device,
            self.size / 1_000_000_000)


def _sink():
    return runtime.current_sink()


def _log(level: str, message: str) -> None:
    _sink().log(level, message)


def _ssl_context() -> ssl.SSLContext:
    """A verifying context. There is deliberately no unverified fallback."""
    try:
        return ssl.create_default_context()
    except Exception:
        pass
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception as exc:
        raise RecoveryServiceUnavailable(
            detail="No certificate store could be loaded, so Apple's service cannot "
                   "be contacted safely: {}".format(exc)) from exc


class _HttpsOnlyRedirect(HTTPRedirectHandler):
    """Refuse a redirect that would drop TLS for the metadata request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise HTTPError(newurl, code,
                            "refusing a non-HTTPS redirect", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _https_opener():
    return build_opener(HTTPSHandler(context=_ssl_context()),
                        _HttpsOnlyRedirect())


class _CdnRedirect(HTTPRedirectHandler):
    """Keep CDN redirects on Apple's CDN. The bytes are hash-checked anyway;
    this just stops the request from wandering to an unrelated host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).hostname != CDN_HOST:
            raise HTTPError(newurl, code,
                            "refusing a redirect away from the CDN", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_all(response, limit: int) -> bytes:
    chunks = []
    size = 0
    while True:
        piece = response.read(64 * 1024)
        if not piece:
            break
        size += len(piece)
        if size > limit:
            raise RecoveryResponseInvalid(
                detail="Apple's recovery service returned more data than this "
                       "protocol can carry.")
        chunks.append(piece)
    return b"".join(chunks)


def fetch_recovery_asset(board_id: str = RECOVERY_BOARD_ID,
                         mlb: str = MLB_ANONYMOUS,
                         os_type: str = "latest",
                         timeout: float = METADATA_TIMEOUT) -> RecoveryAsset:
    """Ask Apple's recovery service for the image for ``board_id`` + ``mlb``.

    The pair selects the release (see :class:`RecoveryRelease`); ``os_type`` is
    ``default`` or ``latest`` and only matters when a serial narrows the answer.
    The response's access tokens are never logged. A redirect out of HTTPS fails
    the request; the payload itself is not signed, so TLS is its only transport
    guarantee.
    """
    opener = _https_opener()
    session = None
    last_error = None
    for _attempt in range(MAX_ATTEMPTS):
        try:
            with opener.open(Request(RECOVERY_ROOT, headers={
                    "User-Agent": "InternetRecovery/1.0",
                    "Connection": "close"}), timeout=timeout) as response:
                for header in response.headers.get_all("Set-Cookie") or []:
                    for part in header.split(";"):
                        part = part.strip()
                        if part.startswith("session="):
                            session = part
                            break
                    if session:
                        break
            if session:
                break
        except (HTTPError, URLError, OSError, ssl.SSLError) as exc:
            last_error = exc
            _log("warning", "Apple recovery session attempt failed: {}".format(exc))
    if not session:
        raise RecoveryServiceUnavailable(
            detail="Apple's recovery service did not return a session: {}".format(
                last_error or "no Set-Cookie header"))

    import secrets
    payload = "\n".join((
        "cid={}".format(secrets.token_hex(8).upper()),
        "sn={}".format(mlb),
        "bid={}".format(board_id),
        "k={}".format(secrets.token_hex(32).upper()),
        "fg={}".format(secrets.token_hex(32).upper()),
        "os={}".format(os_type),
    )).encode()
    request = Request(RECOVERY_PAYLOAD, data=payload, headers={
        "User-Agent": "InternetRecovery/1.0",
        "Cookie": session,
        "Content-Type": "text/plain",
        "Connection": "close",
    })
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.getcode() != 200:
                raise RecoveryResponseInvalid(
                    detail="Apple's recovery service answered HTTP {}.".format(
                        response.getcode()))
            body = _read_all(response, 64 * 1024)
    except RecoveryResponseInvalid:
        raise
    except (HTTPError, URLError, OSError, ssl.SSLError) as exc:
        raise RecoveryServiceUnavailable(
            detail="The recovery payload request failed: {}".format(exc)) from exc

    fields = {}
    for line in body.decode("utf-8", "replace").splitlines():
        key, separator, value = line.partition(": ")
        if separator:
            fields[key.strip()] = value.strip()
    missing = [key for key in ("AP", "AU", "AT", "CU", "CT") if not fields.get(key)]
    if missing:
        raise RecoveryResponseInvalid(
            detail="The payload omitted {}; the service response changed.".format(
                ", ".join(missing)))
    return RecoveryAsset(
        product=fields["AP"],
        image_url=_apple_asset_url(fields["AU"]),
        image_token=fields["AT"],
        chunklist_url=_apple_asset_url(fields["CU"]),
        chunklist_token=fields["CT"])


def _apple_asset_url(url: str) -> str:
    """Pin asset URLs to Apple's CDN, and keep them on the scheme it serves.

    ``oscdn.apple.com`` presents a certificate for a different name, so HTTPS to it
    fails hostname verification. Only this host and path are accepted, and the
    bytes are authenticated by the signed chunklist rather than by the transport.
    """
    parts = urlsplit(url)
    if parts.hostname != CDN_HOST or not parts.path.startswith(CDN_PREFIX):
        raise RecoveryResponseInvalid(
            detail="The payload pointed at an unexpected host; refusing to "
                   "download from it.")
    return urlunsplit(("http", CDN_HOST, parts.path, parts.query, ""))


def parse_chunklist(data: bytes,
                    public_key: int = APPLE_EFI_ROM_PUBLIC_KEY_1
                    ) -> list[tuple[int, bytes]]:
    """Validate and return ``(size, sha256)`` for every chunk.

    The signature covers the header and every chunk entry, and is checked with
    Apple's EFI ROM key. A chunklist that carries no signature is refused rather
    than accepted as a hash list, because an unsigned list would let whoever served
    it choose both the bytes and their hashes.
    """
    if len(data) < _CHUNK_LIST_HEADER_SIZE:
        raise ChunklistInvalid(detail="The chunklist is shorter than its header.")
    header = data[:_CHUNK_LIST_HEADER_SIZE]
    (magic, header_size, version, chunk_method, signature_method,
     count, chunk_offset, signature_offset) = _CHUNK_LIST_HEADER.unpack(header)
    if (magic != b"CNKL" or header_size != _CHUNK_LIST_HEADER_SIZE
            or version != 1 or chunk_method != 1 or count == 0
            or chunk_offset != _CHUNK_LIST_HEADER_SIZE):
        raise ChunklistInvalid(detail="The chunklist header is not in Apple's format.")
    if signature_offset != chunk_offset + _CHUNK_SIZE * count:
        raise ChunklistInvalid(detail="The chunklist's signature offset is inconsistent.")
    if signature_method != 1:
        raise ChunklistInvalid(
            detail="The chunklist is not digitally signed (method {}).".format(
                signature_method))
    expected_length = signature_offset + 256
    if len(data) != expected_length:
        raise ChunklistInvalid(
            detail="The chunklist is {} bytes; its header describes {}.".format(
                len(data), expected_length))

    chunks = []
    digest = hashlib.sha256()
    digest.update(header)
    for index in range(count):
        start = chunk_offset + index * _CHUNK_SIZE
        entry = data[start:start + _CHUNK_SIZE]
        digest.update(entry)
        size, chunk_hash = _CHUNK.unpack(entry)
        if size <= 0:
            raise ChunklistInvalid(
                detail="Chunk {} has a zero length.".format(index + 1))
        chunks.append((size, chunk_hash))

    signature = int.from_bytes(
        data[signature_offset:signature_offset + 256], "little")
    # PKCS#1 v1.5 over SHA-256 with Apple's digest OID:
    # 0x00 0x01 FF..FF 0x00 DigestInfo(SHA-256, digest), padded to 256 bytes.
    digest_info = bytes.fromhex(
        "3031300d060960864801650304020105000420") + digest.digest()
    padding = b"\xff" * (256 - len(digest_info) - 3)
    plaintext = int.from_bytes(b"\x00\x01" + padding + b"\x00" + digest_info, "big")
    if pow(signature, APPLE_SIGNATURE_EXPONENT, public_key) != plaintext:
        raise ChunklistInvalid(
            detail="The chunklist did not verify against Apple's EFI ROM public key.")
    return chunks


def verify_image(path: Path, chunks: list[tuple[int, bytes]],
                 token=None) -> str:
    """Hash ``path`` chunk by chunk against ``chunks``; return the file SHA-256."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for index, (size, expected) in enumerate(chunks, 1):
                if token is not None:
                    token.check()
                piece = handle.read(size)
                if len(piece) != size:
                    raise RecoveryImageCorrupt(
                        detail="The image ended at chunk {} of {}.".format(
                            index, len(chunks)))
                if hashlib.sha256(piece).digest() != expected:
                    raise RecoveryImageCorrupt(
                        detail="Chunk {} of {} did not match Apple's signed "
                               "chunklist.".format(index, len(chunks)))
                digest.update(piece)
            if handle.read(1):
                raise RecoveryImageCorrupt(
                    detail="The image is longer than its signed chunklist.")
    except OSError as exc:
        raise RecoveryImageCorrupt(
            detail="The image could not be read back: {}".format(exc)) from exc
    return digest.hexdigest()


def _stream(url: str, token: str, destination: Path, product: str,
            expected_size: int | None, check) -> Path:
    """Stream one CDN asset to ``destination.part``, resuming when possible.

    Authentication for this hop is content-level: the chunklist arrives first and
    is signature-checked, and the image is checked against it. The CDN's inability
    to serve TLS under its own hostname is never worked around in the SSL layer.
    """
    staging = destination.with_name(destination.name + ".part")
    if expected_size is None and staging.exists():
        # A metadata asset is a few kilobytes; resuming it has no value and a
        # leftover complete .part would make the range request ask past EOF.
        staging.unlink()
    last_error = None
    for _attempt in range(MAX_ATTEMPTS):
        resume_at = staging.stat().st_size if staging.exists() else 0
        if expected_size is not None and resume_at >= expected_size:
            staging.unlink()
            resume_at = 0
        headers = {
            "User-Agent": "InternetRecovery/1.0",
            "Cookie": "AssetToken=" + token,
            "Connection": "close",
        }
        if resume_at:
            headers["Range"] = "bytes={}-".format(resume_at)
        try:
            response = build_opener(_CdnRedirect()).open(
                Request(url, headers=headers), timeout=DOWNLOAD_TIMEOUT)
        except (HTTPError, URLError, OSError, ssl.SSLError) as exc:
            last_error = exc
            _log("warning", "Download attempt for {} failed: {}".format(product, exc))
            continue

        with response:
            code = response.getcode()
            if resume_at and code == 206:
                mode = "ab"
                done = resume_at
            elif code == 200:
                mode = "wb"
                done = 0
            else:
                last_error = "HTTP {}".format(code)
                _log("warning", "Download of {} answered {}; retrying.".format(
                    product, code))
                continue
            last_emit = time.monotonic()
            sampled = done
            try:
                with open(staging, mode) as handle:
                    while True:
                        if check is not None:
                            check.check()
                        piece = response.read(1024 * 1024)
                        if not piece:
                            break
                        handle.write(piece)
                        done += len(piece)
                        now = time.monotonic()
                        if now - last_emit > 0.5:
                            elapsed = max(now - last_emit, 1e-6)
                            _sink().transfer(runtime.Transfer(
                                product=product,
                                done_bytes=done,
                                total_bytes=expected_size,
                                bytes_per_second=(done - sampled) / elapsed))
                            last_emit, sampled = now, done
            except (OSError, http.client.HTTPException) as exc:
                last_error = exc
                _log("warning", "Could not write {}: {}; retrying.".format(
                    product, exc))
                continue

        if expected_size is None or staging.stat().st_size == expected_size:
            return staging
        last_error = "size {} != {}".format(staging.stat().st_size, expected_size)
        _log("warning", "{} is incomplete ({}); resuming.".format(product, last_error))

    raise RecoveryDownloadFailed(
        detail="{} could not be downloaded after {} attempts: {}".format(
            product, MAX_ATTEMPTS, last_error or "unknown error"))


def _cache_dir(release: RecoveryRelease) -> Path:
    """One directory per requested image.

    A zero serial keeps the historic board-only path, so the Tahoe image cached
    before releases were selectable is still found. A real serial is part of the
    key because Apple answers board+serial with a different release than the
    board alone: Catalina and Tahoe share a board and differ only by serial.
    """
    key = release.board_id if release.mlb == MLB_ANONYMOUS else "{}-{}".format(
        release.board_id, release.mlb)
    return Path(engine_paths.current().cache_dir) / "recovery" / key


def _manifest_path(directory: Path) -> Path:
    return directory / "verified.json"


def cached_recovery(release: RecoveryRelease = DEFAULT_RELEASE
                    ) -> RecoveryDownload | None:
    """What is on disk for ``release``, without hashing 843 MB on the GUI thread.

    This is for display only. :func:`download_recovery` re-verifies the bytes
    against the signed chunklist before returning them for a write.
    """
    directory = _cache_dir(release)
    image = directory / "BaseSystem.dmg"
    chunklist = directory / "BaseSystem.chunklist"
    manifest = _manifest_path(directory)
    if not (image.is_file() and chunklist.is_file() and manifest.is_file()):
        return None
    try:
        record = json.loads(manifest.read_text(encoding="utf-8"))
        if record.get("size") != image.stat().st_size:
            return None
        # A manifest written by 3.1 names its release. A directory reused for a
        # different release must not hand its bytes to this one.
        stored_release = str(record.get("release", ""))
        if stored_release and stored_release != release.label:
            return None
        return RecoveryDownload(image=image, chunklist=chunklist,
                                sha256=str(record["sha256"]),
                                size=int(record["size"]),
                                product=str(record.get("product", "")),
                                release=str(record.get("release", "")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def download_recovery(release: RecoveryRelease = DEFAULT_RELEASE, token=None,
                      use_cache: bool = True) -> RecoveryDownload:
    """Return a cache-verified image of ``release``, downloading if necessary.

    A cached image is re-verified against its signed chunklist every time, so a
    corrupted cache cannot reach a USB drive. The image is written to a ``.part``
    sibling and only renamed after every chunk matched.
    """
    directory = _cache_dir(release)
    image = directory / "BaseSystem.dmg"
    chunklist = directory / "BaseSystem.chunklist"
    directory.mkdir(parents=True, exist_ok=True)

    if use_cache and image.is_file() and chunklist.is_file():
        try:
            chunks = parse_chunklist(chunklist.read_bytes())
            if token is not None:
                token.check()
            digest = verify_image(image, chunks, token=token)
            record = cached_recovery(release)
            if record is not None and record.sha256 == digest:
                _sink().transfer(runtime.Transfer(
                    product="macOS recovery", done_bytes=image.stat().st_size,
                    total_bytes=image.stat().st_size, bytes_per_second=0.0))
                _log("info", "Re-used the verified {} image at {}.".format(
                    release.label, image))
                return RecoveryDownload(image=image, chunklist=chunklist,
                                        sha256=digest, size=image.stat().st_size,
                                        product=record.product,
                                        release=release.label)
        except EngineError:
            _log("warning", "The cached recovery image did not verify; downloading again.")

    _sink().section("Downloading macOS recovery")
    asset = fetch_recovery_asset(board_id=release.board_id, mlb=release.mlb,
                                 os_type=release.os_type)
    _log("info", "Apple recovery product {} for {}.".format(
        asset.product, release.label))

    staging_chunklist = _stream(
        asset.chunklist_url, asset.chunklist_token,
        chunklist, "recovery chunklist", None, token)
    chunks = parse_chunklist(staging_chunklist.read_bytes())
    total_size = sum(size for size, _digest in chunks)
    _log("info", "Recovery image is {:.1f} MiB in {} signed chunks.".format(
        total_size / MIB, len(chunks)))

    staging_image = _stream(
        asset.image_url, asset.image_token, image,
        "macOS recovery image", total_size, token)
    digest = verify_image(staging_image, chunks, token=token)
    os.replace(staging_chunklist, chunklist)
    os.replace(staging_image, image)

    record = {
        "release": release.label,
        "board_id": release.board_id,
        "product": asset.product,
        "sha256": digest,
        "size": total_size,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    manifest = _manifest_path(directory)
    temporary = manifest.with_name(manifest.name + ".part")
    temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(temporary, manifest)
    _log("info", "Recovery image verified and cached.")
    return RecoveryDownload(image=image, chunklist=chunklist, sha256=digest,
                            size=total_size, product=asset.product,
                            release=release.label)


# ---- USB discovery -------------------------------------------------------

_FAT_FILESYSTEMS = {"vfat", "msdos", "fat", "fat32", "msdos-fat32"}
_MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")


def _unescape_mount(field: str) -> str:
    """Undo the octal escapes ``/proc/self/mounts`` applies to paths."""
    return _MOUNT_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), field)


def _system_mounts() -> set[str]:
    if sys.platform == "win32":
        return {os.environ.get("SystemDrive", "C:") + "\\"}
    return {"/", "/boot", "/boot/efi", "/efi"}


def _linux_volumes() -> list[UsbVolume]:
    volumes = []
    seen = set()
    try:
        with open("/proc/self/mounts", encoding="utf-8") as handle:
            mounts = [line.split() for line in handle if line.strip()]
    except OSError:
        return volumes
    for entry in mounts:
        if len(entry) < 4:
            continue
        device, mountpoint, filesystem, options = entry[:4]
        mountpoint = _unescape_mount(mountpoint)
        device = _unescape_mount(device)
        if filesystem.lower() not in _FAT_FILESYSTEMS:
            continue
        if "ro" in options.split(","):
            continue
        if mountpoint in _system_mounts() or mountpoint.startswith("/boot/"):
            continue
        try:
            node = os.path.basename(os.path.realpath(device))
            sys_path = os.path.realpath("/sys/class/block/{}".format(node))
            if "usb" not in sys_path.split(os.sep):
                continue
            identity = "{}:{}".format(os.stat(device).st_rdev,
                                      os.path.realpath(device))
            if identity in seen:
                continue
            usage = shutil.disk_usage(mountpoint)
            if not os.access(mountpoint, os.W_OK):
                continue
            seen.add(identity)
            volumes.append(UsbVolume(
                label=os.path.basename(mountpoint.rstrip(os.sep)),
                mount=Path(mountpoint), device=device,
                filesystem=filesystem.upper(), size=usage.total,
                free=usage.free, identity=identity))
        except OSError:
            continue
    return volumes


def _walk_plist(node, key):
    if isinstance(node, dict):
        if key in node:
            yield node[key]
        for value in node.values():
            yield from _walk_plist(value, key)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_plist(value, key)


def _macos_volumes() -> list[UsbVolume]:
    volumes = []
    seen = set()
    try:
        listing = subprocess.run(
            ["diskutil", "list", "-plist"], capture_output=True, timeout=20,
            check=True)
        data = plistlib.loads(listing.stdout)
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
        return volumes
    for device in _walk_plist(data, "DeviceIdentifier"):
        if not isinstance(device, str) or not device.startswith("disk"):
            continue
        try:
            info = plistlib.loads(subprocess.run(
                ["diskutil", "info", "-plist", device],
                capture_output=True, timeout=20, check=True).stdout)
        except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
            continue
        mount = info.get("MountPoint")
        filesystem = str(info.get("FilesystemType", "")).lower()
        if not mount or filesystem not in _FAT_FILESYSTEMS:
            continue
        if info.get("Internal") or info.get("ReadOnlyVolume"):
            continue
        bus = str(info.get("BusProtocol", ""))
        if bus.upper() != "USB" and not info.get("RemovableMedia"):
            continue
        if mount in _system_mounts() or str(mount).startswith("/boot/"):
            continue
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        identity = "{}:{}".format(device, mount)
        if identity in seen:
            continue
        seen.add(identity)
        volumes.append(UsbVolume(
            label=str(info.get("VolumeName") or Path(mount).name),
            mount=Path(mount), device="/dev/" + device,
            filesystem=str(info.get("FilesystemName") or filesystem).upper(),
            size=usage.total, free=usage.free, identity=identity))
    return volumes


_WINDOWS_VOLUMES = r"""
$system = $env:SystemDrive
$volumes = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DriveType=2" |
  Where-Object { $_.FileSystem -eq 'FAT32' -and $_.DeviceID -ne $system } |
  Select-Object DeviceID, VolumeName, FileSystem, Size, FreeSpace
ConvertTo-Json -InputObject @($volumes) -Compress
"""


def _windows_volumes() -> list[UsbVolume]:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             _WINDOWS_VOLUMES],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        records = json.loads(result.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if isinstance(records, dict):
        records = [records]
    volumes = []
    for record in records:
        letter = str(record.get("DeviceID") or "")
        if len(letter) != 2 or not letter.endswith(":"):
            continue
        mount = letter + "\\"
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        volumes.append(UsbVolume(
            label=str(record.get("VolumeName") or letter),
            mount=Path(mount), device=mount,
            filesystem="FAT32", size=int(record.get("Size") or usage.total),
            free=int(record.get("FreeSpace") or usage.free),
            identity=letter.upper()))
    return volumes


def list_usb_volumes() -> list[UsbVolume]:
    """Mounted FAT32 volumes on a USB bus, read-only and best-effort."""
    try:
        if sys.platform == "win32":
            return _windows_volumes()
        if sys.platform == "darwin":
            return _macos_volumes()
        return _linux_volumes()
    except Exception as exc:
        _log("warning", "USB enumeration failed: {}".format(exc))
        return []


def _assert_target(volume: UsbVolume) -> None:
    """Re-check the volume's identity immediately before any write."""
    if not volume.mount.is_dir():
        raise UsbVolumeRefused(
            detail="{} is no longer mounted.".format(volume.mount))
    if str(volume.mount) in _system_mounts():
        raise UsbVolumeRefused(detail="The system volume cannot be an installer target.")
    current = {candidate.identity: candidate for candidate in list_usb_volumes()}
    match = current.get(volume.identity)
    if match is None:
        raise UsbVolumeRefused(
            detail="The selected drive is no longer present under the same "
                   "identity. Reconnect it and choose it again.")
    if not os.access(volume.mount, os.W_OK):
        raise UsbVolumeRefused(
            detail="{} is not writable.".format(volume.mount))


# ---- payload -------------------------------------------------------------

_EFI_REQUIRED = (
    ("BOOT", "BOOTx64.efi"),
    ("OC", "OpenCore.efi"),
    ("OC", "config.plist"),
)


def validate_efi_folder(folder: Path) -> Path:
    """Return the ``EFI`` directory, or raise with the missing piece named."""
    folder = Path(folder)
    efi = folder / "EFI" if (folder / "EFI").is_dir() else folder
    missing = [str(efi.joinpath(*parts)) for parts in _EFI_REQUIRED
               if not efi.joinpath(*parts).is_file()]
    if missing:
        raise InstallerCopyFailed(
            detail="That folder is not a complete OpenCore EFI: missing {}.".format(
                ", ".join(missing)))
    identity = efi / "OC" / "OpenCore.efi"
    if identity.stat().st_size < 64 * 1024:
        raise InstallerCopyFailed(
            detail="{} is too small to be OpenCore.efi.".format(identity))
    return efi


def _tree_size(root: Path) -> int:
    total = 0
    for directory, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                raise InstallerCopyFailed(
                    detail="The EFI folder contains a symbolic link: {}.".format(path))
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return total


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _copy_tree(source: Path, destination: Path, token=None) -> None:
    for directory, dirs, files in os.walk(source, followlinks=False):
        if token is not None:
            token.check()
        relative = Path(directory).relative_to(source)
        target_dir = destination / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in dirs:
            child = Path(directory) / name
            if child.is_symlink():
                raise InstallerCopyFailed(
                    detail="Refusing to copy the symbolic link {}.".format(child))
        for name in files:
            child = Path(directory) / name
            if child.is_symlink():
                raise InstallerCopyFailed(
                    detail="Refusing to copy the symbolic link {}.".format(child))
            if not _regular_file(child):
                raise InstallerCopyFailed(
                    detail="Refusing to copy the non-regular file {}.".format(child))
            shutil.copy2(child, target_dir / name)


def _copy_file_verified(source: Path, destination: Path, expected_sha256: str,
                        expected_size: int, token, progress) -> None:
    digest = hashlib.sha256()
    done = 0
    try:
        with open(source, "rb") as reader, open(destination, "wb") as writer:
            while True:
                if token is not None:
                    token.check()
                piece = reader.read(1024 * 1024)
                if not piece:
                    break
                writer.write(piece)
                digest.update(piece)
                done += len(piece)
                progress(done)
    except OSError as exc:
        raise InstallerCopyFailed(
            detail="Could not copy {}: {}".format(source.name, exc)) from exc
    if done != expected_size or digest.hexdigest() != expected_sha256:
        raise RecoveryImageCorrupt(
            detail="{} changed after it was verified; nothing was activated on "
                   "the drive.".format(source.name))


def write_installer(volume: UsbVolume, efi_folder: Path,
                    recovery: RecoveryDownload, token=None) -> dict:
    """Copy an EFI folder and the verified recovery to a mounted USB volume.

    Only ``EFI`` and ``com.apple.recovery.boot`` are replaced. Each new tree is
    staged under the volume first and swapped in only after every byte is written,
    so a failure or cancellation leaves the previous trees in place. The volume is
    re-identified first; nothing is formatted and no block device is opened.
    """
    _assert_target(volume)
    efi = validate_efi_folder(efi_folder)
    efi_size = _tree_size(efi)
    needed = efi_size + recovery.size + COPY_MARGIN
    usage = shutil.disk_usage(volume.mount)
    if usage.free < needed:
        raise InstallerCopyFailed(
            detail="{} has {:.0f} MiB free; the installer needs {:.0f} MiB.".format(
                volume.label or volume.mount, usage.free / MIB, needed / MIB))

    stage = volume.mount / ".blackdream-stage-{}".format(os.getpid())
    if stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    total = efi_size + recovery.size
    copied = {"done": 0}
    swapped = []

    def progress(done):
        copied["done"] = done
        _sink().transfer(runtime.Transfer(
            product="USB installer", done_bytes=min(done, total),
            total_bytes=total, bytes_per_second=0.0))

    try:
        _log("info", "Copying the EFI folder to {}.".format(volume.mount))
        _copy_tree(efi, stage / "EFI", token=token)
        copied["done"] = efi_size
        progress(efi_size)
        boot = stage / "com.apple.recovery.boot"
        boot.mkdir()
        _copy_file_verified(recovery.image, boot / "BaseSystem.dmg",
                            recovery.sha256, recovery.size, token, progress)
        shutil.copy2(recovery.chunklist, boot / "BaseSystem.chunklist")
        if token is not None:
            token.check()

        for name in ("EFI", "com.apple.recovery.boot"):
            target = volume.mount / name
            previous = volume.mount / (name + ".blackdream-old")
            if previous.exists():
                shutil.rmtree(previous)
            had_previous = target.exists()
            if had_previous:
                os.replace(target, previous)
            # Record before the second half of the swap so a failure there can
            # still put the previous tree back instead of leaving a bare drive.
            swapped.append((target, previous, had_previous))
            os.replace(stage / name, target)
        for _target, previous, _had in swapped:
            if previous.exists():
                shutil.rmtree(previous)
        try:
            marker = volume.mount / MARKER_NAME
            marker.write_text(json.dumps({
                "release": recovery.release,
                "product": recovery.product,
                "image_sha256": recovery.sha256,
                "image_bytes": recovery.size,
                "efi_bytes": efi_size,
                "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }, indent=2), encoding="utf-8")
        except OSError as exc:
            # The payload is already in place; a missing note is not worth
            # failing an otherwise complete installer.
            _log("warning", "Could not write the installer marker: {}".format(exc))
    except BaseException as exc:
        for target, previous, had_previous in reversed(swapped):
            try:
                if target.exists():
                    shutil.rmtree(target)
                if had_previous and previous.exists():
                    os.replace(previous, target)
            except OSError as restore_error:
                _log("warning", "Could not restore {}: {}".format(
                    target, restore_error))
        if isinstance(exc, OSError):
            raise InstallerCopyFailed(
                detail="The drive refused a write while the installer was being "
                       "put in place: {}".format(exc)) from exc
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    _log("info", "Installer written to {}.".format(volume.mount))
    return {"mount": str(volume.mount), "bytes": total,
            "sha256": recovery.sha256, "product": recovery.product}
