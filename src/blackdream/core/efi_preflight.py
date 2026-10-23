"""A read-only review of a generated EFI folder, before anyone tries to boot it.

The build step proves that files were written where the engine put them; it cannot
prove that the ``config.plist`` beside them still points at those files. A user who
renames a kext folder, or opens a config from another machine, gets a folder that
looks complete and fails at boot. This module answers the question the folder itself
can answer: do the references in ``config.plist`` resolve to files that are here?

Two boundaries are deliberate.

* Nothing is written, created, renamed or opened for writing. The tests snapshot the
  tree's bytes and modification times to keep that true.
* A clean report says what it checked, not what will happen. The summary is
  ``No issues detected by these checks.`` -- never "this EFI will boot".

ocvalidate is a different voice and stays separate: the window shows its output as
the validator's, not as one of these advisories.
"""

from __future__ import annotations

import os
import plistlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .efi_manifest import MANIFEST_NAME

ERROR = "error"
WARNING = "warning"
INFO = "info"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

IGNORED_NAMES = frozenset({MANIFEST_NAME, ".DS_Store", "Thumbs.db", "desktop.ini"})

REQUIRED = (
    ("EFI/BOOT/BOOTx64.efi", "The firmware loads this file first."),
    ("EFI/OC/OpenCore.efi", "This is the OpenCore bootloader itself."),
    ("EFI/OC/config.plist", "OpenCore reads its settings from this file."),
)


@dataclass(frozen=True)
class Finding:
    """One thing the folder itself shows, with the evidence it was read from."""

    severity: str
    code: str
    where: str
    message: str
    evidence: str
    action: str


@dataclass(frozen=True)
class Report:
    root: Path
    findings: tuple[Finding, ...]
    files: int

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.severity == ERROR)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.severity == WARNING)

    @property
    def clean(self) -> bool:
        return not self.errors and not self.warnings

    @property
    def summary(self) -> str:
        if self.clean:
            return "No issues detected by these checks."
        counts = []
        if self.errors:
            counts.append("{} error{}".format(
                len(self.errors), "" if len(self.errors) == 1 else "s"))
        if self.warnings:
            counts.append("{} warning{}".format(
                len(self.warnings), "" if len(self.warnings) == 1 else "s"))
        text = ", ".join(counts)
        return text[:1].upper() + text[1:]


class PreflightError(Exception):
    """The folder cannot be analysed at all; the message says why."""


