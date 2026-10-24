"""Explain the kext, driver and quirk relationships a config.plist already encodes.

A build decides these relationships; a hand-edited config inherits them, and a config
carried over from another machine can break them silently. This module reads the edges
and reports the disagreements in the engine's own terms. Every advisory names the line
of this repository the rule comes from, because an advisory nobody can check is a guess.

Three boundaries are deliberate.

* It never reorders ``Kernel/Add``, never edits a quirk and never touches a boot-arg.
  Each rule ends in a sentence rather than an action: the roadmap's own constraint on
  the first release of this feature is that it must not "automatically reorder kexts or
  alter kernel quirks".
* Rules are versioned. :data:`RULESET` is part of every dismissal key, so a rule whose
  meaning changes stops honouring the dismissals made under the old meaning.
* Only the config is read. Bundle *identifiers*, duplicate-identifier and load-order
  against the real ``Info.plist`` files are already verified by the build itself
  (:mod:`blackdream.core.pipeline`), and missing files are preflight's job
  (:mod:`blackdream.core.efi_preflight`). This module answers the one question neither
  of them asks: which relationship *inside the plist* does not hold together.

The dependency edges come from the vendored catalogue, ``ocengine.datasets.kext_data``.
Its rows carry a mutable ``checked`` flag that belongs to one build session; this module
reads ``requires_kexts``, ``conflict_group_id`` and the version windows and never touches
the flag, and it does not import ``kext_maestro``, which owns that session state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ocengine.datasets import kext_data

from blackdream.core import state_store
from ocengine import paths

#: Bump this when a rule's meaning changes, not merely when one is added. Dismissal
#: keys carry it, so a reinterpreted rule cannot stay hidden behind an old dismissal.
RULESET = 1

ERROR = "error"
WARNING = "warning"
INFO = "info"

HIGH = "high"
MEDIUM = "medium"

#: Where the firmware's own macOS selection lives. ``config_prodigy.py:744`` writes
#: ``boot-args`` here; an entry under any other GUID is never read by the firmware.
BOOT_SERVICES_GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"

#: The one sentence that says what these checks are not. The dialog prints it and
#: the export repeats it, so a reader who has only the file still has the boundary.
BOUNDARY = ("These checks read config.plist. They do not reorder kexts, do not "
            "change any quirk, and do not test firmware, hardware or whether "
            "macOS boots.")

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}
_CONFIDENCE_ORDER = {HIGH: 1, MEDIUM: 0}

#: ``conflict_group_id`` is the engine's own word for "pick one of these". The group is
#: named after the hardware it argues about, so the advisory can say what the two kexts
#: are both claiming to do.
_GROUP_LABELS = {
    "GPU": "graphics support",
    "IntelWiFi": "Intel Wi-Fi support",
    "RTL8125": "Realtek RTL8125 Ethernet support",
    "SATA": "unsupported SATA support",
    "PC711": "ASMedia PCIe SATA probing",
    "RealtekCardReader": "Realtek card-reader support",
    "TSC": "time stamp counter synchronisation",
}

#: A boot-arg the engine only ever writes while a particular kext is selected.
#: ``config_prodigy.py:623-631`` gates ``alcid=``, ``-vi2c-force-polling`` and
#: ``ctrsmt=full`` on AppleALC, VoodooI2C and CpuTopologyRebuild respectively.
_ARG_OWNERS = {
    "alcid": ("AppleALC", "the audio codec layout id"),
    "-vi2c-force-polling": ("VoodooI2C", "I2C force polling"),
    "ctrsmt": ("CpuTopologyRebuild", "the rebuild of hybrid core topology"),
}

#: ``config_prodigy.py:607`` writes this only for a Navi dGPU while WhateverGreen is
#: selected. It is listed apart from :data:`_ARG_OWNERS` because the kext may be absent
#: on a machine whose dGPU does not need it, which is why it is only ``info``.
_PIKERA_OWNER = "WhateverGreen"


@dataclass(frozen=True)
class Advisory:
    """One relationship that does not hold, the evidence for it, and the rule's source."""

    rule: str
    severity: str
    confidence: str
    path: tuple
    where: str
    trigger: str
    evidence: str
    advice: str
    source: str

    @property
    def dismissal_key(self) -> str:
        """The stable identity of *this* advisory, for a dismiss/ignore record.

        ``where`` carries a list index so the dialog can jump to the row, but an index
        moves as soon as a neighbour is added or removed. Dropping the numeric parts
        keys the record on the bundle and the key name instead, so a dismissal survives
        a reorder and a ruleset change still invalidates it.
        """
        stable = "/".join(part for part in self.where.split("/") if not part.isdigit())
        return "{}|{}|{}".format(RULESET, self.rule, stable)


