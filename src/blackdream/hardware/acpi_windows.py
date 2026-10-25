"""Reading the firmware ACPI tables on Windows, without elevation.

Unlike Linux, Windows does not expose the tables as files. It exposes the same
tables to user mode through two documented interfaces, and this module uses the
pair ACPICA's own Windows layer uses:

* ``EnumSystemFirmwareTables`` lists every ACPI signature the firmware advertises,
  and ``GetSystemFirmwareTable`` returns one table by signature. Neither needs a
  driver, a service or an administrator token.
* ``GetSystemFirmwareTable`` still answers for ``DSDT`` even though enumeration
  omits it, which is how ACPICA gets the DSDT on Windows.
* The kernel keeps every *instance* of ``SSDT`` under ``HKLM\\HARDWARE\\ACPI``
  (``SSDT``, ``SSD1`` ... ``SSDS``), because the by-signature call returns only
  the first table with a name and a machine usually has more than one SSDT.

The folder this writes is the same shape the Linux dumper produces: one ``.aml``
per table, named for its signature, with ``DSDT.aml`` present.
"""

from __future__ import annotations

import ctypes
import struct
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Callable

from ocengine.fatal import EngineError
from ocengine.utils import Utils

from blackdream.core.pipeline import Cancelled

from .acpi import ACPI_SUBDIR, Dumped, TablesDumpFailed, TablesUnsupported

try:  # not importable off Windows, and this module must stay importable for tests
    import winreg
except ImportError:  # pragma: no cover - the platform, not a path
    winreg = None

#: 'ACPI' read as the little-endian DWORD the Win32 API wants.
_ACPI_PROVIDER = int.from_bytes(b"ACPI", "little")

#: An ACPI description header is 36 bytes and carries its own length at offset 4.
_HEADER = 36

#: Matches the Linux dumper's cap: the largest table seen here was a 245 KB DSDT.
MAX_TABLE_BYTES = 8 << 20

#: Windows names the SSDT instances SSDT, SSD1 ... SSD9, SSDA ... SSDS.
_SSDT_KEYS = ("SSDT",) + tuple(
    "SSD{}".format(i if i < 10 else chr(ord("A") + i - 10)) for i in range(1, 29))


