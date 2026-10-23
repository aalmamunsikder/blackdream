"""A diagnostic bundle a beta tester can read, edit, and send deliberately.

There is no uploader here and no background collection. A bundle is assembled from
what the caller hands it, shown to the user first, and written only to a path the
user chose.

Privacy is a property of the assembly, not of a promise in the UI:

* Serial, MLB, UUID and ROM values from a config are treated as secrets and replaced
  wherever they appear, including inside log text.
* The user's home directory is shortened to ``~`` so paths do not name them.
* ``Report.json`` is never added unless the caller explicitly adds it, and it is
  marked as containing hardware details when it is.
* Every entry is optional unless it is the small environment block, so the user can
  leave out anything they do not want to share.

The archive is a plain zip or a single text file. Nothing leaves the machine unless
the user attaches it to a message themselves.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

#: Config keys whose values identify one machine and must never be shipped.
SECRET_KEYS = (
    "SystemSerialNumber", "MLB", "SystemUUID", "ROM", "Serial", "BoardSerialNumber",
)

_READ_ME = """BlackDream diagnostic bundle

This file was assembled on the machine it describes, at the user's request, and
written to a folder the user chose. Nothing was uploaded.

What a bundle can show: the app version, the platform, relevant log text, and the
validation result. What it cannot show: whether the EFI folder boots, or whether
the chosen settings suit the hardware.
"""


@dataclass
class Entry:
    name: str
    body: str
    optional: bool = True
    included: bool = True
    note: str = ""

    @property
    def size(self) -> int:
        return len(self.body.encode("utf-8", errors="replace"))


@dataclass
class Bundle:
    """Entries to show for review before any file is written."""

    home: Path | None = None
    secrets: tuple[str, ...] = ()
    entries: list[Entry] = field(default_factory=list)

    def add(self, name: str, body: str, *, optional: bool = True,
            included: bool = True, note: str = "") -> Entry:
        entry = Entry(name=name, body=body, optional=optional,
                      included=included, note=note)
        self.entries.append(entry)
        return entry

    def remove(self, name: str) -> None:
        self.entries = [entry for entry in self.entries if entry.name != name]

    def set_included(self, name: str, included: bool) -> None:
        for entry in self.entries:
            if entry.name == name:
                entry.included = included

    def included(self) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.included)

    def scrub(self, text: str) -> str:
        """Remove the home path and every known identity value from ``text``."""
        if self.home is not None:
            home = str(self.home)
            for variant in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
                if variant:
                    text = text.replace(variant, "~")
        for secret in self.secrets:
            if secret:
                text = text.replace(secret, "<redacted>")
        return text

    def preview(self) -> str:
        """What the user sees before writing: names, sizes, and why each is here."""
        lines = [
            "Diagnostic bundle",
            "Nothing has been written or sent yet.",
            "",
        ]
        if not self.entries:
            lines.append("No entries are selected.")
            return "\n".join(lines) + "\n"
        for entry in self.entries:
            marker = "include" if entry.included else "off"
            lines.append("[{}] {} ({} bytes)".format(marker, entry.name, entry.size))
            if entry.note:
                lines.append("    {}".format(entry.note))
        lines.append("")
        lines.append("Serial, MLB, UUID and ROM values are replaced with "
                     "<redacted>. Your home folder is shortened to ~.")
        return "\n".join(lines) + "\n"

    def render(self) -> str:
        parts = [_READ_ME, ""]
        for entry in self.included():
            parts.append("===== {} =====".format(entry.name))
            parts.append(self.scrub(entry.body))
            parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    def write_text(self, path) -> Path:
        target = Path(path)
        target.write_text(self.render(), encoding="utf-8")
        return target

    def write_zip(self, path) -> Path:
        target = Path(path)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("README.txt", _READ_ME)
            for entry in self.included():
                safe = re.sub(r"[^A-Za-z0-9._-]+", "-", entry.name)
                safe = safe.lstrip(".-") or "entry.txt"
                archive.writestr(safe, self.scrub(entry.body))
        target.write_bytes(buffer.getvalue())
        return target


def secrets_from_config(document) -> tuple[str, ...]:
    """Identity values in a parsed config.plist, in both byte spellings."""
    found = []
    platform = document.get("PlatformInfo") if isinstance(document, dict) else None
    generic = platform.get("Generic") if isinstance(platform, dict) else None
    if isinstance(generic, dict):
        for key in SECRET_KEYS:
            value = generic.get(key)
            if isinstance(value, bytes):
                if value:
                    found.append(value.hex())
                    found.append(value.hex().upper())
            elif isinstance(value, str) and value:
                found.append(value)
    return tuple(dict.fromkeys(found))


def environment(version: str, platform_text: str, *, theme: str,
                frozen: bool, architecture: str) -> str:
    """The small block that is always included; it names software, not the user."""
    return "\n".join((
        "BlackDream {}".format(version),
        "Platform: {}".format(platform_text),
        "Architecture: {}".format(architecture),
        "Theme: {}".format(theme),
        "Running from: {}".format("bundled app" if frozen else "source"),
    )) + "\n"


def tail(text: str, limit: int = 32 * 1024) -> str:
    """The end of a log, where the failure is; never the whole of a huge file."""
    if len(text) <= limit:
        return text
    return "[... {} earlier characters omitted ...]\n".format(
        len(text) - limit) + text[-limit:]


def log_text(path, limit: int = 32 * 1024) -> str:
    """Read a log as text, tolerating bytes a crash handler may have left."""
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        return "Could not read {}: {}".format(path, exc)
    return tail(payload.decode("utf-8", errors="replace"), limit)


def report_summary(path) -> str:
    """Describe a Report.json rather than reproducing it."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return "Report.json could not be read: {}".format(exc)
    if not isinstance(document, dict):
        return "Report.json is not an object."
    names = sorted(document)
    return "Report.json with {} top-level key(s): {}".format(
        len(names), ", ".join(names)) + "\n"