@dataclass(frozen=True)
class Report:
    """The advisories, in the order a reader should see them, plus what was skipped."""

    advisories: tuple[Advisory, ...]
    skipped: tuple[str, ...]
    entries: int
    rules: int

    def _counted(self, severity: str) -> tuple[Advisory, ...]:
        return tuple(item for item in self.advisories if item.severity == severity)

    @property
    def errors(self) -> tuple[Advisory, ...]:
        return self._counted(ERROR)

    @property
    def warnings(self) -> tuple[Advisory, ...]:
        return self._counted(WARNING)

    @property
    def notes(self) -> tuple[Advisory, ...]:
        return self._counted(INFO)

    @property
    def clean(self) -> bool:
        return not self.advisories

    @property
    def summary(self) -> str:
        if self.clean:
            return "No dependency issues detected by these checks."
        counts = []
        for severity, label in ((ERROR, "error"), (WARNING, "warning"), (INFO, "note")):
            total = len(self._counted(severity))
            if total:
                counts.append("{} {}".format(total, label if total == 1 else label + "s"))
        text = ", ".join(counts)
        return text[:1].upper() + text[1:] + "."


class AdvisorError(Exception):
    """The document cannot be reasoned about at all; the message says why."""


_CATALOGUE = {kext.name: kext for kext in kext_data.kexts}


def _advisory(rule, severity, confidence, path, where, trigger, evidence, advice,
              source) -> Advisory:
    return Advisory(rule=rule, severity=severity, confidence=confidence, path=path,
                    where=where, trigger=trigger, evidence=evidence, advice=advice,
                    source=source)


def _darwin(text):
    """``"22.4.0"`` to ``(22, 4, 0)``; anything unusable reads as None.

    ``MinKernel`` and ``MaxKernel`` are written empty by the engine when they mean the
    whole range (``kext_maestro.py:1249``), and a hand-edited plist can hold anything,
    so a value that will not parse must not become an advisory.
    """
    if not isinstance(text, str):
        return None
    parts = text.strip().split(".")
    if len(parts) != 3:
        return None
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def bundle_name(reference) -> str:
    """The catalogue name a ``BundlePath`` refers to, or "" when it matches nothing.

    ``BundlePath`` can name a plug-in nested inside a bundle, and the engine's own
    catalogue is keyed by bare kext name, so the last component is what counts.
    """
    if not isinstance(reference, str):
        return ""
    tail = reference.strip().replace("\\", "/").rstrip("/").split("/")[-1]
    if not tail.casefold().endswith(".kext"):
        return ""
    return tail[:-len(".kext")]


def _kernel_entries(document: dict) -> list:
    value = document.get("Kernel")
    add = value.get("Add") if isinstance(value, dict) else None
    return add if isinstance(add, list) else []


def _enabled(entry) -> bool:
    return not isinstance(entry, dict) or bool(entry.get("Enabled", True))


def _entry_name(entry):
    if isinstance(entry, dict):
        return bundle_name(entry.get("BundlePath"))
    return bundle_name(entry)


