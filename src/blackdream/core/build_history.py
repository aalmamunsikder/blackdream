"""A local, append-only record of what BlackDream built and what came of it.

The history answers questions a folder cannot: which release was tried, when, and
whether the run succeeded or stopped early. It is one JSON object per line, newest
last on disk, so the newest record can be appended without parsing the rest. The
file is rewritten atomically when the oldest records must be dropped.

A build folder can be deleted or moved after the fact, so every state read here is
defensive: the history says what was recorded, never that a folder still exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from blackdream.core import state_store
from ocengine import paths

#: Records kept before the oldest is dropped.
MAX_ENTRIES = 100
STATUSES = ("succeeded", "failed", "cancelled")


@dataclass(frozen=True)
class Entry:
    at: str
    status: str
    release: str = ""
    output: str = ""
    manifest: str = ""
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "at": self.at,
            "status": self.status,
            "release": self.release,
            "output": self.output,
            "manifest": self.manifest,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data) -> "Entry | None":
        """Build an entry from stored data, or None when it is malformed."""
        if not isinstance(data, dict):
            return None
        at = data.get("at")
        status = data.get("status")
        if not isinstance(at, str) or not at.strip():
            return None
        if not isinstance(status, str) or status not in STATUSES:
            return None
        optional = {}
        for field in ("release", "output", "manifest", "detail"):
            value = data.get(field, "")
            if not isinstance(value, str):
                return None
            optional[field] = value
        return cls(at=at, status=status, **optional)


def default_path() -> Path:
    return paths.current().state_dir / "build-history.jsonl"


def read(path=None) -> list[Entry]:
    """The stored entries, newest first; malformed lines are skipped."""
    target = Path(path) if path is not None else default_path()
    text = state_store.read_text(target)
    if text is None:
        return []
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        entry = Entry.from_dict(record)
        if entry is not None:
            entries.append(entry)
    entries.reverse()
    return entries


def append(entry: Entry, path=None) -> None:
    """Append one entry and keep only the newest ``MAX_ENTRIES``."""
    target = Path(path) if path is not None else default_path()
    kept = [entry] + read(target)
    kept = kept[:MAX_ENTRIES]
    lines = [json.dumps(item.to_dict()) for item in reversed(kept)]
    state_store.atomic_write_text(
        target, "\n".join(lines) + ("\n" if lines else ""))


def folder_state(entry: Entry) -> str:
    """Whether the recorded build folder is still a folder; never raises."""
    if not entry.output:
        return "missing"
    try:
        return "ok" if Path(entry.output).is_dir() else "missing"
    except (OSError, ValueError, TypeError):
        return "missing"


def manifest_state(entry: Entry) -> str:
    """Whether the recorded manifest still sits in or beside the folder.

    The manifest is written inside the build root, but a recorded output may be
    the EFI folder itself; checking both keeps a valid record from reading as
    lost.
    """
    if not entry.manifest:
        return "unrecorded"
    if not entry.output:
        return "missing"
    try:
        folder = Path(entry.output)
        for candidate in (folder / entry.manifest,
                          folder.parent / entry.manifest):
            if candidate.is_file():
                return "recorded"
        return "missing"
    except (OSError, ValueError, TypeError):
        return "missing"


def _cell(value) -> str:
    """One tab-separated field, with embedded line breaks flattened."""
    text = "" if value is None else str(value)
    return (text.replace("\r\n", " ").replace("\r", " ")
            .replace("\n", " ").replace("\t", " "))


def to_text(entries) -> str:
    """A portable copy: one tab-separated line per build, newest first."""
    lines = ["BlackDream build history"]
    for entry in entries:
        lines.append("\t".join((
            _cell(entry.at),
            _cell(entry.status),
            _cell(entry.release),
            _cell(entry.output),
            folder_state(entry),
            manifest_state(entry),
        )))
    return "\n".join(lines) + "\n"
