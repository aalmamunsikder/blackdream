"""What changed in a config.plist, and how to walk back through the changes.

Two jobs, both about making an edit reviewable before it reaches the disk.

``diff`` compares two parsed documents and names every added, removed and changed
value with its path. Types are compared by identity of kind, not by Python's
``==``: ``True`` is not ``1`` and ``1`` is not ``1.0`` when a plist is the thing
being compared. Arrays are aligned with a sequence matcher so removing the first
kext reads as one removal, not as a change to every later index.

``History`` keeps snapshots so Undo and Redo can restore the exact document,
including unknown keys, key order and binary data. It never writes anything; the
caller decides when to save.
"""

from __future__ import annotations

import copy
import datetime
import difflib
from dataclasses import dataclass

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"

MAX_HISTORY = 100


@dataclass(frozen=True)
class Change:
    kind: str
    path: tuple
    before: object = None
    after: object = None

    @property
    def label(self) -> str:
        return path_label(self.path)

    @property
    def pair(self) -> tuple[str, str]:
        return (format_value(self.before), format_value(self.after))


def path_label(path) -> str:
    if not path:
        return "config.plist"
    parts = []
    for part in path:
        parts.append("[{}]".format(part) if isinstance(part, int) else str(part))
    return " > ".join(parts)


def format_value(value, limit: int = 80) -> str:
    if value is _ABSENT:
        return "nothing"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, bytes):
        text = "<{} byte{}>".format(
            len(value), "" if len(value) == 1 else "s")
    elif isinstance(value, datetime.datetime):
        text = value.isoformat()
    elif isinstance(value, dict):
        text = "{} key{}".format(
            len(value), "" if len(value) == 1 else "s")
    elif isinstance(value, list):
        text = "{} item{}".format(
            len(value), "" if len(value) == 1 else "s")
    else:
        text = value if isinstance(value, str) else str(value)
        if not text:
            text = '""'
    text = text.replace("\n", " ")
    if len(text) > limit:
        text = text[:limit - 1] + "\u2026"
    return text


class _Absent:
    def __repr__(self) -> str:
        return "<absent>"


_ABSENT = _Absent()


def _key(value):
    """A hashable, type-faithful rendering used only for alignment."""
    if isinstance(value, dict):
        return ("dict", tuple((key, _key(child)) for key, child in value.items()))
    if isinstance(value, list):
        return ("list", tuple(_key(child) for child in value))
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("integer", value)
    if isinstance(value, float):
        return ("real", value)
    if isinstance(value, bytes):
        return ("data", value)
    if isinstance(value, datetime.datetime):
        return ("date", value.isoformat())
    if isinstance(value, str):
        return ("string", value)
    return (type(value).__name__, repr(value))


def _same(before, after) -> bool:
    return _key(before) == _key(after)


def diff(before, after) -> list[Change]:
    """Every added, removed or changed value, in document order."""
    changes: list[Change] = []
    _diff(before, after, (), changes)
    return changes


def _diff(before, after, path: tuple, changes: list) -> None:
    if _same(before, after):
        return
    if isinstance(before, dict) and isinstance(after, dict):
        for key, value in after.items():
            if key in before:
                _diff(before[key], value, path + (key,), changes)
            else:
                changes.append(Change(ADDED, path + (key,), _ABSENT, value))
        for key, value in before.items():
            if key not in after:
                changes.append(Change(REMOVED, path + (key,), value, _ABSENT))
        return
    if isinstance(before, list) and isinstance(after, list):
        _diff_sequence(before, after, path, changes)
        return
    changes.append(Change(CHANGED, path, before, after))


def _diff_sequence(before: list, after: list, path: tuple, changes: list) -> None:
    matcher = difflib.SequenceMatcher(
        None, [_key(item) for item in before], [_key(item) for item in after],
        autojunk=False)
    for tag, left, left_end, right, right_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            if (left_end - left) == (right_end - right):
                for offset in range(right_end - right):
                    _diff(before[left + offset], after[right + offset],
                          path + (right + offset,), changes)
            else:
                for index in range(left, left_end):
                    changes.append(Change(REMOVED, path + (index,), before[index],
                                          _ABSENT))
                for index in range(right, right_end):
                    changes.append(Change(ADDED, path + (index,), _ABSENT,
                                          after[index]))
        elif tag == "delete":
            for index in range(left, left_end):
                changes.append(Change(REMOVED, path + (index,), before[index],
                                      _ABSENT))
        elif tag == "insert":
            for index in range(right, right_end):
                changes.append(Change(ADDED, path + (index,), _ABSENT, after[index]))


@dataclass
class _Snapshot:
    data: dict
    label: str


class History:
    """Undo and redo for one open document, held as snapshots.

    ``record`` is called after a change has been applied. ``undo`` and ``redo``
    return a copy of the document at that point; the caller replaces its own
    document and rebuilds whatever it shows. Nothing here touches the file.
    """

    def __init__(self, data: dict, limit: int = MAX_HISTORY):
        self._limit = max(1, limit)
        self._snapshots = [_Snapshot(copy.deepcopy(data), "Open")]
        self._index = 0

    def _current(self) -> _Snapshot:
        return self._snapshots[self._index]

    def record(self, data: dict, label: str = "Edit") -> bool:
        """Keep ``data`` as the next state. Returns False for a no-op."""
        if _same(self._current().data, data):
            return False
        del self._snapshots[self._index + 1:]
        self._snapshots.append(_Snapshot(copy.deepcopy(data), label or "Edit"))
        self._index += 1
        overflow = len(self._snapshots) - self._limit
        if overflow > 0:
            del self._snapshots[:overflow]
            self._index -= overflow
        return True

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._snapshots) - 1

    @property
    def undo_label(self) -> str:
        return self._current().label if self.can_undo else ""

    @property
    def redo_label(self) -> str:
        return (self._snapshots[self._index + 1].label
                if self.can_redo else "")

    def undo(self) -> dict | None:
        if not self.can_undo:
            return None
        self._index -= 1
        return copy.deepcopy(self._current().data)

    def redo(self) -> dict | None:
        if not self.can_redo:
            return None
        self._index += 1
        return copy.deepcopy(self._current().data)

    def reset(self, data: dict) -> None:
        self._snapshots = [_Snapshot(copy.deepcopy(data), "Open")]
        self._index = 0

    def changes(self) -> list[Change]:
        """Edits since the document was opened."""
        return diff(self._snapshots[0].data, self._current().data)


def to_text(changes) -> str:
    """The review a user can read before saving; no file is involved."""
    if not changes:
        return "No changes since the file was opened.\n"
    lines = ["Changes since the file was opened", ""]
    for change in changes:
        lines.append("[{}] {}".format(change.kind.upper(), change.label))
        if change.kind == CHANGED:
            lines.append("  before: {}".format(format_value(change.before)))
            lines.append("  after:  {}".format(format_value(change.after)))
        elif change.kind == ADDED:
            lines.append("  added:  {}".format(format_value(change.after)))
        else:
            lines.append("  removed: {}".format(format_value(change.before)))
    return "\n".join(lines).rstrip() + "\n"