def _entry_path(index, key="BundlePath") -> tuple:
    return ("Kernel", "Add", index, key)


def _order_and_dependency(document: dict) -> list[Advisory]:
    findings: list[Advisory] = []
    entries = _kernel_entries(document)
    enabled_at: dict[str, int] = {}
    listed_at: dict[str, int] = {}
    for index, entry in enumerate(entries):
        name = _entry_name(entry)
        if not name:
            continue
        listed_at.setdefault(name, index)
        if _enabled(entry):
            enabled_at.setdefault(name, index)

    for index, entry in enumerate(entries):
        if not _enabled(entry):
            continue
        name = _entry_name(entry)
        kext = _CATALOGUE.get(name)
        if kext is None or not kext.requires_kexts:
            continue
        for parent in kext.requires_kexts:
            path = _entry_path(index)
            where = "Kernel/Add/{}/{}/{}".format(index, name, parent)
            position = enabled_at.get(parent)
            if position is None and parent in listed_at:
                slot = listed_at[parent]
                findings.append(_advisory(
                    "dependency.disabled", ERROR, HIGH,
                    _entry_path(slot, "Enabled"),
                    "Kernel/Add/{}/{}/Enabled".format(slot, parent),
                    "{} is enabled, but {} is switched off.".format(name, parent),
                    "{}.kext is in Kernel/Add with Enabled false".format(parent),
                    "Enable {}.kext, or the loader will refuse {}.".format(parent, name),
                    "ocengine/kext_maestro.py:645-649 (a dependency is pulled in with "
                    "its dependent)"))
            elif position is None:
                findings.append(_advisory(
                    "dependency.missing", ERROR, HIGH, path, where,
                    "{} is enabled, but {} is not in Kernel/Add.".format(name, parent),
                    "Kernel/Add has no entry for {}.kext".format(parent),
                    "Add {}.kext to Kernel/Add before it, or the loader will refuse "
                    "{}.".format(parent, name),
                    "ocengine/datasets/kext_data.py:12 (requires_kexts)"))
            elif position > index:
                findings.append(_advisory(
                    "order.parent_after_dependent", ERROR, HIGH, path, where,
                    "{} is enabled before {}.".format(name, parent),
                    "{} is entry {}, {} is entry {}".format(
                        name, index, parent, position),
                    "Move {} above {} in Kernel/Add. The engine emits a dependency "
                    "before whatever needs it.".format(parent, name),
                    "ocengine/kext_maestro.py:1201-1203 (dependency visit order)"))
    return findings


def _conflicts(document: dict) -> list[Advisory]:
    findings: list[Advisory] = []
    entries = _kernel_entries(document)
    by_group: dict[str, list] = {}
    for index, entry in enumerate(entries):
        name = _entry_name(entry)
        kext = _CATALOGUE.get(name)
        if not _enabled(entry) or kext is None or not kext.conflict_group_id:
            continue
        by_group.setdefault(kext.conflict_group_id, []).append((index, name))

    for group, members in sorted(by_group.items()):
        if len(members) < 2:
            continue
        subject = _GROUP_LABELS.get(group, group)
        for index, name in members:
            others = ", ".join(dict.fromkeys(
                other for _other_index, other in members if other != name))
            findings.append(_advisory(
                "conflict.group", WARNING, HIGH, _entry_path(index),
                "Kernel/Add/{}/{}".format(index, name),
                "{} is enabled alongside {}; both claim {}.".format(name, others, subject),
                "both are enabled in the engine's {} group".format(group),
                "Keep one of them enabled. Two kexts that patch the same hardware can "
                "undo each other.",
                "ocengine/datasets/kext_data.py:13 (conflict_group_id)"))
    return findings


