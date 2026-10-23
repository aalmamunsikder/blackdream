"""Ready-made config.plist entries offered by the editor.

The patch templates come from the preset library shipped with OpenCore Auxiliary
Tools (``Database/preset/PreSet.plist``, MIT, Copyright (c) 2020-2022 ic005k) and
are limited to fields the pinned OpenCore 1.0.8 sample declares, so inserting one
cannot introduce a key the schema does not know. Insertion never touches the file;
it only changes the in-memory document, exactly like typing a value by hand.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

TARGET_LABEL = " > "


@dataclass(frozen=True)
class ConfigPreset:
    key: str
    title: str
    target: tuple
    detail: str
    value: dict


@dataclass(frozen=True)
class PresetInsert:
    inserted: bool
    path: tuple


def _entry(**fields):
    return fields


_ACPI_PATCHES = (
    ConfigPreset(
        key="acpi-osid-xsid",
        title="Rename OSID to XSID",
        target=("ACPI", "Patch"),
        detail=(
            "Renames OSID to XSID so the _OSI to XOSI rename cannot match it. "
            "Pair it with SSDT-XOSI.aml in ACPI > Add."),
        value=_entry(
            Base="", BaseSkip=0,
            Comment=("change OSID to XSID (to avoid match against _OSI XOSI "
                     "patch)"),
            Count=0, Enabled=True, Find=b"OSID", Limit=0, Mask=b"",
            OemTableId=b"", Replace=b"XSID", ReplaceMask=b"", Skip=0,
            TableLength=0, TableSignature=b""),
    ),
    ConfigPreset(
        key="acpi-osi-xosi",
        title="Rename _OSI to XOSI",
        target=("ACPI", "Patch"),
        detail=(
            "Renames _OSI to XOSI so macOS uses SSDT-XOSI.aml instead of its "
            "own _OSI. Add SSDT-XOSI.aml to ACPI > Add first."),
        value=_entry(
            Base="", BaseSkip=0,
            Comment="change _OSI to XOSI, pair with SSDT-XOSI.aml",
            Count=0, Enabled=True, Find=b"_OSI", Limit=0, Mask=b"",
            OemTableId=b"", Replace=b"XOSI", ReplaceMask=b"", Skip=0,
            TableLength=0, TableSignature=b""),
    ),
    ConfigPreset(
        key="acpi-gprw-xprw",
        title="Rename GPRW to XPRW",
        target=("ACPI", "Patch"),
        detail=(
            "Renames Method(GPRW,2,N) to XPRW for the instant-wake fix. Pair it "
            "with SSDT-GPRW.aml in ACPI > Add."),
        value=_entry(
            Base="", BaseSkip=0, Comment="change Method(GPRW,2,N) to XPRW",
            Count=0, Enabled=True, Find=b"GPRW\x02", Limit=0, Mask=b"",
            OemTableId=b"", Replace=b"XPRW\x02", ReplaceMask=b"", Skip=0,
            TableLength=0, TableSignature=b""),
    ),
    ConfigPreset(
        key="acpi-pts-zpts",
        title="Rename _PTS to ZPTS",
        target=("ACPI", "Patch"),
        detail=(
            "Renames Method(_PTS,1,N) to ZPTS for the sleep and wake fix. Pair "
            "it with SSDT-PTSWAK.aml in ACPI > Add."),
        value=_entry(
            Base="", BaseSkip=0,
            Comment="change Method(_PTS,1,N) to ZPTS, pair with SSDT-PTSWAK.aml",
            Count=0, Enabled=True, Find=b"_PTS\x01", Limit=0, Mask=b"",
            OemTableId=b"", Replace=b"ZPTS\x01", ReplaceMask=b"", Skip=0,
            TableLength=0, TableSignature=b"DSDT"),
    ),
)

_KERNEL_PATCHES = (
    ConfigPreset(
        key="kernel-rtc-wake",
        title="Disable RTC wake scheduling",
        target=("Kernel", "Patch"),
        detail=(
            "Patches AppleRTC so wake alarms are no longer scheduled. For "
            "diagnosing wake problems."),
        value=_entry(
            Arch="Any",
            Base="__ZN8AppleRTC18setupDateTimeAlarmEPK11RTCDateTime",
            Comment="Disable RTC wake scheduling", Count=1, Enabled=False,
            Find=b"", Identifier="com.apple.driver.AppleRTC", Limit=0,
            Mask=b"", MaxKernel="", MinKernel="19.0.0", Replace=b"\xc3",
            ReplaceMask=b"", Skip=0),
    ),
    ConfigPreset(
        key="kernel-acpi-logging",
        title="Disable ACPI logging",
        target=("Kernel", "Patch"),
        detail="Patches AppleACPIPlatform logging out. For debugging only.",
        value=_entry(
            Arch="Any", Base="_AcpiOsVprintf", Comment="Disable ACPI logging",
            Count=0, Enabled=False, Find=b"",
            Identifier="com.apple.driver.AppleACPIPlatform", Limit=0,
            Mask=b"", MaxKernel="18.5.0", MinKernel="18.5.0",
            Replace=b"\xc3", ReplaceMask=b"", Skip=0),
    ),
    ConfigPreset(
        key="kernel-bcm57785",
        title="Broadcom BCM57785 patch",
        target=("Kernel", "Patch"),
        detail=(
            "Fixes adapter information on Broadcom BCM57785 Ethernet. For "
            "machines with that chip."),
        value=_entry(
            Arch="x86_64", Base="__ZN11BCM5701Enet14getAdapterInfoEv",
            Comment="Broadcom BCM57785 patch", Count=1, Enabled=False,
            Find=b"\xe8\x00\x00\xff\xfff\x89\x83\x00\x05\x00\x00",
            Identifier="com.apple.iokit.AppleBCM5701Ethernet", Limit=0,
            Mask=b"\xff\x00\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff",
            MaxKernel="19.9.9", MinKernel="",
            Replace=b"\xb8\xb4\x16\x00\x00f\x89\x83\x00\x05\x00\x00",
            ReplaceMask=b"", Skip=0),
    ),
    ConfigPreset(
        key="kernel-panic-serial",
        title="Send panic strings to serial",
        target=("Kernel", "Patch"),
        detail=(
            "Redirects panic strings to the serial port. For debugging with a "
            "serial cable."),
        value=_entry(
            Arch="x86_64", Base="_panic", Comment="Send panic string to serial port",
            Count=1, Enabled=False, Find=b"", Identifier="kernel", Limit=0,
            Mask=b"", MaxKernel="", MinKernel="",
            Replace=(b"1\xf6\x8a\x0f\x84\xc9u\x04\xff\xc6\xb1\nf\xba\xfd\x03"
                     b"\xec\xa8 t\xfbf\xba\xf8\x03\x88\xc8\xeeH\xff\xc7\x85"
                     b"\xf6t\xdf\xeb\xfe"),
            ReplaceMask=b"", Skip=0),
    ),
    ConfigPreset(
        key="kernel-early-serial",
        title="Send early prints to serial",
        target=("Kernel", "Patch"),
        detail=(
            "Redirects early kernel prints to the serial port. For debugging "
            "with a serial cable."),
        value=_entry(
            Arch="x86_64", Base="_kernel_debug_string_early",
            Comment="Send early prints to serial port", Count=1, Enabled=False,
            Find=b"", Identifier="kernel", Limit=0, Mask=b"", MaxKernel="",
            MinKernel="",
            Replace=(b"1\xf6\x8a\x0f\x84\xc9u\x04\xff\xc6\xb1\nf\xba\xfd\x03"
                     b"\xec\xa8 t\xfbf\xba\xf8\x03\x88\xc8\xeeH\xff\xc7\x85"
                     b"\xf6t\xdf\xc3"),
            ReplaceMask=b"", Skip=0),
    ),
    ConfigPreset(
        key="kernel-print-k",
        title="Print K and halt",
        target=("Kernel", "Patch"),
        detail=(
            "Prints K on the serial port and halts. For debugging early boot."),
        value=_entry(
            Arch="x86_64", Base="_vstart", Comment="Print K and dead loop",
            Count=1, Enabled=False, Find=b"", Identifier="kernel", Limit=0,
            Mask=b"", MaxKernel="", MinKernel="",
            Replace=(b"\xb1Kf\xba\xfd\x03\xec\xa8 t\xfbf\xba\xf8\x03\x88\xc8"
                     b"\xee\xb1\nf\xba\xfd\x03\xec\xa8 t\xfbf\xba\xf8\x03\x88"
                     b"\xc8\xee\xeb\xfe"),
            ReplaceMask=b"", Skip=0),
    ),
    ConfigPreset(
        key="kernel-early-reboot",
        title="Reboot at early boot",
        target=("Kernel", "Patch"),
        detail="Reboots immediately at _vstart. For bisecting early boot failures.",
        value=_entry(
            Arch="x86_64", Base="_vstart", Comment="Early reboot", Count=1,
            Enabled=False, Find=b"", Identifier="kernel", Limit=0, Mask=b"",
            MaxKernel="", MinKernel="",
            Replace=b"1\xc0\xb0\x06\xba\xf9\x0c\x00\x00\xee\xeb\xfe",
            ReplaceMask=b"", Skip=0),
    ),
    ConfigPreset(
        key="kernel-trim",
        title="Enable TRIM for SSD",
        target=("Kernel", "Patch"),
        detail=(
            "Lets macOS send TRIM to non-Apple SSDs by patching "
            "IOAHCIBlockStorage. Turn Enabled on after inserting it."),
        value=_entry(
            Arch="Any", Base="", Comment="Enable TRIM for SSD", Count=0,
            Enabled=False, Find=b"\x00APPLE SSD\x00",
            Identifier="com.apple.iokit.IOAHCIBlockStorage", Limit=0, Mask=b"",
            MaxKernel="", MinKernel="",
            Replace=b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            ReplaceMask=b"", Skip=0),
    ),
)

PRESETS: tuple[ConfigPreset, ...] = _ACPI_PATCHES + _KERNEL_PATCHES


def preset_by_key(key: str) -> ConfigPreset | None:
    for preset in PRESETS:
        if preset.key == key:
            return preset
    return None


def path_label(path) -> str:
    return TARGET_LABEL.join(str(part) for part in path)


def _freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item))
                            for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _identity(value: dict) -> tuple:
    """What a patch does, ignoring its comment and on/off switch."""
    return tuple(sorted((key, _freeze(item)) for key, item in value.items()
                        if key not in ("Comment", "Enabled")))


def _array(data: dict, target, create: bool) -> list | None:
    node = data
    for part in target[:-1]:
        child = node.get(part) if isinstance(node, dict) else None
        if child is None:
            if not create:
                return None
            child = {}
            node[part] = child
        if not isinstance(child, dict):
            raise ValueError("{} is not a dictionary.".format(part))
        node = child
    last = target[-1]
    sequence = node.get(last) if isinstance(node, dict) else None
    if sequence is None:
        if not create:
            return None
        sequence = []
        node[last] = sequence
    if not isinstance(sequence, list):
        raise ValueError("{} is not an array.".format(path_label(target)))
    return sequence


def find_preset(data: dict, preset: ConfigPreset) -> tuple | None:
    """The existing entry that does the same thing, if any."""
    sequence = _array(data, preset.target, create=False)
    if sequence is None:
        return None
    wanted = _identity(preset.value)
    for index, item in enumerate(sequence):
        if isinstance(item, dict) and _identity(item) == wanted:
            return tuple(preset.target) + (index,)
    return None


def insert_preset(data: dict, preset: ConfigPreset) -> PresetInsert:
    """Append the preset, or report the equivalent entry already in the file."""
    existing = find_preset(data, preset)
    if existing is not None:
        return PresetInsert(inserted=False, path=existing)
    sequence = _array(data, preset.target, create=True)
    sequence.append(copy.deepcopy(preset.value))
    return PresetInsert(
        inserted=True, path=tuple(preset.target) + (len(sequence) - 1,))
