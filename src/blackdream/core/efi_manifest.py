"""A record of what a build wrote, so a folder can be compared with itself later.

The manifest answers one question: *is this the same folder BlackDream produced?*
It cannot answer whether the folder boots, or whether its settings suit a machine.
The report text and the window both say so; the verifier is careful to report only
absence, difference and addition.

It is local and read-only apart from the one file it writes beside the tree. It
never writes into ``EFI/`` and never touches the config.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

FORMAT = 1
MANIFEST_NAME = ".blackdream-manifest.json"
#: Files the operating system drops into folders; they say nothing about the build.
NOISE = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})


class ManifestError(Exception):
    """The manifest is absent or cannot be understood."""


@dataclass(frozen=True)
class Difference:
    kind: str  # "missing" | "changed" | "added"
    path: str
    recorded: str | None = None
    found: str | None = None


@dataclass(frozen=True)
class Verification:
    root: Path
    unchanged: int
    differences: tuple[Difference, ...]
    recorded_at: str | None

    @property
    def missing(self) -> tuple[Difference, ...]:
        return tuple(item for item in self.differences if item.kind == "missing")

    @property
    def changed(self) -> tuple[Difference, ...]:
        return tuple(item for item in self.differences if item.kind == "changed")

    @property
    def added(self) -> tuple[Difference, ...]:
        return tuple(item for item in self.differences if item.kind == "added")

    @property
    def intact(self) -> bool:
        return not self.differences

    @property
    def summary(self) -> str:
        if self.intact:
            return "Every file matches the recorded manifest."
        return "{} missing, {} changed, {} added".format(
            len(self.missing), len(self.changed), len(self.added))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _files(root: Path) -> list[Path]:
    found = []
    for path in sorted(root.rglob("*")):
        name = path.name
        if not path.is_file() or name in NOISE:
            continue
        if path == root / MANIFEST_NAME:
            continue
        found.append(path)
    return found


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def build_document(root, *, build=None, validation=None, now=None) -> dict:
    """The manifest for the tree as it is now. Paths are relative and sorted."""
    folder = Path(root)
    if not folder.is_dir():
        raise ManifestError("{} is not a folder.".format(folder))
    files = []
    for path in _files(folder):
        files.append({
            "path": _relative(folder, path),
            "size": path.stat().st_size,
            "sha256": _digest(path),
        })
    return {
        "tool": "BlackDream",
        "format": FORMAT,
        "created": now or _now(),
        "build": build if isinstance(build, dict) else {},
        "validation": validation if isinstance(validation, dict) else {},
        "files": files,
    }


def write(root, *, build=None, validation=None, now=None) -> Path:
    """Write the manifest beside the tree; returns its path."""
    folder = Path(root)
    document = build_document(folder, build=build, validation=validation, now=now)
    target = folder / MANIFEST_NAME
    target.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n",
                      encoding="utf-8")
    return target


def read(root) -> dict:
    folder = Path(root)
    target = folder / MANIFEST_NAME
    if not target.is_file():
        raise ManifestError("There is no {} in {}.".format(MANIFEST_NAME, folder))
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError("{} cannot be read: {}".format(target.name, exc)) from exc
    if not isinstance(document, dict):
        raise ManifestError("{} is not a manifest object.".format(target.name))
    if document.get("format") != FORMAT:
        raise ManifestError("{} has format {}, not {}.".format(
            target.name, document.get("format"), FORMAT))
    if not isinstance(document.get("files"), list):
        raise ManifestError("{} has no file list.".format(target.name))
    for entry in document["files"]:
        if not (isinstance(entry, dict) and isinstance(entry.get("path"), str)
                and isinstance(entry.get("sha256"), str)):
            raise ManifestError("{} contains an entry without a path and hash.".format(
                target.name))
    return document


def verify(root) -> Verification:
    """Compare the tree with its manifest. Reads only; writes nothing."""
    folder = Path(root)
    document = read(folder)
    recorded = {entry["path"]: entry for entry in document["files"]}
    present = {_relative(folder, path): path for path in _files(folder)}

    differences = []
    unchanged = 0
    for name, entry in recorded.items():
        path = present.get(name)
        if path is None:
            differences.append(Difference("missing", name, entry.get("sha256")))
            continue
        actual = _digest(path)
        if actual != entry["sha256"]:
            differences.append(Difference("changed", name, entry.get("sha256"), actual))
        else:
            unchanged += 1
    for name in present:
        if name not in recorded:
            differences.append(Difference("added", name))

    kind_order = {"missing": 0, "changed": 1, "added": 2}
    differences.sort(key=lambda item: (kind_order[item.kind], item.path.casefold()))
    return Verification(root=folder, unchanged=unchanged,
                        differences=tuple(differences),
                        recorded_at=document.get("created"))


def to_text(result: Verification) -> str:
    """The export; it repeats what a match does and does not prove."""
    lines = [
        "BlackDream EFI manifest check",
        "Folder: {}".format(result.root),
        "Manifest recorded: {}".format(result.recorded_at or "unknown"),
        "Result: {}".format(result.summary),
        "Files unchanged: {}".format(result.unchanged),
        "",
        "A match proves these files are the ones recorded, nothing more. It does "
        "not prove the folder boots, and it does not judge whether the settings "
        "suit this machine.",
        "",
    ]
    if not result.differences:
        lines.append("No differences.")
    for item in result.differences:
        if item.kind == "missing":
            lines.append("[MISSING] {}".format(item.path))
        elif item.kind == "changed":
            lines.append("[CHANGED] {}".format(item.path))
            lines.append("  recorded {}".format((item.recorded or "")[:16]))
            lines.append("  found    {}".format((item.found or "")[:16]))
        else:
            lines.append("[ADDED] {}".format(item.path))
    return "\n".join(lines).rstrip() + "\n"