def _boot_args(document: dict):
    """``(text, path)`` for the boot-args the firmware actually reads."""
    nvram = document.get("NVRAM")
    if not isinstance(nvram, dict):
        return "", None
    add = nvram.get("Add")
    if not isinstance(add, dict):
        return "", None
    services = add.get(BOOT_SERVICES_GUID)
    if not isinstance(services, dict):
        return "", None
    value = services.get("boot-args")
    return (value if isinstance(value, str) else ""), ("NVRAM", "Add",
                                                        BOOT_SERVICES_GUID, "boot-args")


def _arg_keys(text: str) -> list[str]:
    """Every boot-arg token, with its ``key=value`` form reduced to its key."""
    return [token.split("=", 1)[0] for token in text.split() if token]


def _other_guids_with_boot_args(document: dict) -> list[str]:
    """GUIDs under ``NVRAM/Add`` that carry ``boot-args`` but are not BootServices.

    OpenCore reads its boot arguments from one GUID
    (``ocengine/config_prodigy.py:744``). An entry under any other is written, kept in
    sync by hand, and never read by the firmware - which is the kind of thing a config
    copied from another machine carries.
    """
    nvram = document.get("NVRAM")
    add = nvram.get("Add") if isinstance(nvram, dict) else None
    if not isinstance(add, dict):
        return []
    found = []
    for guid, value in add.items():
        if guid == BOOT_SERVICES_GUID or not isinstance(value, dict):
            continue
        if isinstance(value.get("boot-args"), str) and value["boot-args"].strip():
            found.append(guid)
    return sorted(found)


def _boot_arg_findings(document: dict, target, flagged=()) -> list[Advisory]:
    findings: list[Advisory] = []
    for guid in _other_guids_with_boot_args(document):
        findings.append(_advisory(
            "boot_args.wrong_guid", WARNING, HIGH,
            ("NVRAM", "Add", guid, "boot-args"),
            "NVRAM/Add/{}/boot-args".format(guid[:8]),
            "boot-args is stored under a GUID the firmware does not read.",
            "GUID {}".format(guid),
            "Move the arguments under {}, where OpenCore looks.".format(
                BOOT_SERVICES_GUID),
            "ocengine/config_prodigy.py:744"))

    text, path = _boot_args(document)
    if path is None:
        return findings

    present = _arg_keys(text)
    names = {_entry_name(entry) for entry in _kernel_entries(document)
             if _enabled(entry)}
    where = "NVRAM/Add/{}/boot-args".format(BOOT_SERVICES_GUID)
    for token in present:
        owner = _ARG_OWNERS.get(token)
        if owner and owner[0] not in names:
            findings.append(_advisory(
                "boot_arg.orphan", WARNING, MEDIUM, path, where,
                "{} is set but {} is not enabled.".format(token, owner[0]),
                "boot-args reads {!r}".format(text),
                "Enable {}.kext, or drop {} - it does nothing on its own.".format(
                    owner[0], token),
                "ocengine/config_prodigy.py:623-631"))
        elif token == "agdpmod" and _PIKERA_OWNER not in names:
            findings.append(_advisory(
                "boot_arg.pikera_without_weg", INFO, MEDIUM, path, where,
                "agdpmod=pikera is set but WhateverGreen is not enabled.",
                "boot-args reads {!r}".format(text),
                "The engine writes this only while WhateverGreen is selected for a Navi "
                "dGPU; check it still applies to this machine.",
                "ocengine/config_prodigy.py:607"))

    if "-lilubetaall" not in present and target:
        window = _first_out_of_window(document, target, flagged)
        if window is not None:
            index, name, low, high = window
            findings.append(_advisory(
                "boot_arg.lilubeta_missing", WARNING, HIGH,
                _entry_path(index),
                "Kernel/Add/{}/{}/MinKernel".format(index, name),
                "{}'s version window excludes the release you are targeting.".format(name),
                "{} needs a beta Lilu plug-in path outside {}-{}".format(name, low, high),
                "The engine adds -lilubetaall in this case; this config does not carry "
                "it, so the plug-in may be skipped.",
                "ocengine/config_prodigy.py:577-579"))
    return findings


