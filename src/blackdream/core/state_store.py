"""Small, dependency-free helpers for the application's local record files.

Every record BlackDream keeps for itself -- machine profiles, build history -- is a
plain file in the per-user state directory. A file written in place can be left
half-finished by a crash or a full disk, so writes go to a temporary file in the
same directory, are flushed to disk, and only then replace the old file. Readers
never raise: a missing, unreadable or older file simply reads as absent.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_text(path, text: str) -> None:
    """Replace ``path`` with ``text`` without ever exposing a partial file.

    The temporary file lives in the target's own directory so ``os.replace`` is a
    same-filesystem rename. Write failures propagate as :class:`OSError`; the
    caller decides whether that is worth reporting.
    """
    target = Path(path)
    directory = target.parent
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix="." + target.name + ".", suffix=".tmp", dir=str(directory))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def read_text(path) -> str | None:
    """The file's text, or None when it is absent or cannot be decoded."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def read_json(path) -> dict | None:
    """The file's top-level JSON object, or None when it has none."""
    text = read_text(path)
    if text is None:
        return None
    try:
        document = json.loads(text)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None
