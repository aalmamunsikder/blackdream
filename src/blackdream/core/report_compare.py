"""Compare two parsed Report.json files without grading either one.

This is a read-only diff of what the files recorded. It never runs the
compatibility engine and never writes anything, so it cannot tell whether either
machine boots macOS. A difference in a recorded compatibility tuple says only
that the two files disagree -- it can come from a different engine or database
version, not necessarily from a hardware change. The export says so in as many
words.

Hardware differences (ids, names, paths) are kept apart from differences in what
the engine recorded, because only the first kind is a statement about a machine.
"""

from __future__ import annotations

from dataclasses import dataclass

from blackdream.core import verdicts

#: The only report keys treated as hardware evidence, in the order they print.
HARDWARE_FIELDS = (
    "Processor Name", "Manufacturer", "Vendor", "Device ID", "Subsystem ID",
    "Subsystem", "PCI Path", "Device Type",
)

BOUNDARY = ("A recorded compatibility change can come from a different engine or "
            "database version, not from this machine. Neither side was re-graded.")

_MARKERS = {
    "added": "ADDED",
    "removed": "REMOVED",
    "hardware": "HARDWARE",
    "reading": "READING",
}


@dataclass(frozen=True)
class Device:
    section: str
    name: str
    fields: tuple[tuple[str, str], ...]
    compatibility: tuple | None
    oclp: tuple | None


@dataclass(frozen=True)
class Change:
    kind: str  # "added" | "removed" | "hardware" | "reading"
    section: str
    name: str
    detail: str


@dataclass(frozen=True)
class Comparison:
    changes: tuple[Change, ...]
    unchanged: int
    devices_before: int
    devices_after: int

    @property
    def empty(self) -> bool:
        return not self.changes


def _pair(value) -> tuple | None:
    """The recorded range as a tuple, without reinterpreting its contents."""
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return None


def _fields(device: dict) -> tuple[tuple[str, str], ...]:
    found = []
    for key in HARDWARE_FIELDS:
        value = device.get(key)
        if value in (None, ""):
            continue
        found.append((key, str(value)))
    return tuple(found)


def _device(section: str, name: str, raw: dict) -> Device:
    return Device(
        section=section,
        name=name,
        fields=_fields(raw),
        compatibility=_pair(raw.get("Compatibility")),
        oclp=_pair(raw.get("OCLP Compatibility")),
    )


def devices(report: dict) -> dict[tuple[str, str], Device]:
    """Every device the report recorded, keyed by section and printable name.

    Names and selection come from :func:`blackdream.core.verdicts.device_blocks`,
    the same rule the Compatibility table uses, so a row here is the row the user
    already recognises -- and every device counts, graded or not, because a freshly
    collected report has no verdicts in it yet. A report keys each device once, so
    no two devices are merged under one name; that would hide exactly the difference
    this comparison exists to show.
    """
    return {(section, name): _device(section, name, raw)
            for section, name, raw in verdicts.device_blocks(report, True)}


def _text(value) -> str:
    return "not recorded" if value is None else str(value)


def _pair_text(pair: tuple | None) -> str:
    if pair is None:
        return "not recorded"
    return "({})".format(", ".join(str(item) for item in pair))


def _hardware_detail(before: Device, after: Device) -> str:
    old = dict(before.fields)
    new = dict(after.fields)
    parts = []
    for field in HARDWARE_FIELDS:
        left, right = old.get(field), new.get(field)
        if left != right:
            parts.append("{}: {} -> {}".format(field, _text(left), _text(right)))
    return "; ".join(parts)


def _reading_detail(before: Device, after: Device) -> str:
    parts = []
    if before.compatibility != after.compatibility:
        parts.append("Compatibility: {} -> {}".format(
            _pair_text(before.compatibility), _pair_text(after.compatibility)))
    if before.oclp != after.oclp:
        parts.append("OCLP Compatibility: {} -> {}".format(
            _pair_text(before.oclp), _pair_text(after.oclp)))
    return "; ".join(parts)


def compare(before: dict, after: dict) -> Comparison:
    """Diff two parsed reports. Reads both arguments only; never grades them."""
    old = devices(before)
    new = devices(after)
    changes: list[Change] = []

    for key, device in old.items():
        if key not in new:
            changes.append(Change("removed", device.section, device.name,
                                  "Not in the later report."))
    for key, device in new.items():
        if key not in old:
            changes.append(Change("added", device.section, device.name,
                                  "Not in the earlier report."))

    unchanged = 0
    hardware_changes: list[Change] = []
    reading_changes: list[Change] = []
    for key, device in old.items():
        other = new.get(key)
        if other is None:
            continue
        hardware = _hardware_detail(device, other)
        reading = _reading_detail(device, other)
        if hardware:
            hardware_changes.append(
                Change("hardware", device.section, device.name, hardware))
        if reading:
            reading_changes.append(
                Change("reading", device.section, device.name, reading))
        if not hardware and not reading:
            unchanged += 1

    changes.extend(hardware_changes)
    changes.extend(reading_changes)
    return Comparison(tuple(changes), unchanged, len(old), len(new))


def to_text(comparison: Comparison) -> str:
    """The export, with each change labelled and the re-grading caveat attached."""
    hardware = sum(1 for item in comparison.changes if item.kind == "hardware")
    reading = sum(1 for item in comparison.changes if item.kind == "reading")
    lines = [
        "BlackDream report comparison",
        "Devices before: {}".format(comparison.devices_before),
        "Devices after: {}".format(comparison.devices_after),
        "Hardware changes: {}".format(hardware),
        "Recorded compatibility changes: {}".format(reading),
        "Unchanged: {}".format(comparison.unchanged),
    ]
    if not comparison.changes:
        lines.append("No differences.")
    for item in comparison.changes:
        lines.append("[{}] {}: {}".format(_MARKERS.get(item.kind, item.kind.upper()),
                                         item.section, item.name))
        lines.append("  {}".format(item.detail))
    lines.append(BOUNDARY)
    return "\n".join(lines) + "\n"
