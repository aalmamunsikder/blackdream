"""Turn a graded hardware report into rows the GUI can render.

Upstream printed this table to a terminal, one ANSI-colored line per device, as a
side effect of checking compatibility. The data was never returned, so a GUI had
nothing to bind to. The verdict *wording* is still produced by the engine
(:meth:`CompatibilityChecker.show_macos_compatibility`); this only selects which
devices deserve a row and says whether the text is good news.

The table's fourth column is target-relative: a device can be native on one macOS
release and unreachable on the next. ``target_status`` derives that answer from the
engine's own compatibility tuple and the version the user has selected -- it never
introduces a judgement the engine did not already make.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ocengine.compatibility_checker import CompatibilityChecker
from ocengine.datasets import os_data
from ocengine.utils import Utils

_CHECKER = CompatibilityChecker()
_UTILS = Utils()

#: Only these sections carry per-device compatibility, in upstream's own order.
#: Sections absent from a report are skipped rather than shown as empty rows.
SECTIONS = (
    "CPU", "GPU", "Storage Controllers", "Network", "Sound",
    "USB Controllers", "Bluetooth", "SD Controller", "Monitor",
)

# Key to label a device by when the section's own dict keys are not names.
_NAME_KEYS = ("Processor Name", "Name", "Model", "Device", "Controller")

_EMPTY = "\u2014"


@dataclass(frozen=True)
class Verdict:
    section: str
    name: str
    text: str
    #: None means the engine did not grade this device class at all.
    compatible: bool | None
    class_label: str = ""
    #: The engine's ``(max, min)`` Darwin pair, kept for the target-relative column.
    compatibility: tuple | None = None
    #: A per-device OCLP pair when the report carries one.
    oclp: tuple | None = None
    #: Vendor / Device ID / Subsystem, as the report states them.
    fields: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Status:
    """One row's answer for one selected macOS release."""

    key: str
    label: str
    detail: str
    recommendation: str


def rows(report: dict[str, Any]) -> list[Verdict]:
    out: list[Verdict] = []
    for section, name, device in device_blocks(report):
        if "Compatibility" in device:
            out.append(_one(section, name, device))
        else:
            # An ungraded GPU row still matters: it is how the user sees the
            # device the engine refused to judge.
            out.append(Verdict(section, name, "Unchecked", None,
                               class_label(section, name),
                               fields=_raw_fields(device)))
    return out


def device_blocks(report: dict[str, Any],
                  include_ungraded: bool = False) -> list[tuple[str, str, dict]]:
    """The device blocks a report records, named exactly the way :func:`rows` names them.

    Selection only -- nothing here asks the engine anything -- which is what lets
    :mod:`blackdream.core.report_compare` diff two files and still agree with the
    table about which device is which. That disagreement was the bug this function
    exists to prevent: a report keys each device by its own printable name, so the
    key is the name, and only a block that *is* one device (``CPU``) has to be
    labelled from inside it.

    The table wants graded devices, plus GPUs the engine refused to judge. A report
    comparison wants every device, because hardware that never got a verdict is
    still hardware.
    """
    out: list[tuple[str, str, dict]] = []
    for section in SECTIONS:
        block = report.get(section)
        if not isinstance(block, dict) or not block:
            continue
        if "Compatibility" in block:
            out.append((section, label(block), block))
            continue
        if include_ungraded and _is_device_block(block):
            out.append((section, label(block), block))
            continue
        for name, device in block.items():
            if not isinstance(device, dict):
                continue
            if include_ungraded or "Compatibility" in device or section == "GPU":
                out.append((section, str(name), device))
    return out


def _is_device_block(block: dict) -> bool:
    """True when a section block describes one device rather than a set of them."""
    return not any(isinstance(value, dict) for value in block.values())


def _one(section: str, name: str, device: dict) -> Verdict:
    compatibility = device.get("Compatibility")
    text = _CHECKER.show_macos_compatibility(compatibility)
    if text == "Unsupported":
        # Graded, and rejected. A laptop's HDMI audio device lands here on almost
        # every report, which is why it is a red row and not a blocked build.
        compatible: bool | None = False
    elif text == "Unchecked":
        compatible = None
    else:
        compatible = True
    return Verdict(section, name, text, compatible,
                   class_label(section, name),
                   compatibility=compatibility,
                   oclp=device.get("OCLP Compatibility"),
                   fields=_raw_fields(device))


def label(device: dict) -> str:
    """The name a report block calls itself by, for a device or a whole section."""
    for key in _NAME_KEYS:
        if device.get(key):
            return str(device[key])
    return "Device"