def _first_out_of_window(document: dict, target, flagged=()):
    """The first enabled Lilu plug-in whose window misses ``target``.

    Entries the window rule already reported are skipped: that rule speaks for a bound
    written in the plist, and this one only has something to add when the plist carries
    no bound and the catalogue window is what excludes the release. Two advisories on
    one entry for one cause reads as two problems.
    """
    wanted = _darwin(target)
    if wanted is None:
        return None
    already = set(flagged)
    for index, entry in enumerate(_kernel_entries(document)):
        if index in already or not _enabled(entry) or not isinstance(entry, dict):
            continue
        name = _entry_name(entry)
        kext = _CATALOGUE.get(name)
        if kext is None or "Lilu" not in kext.requires_kexts:
            continue
        low = _darwin(entry.get("MinKernel")) or _darwin(kext.min_darwin_version)
        high = _darwin(entry.get("MaxKernel")) or _darwin(kext.max_darwin_version)
        if low and high and not (low <= wanted <= high):
            return index, name, entry.get("MinKernel") or kext.min_darwin_version, \
                entry.get("MaxKernel") or kext.max_darwin_version
    return None


def _window_findings(document: dict, target) -> list[Advisory]:
    findings: list[Advisory] = []
    wanted = _darwin(target)
    if wanted is None:
        return findings
    for index, entry in enumerate(_kernel_entries(document)):
        if not _enabled(entry) or not isinstance(entry, dict):
            continue
        name = _entry_name(entry)
        if not name:
            continue
        low = _darwin(entry.get("MinKernel"))
        high = _darwin(entry.get("MaxKernel"))
        # An empty window in the plist means the whole range: the engine writes ""
        # rather than the lowest version it knows (kext_maestro.py:1249), so an absent
        # bound is not a bound, and no catalogue guess should become an advisory.
        if low and wanted < low:
            findings.append(_advisory(
                "window.excludes_target", ERROR, HIGH, _entry_path(index, "MinKernel"),
                "Kernel/Add/{}/{}/MinKernel".format(index, name),
                "{} will not load on the release you are targeting.".format(name),
                "MinKernel {} is newer than the target {}".format(
                    entry.get("MinKernel"), target),
                "Choose an older release, or enable the kext for a machine that needs "
                "it; MinKernel hides it from anything below {}.".format(
                    entry.get("MinKernel")),
                "ocengine/kext_maestro.py:1249 (MinKernel is written per entry)"))
        if high and wanted > high:
            findings.append(_advisory(
                "window.excludes_target", ERROR, HIGH, _entry_path(index, "MaxKernel"),
                "Kernel/Add/{}/{}/MaxKernel".format(index, name),
                "{} will not load on the release you are targeting.".format(name),
                "MaxKernel {} is older than the target {}".format(
                    entry.get("MaxKernel"), target),
                "Choose an older release, or raise MaxKernel only if you know this kext "
                "works past {}.".format(entry.get("MaxKernel")),
                "ocengine/kext_maestro.py:1198-1199 (MaxKernel comes from the "
                "catalogue window)"))
    return findings


def _duplicate_paths(document: dict) -> list[Advisory]:
    findings: list[Advisory] = []
    seen: dict[str, int] = {}
    entries = _kernel_entries(document)
    for index, entry in enumerate(entries):
        reference = entry.get("BundlePath") if isinstance(entry, dict) else entry
        if not isinstance(reference, str) or not reference.strip():
            continue
        folded = reference.strip().casefold()
        if folded in seen:
            previous = seen[folded]
            # The engine disables the second of two bundles sharing an identifier
            # rather than dropping it (kext_maestro.py:1228-1231), so a disabled twin
            # is the recorded answer, not a defect worth raising twice.
            if not _enabled(entry):
                continue
            findings.append(_advisory(
                "entry.duplicate", WARNING, HIGH, _entry_path(index),
                "Kernel/Add/{}".format(index),
                "{} is listed twice.".format(reference),
                "entries {} and {} name the same bundle".format(previous, index),
                "Remove the repeated entry. The second one loads nothing new.",
                "ocengine/kext_maestro.py:1228-1231 (a repeated bundle is disabled, "
                "not re-listed)"))
            continue
        seen[folded] = index
    return findings