def _finding(severity: str, code: str, where: str, message: str,
             evidence: str, action: str) -> Finding:
    return Finding(severity=severity, code=code, where=where, message=message,
                   evidence=evidence, action=action)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _safe_reference(value) -> str | None:
    """A config reference is a path inside the folder, written with forward slashes."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts or re.match(r"^[A-Za-z]:", text):
        return None
    return str(pure)


def _entries(document: dict, section: str, key: str = "Add") -> list:
    """The list at ``section/key``, tolerating a section that is absent or wrong-typed."""
    block = document.get(section)
    if not isinstance(block, dict):
        return []
    value = block.get(key)
    return value if isinstance(value, list) else []


#: ``(label, section, list key, reference key, folder)`` for each referenced list.
#: Kexts point at a bundle folder through ``BundlePath``; everything else uses ``Path``.
SECTIONS = (
    ("ACPI table", "ACPI", "Add", "Path", "EFI/OC/ACPI"),
    ("kext", "Kernel", "Add", "BundlePath", "EFI/OC/Kexts"),
    ("driver", "UEFI", "Drivers", "Path", "EFI/OC/Drivers"),
    ("tool", "Misc", "Tools", "Path", "EFI/OC/Tools"),
)


def _raw_reference(entry, key: str = "Path"):
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get(key)
    return None


def _entry_path(entry, key: str = "Path") -> str | None:
    return _safe_reference(_raw_reference(entry, key))


def _entry_enabled(entry) -> bool:
    if isinstance(entry, dict):
        enabled = entry.get("Enabled", True)
        return bool(enabled)
    return True


def _duplicates(values):
    """Values that appear more than once, case-insensitively, in first-seen order."""
    seen = {}
    duplicated = []
    for value in values:
        folded = value.casefold()
        if folded in seen:
            if seen[folded] is not None:
                duplicated.append(value)
                seen[folded] = None
        else:
            seen[folded] = value
    return duplicated


def _reference_findings(document: dict, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for label, section, list_key, ref_key, base in SECTIONS:
        entries = _entries(document, section, list_key)
        where_key = "{}/{}".format(section, list_key)
        for position, entry in enumerate(entries):
            raw = _raw_reference(entry, ref_key)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            where = "{}/{}/{}".format(where_key, position, ref_key)
            enabled = _entry_enabled(entry)
            reference = _safe_reference(raw)
            if reference is None:
                findings.append(_finding(
                    ERROR, "path.unsafe", where,
                    "This reference is absolute or climbs out of the EFI folder.",
                    str(raw),
                    "Use a path relative to {}.".format(base)))
                continue
            target = root / base / reference
            if not target.exists():
                severity = ERROR if enabled else WARNING
                findings.append(_finding(
                    severity, "file.missing", where,
                    "{} is referenced but is not in the folder.".format(reference),
                    "{} does not exist".format(_relative(root, target)),
                    "Put {} back in {}, or remove the entry.".format(
                        reference, base)))
            elif label == "kext" and not target.is_dir():
                findings.append(_finding(
                    ERROR, "kext.not_a_folder", where,
                    "{} is not a kext folder.".format(reference),
                    "{} is a file".format(_relative(root, target)),
                    "Point BundlePath at the .kext directory."))

        references = [path for path in
                      (_entry_path(entry, ref_key) for entry in entries) if path]
        for repeated in _duplicates(references):
            findings.append(_finding(
                WARNING, "entry.duplicate", where_key,
                "{} is referenced more than once.".format(repeated),
                "duplicate entry: {}".format(repeated),
                "Remove the repeated entry; the second one adds nothing."))

    driver_entries = _entries(document, "UEFI", "Drivers")
    listed = [path for path in
              (_entry_path(entry, "Path") for entry in driver_entries) if path]
    present = [name for name in listed if (root / "EFI/OC/Drivers" / name).is_file()]
    if listed and not present:
        findings.append(_finding(
            WARNING, "driver.openruntime", "UEFI/Drivers",
            "No UEFI driver in this folder is present, and OpenCore needs "
            "OpenRuntime.efi on modern firmware.",
            "no driver resolved under EFI/OC/Drivers",
            "Build the folder again so the engine includes OpenRuntime.efi."))
    elif present and not any(name.casefold() == "openruntime.efi" for name in listed):
        findings.append(_finding(
            WARNING, "driver.openruntime", "UEFI/Drivers",
            "OpenRuntime.efi is not listed in UEFI/Drivers.",
            "UEFI/Drivers lists {}".format(", ".join(listed)),
            "Add OpenRuntime.efi to UEFI/Drivers; OpenCore needs it for macOS."))
    return findings


def _unreferenced_findings(document: dict, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    referenced = set()
    for _label, section, list_key, ref_key, _base in SECTIONS:
        for entry in _entries(document, section, list_key):
            path = _entry_path(entry, ref_key)
            if path:
                referenced.add(path.casefold())
    for _label, _section, _list_key, _ref_key, base in SECTIONS:
        folder = root / base
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            name = path.name
            if name in IGNORED_NAMES:
                continue
            relative = "{}/{}".format(base, name)
            if name.casefold() in referenced or relative.casefold() in referenced:
                continue
            if base == "EFI/OC/Kexts" and not path.is_dir():
                continue
            findings.append(_finding(
                INFO, "file.unreferenced", relative,
                "This file is in the folder but config.plist does not reference it.",
                "not listed in config.plist",
                "Leave it if you keep spares here; OpenCore ignores unreferenced "
                "files."))
    return findings


def analyse(root) -> Report:
    """Read ``root`` and return findings. Raises :class:`PreflightError` if it
    cannot be read at all; raises nothing else for ordinary content problems."""
    folder = Path(root)
    if not folder.is_dir():
        raise PreflightError("{} is not a folder.".format(folder))
    if os.path.ismount(folder):
        raise PreflightError(
            "{} is a mount point. Preflight reads a folder that was built, and never "
            "mounts or reads a volume.".format(folder))

    findings: list[Finding] = []
    for name, why in REQUIRED:
        if not (folder / name).is_file():
            findings.append(_finding(
                ERROR, "file.missing", name,
                "{} is missing from this folder.".format(name),
                "{} not found".format(name),
                "Build the EFI folder again, or put the file back. {}".format(why)))

    document = None
    config = folder / "EFI/OC/config.plist"
    if config.is_file():
        try:
            document = plistlib.loads(config.read_bytes())
        except Exception as exc:  # plistlib raises ExpatError, ValueError, OSError...
            findings.append(_finding(
                ERROR, "config.unreadable", "EFI/OC/config.plist",
                "config.plist could not be read as a property list.",
                str(exc),
                "Build the folder again, or repair the plist before booting."))
        else:
            if not isinstance(document, dict):
                findings.append(_finding(
                    ERROR, "config.root", "EFI/OC/config.plist",
                    "The property list root is not a dictionary.",
                    type(document).__name__,
                    "Replace it with a config.plist OpenCore can read."))
                document = None

    if document is not None:
        findings.extend(_reference_findings(document, folder))
        findings.extend(_unreferenced_findings(document, folder))

    files = sum(1 for path in folder.rglob("*") if path.is_file()) if folder.is_dir() else 0
    ordered = tuple(sorted(findings, key=lambda item: (
        _SEVERITY_ORDER.get(item.severity, 9), item.where.casefold(), item.code)))
    return Report(root=folder, findings=ordered, files=files)


def to_text(report: Report) -> str:
    """The export a tester can attach; it repeats the boundary the window states."""
    lines = [
        "BlackDream EFI preflight",
        "Folder: {}".format(report.root),
        "Files read: {}".format(report.files),
        "Result: {}".format(report.summary),
        "",
        "These checks read the folder. They do not test firmware, hardware or "
        "whether macOS boots.",
        "",
    ]
    if not report.findings:
        lines.append("No findings.")
    for finding in report.findings:
        lines.extend((
            "[{}] {}".format(finding.severity.upper(), finding.where),
            "  {}".format(finding.message),
            "  Evidence: {}".format(finding.evidence),
            "  Next: {}".format(finding.action),
        ))
    return "\n".join(lines).rstrip() + "\n"