def _first(device, keys):
    for key in keys:
        value = device.get(key)
        if value not in (None, ""):
            return str(value)
    return _EMPTY


def _raw_fields(device) -> tuple[tuple[str, str], ...]:
    return (
        ("Vendor", _first(device, ("Manufacturer", "Vendor"))),
        ("Device ID", _first(device, ("Device ID",))),
        ("Subsystem", _first(device, ("Subsystem ID", "Subsystem"))),
    )


def class_label(section: str, name: str) -> str:
    """The plain word a person would use for this device class.

    Network devices carry no type field in the report, so the name is the only
    signal that separates a Wi-Fi card from an Ethernet controller; everything else
    is settled by the section the engine put the device in.
    """
    if section == "CPU":
        return "CPU"
    if section == "GPU":
        return "GPU"
    if section == "Sound":
        return "Audio"
    if section == "Network":
        lowered = name.lower()
        if any(word in lowered for word in ("wi-fi", "wifi", "wireless", "wlan")):
            return "Wi-Fi"
        return "Ethernet"
    if section == "Storage Controllers":
        return "Storage"
    if section == "USB Controllers":
        return "USB"
    if section == "Bluetooth":
        return "Bluetooth"
    if section == "SD Controller":
        return "SD card"
    if section == "Monitor":
        return "Display"
    if section == "Biometric":
        return "Biometric"
    return section


# ---- target-relative status ----

def _parse(value) -> tuple[int, int, int]:
    return _UTILS.parse_darwin_version(str(value))


def _bounds(pair) -> tuple | None:
    if not pair or len(pair) < 2 or not pair[0] or not pair[-1]:
        return None
    try:
        low, high = _parse(pair[0]), _parse(pair[-1])
    except (TypeError, ValueError):
        return None
    return (low, high) if low <= high else (high, low)


def _name(darwin) -> str:
    try:
        return os_data.get_macos_name_by_darwin(darwin) or str(darwin)
    except Exception:
        return str(darwin)


def target_status(verdict: Verdict, target: str | None = None,
                  oclp_range: tuple[str, str] | None = None) -> Status:
    """Answer "will this device work on the release the user picked?"

    ``verdict.compatible`` is the engine's global judgement -- false only when the
    engine found no supported release at all. The useful answer is narrower, so it
    is computed against the chosen Darwin version and the same tuples the engine
    used, with the OCLP range only deciding between "limited" and "not supported".
    """
    native = _bounds(verdict.compatibility)
    if native is None:
        if verdict.compatible is False:
            return Status(
                "unsupported", "Not supported",
                "The engine found no macOS release that supports this device.",
                "A different device is needed: no macOS release supports this one.")
        return Status(
            "unknown", "Not graded",
            "The engine did not grade this device.",
            "Check that the report carries this device's details.")

    low, high = native
    if target is None:
        if verdict.compatible is True:
            return Status(
                "supported", "Supported",
                "Supported up to {}.".format(_name(high)),
                "Choose a release inside the supported range.")
        return Status(
            "unknown", "Not graded",
            "The engine did not grade this device for a specific release.",
            "Select a macOS version to see this device's status.")

    try:
        point = _parse(target)
    except (TypeError, ValueError):
        point = high
    chosen = _name(target)

    if point < low:
        return Status(
            "unsupported", "Not supported",
            "Not supported on {}. The engine supports this device from {}.".format(
                chosen, _name(low)),
            "Choose {} or newer.".format(_name(low)))
    if point <= high:
        return Status(
            "supported", "Supported",
            "Supported on {}.".format(chosen),
            "No action needed: this device runs natively on the selected release.")

    oclp = _bounds(verdict.oclp) or _bounds(oclp_range)
    if oclp is not None and oclp[0] <= point <= oclp[1]:
        return Status(
            "limited", "Limited support",
            "Limited support on {}: runs through OpenCore Legacy Patcher.".format(chosen),
            "This release needs OpenCore Legacy Patcher for this device.")
    return Status(
        "unsupported", "Not supported",
        "Not supported on {}. Last native support is {}.".format(chosen, _name(high)),
        "Choose {} or earlier for native support.".format(_name(high)))


def friendly_range(darwins: tuple[str, str] | None) -> str:
    """"macOS 10.13 High Sierra - 26 Tahoe" from a pair of darwin versions.

    Sorted by darwin version because the engine hands native ranges back as
    (min, max) and OCLP ranges as (max, min) -- see ``blackdream.core.versions``.
    """
    if not darwins:
        return ""
    low, high = sorted(darwins, key=_parse)
    return "{} - {}".format(_name(low), _name(high))