def _drivers(document: dict) -> list:
    uefi = document.get("UEFI")
    drivers = uefi.get("Drivers") if isinstance(uefi, dict) else None
    return drivers if isinstance(drivers, list) else []


def _driver_names(document: dict) -> list:
    names = []
    for entry in _drivers(document):
        reference = entry.get("Path") if isinstance(entry, dict) else entry
        if isinstance(reference, str) and reference.strip():
            names.append(reference.strip())
    return names


def _driver_findings(document: dict, target) -> list[Advisory]:
    findings: list[Advisory] = []
    if not isinstance(document.get("UEFI"), dict):
        # Absence of the section is not absence of a driver: a partial or freshly
        # started document has no UEFI key at all, and "OpenRuntime.efi is missing"
        # would be a claim about a list that was never written.
        return findings
    names = _driver_names(document)
    present = {name.casefold() for name in names}
    where = "UEFI/Drivers"

    if "openruntime.efi" not in present:
        findings.append(_advisory(
            "driver.pairing", ERROR, HIGH, ("UEFI", "Drivers"), where,
            "OpenRuntime.efi is not listed.",
            "UEFI/Drivers lists {}".format(", ".join(names) or "nothing"),
            "Add OpenRuntime.efi to UEFI/Drivers. The engine lists it for every build, "
            "and OpenCore's protocol replacement needs it.",
            "ocengine/config_prodigy.py:645"))
    if "hfsplus.efi" in present and "hfspluslegacy.efi" in present:
        findings.append(_advisory(
            "driver.pairing", WARNING, HIGH, ("UEFI", "Drivers"), where,
            "HfsPlus.efi and HfsPlusLegacy.efi are both listed.",
            "UEFI/Drivers lists {}".format(", ".join(names)),
            "Keep one. The engine picks the legacy variant for the newest CPU "
            "generations and the ordinary one otherwise - never both.",
            "ocengine/config_prodigy.py:645"))
    wanted = _darwin(target)
    if wanted and wanted >= (25, 0, 0) and "apfs_aligned.efi" not in present:
        findings.append(_advisory(
            "driver.tahoe_apfs", INFO, MEDIUM, ("UEFI", "Drivers"), where,
            "apfs_aligned.efi is not listed, and the target release is Tahoe or newer.",
            "UEFI/Drivers lists {}".format(", ".join(names) or "nothing"),
            "The engine adds apfs_aligned.efi for a 25.x target; check whether this "
            "folder still needs it.",
            "ocengine/config_prodigy.py:653-654"))
    return findings


#: Two quirks the engine ties together, and the tie it uses.
#:
#: ``equal`` pairs are derived from one condition, so they agree in every build the
#: engine makes. ``not_both_on`` pairs are the engine's own words for one switch and
#: its negation - but both off is legitimate there too: an AMD CPU gets
#: ``AppleXcpmCfgLock = False`` whatever the first quirk says
#: (:class:`ocengine.config_prodigy`, line 710), so only both-on is impossible.
#: ``(rule, block, keys, expectation, why, advice, source)``
_QUIRK_PAIRS = (
    ("quirk.cfg_locks", ("Kernel", "Quirks"), ("AppleCpuPmCfgLock", "AppleXcpmCfgLock"),
     "not_both_on",
     "The engine sets the second as the negation of the first, and forces it off for "
     "AMD.",
     "Keep one of them off. Two CFG locks patched at once fight over the same MSR.",
     "ocengine/config_prodigy.py:709-710"),
    ("quirk.slide_pair", ("Booter", "Quirks"),
     ("EnableSafeModeSlide", "ProvideCustomSlide"), "equal",
     "The engine derives both from the firmware type alone, so a build of this engine "
     "never has them apart.",
     "Make them match. A slide that is provided but not allowed in Safe Mode, or the "
     "reverse, is usually a hand edit.",
     "ocengine/config_prodigy.py:683 and :689"),
    ("quirk.memory_map", ("Booter", "Quirks"),
     ("EnableWriteUnprotector", "RebuildAppleMemoryMap"), "not_both_on",
     "The engine sets the rebuild only when the write unprotector is off.",
     "Turn one off. Both on means two strategies for the same memory map.",
     "ocengine/config_prodigy.py:684 and :690"),
)


