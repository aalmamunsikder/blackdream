"""A read-only comparison of the open config.plist with the pinned OpenCore sample.

The preview answers three questions before a migration is considered: which keys
the pinned sample declares that this file does not have, which keys this file has
that the sample does not, and where both declare the same path with a different
plist type. It is a reading, not a repair.

Nothing here writes a file, edits a document, or applies a change. ``compare``
copies the document and appends only values a migration could safely add -- the
sample's scalars and empty containers. Non-empty lists and dictionaries are named
in the report but never copied, because injecting the sample's kexts, ACPI
patches or other tables would fabricate a configuration this machine never had.
``Preview.projected`` is a candidate for a reviewed save; it is never saved here.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from blackdream.core import config_diff, config_editor

MISSING = "missing"
EXTRA = "extra"
TYPE = "type"

_KIND_ORDER = {MISSING: 0, EXTRA: 1, TYPE: 2}
#: Plist kinds whose sample value is safe to copy into the projection.
_SCALAR_TYPES = frozenset({
    "boolean", "integer", "real", "string", "data", "date",
})


@dataclass(frozen=True)
class Finding:
    kind: str        # "missing" | "extra" | "type"
    path: tuple      # path into the document/schema
    schema: str      # formatted sample value (or empty for "extra")
    current: str     # formatted current value (or empty for "missing")
    schema_type: str = ""   # plist type name, set for "type" findings
    current_type: str = ""  # plist type name, set for "type" findings

    @property
    def label(self) -> str:
        return config_diff.path_label(self.path)


@dataclass(frozen=True)
class Preview:
    schema_version: str
    findings: tuple[Finding, ...]
    projected: dict  # a new document: current + safe additions only

    @property
    def missing(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.kind == MISSING)

    @property
    def extra(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.kind == EXTRA)

    @property
    def types(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.kind == TYPE)

    @property
    def empty(self) -> bool:
        return not self.findings


def _safe_to_add(value) -> bool:
    """True for the sample values a migration may copy without inventing a table."""
    if config_editor.type_name(value) in _SCALAR_TYPES:
        return True
    return isinstance(value, (list, dict)) and not value


def compare(document: dict, sample: dict, schema_version: str) -> Preview:
    """Compare ``document`` with the pinned ``sample``. Neither input is touched."""
    projected = copy.deepcopy(document)
    findings: list[Finding] = []
    if isinstance(projected, dict) and isinstance(sample, dict):
        _walk(projected, sample, (), findings)
    findings.sort(key=lambda item: (_KIND_ORDER[item.kind], item.label))
    return Preview(schema_version=schema_version, findings=tuple(findings),
                   projected=projected)


def _walk(node: dict, schema: dict, path: tuple, findings: list) -> None:
    for key, expected in schema.items():
        if key.startswith("#"):
            continue
        here = path + (key,)
        if key not in node:
            expected_type = config_editor.type_name(expected)
            findings.append(Finding(
                MISSING, here, config_editor.format_value(expected), "",
                schema_type=expected_type))
            if _safe_to_add(expected):
                # Appending in sample order keeps the document's own keys first.
                node[key] = copy.deepcopy(expected)
            continue
        actual = node[key]
        if isinstance(actual, dict) and isinstance(expected, dict):
            _walk(actual, expected, here, findings)
            continue
        actual_type = config_editor.type_name(actual)
        expected_type = config_editor.type_name(expected)
        if actual_type != expected_type:
            findings.append(Finding(
                TYPE, here, config_editor.format_value(expected),
                config_editor.format_value(actual),
                schema_type=expected_type, current_type=actual_type))
    for key, actual in node.items():
        if key.startswith("#") or key in schema:
            continue
        findings.append(Finding(
            EXTRA, path + (key,), "", config_editor.format_value(actual)))


def to_text(preview: Preview) -> str:
    """The review a user can read; it repeats that nothing here was applied."""
    lines = [
        "BlackDream schema preview",
        "Pinned schema: OpenCore {}".format(preview.schema_version),
        "Missing: {}".format(len(preview.missing)),
        "Extra: {}".format(len(preview.extra)),
        "Different types: {}".format(len(preview.types)),
        "",
    ]
    if preview.empty:
        lines.append("No differences.")
    else:
        lines.append("Missing from this config")
        for finding in preview.missing:
            lines.append("[MISSING] {} = {}".format(finding.label, finding.schema))
        lines.append("")
        lines.append("Not in the pinned schema")
        for finding in preview.extra:
            lines.append("[EXTRA] {}".format(finding.label))
        lines.append("")
        lines.append("Different types")
        for finding in preview.types:
            lines.append("[TYPE] {}: {} -> {}".format(
                finding.label, finding.current_type, finding.schema_type))
    lines.append("")
    lines.append(
        "A key that is missing from this config may be optional or unnecessary "
        "for this machine.")
    lines.append(
        "This preview changes nothing. A migration would need a review and a save.")
    return "\n".join(lines) + "\n"