class WindowsFirmware:
    """The two Win32 calls, behind one object so the parser can be tested elsewhere."""

    def __init__(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._enum = kernel32.EnumSystemFirmwareTables
        self._enum.argtypes = (wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        self._enum.restype = wintypes.UINT
        self._get = kernel32.GetSystemFirmwareTable
        self._get.argtypes = (wintypes.DWORD, wintypes.DWORD,
                              ctypes.c_void_p, wintypes.DWORD)
        self._get.restype = wintypes.UINT

    def signatures(self) -> list[tuple[str, int]]:
        """Every advertised signature, as its ASCII name and the DWORD the API wants."""
        size = self._enum(_ACPI_PROVIDER, None, 0)
        if not size or size % 4:
            return []
        buffer = ctypes.create_string_buffer(size)
        written = self._enum(_ACPI_PROVIDER, buffer, size)
        if not written or written > size or written % 4:
            return []
        raw = buffer.raw[:written]
        found = []
        for offset in range(0, written, 4):
            chunk = raw[offset:offset + 4]
            found.append((chunk.decode("ascii", "replace"),
                          struct.unpack("<I", chunk)[0]))
        return found

    def table(self, signature: int) -> bytes | None:
        """The table for one signature, exactly as the firmware has it."""
        size = self._get(_ACPI_PROVIDER, signature, None, 0)
        if not size or size > MAX_TABLE_BYTES:
            return None
        buffer = ctypes.create_string_buffer(size)
        written = self._get(_ACPI_PROVIDER, signature, buffer, size)
        if not written or written > size:
            return None
        return buffer.raw[:written]

    def registry_table(self, key: str) -> bytes | None:
        """The REG_BINARY value Windows filed under ``HARDWARE\\ACPI\\<key>``."""
        if winreg is None:
            return None
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                  "HARDWARE\\ACPI\\" + key, 0, winreg.KEY_READ)
        except OSError:
            return None
        try:
            # The value sits below the OEM and table id keys; descend to the last.
            while True:
                count = winreg.QueryInfoKey(root)[0]
                if not count:
                    break
                child = winreg.OpenKey(root, winreg.EnumKey(root, 0))
                root.Close()
                root = child
            index = 0
            while True:
                try:
                    _name, value, kind = winreg.EnumValue(root, index)
                except OSError:
                    return None
                if kind == winreg.REG_BINARY:
                    return value
                index += 1
        finally:
            root.Close()


def supported() -> bool:
    return sys.platform == "win32"


def _signature_id(name: str) -> int:
    return int.from_bytes(name.encode("ascii", "replace"), "little")


def _valid(name: str, data) -> bytes | None:
    """One table if ``data`` is a sane table called ``name``, else None.

    The header checks are the same ones the engine applies to a dropped file: the
    signature is the table's first four bytes and the length field has to fit.
    """
    if not isinstance(data, (bytes, bytearray)):
        return None
    if len(data) < _HEADER or len(data) > MAX_TABLE_BYTES:
        return None
    if data[:4] != name.encode("ascii"):
        return None
    length = struct.unpack("<I", data[4:8])[0]
    if length < _HEADER or length > len(data):
        return None
    return bytes(data)


def _read_tables(firmware, sink) -> dict[str, bytes]:
    """Every table this machine exposes, keyed by the file stem to write."""
    tables: dict[str, bytes] = {}

    dsdts = _signature_id("DSDT")
    dsdt = _valid("DSDT", firmware.table(dsdts))
    if dsdt is None:
        dsdt = _valid("DSDT", firmware.registry_table("DSDT"))
    if dsdt is None:
        raise TablesDumpFailed(detail=(
            "Windows did not return a DSDT. Every other table is a supplement to it, "
            "so there is nothing for the build to patch."))
    tables["DSDT"] = dsdt

    # SSDTs come from the registry because the by-signature call returns only the
    # first one, and a machine with several loses all but one without it.
    ssdt_index = 0
    for key in _SSDT_KEYS:
        blob = _valid("SSDT", firmware.registry_table(key))
        if blob is None:
            continue
        stem = "SSDT" if ssdt_index == 0 else "SSDT{}".format(ssdt_index)
        tables[stem] = blob
        ssdt_index += 1
    if not ssdt_index:
        first = _valid("SSDT", firmware.table(_signature_id("SSDT")))
        if first is not None:
            tables["SSDT"] = first

    seen: set[str] = set()
    for name, signature in firmware.signatures():
        if name in ("DSDT", "SSDT") or name in seen:
            continue
        seen.add(name)
        if not (len(name) == 4 and name.isascii() and name.isalnum()
                and name[0].isalpha() and name.isupper()):
            sink.log("warning", "Skipped a firmware table named {!r}.".format(name))
            continue
        blob = _valid(name, firmware.table(signature))
        if blob is not None:
            tables[name] = blob

    if len(tables) < 2:
        sink.log("warning", "Windows exposed only the DSDT; the build can proceed but "
                            "patches that need a supplementary table will not see one.")
    return tables


class WindowsAcpiDumper:
    """Read the tables in-process and write them where the build expects them.

    ``firmware`` is injectable so the parsing and file rules can be tested on a
    machine that is not Windows.
    """

    def __init__(self, utils: Utils | None = None, firmware=None) -> None:
        self.utils = utils or Utils()
        self._firmware = firmware

    def dump(self, out_dir: str | Path,
             is_cancelled: Callable[[], bool] | None = None) -> Dumped:
        if not supported():
            raise TablesUnsupported()
        if is_cancelled is not None and is_cancelled():
            raise Cancelled()
        firmware = self._firmware or WindowsFirmware()
        sink = self.utils.sink
        sink.section("Reading ACPI tables")
        try:
            tables = _read_tables(firmware, sink)
        except TablesDumpFailed as failure:
            self.utils.log_message(failure.detail or "no tables", level="error")
            raise
        if is_cancelled is not None and is_cancelled():
            raise Cancelled()

        destination = Path(self.utils.normalize_path(str(out_dir))) / ACPI_SUBDIR
        destination.mkdir(parents=True, exist_ok=True)
        # A previous dump in this folder must not survive beside a new one: two
        # DSDTs make the engine refuse the folder outright. Only the app's own
        # <NAME>.aml files are removed, and only now that the new DSDT is in hand.
        for entry in destination.iterdir():
            if entry.is_file() and entry.suffix == ".aml" and _looks_like_table(entry.stem):
                entry.unlink(missing_ok=True)
        for stem in sorted(tables, key=lambda name: (name != "DSDT", name)):
            (destination / "{}.aml".format(stem)).write_bytes(tables[stem])

        sink.log("info", "{} ACPI tables read from Windows".format(len(tables)))
        sink.log("info", "ACPI tables written to {}".format(destination))
        return Dumped(acpi_dir=destination, tables=tuple(tables))


def _looks_like_table(stem: str) -> bool:
    """The same name grammar the Linux dumper and the engine's picker use."""
    return (4 <= len(stem) <= 16 and stem[0].isalpha() and stem[0].isupper()
            and all(character.isalnum() for character in stem)
            and stem.isascii())


__all__ = [
    "MAX_TABLE_BYTES",
    "WindowsAcpiDumper",
    "WindowsFirmware",
    "supported",
]