def _pair_breaks(expectation: str, flags) -> bool:
    if expectation == "equal":
        return flags[0] != flags[1]
    return all(flags)


def _quirk_findings(document: dict) -> list[Advisory]:
    findings: list[Advisory] = []
    for rule, block, keys, expectation, why, fix, source in _QUIRK_PAIRS:
        section = document.get(block[0])
        values = section.get(block[1]) if isinstance(section, dict) else None
        if not isinstance(values, dict):
            continue
        flags = [values.get(key) for key in keys]
        if not all(isinstance(flag, bool) for flag in flags):
            continue
        if not _pair_breaks(expectation, flags):
            continue
        if expectation == "equal":
            trigger = "{} is {} while {} is {}.".format(
                keys[0], "on" if flags[0] else "off",
                keys[1], "on" if flags[1] else "off")
        else:
            trigger = "{} and {} are both on.".format(*keys)
        findings.append(_advisory(
            rule, WARNING, HIGH, block + (keys[1],),
            "{}/{}".format(".".join(block), keys[1]), trigger, why, fix, source))

    kernel = document.get("Kernel")
    platform = document.get("PlatformInfo")
    if isinstance(kernel, dict) and isinstance(platform, dict):
        quirks = kernel.get("Quirks")
        guid = quirks.get("CustomSMBIOSGuid") if isinstance(quirks, dict) else None
        mode = platform.get("UpdateSMBIOSMode")
        if guid is True and isinstance(mode, str) and mode != "Custom":
            findings.append(_advisory(
                "quirk.smbios_guid_mode", WARNING, HIGH,
                ("PlatformInfo", "UpdateSMBIOSMode"), "PlatformInfo/UpdateSMBIOSMode",
                "CustomSMBIOSGuid is on while UpdateSMBIOSMode is {!r}.".format(mode),
                "The engine pairs a custom GUID with UpdateSMBIOSMode Custom.",
                "Set UpdateSMBIOSMode to Custom, or turn CustomSMBIOSGuid off.",
                "ocengine/config_prodigy.py:713 and :751"))

    bars = _resize_gpu_bars(document)
    text, path = _boot_args(document)
    if bars is not None and path is not None and "npci" in _arg_keys(text):
        if bars == 0:
            findings.append(_advisory(
                "quirk.resize_bars_npai", WARNING, HIGH, path,
                "NVRAM/Add/{}/boot-args".format(BOOT_SERVICES_GUID),
                "npci=0x2000 is set while ResizeAppleGpuBars is 0.",
                "The engine writes npci=0x2000 only when the bar resize is not disabled.",
                "Remove npci=0x2000, or set ResizeAppleGpuBars to -1 if the resize is "
                "what this machine needs.",
                "ocengine/config_prodigy.py:570-571 and :691"))
    return findings


def _resize_gpu_bars(document: dict):
    booter = document.get("Booter")
    quirks = booter.get("Quirks") if isinstance(booter, dict) else None
    if not isinstance(quirks, dict):
        return None
    value = quirks.get("ResizeAppleGpuBars")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _skipped(target) -> tuple[str, ...]:
    if target:
        return ()
    return ("No macOS release was selected, so the version-window and Lilu beta checks "
            "were not run.",)


