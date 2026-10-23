"""Turn ocvalidate's lines into a place in the document and a sentence in English.

The validator names a key, an index and a context, but not a path: ``context`` is the
dictionary the key sits in, and the same name can appear in several sections. The
mapping here is deliberately conservative. When more than one place could be meant,
nothing is returned and the window shows the validator's own line instead -- a wrong
jump is worse than no jump, because it teaches the user to distrust every jump.

Nothing in this module edits the document. ``Explanation.path`` is a reading of the
message, not a repair.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_OCS_UNKNOWN = re.compile(
    r"^OCS:\s*No schema for (?P<key>\S+) at (?P<index>\d+) index, "
    r"context <(?P<context>[^>]*)>!?$")
_OCS_MISSING = re.compile(
    r"^OCS:\s*Missing key (?P<key>\S+), context <(?P<context>[^>]*)>!?$")
_SERIALISATION = re.compile(r"^Serialisation returns (\d+) errors?!?$")


@dataclass(frozen=True)
class Explanation:
    """One validator line, read as far as it can be read without guessing."""

    raw: str
    kind: str
    path: tuple | None
    message: str | None

    @property
    def navigable(self) -> bool:
        return self.path is not None


def _dict_paths(data, path: tuple = ()):
    """Every ``(path, mapping)`` in the document, depth first, in document order."""
    if isinstance(data, dict):
        yield path, data
        for key, value in data.items():
            yield from _dict_paths(value, path + (key,))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            yield from _dict_paths(value, path + (index,))


def _contexts(data, context: str, path: tuple = ()):
    """Every container whose own key is ``context``, as ``(path, container)``.

    A context is usually a dictionary, but ocvalidate also names array sections such
    as ``Add`` and ``Drivers``; there the index in the message is the item's position
    in that array.
    """
    if isinstance(data, dict):
        if path and str(path[-1]) == context:
            yield path, data
        for key, value in data.items():
            yield from _contexts(value, context, path + (key,))
    elif isinstance(data, list):
        if path and str(path[-1]) == context:
            yield path, data
        for index, value in enumerate(data):
            yield from _contexts(value, context, path + (index,))


def _unknown_key_path(data, key: str, index: int, context: str) -> tuple | None:
    candidates = []
    for path, container in _contexts(data, context):
        if isinstance(container, dict):
            if key in container:
                candidates.append((path + (key,), _position(container, key)))
        elif 0 <= index < len(container) and isinstance(container[index], dict) \
                and key in container[index]:
            candidates.append((path + (index, key), index))
    if len(candidates) == 1:
        return candidates[0][0]
    if len(candidates) > 1:
        # The index can separate two sections that share a name, but not two
        # candidates that both put the key at that position. Then the message is
        # not specific enough to move the selection.
        exact = [path for path, position in candidates if position == index]
        if len(exact) == 1:
            return exact[0]
    return None


def _named_dicts(data, context: str):
    return [(path, mapping) for path, mapping in _dict_paths(data)
            if path and str(path[-1]) == context]


def _missing_key_path(data, key: str, context: str) -> tuple | None:
    """The dictionary the key is missing from; the key itself has no path yet."""
    found = [path for path, mapping in _named_dicts(data, context) if key not in mapping]
    if len(found) != 1:
        return None
    return found[0]


def _position(mapping: dict, key: str) -> int:
    for index, name in enumerate(mapping):
        if name == key:
            return index
    return -1


def explain(raw: str, data: dict | None = None) -> Explanation:
    line = (raw or "").strip()
    match = _OCS_UNKNOWN.match(line)
    if match:
        key = match.group("key")
        context = match.group("context")
        path = (_unknown_key_path(data, key, int(match.group("index")), context)
                if isinstance(data, dict) else None)
        return Explanation(
            raw=line, kind="unknown-key", path=path,
            message=("OpenCore's schema has no key named {} inside {}. It may belong "
                     "to another OpenCore version, or be a spelling of a key that "
                     "does exist.".format(key, context)))
    match = _OCS_MISSING.match(line)
    if match:
        key = match.group("key")
        context = match.group("context")
        path = _missing_key_path(data, key, context) if isinstance(data, dict) else None
        return Explanation(
            raw=line, kind="missing-key", path=path,
            message=("{} is missing {}, which the OpenCore version this build targets "
                     "expects.".format(context, key)))
    match = _SERIALISATION.match(line)
    if match:
        return Explanation(
            raw=line, kind="serialisation", path=None,
            message=("ocvalidate could not serialise the property list. The lines above "
                     "name the keys it stopped on."))
    if line.startswith("OCS:") or line.startswith("OCV:"):
        return Explanation(
            raw=line, kind="validator", path=None,
            message=("ocvalidate reported this key or value. The window cannot map it "
                     "to a section of the document, so the message is shown unchanged."))
    return Explanation(raw=line, kind="other", path=None, message=None)


def annotate(issues, data: dict | None = None) -> tuple[Explanation, ...]:
    return tuple(explain(raw, data) for raw in issues)