def advise(document, target=None) -> Report:
    """Return every advisory for ``document``, without changing it.

    ``target`` is a Darwin version string such as ``"23.99.99"``; without it the two
    rules that need a release are reported as skipped rather than guessed.
    """
    if not isinstance(document, dict):
        raise AdvisorError("The config is not a dictionary of keys.")
    findings: list[Advisory] = []
    findings.extend(_order_and_dependency(document))
    findings.extend(_conflicts(document))
    findings.extend(_duplicate_paths(document))
    findings.extend(_driver_findings(document, target))
    windowed = _window_findings(document, target)
    findings.extend(windowed)
    findings.extend(_boot_arg_findings(
        document, target,
        {item.path[2] for item in windowed if len(item.path) > 2}))
    findings.extend(_quirk_findings(document))
    ordered = sorted(findings, key=lambda item: (
        _SEVERITY_ORDER.get(item.severity, 9), -_CONFIDENCE_ORDER.get(item.confidence, 0),
        item.where.casefold()))
    return Report(advisories=tuple(ordered), skipped=_skipped(target),
                  entries=len(_kernel_entries(document)), rules=RULESET)


def to_text(report: Report) -> str:
    """The export a tester can attach. It states the boundary the dialog states."""
    lines = [
        "BlackDream dependency advisory",
        "Ruleset: {}".format(report.rules),
        "Kernel/Add entries: {}".format(report.entries),
        "Result: {}".format(report.summary),
        "",
        BOUNDARY,
        "",
    ]
    for note in report.skipped:
        lines.append("Not checked: {}".format(note))
        lines.append("")
    if not report.advisories:
        lines.append("No advisories.")
    for item in report.advisories:
        lines.extend((
            "[{}] {}".format(item.severity.upper(), item.where),
            "  {}".format(item.trigger),
            "  Evidence: {}".format(item.evidence),
            "  Confidence: {}".format(item.confidence),
            "  Next: {}".format(item.advice),
            "  Rule: {} ({})".format(item.rule, item.source),
        ))
    return "\n".join(lines).rstrip() + "\n"


def default_dismissal_path() -> Path:
    return paths.current().state_dir / "advisor-dismissals.json"


def load_dismissals(path=None) -> frozenset:
    """The dismissed advisory keys. Absent or corrupt reads as nothing dismissed.

    A record from an older ruleset is dropped rather than honoured, because a key that
    no longer means the same thing must not keep an advisory hidden forever.
    """
    target = Path(path) if path is not None else default_dismissal_path()
    document = state_store.read_json(target)
    if not isinstance(document, dict) or document.get("ruleset") != RULESET:
        return frozenset()
    keys = document.get("dismissed")
    if not isinstance(keys, list):
        return frozenset()
    return frozenset(key for key in keys if isinstance(key, str))


def dismissed(advisory: Advisory, keys) -> bool:
    return advisory.dismissal_key in set(keys)


def visible(report: Report, keys) -> tuple[Advisory, ...]:
    """The advisories a reader should see: everything not dismissed."""
    kept = set(keys)
    return tuple(item for item in report.advisories if not dismissed(item, kept))


def dismiss(keys, advisory: Advisory) -> frozenset:
    """Add one key. The caller decides when the record is written."""
    return frozenset(set(keys) | {advisory.dismissal_key})


def restore(keys, advisory: Advisory) -> frozenset:
    return frozenset(set(keys) - {advisory.dismissal_key})


def save_dismissals(keys, path=None) -> Path:
    """Write the dismissal record sorted, so the file has one stable form."""
    target = Path(path) if path is not None else default_dismissal_path()
    document = {"ruleset": RULESET, "dismissed": sorted(set(keys))}
    state_store.atomic_write_text(target, json.dumps(document, indent=2) + "\n")
    return target
