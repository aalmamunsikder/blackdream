"""Kernel extension selection: hardware report + macOS version -> checked kexts.

Upstream drove this module from a terminal: it cleared the screen, printed a
numbered list, and blocked on a terminal read four times inside what is
otherwise a deterministic rules pass. Terminal I/O is gone here. Each former
prompt is now a pure ``plan_*()`` function that returns a ``KextChoice`` (the
candidates, a deterministic default, and the explanatory note as plain text)
and ``apply_kext_choice()`` records the user's answer. ``select_required_kexts()``
uses the recorded answer when there is one and the default otherwise, so a headless
run produces exactly what the terminal produced when the user just pressed Enter.

Intended GUI flow:

    maestro = KextMaestro()
    needs_oclp = maestro.select_required_kexts(report, version, needs_oclp, patches)
    for choice in maestro.get_kext_choice_plans():      # what the terminal asked
        answer = ask_the_user(choice)                   # or leave the default
        maestro.apply_kext_choice(choice.key, answer)
    needs_oclp = maestro.select_required_kexts(...)     # re-run, now with answers

The Wi-Fi password recovery step that used to hide inside the build path is the
explicit ``needs_wifi_profiles()`` / ``apply_wifi_profiles()`` pair: the caller
collects the profiles and hands them in as an argument, so building never blocks
and a failed injection is reported instead of silently producing a broken EFI.
"""

from ocengine.datasets import cpu_data
from ocengine.datasets import gpu_data
from ocengine.datasets import kext_data
from ocengine.datasets import os_data
from ocengine.datasets import pci_data
from ocengine.datasets import codec_layouts
from ocengine import paths
from ocengine import utils
from ocengine.fatal import EngineError
import copy
import os
import shutil
from dataclasses import dataclass


# Keys for the former blocking-prompt gates. The GUI passes these to
# apply_kext_choice(); they are stable across runs.
KEXT_CHOICE_AUDIO = "audio_tahoe"
KEXT_CHOICE_AMD_GPU = "amd_gpu"
KEXT_CHOICE_INTEL_WIFI = "intel_wifi"
KEXT_CHOICE_FORCE_LOAD = "force_load"

# The menu markers, as data. The UI renders these; the engine never emits
# preformatted colored lines.
KEXT_STATUS_MARKERS = {
    "required": "[R]",
    "selected": "[*]",
    "force_loaded": "[!]",
    "available": "[ ]",
    "force_available": "[?]",
    "not_needed": "[-]",
    "requires_newer": "[-]",
}

KEXT_STATUS_LEGEND = (
    "[R] Required",
    "[*] Selected",
    "[!] Force loaded",
    "[ ] Available",
    "[?] Force available",
    "[-] Unavailable",
)

KEXT_SELECTION_HINTS = (
    "When a plugin of a kext is selected, the entire kext will be automatically selected.",
    "You can select multiple kexts by entering their indices separated by commas (e.g., '1, 2, 3').",
)


class KextInstallIncomplete(EngineError):
    """A selected kext has no bundle in the EFI, or its bundle cannot be read.

    Upstream skipped a missing bundle and swallowed copy errors, so the build
    reported success while config.plist silently listed fewer kexts than the
    user selected. That produces an EFI that boots and then misbehaves, which is
    worse than a build failure the user can retry.
    """

    code = "kext.install_incomplete"
    title = "The EFI is missing selected kernel extensions"
    remediation = (
        "Run the download stage again so every selected kext lands in the cache.",
        "If the download stage reported success, the cached bundle is damaged; "
        "remove that product from the cache and download it again.",
    )


@dataclass(frozen=True)
class KextOption:
    """One answer to a former prompt, plus every kext and flag it implies."""

    index: int
    name: str
    label: str
    detail: str = ""
    kexts: tuple = ()
    needs_oclp: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class KextChoice:
    """A former blocking prompt, expressed as data.

    ``default_index`` is what the terminal used on empty input. ``forced`` means
    only one answer is legal for this machine, so there is nothing to ask.
    ``acknowledge_only`` reproduces the incompatibility gate, which printed a
    warning, waited for Enter, and then selected nothing for that device.
    """

    key: str
    title: str
    question: str
    note: str = ""
    options: tuple = ()
    default_index: int = 1
    device: str = ""
    forced: bool = False
    acknowledge_only: bool = False

    @property
    def default(self):
        return self.option(self.default_index)

    def option(self, index):
        for option in self.options:
            if option.index == index:
                return option
        return None

    def describe(self):
        """The full plain-text block the terminal used to draw."""
        lines = [self.note] if self.note else []
        for option in self.options:
            head = "{}. {}".format(option.index, option.label)
            lines.append("{} - {}".format(head, option.detail) if option.detail else head)
        return "\n".join(line for line in lines if line)


class KextMaestro:
    def __init__(self):
        self.utils = utils.Utils()
        self.matching_keys = [
            "IOPCIMatch", 
            "IONameMatch", 
            "IOPCIPrimaryMatch", 
            "idProduct", 
            "idVendor", 
            "HDAConfigDefault"
        ]
        self.ock_files_dir = str(paths.current().cache_dir)
        # Per-session copy: `checked` is written on these objects, and sharing the
        # dataset list would leak one build's selections into the next. Order is
        # preserved, so kext_data.kext_index_by_name's indices stay valid here.
        self.kexts = copy.deepcopy(kext_data.kexts)
        self.kext_choices = {}
        self._kext_choice_plans = {}
        #: The display GPU this selection handed to the NullMoth driver, if any. The
        #: driver itself is installed on the target, so the name is the only record
        #: that the build owes the user a hand-off file.
        self.nullmoth_gpu = None

    # ---- former prompts: pure plans --------------------------------------

    def plan_audio_kext_choice(self):
        """How to restore AppleHDA on macOS Tahoe (was a blocked 1/2 prompt).

        Upstream looped until the user typed 1 or 2, so empty input had no
        default at all. Option 2 is used: it delivers working audio from the EFI
        alone, whereas option 1 also flips ``needs_oclp`` and changes the rest of
        the build (OCLP download flow, AMFIPass, RestrictEvents) for audio.
        """
        return KextChoice(
            key=KEXT_CHOICE_AUDIO,
            title="Audio Restoration Method",
            question="Select audio kext for your system",
            note="Note: macOS Tahoe no longer includes AppleHDA. AppleALC needs one of these restoration methods.",
            options=(
                KextOption(
                    index=1,
                    name="AppleALC + OCLP",
                    label="AppleALC + OCLP",
                    detail="Restores AppleHDA with a system root patch",
                    kexts=("AppleALC",),
                    needs_oclp=True,
                ),
                KextOption(
                    index=2,
                    name="AppleALC + SimpleHDA",
                    label="AppleALC + SimpleHDA",
                    detail="OpenCore injection without audio root patches",
                    kexts=("AppleALC", "SimpleHDA"),
                ),
            ),
            default_index=2,
        )

    def plan_amd_gpu_kext_choice(self, gpu_name, gpu_props, hardware_report):
        """NootRX versus WhateverGreen on an AMD Navi 21/23 (was a 1/2 prompt).

        Default 2 (WhateverGreen) reproduces ``recommended_option = 2`` combined
        with the ``or str(recommended_option)`` empty-input fallback. With an
        Intel GPU present, NootRX is blocked; upstream printed the incompatibility
        warning, waited for Enter, and then selected nothing for that discrete
        GPU (WhateverGreen came from the Intel iGPU entry), which is preserved as
        ``acknowledge_only``.
        """
        codename = gpu_props.get("Codename")
        intel_gpu_present = any(
            other_gpu_props.get("Manufacturer") == "Intel"
            for other_gpu_props in hardware_report.get("GPU", {}).values()
        )

        note_lines = [
            "*** Found {} is AMD {} GPU.".format(gpu_name, codename),
            "",
            "Important: Black Screen Fix",
            "If you experience a black screen after verbose mode:",
            "    1. Use ProperTree to open config.plist",
            "    2. Navigate to NVRAM -> Add -> 7C436110-AB2A-4BBB-A880-FE41995C9F82 -> boot-args",
            "    3. Remove \"-v debug=0x100 keepsyms=1\" from boot-args",
            "",
            "Note:",
            "- AMD {} GPUs have two available kext options:".format(codename),
            "- You can try different kexts after installation to find the best one for your system",
        ]

        if intel_gpu_present:
            note_lines.extend((
                "",
                "Important: NootRX kext is not compatible with Intel GPUs",
                "Automatically selecting WhateverGreen kext due to Intel GPU compatibility",
            ))

        return KextChoice(
            key=KEXT_CHOICE_AMD_GPU,
            title="AMD GPU Kernel Extension Selection",
            question="Select kext for your AMD {} GPU (default: WhateverGreen)".format(codename),
            note="\n".join(note_lines),
            options=(
                KextOption(
                    index=1,
                    name="NootRX",
                    label="NootRX",
                    detail="Uses latest GPU firmware",
                    kexts=("NootRX",),
                    enabled=not intel_gpu_present,
                ),
                KextOption(
                    index=2,
                    name="WhateverGreen",
                    label="WhateverGreen",
                    detail="Uses original Apple firmware",
                    kexts=("WhateverGreen",),
                ),
            ),
            default_index=2,
            device=gpu_name,
            acknowledge_only=intel_gpu_present,
        )

    def plan_intel_wifi_kext_choice(self, network_name, macos_version):
        """Which itlwm-family kext drives an Intel WiFi card (was a 1/2/3 prompt).

        Candidate order and the recommended index follow upstream exactly: the
        laobamac fork is offered first only when compatible with the target
        macOS, and the default is
        ``1 if native_fork_available or darwin_major < 23 else 2``, which is what
        empty input produced through ``or str(recommended_option)``. On an
        unsupported macOS Beta without that fork, upstream selected itlwm without
        asking at all, so the choice comes back ``forced``.
        """
        darwin_major = self.utils.parse_darwin_version(macos_version)[0]
        native_fork_available = self.is_kext_compatible(self.kexts[kext_data.kext_index_by_name["AirportItlwm-laobamac"]], macos_version)
        beta_without_native_fork = "Beta" in os_data.get_macos_name_by_darwin(macos_version) and not native_fork_available

        airport_kexts = ("AirportItlwm",)
        airport_needs_oclp = False
        if darwin_major >= 24:
            airport_kexts = ("AirportItlwm", "IOSkywalkFamily")
            airport_needs_oclp = True
            if darwin_major >= 25:
                airport_kexts = airport_kexts + ("AirPortBrcmNIC-Tahoe",)

        airport_detail = (
            "Uses native WiFi settings menu\n"
            "   - Provides Handoff, Universal Clipboard, Location Services, Instant Hotspot support\n"
            "   - Supports enterprise-level security"
        )
        if darwin_major >= 24:
            airport_detail += "\n   - Requires OCLP root patches on Sequoia and Tahoe but may cause issues"

        options = []

        if native_fork_available:
            options.append(KextOption(
                index=1,
                name="AirportItlwm-laobamac",
                label="laobamac AirportItlwm",
                detail="Native WiFi on Sequoia 15.2+ and Tahoe without OCLP root patches",
                kexts=("AirportItlwm-laobamac",),
            ))

        options.append(KextOption(
            index=len(options) + 1,
            name="AirportItlwm",
            label="AirportItlwm",
            detail=airport_detail,
            kexts=airport_kexts,
            needs_oclp=airport_needs_oclp,
        ))

        options.append(KextOption(
            index=len(options) + 1,
            name="itlwm",
            label="itlwm",
            detail=(
                "More stable overall\n"
                "   - Works with HeliPort app instead of native WiFi settings menu\n"
                "   - No Apple Continuity features and enterprise-level security\n"
                "   - Can connect to Hidden Networks"
            ),
            kexts=("itlwm",),
        ))

        options = tuple(options)
        itlwm_option = options[-1]

        note_lines = [
            "*** Found {} is Intel WiFi device.".format(network_name),
            "",
            "Note: Intel WiFi devices have {} available kext options:".format(len(options)),
        ]

        if beta_without_native_fork:
            note_lines.append("For unsupported macOS Beta versions, only itlwm is supported.")
            return KextChoice(
                key=KEXT_CHOICE_INTEL_WIFI,
                title="Intel WiFi Kernel Extension Selection",
                question="Select Intel Wi-Fi kext",
                note="\n".join(note_lines),
                options=(itlwm_option,),
                default_index=itlwm_option.index,
                device=network_name,
                forced=True,
            )

        default_index = 1 if native_fork_available or darwin_major < 23 else 2

        return KextChoice(
            key=KEXT_CHOICE_INTEL_WIFI,
            title="Intel WiFi Kernel Extension Selection",
            question="Select Intel Wi-Fi kext (default: {})".format(options[default_index - 1].label),
            note="\n".join(note_lines),
            options=options,
            default_index=default_index,
            device=network_name,
        )

    def plan_kext_force_load_choice(self, incompatible_kexts, target_darwin_version):
        """Force-load kexts the target macOS does not support (was a yes/No gate).

        ``(yes/No)`` marked No as the default, so empty input maps to option 2.
        ``kexts`` on the yes option carries the names, which is what
        ``verify_kext_compatibility`` returns as the force-load set.
        """
        listing = "\n".join(
            "{:2}. {:25}{}".format(index, kext_name, " - Lilu Plugin" if is_lilu_dependent else "")
            for index, (kext_name, is_lilu_dependent) in enumerate(incompatible_kexts, start=1)
        )

        note = (
            "Incompatible kexts for the current macOS version ({}):\n{}\n\n"
            "Note:\n"
            "- With Lilu plugins, using the \"-lilubetaall\" boot argument will force them to load.\n"
            "- Forcing unsupported kexts can cause system instability. Proceed with caution."
        ).format(target_darwin_version, listing)

        kext_names = tuple(kext_name for kext_name, _ in incompatible_kexts)

        return KextChoice(
            key=KEXT_CHOICE_FORCE_LOAD,
            title="Kext Compatibility Check",
            question="Do you want to force load {} on the unsupported macOS version?".format(
                "these kexts" if len(incompatible_kexts) > 1 else "this kext"
            ),
            note=note,
            options=(
                KextOption(index=1, name="yes", label="Yes", detail="Force load", kexts=kext_names),
                KextOption(index=2, name="no", label="No", detail="Leave them unloaded", kexts=()),
            ),
            default_index=2,
        )

    # ---- former prompts: apply steps a GUI can call ------------------------

    def apply_kext_choice(self, key, option_index):
        """Record the user's answer for a former prompt.

        ``option_index`` is the 1-based number a ``plan_*()`` choice advertised.
        Unknown keys and out-of-range answers are logged and ignored at build
        time by ``resolve_kext_choice()``, which falls back to the default, so a
        stale answer can never drive the selection into a silent wrong state.
        """
        try:
            index = int(option_index)
        except (TypeError, ValueError):
            self.utils.log_message("Invalid selection for {}, using recommended option.".format(key), level="warning")
            return False

        self.kext_choices[key] = index
        return True

    def clear_kext_choices(self):
        """Drop recorded answers so every choice falls back to its default."""
        self.kext_choices.clear()
        return True

    def resolve_kext_choice(self, choice):
        """The option this run uses: the recorded answer, else the default."""
        self._kext_choice_plans[choice.key] = choice

        if choice.forced:
            return choice.default

        index = self.kext_choices.get(choice.key, choice.default_index)
        option = choice.option(index)

        if option is None or not option.enabled:
            self.utils.log_message(
                "Invalid selection, using recommended option: {} ({})".format(choice.default_index, choice.default.label),
                level="warning",
            )
            return choice.default

        return option

    def get_kext_choice_plans(self):
        """Every choice this process has presented, in first-seen order."""
        return list(self._kext_choice_plans.values())

    def get_kext_choice_plan(self, key):
        return self._kext_choice_plans.get(key)

    def log_kext_choice(self, choice, option):
        """Emit the explanatory note the terminal printed before the prompt."""
        self.utils.log_message(choice.describe(), level="info")
        self.utils.log_message("Selected: {} (option {})".format(option.label, option.index), level="info")

    # ---- kext state model, as data ---------------------------------------

    def kext_rows(self, macos_version):
        """The kext list the terminal menu drew, as rows for the UI to render.

        Status is a string from ``get_kext_status()`` plus its marker; color and
        column layout were dropped because they were terminal presentation.
        """
        rows = []
        current_category = None

        for index, kext in enumerate(self.kexts):
            category = kext.category if kext.category else "Uncategorized"
            category_starts = category != current_category
            current_category = category
            status = self.get_kext_status(kext, macos_version)

            rows.append({
                "index": index,
                "display_index": index + 1,
                "name": kext.name,
                "description": kext.description,
                "category": category,
                "category_starts": category_starts,
                "status": status,
                "marker": KEXT_STATUS_MARKERS[status],
                "checked": kext.checked,
                "required": kext.required,
                "allow_force_load": kext.allow_force_load,
                "min_darwin_version": kext.min_darwin_version,
                "max_darwin_version": kext.max_darwin_version,
            })

        return rows

    @staticmethod
    def parse_kext_indices(option_text):
        """Comma-separated 1-based menu indices -> 0-based indices.

        Out-of-range values survive here; ``toggle_kexts_by_index()`` drops them,
        exactly as the menu's own bounds check did.
        """
        indices = [int(item.strip()) - 1 for item in str(option_text).split(",") if item.strip().isdigit()]

        return indices

    def kext_configuration_menu(self, macos_version):
        """Former multi-select screen; the interactive loop is gone.

        The name is kept for the orchestrator. It now returns the rows the menu
        drew, because the UI owns redraw, selection parsing (see
        ``parse_kext_indices``), Back, and Quit. Quit was the only place the
        engine terminated the process; a GUI cannot quit the session from here.
        """
        self.utils.head("Configure Kernel Extensions")
        self.utils.log_message("List of available kexts:", level="info")
        self.utils.log_message(
            "Status: " + ", ".join(KEXT_STATUS_LEGEND) + ". " + " ".join(KEXT_SELECTION_HINTS),
            level="info",
        )

        return self.kext_rows(macos_version)

    def toggle_kexts_by_index(self, indices, macos_version):
        """Apply step for the former menu: toggle indices, return status lines.

        ``indices`` are 0-based positions in ``self.kexts`` -- exactly the set
        ``parse_kext_indices()`` produced from the old '1, 2, 3' input. The
        returned messages are the plain-text feedback the menu printed after the
        redraw, so the UI can show them as-is.
        """
        messages = []
        indices = [index for index in indices if index is not None and 0 <= index < len(self.kexts)]

        kexts_to_enable = [self.kexts[index].name for index in indices if not self.kexts[index].checked]
        force_load_kexts = self.verify_kext_compatibility(kexts_to_enable, macos_version)

        for index in indices:
            kext = self.kexts[index]
            if kext.checked and not kext.required:
                checked_dependents = [other_kext.name for other_kext in self.kexts if other_kext.checked and kext.name in other_kext.requires_kexts]
                self.uncheck_kext(index)
                if checked_dependents:
                    messages.append("{} and dependent kext{} {} disabled.".format(kext.name, "s" if len(checked_dependents) > 1 else "", ", ".join(checked_dependents)))
            else:
                status = self.get_kext_status(kext, macos_version)
                if status == "not_needed":
                    messages.append("{} is not needed on {}.".format(kext.name, os_data.get_macos_name_by_darwin(macos_version)))
                    continue
                if status == "requires_newer":
                    messages.append("{} requires a newer macOS version.".format(kext.name))
                    continue

                conflicts = [other_kext.name for other_kext in self.kexts if other_kext.checked and kext.conflict_group_id and other_kext.conflict_group_id == kext.conflict_group_id and other_kext.name != kext.name]
                if self.check_kext(index, macos_version, kext.name in force_load_kexts):
                    if conflicts:
                        messages.append("{} selected; mutually exclusive kext{} disabled: {}.".format(kext.name, "s" if len(conflicts) > 1 else "", ", ".join(conflicts)))
                else:
                    messages.append("{} could not be selected because a required dependency is unavailable.".format(kext.name))

        for message in messages:
            self.utils.log_message(message, level="info")

        return messages

    # ---- detection helpers -------------------------------------------------

    def extract_pci_id(self, kext_path):
        if not os.path.exists(kext_path):
            return []

        plist_path = os.path.join(kext_path, "Contents", "Info.plist")
        plist_data = self.utils.read_file(plist_path)

        pci_ids = []

        for personality_name, properties in plist_data.get("IOKitPersonalities", {}).items():
            matching_keys = [key for key in self.matching_keys if key in properties]
            
            if not matching_keys:
                continue
            
            match_key = matching_keys[0]

            if match_key in ["IOPCIMatch", "IOPCIPrimaryMatch"]:
                pci_list = properties[match_key].split(" ")
                for pci_id in pci_list:
                    vendor_id = pci_id[-4:]
                    device_id = pci_id[2:6]
                    pci_ids.append("{}-{}".format(vendor_id, device_id).upper())
            elif match_key == "IONameMatch":
                for pci_id in properties[match_key]:
                    vendor_id = pci_id[3:7]
                    device_id = pci_id.split(",")[1].zfill(4)
                    pci_ids.append("{}-{}".format(vendor_id, device_id).upper())
            elif match_key == "idProduct":
                vendor_id = self.utils.int_to_hex(properties["idVendor"]).zfill(4)
                device_id = self.utils.int_to_hex(properties["idProduct"]).zfill(4)
                pci_ids.append("{}-{}".format(vendor_id, device_id).upper())
            elif match_key == "HDAConfigDefault":
                for codec_layout in properties[match_key]:
                    codec_id = self.utils.int_to_hex(codec_layout.get("CodecID")).zfill(8)
                    pci_ids.append("{}-{}".format(codec_id[:4], codec_id[-4:]))
                pci_ids = sorted(list(set(pci_ids)))

        return pci_ids

    def is_intel_hedt_cpu(self, processor_name, cpu_codename):
        if cpu_codename in cpu_data.IntelCPUGenerations[45:66]:
            return cpu_codename.endswith(("-X", "-P", "-W", "-E", "-EP", "-EX"))
        
        if cpu_codename in cpu_data.IntelCPUGenerations[66:]:
            return "Xeon" in processor_name
        
        return False

    def is_kext_compatible(self, kext, target_darwin_version):
        return self.utils.parse_darwin_version(kext.min_darwin_version) <= self.utils.parse_darwin_version(target_darwin_version) <= self.utils.parse_darwin_version(kext.max_darwin_version)

    def get_kext_status(self, kext, target_darwin_version):
        if kext.required:
            return "required"

        if self.is_kext_compatible(kext, target_darwin_version):
            return "selected" if kext.checked else "available"

        if kext.checked:
            return "force_loaded"

        if kext.allow_force_load:
            return "force_available"

        if self.utils.parse_darwin_version(target_darwin_version) > self.utils.parse_darwin_version(kext.max_darwin_version):
            return "not_needed"

        return "requires_newer"

    def check_kext(self, index, target_darwin_version, force_load=False, checking=None):
        if index is None or not 0 <= index < len(self.kexts):
            return False

        kext = self.kexts[index]
        checking = checking or set()

        if kext.checked:
            return True

        if index in checking:
            return True

        if not self.is_kext_compatible(kext, target_darwin_version) and not (force_load and kext.allow_force_load):
            return False

        checking.add(index)
        for requires_kext_name in kext.requires_kexts:
            requires_kext_index = kext_data.kext_index_by_name.get(requires_kext_name)
            if not self.check_kext(requires_kext_index, target_darwin_version, force_load, checking):
                checking.remove(index)
                return False
        checking.remove(index)

        kext.checked = True

        if kext.conflict_group_id:
            for other_index, other_kext in enumerate(self.kexts):
                if other_kext.conflict_group_id == kext.conflict_group_id and other_kext.name != kext.name:
                    self.uncheck_kext(other_index)

        return True

    def select_required_kexts(self, hardware_report, macos_version, needs_oclp, acpi_patches):
        self.utils.head("Select Required Kernel Extensions")
        self.utils.log_message("Checking for required kernel extensions...", level="info")

        for kext in self.kexts:
            kext.checked = kext.required

        selected_kexts = ["UTBDefault"]

        # NullMoth keeps its kexts in /Library and loads them from the AuxKC, so the
        # EFI only carries their Lilu/AMFIPass prerequisites. A GPU the checker
        # nullified (an internal panel on another card) is not a display path and
        # must not pull those in.
        self.nullmoth_gpu = next((
            gpu_name for gpu_name, gpu_props in hardware_report.get("GPU", {}).items()
            if gpu_props.get("NullMoth")
            and gpu_props.get("Compatibility") != (None, None)
        ), None)

        # WhateverXe replaces WhateverGreen outright on the iGPUs it supports; the
        # project states the two must never be enabled together, mixed GPUs included.
        whateverxe_gpu = next((
            gpu_name for gpu_name, gpu_props in hardware_report.get("GPU", {}).items()
            if gpu_props.get("WhateverXe") or (
                gpu_props.get("Manufacturer") == "Intel"
                and gpu_props.get("Device Type") == "Integrated GPU"
                and gpu_data.is_whateverxe_device_id(gpu_props.get("Device ID")))
        ), None)

        # NootRX and WhateverXe share the one graphics slot the dependency table
        # allows. On a machine that also has a Navi 22 card the card is the display
        # GPU, so NootRX keeps the slot and the Xe iGPU falls back to the native
        # driver -- exactly what the engine did before WhateverXe existed. Decide
        # that here, because once the Mod AMFIPass build is appended it would
        # survive the conflict check alone.
        if whateverxe_gpu:
            navi22_gpu = next((
                gpu_name for gpu_name, gpu_props in hardware_report.get("GPU", {}).items()
                if "Integrated GPU" not in gpu_props.get("Device Type")
                and "Navi 22" in (gpu_props.get("Codename") or "")
            ), None)
            if navi22_gpu:
                self.utils.log_message(
                    "WhateverXe is not selected because NootRX keeps the graphics stack "
                    "for the {}; the {} is left to the native driver.".format(
                        navi22_gpu, whateverxe_gpu),
                    level="warning")
                whateverxe_gpu = None

        if whateverxe_gpu and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version(gpu_data.WHATEVERXE_MIN_DARWIN):
            selected_kexts.extend(("WhateverXe", "AMFIPass-Mod"))

        if self.nullmoth_gpu and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version(gpu_data.NULLMOTH_MIN_DARWIN):
            # Upstream AMFIPass, not the Mod build: NullMoth's README asks for the
            # release build, and one EFI can only carry one AMFIPass identifier.
            if not whateverxe_gpu:
                selected_kexts.append("AMFIPass")
            self.utils.log_message(
                "{} is handed to the NullMoth NVIDIA driver; its kexts are installed "
                "on the target and load from the AuxKC, not from this EFI.".format(
                    self.nullmoth_gpu))
        else:
            self.nullmoth_gpu = None

        if "Intel" in hardware_report.get("CPU").get("Manufacturer"):
            selected_kexts.extend(("SMCProcessor", "SMCSuperIO"))

        if "Laptop" in hardware_report.get("Motherboard").get("Platform") and not "SURFACE" in hardware_report.get("Motherboard").get("Name"):
            selected_kexts.append("SMCBatteryManager")
            if "DELL" in hardware_report.get("Motherboard").get("Name"):
                selected_kexts.append("SMCDellSensors")
            selected_kexts.append("SMCLightSensor")

        if  not (" Core" in hardware_report.get("CPU").get("Processor Name") and \
                 hardware_report.get("CPU").get("Codename") in cpu_data.IntelCPUGenerations[28:]) or \
            self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("23.0.0"):
            selected_kexts.append("RestrictEvents")

        if any(codec_properties.get("Device ID") in codec_layouts.data for codec_properties in hardware_report.get("Sound", {}).values()):
            if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("25.0.0"):
                audio_choice = self.plan_audio_kext_choice()
                audio_option = self.resolve_kext_choice(audio_choice)
                self.log_kext_choice(audio_choice, audio_option)
                selected_kexts.extend(audio_option.kexts)
                needs_oclp = needs_oclp or audio_option.needs_oclp
            else:
                selected_kexts.append("AppleALC")
        
        if "AMD" in hardware_report.get("CPU").get("Manufacturer") and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("21.4.0") or \
            int(hardware_report.get("CPU").get("CPU Count")) > 1 and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("19.0.0") or \
            hardware_report.get("CPU").get("Codename") in cpu_data.IntelCPUGenerations[:4]:
            selected_kexts.append("AppleMCEReporterDisabler")

        if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("22.0.0") and not "AVX2" in hardware_report.get("CPU").get("SIMD Features"):
            selected_kexts.append("CryptexFixup")

        if  "Lunar Lake" not in hardware_report.get("CPU").get("Codename") and \
            "Meteor Lake" not in hardware_report.get("CPU").get("Codename") and \
            hardware_report.get("CPU").get("Codename") in cpu_data.IntelCPUGenerations[:20] and \
            int(hardware_report.get("CPU").get("Core Count")) > 6:
            selected_kexts.append("CpuTopologyRebuild")

        for gpu_name, gpu_props in hardware_report.get("GPU", {}).items():
            if "Integrated GPU" in gpu_props.get("Device Type"):
                if "AMD" in gpu_props.get("Manufacturer"):
                    selected_kexts.append("NootedRed")
                elif gpu_name == whateverxe_gpu:
                    # Selected above, before any device could pull in WhateverGreen.
                    pass
                else:
                    selected_kexts.append("WhateverGreen")
            else:
                if gpu_props.get("NullMoth"):
                    # WhateverGreen is not this card's driver; NullMoth supplies it
                    # from /Library. Do not write a kext that cannot help it.
                    continue

                if "Navi 22" in gpu_props.get("Codename"):
                    selected_kexts.append("NootRX")
                    break

                if whateverxe_gpu:
                    # WhateverGreen is the engine's only patch for these cards, and it
                    # cannot be loaded beside WhateverXe. Say so instead of writing a
                    # pair the project forbids.
                    self.utils.log_message(
                        "WhateverGreen is not selected because WhateverXe replaces it; "
                        "the {} is left to the native driver.".format(gpu_name),
                        level="warning")
                    continue

                if gpu_props.get("Codename") in {"Navi 21", "Navi 23"}:
                    gpu_choice = self.plan_amd_gpu_kext_choice(gpu_name, gpu_props, hardware_report)

                    if gpu_choice.acknowledge_only:
                        self._kext_choice_plans[gpu_choice.key] = gpu_choice
                        self.utils.log_message(gpu_choice.describe(), level="warning")
                        self.utils.notify(
                            "NootRX is not compatible with Intel GPUs",
                            "The AMD {} GPU is left to WhateverGreen, which comes from the Intel graphics entry.".format(gpu_props.get("Codename")),
                            level="warning",
                        )
                        continue

                    gpu_option = self.resolve_kext_choice(gpu_choice)
                    self.log_kext_choice(gpu_choice, gpu_option)
                    selected_kexts.extend(gpu_option.kexts)
                    continue

                selected_kexts.append("WhateverGreen")

        if "Laptop" in hardware_report.get("Motherboard").get("Platform") and ("ASUS" in hardware_report.get("Motherboard").get("Name") or "NootedRed" in selected_kexts):
            selected_kexts.append("ForgedInvariant")

        if self.is_intel_hedt_cpu(hardware_report.get("CPU").get("Processor Name"), hardware_report.get("CPU").get("Codename")):
            selected_kexts.append("CpuTscSync")

        for network_name, network_props in hardware_report.get("Network", {}).items():
            device_id = network_props.get("Device ID")

            if device_id in pci_data.BroadcomWiFiIDs and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("23.0.0"):
                selected_kexts.append("IOSkywalkFamily")
                if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("25.0.0"):
                    selected_kexts.append("AirPortBrcmNIC-Tahoe")

            if device_id in pci_data.BroadcomWiFiIDs[:15]:
                selected_kexts.append("AirportBrcmFixup")
            elif device_id == pci_data.BroadcomWiFiIDs[15] and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("19.0.0"):
                selected_kexts.append("AirportBrcmFixup")
            elif device_id in pci_data.BroadcomWiFiIDs[16:18] and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("20.0.0"):
                selected_kexts.append("AirportBrcmFixup")
            elif device_id in pci_data.IntelWiFiIDs:
                wifi_choice = self.plan_intel_wifi_kext_choice(network_name, macos_version)
                wifi_option = self.resolve_kext_choice(wifi_choice)
                self.log_kext_choice(wifi_choice, wifi_option)
                selected_kexts.extend(wifi_option.kexts)
                needs_oclp = needs_oclp or wifi_option.needs_oclp
            elif device_id in pci_data.AtherosWiFiIDs[:8]:
                selected_kexts.append("corecaptureElCap")
                if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("25.0.0"):
                    selected_kexts.append("AirPortAtheros40-Tahoe")
                if self.utils.parse_darwin_version(macos_version) > self.utils.parse_darwin_version("20.99.99"):
                    selected_kexts.append("AMFIPass")
            elif device_id in pci_data.rtw88WiFiIDs:
                selected_kexts.append("Feixiao")
            elif device_id in pci_data.IntelI22XIDs:
                selected_kexts.append("AppleIGC")
            elif device_id in pci_data.AtherosE2200IDs:
                selected_kexts.append("AtherosE2200Ethernet")
            elif device_id in pci_data.IntelMausiIDs:
                selected_kexts.append("IntelMausiEthernet")
            elif device_id in pci_data.RealtekRTL8100IDs:
                selected_kexts.append("RealtekRTL8100")
            elif device_id in pci_data.RealtekRTL8111IDs:
                selected_kexts.append("RealtekRTL8111")
            elif device_id in pci_data.AppleIGBIDs:
                selected_kexts.append("AppleIGB")
            elif device_id in pci_data.BroadcomBCM57XXIDs:
                selected_kexts.append("CatalinaBCM5701Ethernet")
            elif device_id in pci_data.IntelX500IDs:
                selected_kexts.append("IntelLucy")
            elif device_id in pci_data.RealtekRTL812xIDs:
                selected_kexts.append("RTL812xLucy")

        if all(network_props.get("Bus Type") == "USB" for network_props in hardware_report.get("Network", {}).values()):
            selected_kexts.append("NullEthernet")

        for bluetooth_name, bluetooth_props in hardware_report.get("Bluetooth", {}).items():
            usb_id = bluetooth_props.get("Device ID")

            if usb_id in pci_data.AtherosBluetoothIDs:
                selected_kexts.extend(("Ath3kBT", "Ath3kBTInjector"))
            elif usb_id in pci_data.BroadcomBluetoothIDs:               
                selected_kexts.extend(("BrcmFirmwareData", "BrcmPatchRAM2", "BrcmPatchRAM3", "BrcmBluetoothInjector", "BlueToolFixup"))
            elif usb_id in pci_data.IntelBluetoothIDs:
                selected_kexts.extend(("IntelBluetoothFirmware", "IntelBTPatcher", "IntelBluetoothInjector", "BlueToolFixup"))
            elif usb_id in pci_data.RealtekBluetoothIDs:
                selected_kexts.extend(("RealtekBluetoothFirmware", "BlueToolFixup"))
            elif usb_id in pci_data.BluetoothIDs[-1]:
                selected_kexts.append("BlueToolFixup")

        if "Laptop" in hardware_report.get("Motherboard").get("Platform"):
            if "SURFACE" in hardware_report.get("Motherboard").get("Name"):
                selected_kexts.append("BigSurface")
            else:
                if "ASUS" in hardware_report.get("Motherboard").get("Name"):
                    selected_kexts.append("AsusSMC")
                selected_kexts.append("BrightnessKeys")

                for device_name, device_props in hardware_report.get("Input").items():
                    if not device_props.get("Device"):
                        continue

                    device_id = device_props.get("Device")
                    idx = None
                    if device_id in pci_data.InputIDs:
                        idx = pci_data.InputIDs.index(device_id)

                    if "PS/2" in device_props.get("Device Type", "None"):
                        selected_kexts.append("VoodooPS2Controller")
                        if device_id.startswith("SYN"):
                            selected_kexts.append("VoodooRMI")
                        elif idx and 75 < idx < 79:
                            selected_kexts.append("VoodooSMBus")
                    if "I2C" in device_props.get("Device Type", "None"):
                        selected_kexts.append("VoodooI2CHID")
                        if idx:
                            if idx < 76:
                                selected_kexts.append("AlpsHID")
                            elif 78 < idx:
                                selected_kexts.append("VoodooRMI")
        
        for device_name, device_info in hardware_report.get("System Devices", {}).items():
            if device_info.get("Bus Type") == "ACPI" and device_info.get("Device") in pci_data.YogaHIDs:
                selected_kexts.append("YogaSMC")

        if any(patch.checked for patch in acpi_patches if patch.name == "BATP"):
            selected_kexts.append("ECEnabler")

        for controller_name, controller_props in hardware_report.get("SD Controller", {}).items():
            if controller_props.get("Device ID") in pci_data.RealtekCardReaderIDs:
                if controller_props.get("Device ID") in pci_data.RealtekCardReaderIDs[5:]:
                    selected_kexts.append("Sinetek-rtsx")
                else:
                    selected_kexts.append("RealtekCardReader")
        
        for controller_name, controller_props in hardware_report.get("Storage Controllers", {}).items():
            if controller_props.get("Device ID") == "1C5C-174A":
                selected_kexts.append("PC711Probe")

            if "NVMe" in controller_name or "NVM Express" in controller_name:
                selected_kexts.append("NVMeFix")
            elif not "AHCI" in controller_name or "AMD" in hardware_report.get("CPU").get("Manufacturer"):
                if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("20.0.0"):
                    if controller_props.get("Device ID") in pci_data.UnsupportedSATAControllerIDs:
                        selected_kexts.append("CtlnaAHCIPort")
                else:
                    if controller_props.get("Device ID") in pci_data.UnsupportedSATAControllerIDs[15:]:
                        selected_kexts.append("SATA-unsupported")

        for controller_name, controller_props in hardware_report.get("USB Controllers").items():
            device_id = controller_props.get("Device ID")
            subsystem_id = controller_props.get("Subsystem ID", "0"*8)
            unsupported_controller = next((controller for controller in pci_data.UnsupportedUSBControllerIDs if device_id == controller[0]), None)

            if unsupported_controller:
                subsystem_ids = unsupported_controller[1]

                if len(subsystem_ids) > 0 and subsystem_id not in subsystem_ids:
                    continue

                if device_id.startswith("1022"):
                    if "Laptop" in hardware_report.get("Motherboard").get("Platform"):
                        selected_kexts.append("GenericUSBXHCI")
                else:
                    selected_kexts.append("XHCI-unsupported")

        if "Sandy Bridge" in hardware_report.get("CPU").get("Codename"):
            selected_kexts.append("ASPP-Override")

        if "Sandy Bridge" in hardware_report.get("CPU").get("Codename") or "Ivy Bridge" in hardware_report.get("CPU").get("Codename"):
            selected_kexts.extend(("AppleIntelCPUPowerManagement", "AppleIntelCPUPowerManagementClient"))

        if needs_oclp:
            # WhateverXe already pulled the Mod build; loading upstream AMFIPass as
            # well would put two bundles with one identifier in the EFI.
            if not whateverxe_gpu:
                selected_kexts.append("AMFIPass")
            selected_kexts.append("RestrictEvents")

        selected_kexts = list(dict.fromkeys(selected_kexts))
        force_load_kexts = self.verify_kext_compatibility(selected_kexts, macos_version)

        for name in selected_kexts:
            self.check_kext(kext_data.kext_index_by_name.get(name), macos_version, name in force_load_kexts)

        return needs_oclp

    def install_kexts_to_efi(self, macos_version, kexts_directory):
        """Copy every selected bundle into the EFI, or fail the build.

        The selection is whatever is checked when this runs, not what was
        checked at planning time: the build re-probes BATP and may uncheck
        ECEnabler, and that later state is the one the EFI must honour.
        """
        selected = [kext for kext in self.kexts if kext.checked]
        missing = []

        for kext in selected:
            kext_name = kext.name

            if kext_name == "Feixiao":
                kext_name = "rtw88"

            search_directory = self.ock_files_dir
            if kext_name == "AirportItlwm-laobamac":
                search_directory = os.path.join(self.ock_files_dir, kext_name + macos_version[:2])
                kext_name = "AirportItlwm"
            elif kext_name == "AMFIPass-Mod":
                # The archive holds a bundle named AMFIPass.kext. Its own product
                # folder keeps it apart from the upstream build with the same name.
                search_directory = os.path.join(self.ock_files_dir, kext_name)
                kext_name = "AMFIPass"

            source_kext_path = destination_kext_path = None
            for kext_path, _kind in self.utils.find_matching_paths(
                    search_directory, extension_filter=".kext", name_filter=kext_name):
                if kext.name == "AirportItlwm":
                    version = macos_version[:2]
                    if all((self.kexts[kext_data.kext_index_by_name.get("IOSkywalkFamily")].checked, self.kexts[kext_data.kext_index_by_name.get("IO80211FamilyLegacy")].checked)) or self.utils.parse_darwin_version("24.0.0") <= self.utils.parse_darwin_version(macos_version):
                        version = "22"
                    elif self.utils.parse_darwin_version("23.4.0") <= self.utils.parse_darwin_version(macos_version):
                        version = "23.4"
                    elif self.utils.parse_darwin_version("23.0.0") <= self.utils.parse_darwin_version(macos_version):
                        version = "23.0"

                    if kext_path.replace("\\", "/").split("/")[0] == "AirportItlwm" + version and os.path.basename(kext_path) == "AirportItlwm.kext":
                        source_kext_path = os.path.join(self.ock_files_dir, kext_path)
                        destination_kext_path = os.path.join(kexts_directory, os.path.basename(kext_path))
                        break
                else:
                    main_kext = kext_path.replace("\\", "/").split("/")[0]
                    main_kext_index = kext_data.kext_index_by_name.get(main_kext)
                    # AMFIPass-Mod's bundle is named AMFIPass, whose catalogue row is
                    # the upstream build this selection deliberately replaced.
                    if (kext.name == "AMFIPass-Mod" or not main_kext_index
                            or self.kexts[main_kext_index].checked):
                        if os.path.splitext(os.path.basename(kext_path))[0] == kext_name:
                            source_kext_path = os.path.join(search_directory, kext_path)
                            destination_kext_path = os.path.join(kexts_directory, os.path.basename(kext_path))

            if source_kext_path is None:
                missing.append("{} (no bundle in the cache)".format(kext.name))
                continue

            try:
                shutil.copytree(source_kext_path, destination_kext_path, dirs_exist_ok=True)
            except OSError as error:
                missing.append("{} ({})".format(kext.name, error))

        if missing:
            raise KextInstallIncomplete(detail=(
                "{} selected kernel extension(s) did not reach {}: {}. The build "
                "stopped instead of writing a boot set that silently omits them.".format(
                    len(missing), kexts_directory, "; ".join(sorted(missing)))))

    def process_kext(self, kexts_directory, kext_path):
        try:
            plist_path = self.utils.find_matching_paths(os.path.join(kexts_directory, kext_path), extension_filter=".plist", name_filter="Info")[0][0]
            bundle_info = self.utils.read_file(os.path.join(kexts_directory, kext_path, plist_path))

            if not isinstance(bundle_info, dict):
                return None
        except:
            return None

        executable_path = os.path.join("Contents", "MacOS", bundle_info.get("CFBundleExecutable", "None"))
        if not os.path.exists(os.path.join(kexts_directory, kext_path, executable_path)):
            executable_path = ""

        bundle_libraries = {
            bundle_identifier: bundle_version
            for bundle_identifier, bundle_version in bundle_info.get("OSBundleLibraries", {}).items() 
        }

        if bundle_info.get("CFBundleExecutable", "None") == "AppleALC":
            bundle_libraries["org.ChefKiss.NootedRed"] = "0.8.10"
        elif bundle_info.get("CFBundleExecutable", "None") == "SimpleHDA":
            bundle_libraries["as.vit9696.AppleALC"] = "1.9.9"
        
        return {
            "BundlePath": kext_path.replace("\\", "/").lstrip("/"),
            "Enabled": True,
            "ExecutablePath": executable_path.replace("\\", "/").lstrip("/"),
            "PlistPath": plist_path.replace("\\", "/").lstrip("/"),
            "BundleIdentifier": bundle_info.get("CFBundleIdentifier"),
            "BundleVersion": bundle_info.get("CFBundleVersion"),
            "BundleLibraries": bundle_libraries
        }

    # ---- Wi-Fi profiles: an explicit, caller-supplied step -----------------

    def needs_wifi_profiles(self, kexts_directory):
        """Installed plists whose itlwm WiFiConfig is still the stock stub.

        The GUI calls this after ``install_kexts_to_efi()`` to decide whether to
        offer password recovery, then hands the resulting profiles to
        ``apply_wifi_profiles()``. Reading only, never writing.
        """
        plist_paths = []

        if not os.path.isdir(kexts_directory):
            return plist_paths

        for kext_path, kext_type in self.utils.find_matching_paths(kexts_directory, extension_filter=".kext"):
            if os.path.splitext(os.path.basename(kext_path))[0] != "itlwm":
                continue

            plist_path = os.path.join(kexts_directory, kext_path, "Contents", "Info.plist")

            try:
                bundle_info = self.utils.read_file(plist_path)
            except (OSError, ValueError) as exception:
                self.utils.log_message("Could not read {}: {}".format(plist_path, exception), level="warning")
                continue

            personalities = (bundle_info or {}).get("IOKitPersonalities") or {}

            if personalities.get("itlwm", {}).get("WiFiConfig"):
                plist_paths.append(plist_path)

        return plist_paths

    def apply_wifi_profiles(self, plist_path, wifi_profiles):
        """Write recovered networks into an itlwm WiFiConfig stub.

        Replaces the blocking prompt flow that used to run inside
        ``modify_kexts()``: profiles are now an argument, so the build never
        blocks on a privileged password scan, and failure is reported instead of
        swallowed. Returns True only when the plist was actually rewritten;
        ``False`` plus an error-level log is the failure indicator, chosen over
        re-raising because ``apply_wifi_profiles_to_directory()`` loops over
        several plists and the caller reports a per-plist result.

        ``wifi_profiles`` is a sequence of ``(ssid, password)`` pairs -- the same
        shape upstream wrote into the plist. Required from
        ``ocengine.wifi_profile_extractor`` (owned by a separate conversion and
        deliberately not imported here any more):
        ``WifiProfileExtractor().get_profiles(interactive=False)`` returning a
        ``list`` of ``(ssid, password)`` tuples, performing no terminal reads and
        dropping its own "Would you like to scan for WiFi profiles?" gate -- the
        GUI asks first, then calls it. It must return ``[]`` for "nothing
        recovered" instead of raising, so an empty answer stays distinguishable
        from an injection failure, which this method reports.
        """
        try:
            bundle_info = self.utils.read_file(plist_path)
            personalities = bundle_info.get("IOKitPersonalities") or {}
            itlwm_personalities = personalities.get("itlwm") or {}

            if not itlwm_personalities.get("WiFiConfig"):
                self.utils.log_message("No itlwm WiFiConfig stub in {}, skipping.".format(plist_path), level="info")
                return False

            if not wifi_profiles:
                self.utils.log_message("No WiFi profiles supplied for {}, leaving the stub in place.".format(plist_path), level="info")
                return False

            itlwm_personalities["WiFiConfig"] = {
                "WiFi_{}".format(index): {
                    "password": profile[1],
                    "ssid": profile[0]
                }
                for index, profile in enumerate(wifi_profiles, start=1)
            }

            self.utils.write_file(plist_path, bundle_info)
            self.utils.log_message("Applied {} WiFi profile(s) to {}.".format(len(wifi_profiles), plist_path), level="info")
            return True
        except Exception as exception:
            self.utils.log_message(
                "WiFi profile injection failed for {}: {}".format(plist_path, exception),
                level="error",
            )
            self.utils.notify(
                "WiFi password injection failed",
                "The itlwm WiFiConfig stub was not replaced, so auto-connect will not work: {}".format(exception),
                level="error",
            )
            return False

    def apply_wifi_profiles_to_directory(self, kexts_directory, wifi_profiles):
        """Inject into every installed itlwm plist that still has the stub.

        Returns ``{plist_path: injected}`` so the caller can show exactly which
        bundles took the profiles; an empty dict means nothing needed them.
        """
        return {
            plist_path: self.apply_wifi_profiles(plist_path, wifi_profiles)
            for plist_path in self.needs_wifi_profiles(kexts_directory)
        }

    def modify_kexts(self, plist_path, hardware_report, macos_version):
        """Per-bundle plist fixes applied while loading kexts.

        The itlwm WiFiConfig branch is gone: it used to reach into
        wifi_profile_extractor and block on a privileged multi-prompt password
        scan, then swallow every failure of that scan. Wi-Fi profiles are now an
        explicit caller step (``apply_wifi_profiles``).

        Worth knowing when rebasing: upstream's chained
        ``.get("IOKitPersonalities").get("itlwm").get("WiFiConfig")`` raised
        AttributeError for every plist without an itlwm personality, so the two
        TSC branches below sat behind the bare except and never ran. Removing the
        swallow makes them reachable, which is the one observable change here.

        Returns True when the plist was rewritten, False otherwise. Callers in
        ``load_kexts()`` ignore the value, so a failure must stay non-fatal here;
        it is logged at error level rather than hidden.
        """
        try:
            bundle_info = self.utils.read_file(plist_path)
            personalities = bundle_info.get("IOKitPersonalities") or {}

            if personalities.get("VoodooTSCSync"):
                personalities["VoodooTSCSync"]["IOPropertyMatch"]["IOCPUNumber"] = 0 if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("21.0.0") else int(hardware_report["CPU"]["Core Count"]) - 1
            elif personalities.get("AmdTscSync"):
                personalities["AmdTscSync"]["IOPropertyMatch"]["IOCPUNumber"] = 0 if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("21.0.0") else int(hardware_report["CPU"]["Core Count"]) - 1
            else:
                return False

            self.utils.write_file(plist_path, bundle_info)
            return True
        except Exception as exception:
            self.utils.log_message("Could not modify {}: {}".format(plist_path, exception), level="error")
            return False

    def load_kexts(self, hardware_report, macos_version, kexts_directory):
        kernel_add = []
        unload_kext = []

        if self.kexts[kext_data.kext_index_by_name.get("IO80211ElCap")].checked:
            unload_kext.extend((
                "AirPortBrcm4331",
                "AppleAirPortBrcm43224"
            ))
        elif self.kexts[kext_data.kext_index_by_name.get("VoodooSMBus")].checked:
            unload_kext.append("VoodooPS2Mouse")
        elif self.kexts[kext_data.kext_index_by_name.get("VoodooRMI")].checked:
            if not self.kexts[kext_data.kext_index_by_name.get("VoodooI2C")].checked:
                unload_kext.append("RMII2C")
            else:
                unload_kext.extend((
                    "VoodooSMBus",
                    "RMISMBus",
                    "VoodooI2CHID"
                ))

        kext_paths = self.utils.find_matching_paths(kexts_directory, extension_filter=".kext")
        bundle_list = []
        unreadable = []

        for kext_path, type in kext_paths:
            bundle_info = self.process_kext(kexts_directory, kext_path)

            if bundle_info:
                self.modify_kexts(os.path.join(kexts_directory, kext_path, bundle_info.get("PlistPath")), hardware_report, macos_version)

                bundle_list.append(bundle_info)
            else:
                unreadable.append(kext_path)

        if unreadable:
            raise KextInstallIncomplete(detail=(
                "{} bundle(s) in {} do not have a readable Info.plist, so they "
                "cannot be added to config.plist: {}. The build stopped instead of "
                "dropping them silently.".format(
                    len(unreadable), kexts_directory, ", ".join(sorted(unreadable)))))

        bundle_dict = {bundle["BundleIdentifier"]: bundle for bundle in bundle_list}

        sorted_bundles = []
        
        visited = set()
        seen_identifier = set()

        def visit(bundle):
            kext_name = os.path.splitext(os.path.basename(bundle.get("BundlePath")))[0]
            if kext_name == "rtw88":
                kext_name = "Feixiao"
            elif kext_name == "AirportItlwm" and self.kexts[kext_data.kext_index_by_name["AirportItlwm-laobamac"]].checked:
                kext_name = "AirportItlwm-laobamac"

            if kext_name in unload_kext or (bundle.get("BundlePath"), bundle.get("BundleIdentifier")) in visited:
                return
                        
            bundle["MaxKernel"] = os_data.get_latest_darwin_version()
            bundle["MinKernel"] = os_data.get_lowest_darwin_version()

            kext_index = kext_data.kext_index_by_name.get(kext_name)

            if kext_index:
                bundle["MaxKernel"] = self.kexts[kext_index].max_darwin_version
                bundle["MinKernel"] = self.kexts[kext_index].min_darwin_version
            
            for dep_identifier in bundle.get("BundleLibraries"):
                if dep_identifier in bundle_dict:
                    visit(bundle_dict[dep_identifier])
                    
                    bundle["MaxKernel"] = bundle["MaxKernel"] if self.utils.parse_darwin_version(bundle["MaxKernel"]) < self.utils.parse_darwin_version(bundle_dict[dep_identifier].get("MaxKernel", "99.99.99")) else bundle_dict[dep_identifier]["MaxKernel"]
                    bundle["MinKernel"] = bundle["MinKernel"] if self.utils.parse_darwin_version(bundle["MinKernel"]) > self.utils.parse_darwin_version(bundle_dict[dep_identifier].get("MinKernel", "0.0.0")) else bundle_dict[dep_identifier]["MinKernel"]

            wifi_identifier = bundle.get("BundleIdentifier")
            if wifi_identifier in ("com.apple.driver.AirPort.BrcmNIC", "com.apple.driver.AirPort.Atheros40"):
                if bundle["BundlePath"].endswith("-Tahoe.kext"):
                    bundle["MinKernel"] = "25.0.0"
                else:
                    bundle["MaxKernel"] = "24.99.99"
                    bundle["MinKernel"] = "23.0.0" if wifi_identifier == "com.apple.driver.AirPort.BrcmNIC" else "18.0.0"

            if kext_name == "AirPortBrcm4360_Injector":
                bundle["MaxKernel"] = "19.99.99"
            elif kext_name in ("AirportItlwm", "AirportItlwm-laobamac"):
                bundle["MaxKernel"] = macos_version[:2] + bundle["MaxKernel"][2:]
                if kext_name == "AirportItlwm" or macos_version.startswith("25."):
                    bundle["MinKernel"] = macos_version[:2] + ".0.0"

            visited.add((bundle.get("BundlePath"), bundle.get("BundleIdentifier")))

            identifier = bundle.get("BundleIdentifier")
            if identifier in ("com.apple.driver.AirPort.BrcmNIC", "com.apple.driver.AirPort.Atheros40"):
                identifier = (identifier, bundle["MinKernel"], bundle["MaxKernel"])
            if identifier in seen_identifier:
                bundle["Enabled"] = False
            else:
                seen_identifier.add(identifier)

            sorted_bundles.append(bundle)

        for bundle in bundle_list:
            visit(bundle)

        latest_darwin_version = (os_data.get_latest_darwin_version(), os_data.get_latest_darwin_version(include_beta=False))
        lowest_darwin_version = os_data.get_lowest_darwin_version()

        for bundle in sorted_bundles:
            kernel_add.append({
                "Arch": "Any",
                "BundlePath": bundle.get("BundlePath"),
                "Comment": "",
                "Enabled": bundle.get("Enabled"),
                "ExecutablePath": bundle.get("ExecutablePath"),
                "MaxKernel": "" if bundle.get("MaxKernel") in latest_darwin_version else bundle.get("MaxKernel"),
                "MinKernel": "" if bundle.get("MinKernel") == lowest_darwin_version else bundle.get("MinKernel"),
                "PlistPath": bundle.get("PlistPath")
            })

        return kernel_add

    def uncheck_kext(self, index):
        if index is None or not 0 <= index < len(self.kexts):
            return False

        kext = self.kexts[index]

        if not kext.checked:
            return True

        dependents = [
            (other_index, other_kext)
            for other_index, other_kext in enumerate(self.kexts)
            if other_kext.checked and kext.name in other_kext.requires_kexts
        ]

        if kext.required or any(dependent.required for _, dependent in dependents):
            return False

        kext.checked = False

        for dependent_index, _ in dependents:
            self.uncheck_kext(dependent_index)

        for dependency_name in kext.requires_kexts:
            dependency_index = kext_data.kext_index_by_name.get(dependency_name)
            dependency = self.kexts[dependency_index]
            if not dependency.required and not any(other_kext.checked and dependency_name in other_kext.requires_kexts for other_kext in self.kexts):
                self.uncheck_kext(dependency_index)

        return True

    def incompatible_kext_candidates(self, kext_names, target_darwin_version):
        """Pure half of the compatibility gate: (name, is_lilu_plugin) pairs.

        The terminal listed these and then asked whether to force-load them;
        ``plan_kext_force_load_choice()`` turns the list into a choice.
        """
        incompatible_kexts = []

        for kext_name in dict.fromkeys(kext_names):
            kext_index = kext_data.kext_index_by_name.get(kext_name)
            if kext_index is None:
                continue

            kext = self.kexts[kext_index]
            if not self.is_kext_compatible(kext, target_darwin_version) and kext.allow_force_load:
                incompatible_kexts.append((kext.name, "Lilu" in kext.requires_kexts))

        return incompatible_kexts

    def verify_kext_compatibility(self, kext_names, target_darwin_version, force_load=None):
        """Return the kext names to force-load despite version mismatch.

        ``force_load`` is the caller's answer: True forces, False declines. When
        it is None the recorded menu choice is used, whose default is the
        terminal's capital-N "No" -- an empty answer declined and loaded nothing.
        """
        incompatible_kexts = self.incompatible_kext_candidates(kext_names, target_darwin_version)

        if not incompatible_kexts:
            return set()

        self.utils.head("Kext Compatibility Check")

        choice = self.plan_kext_force_load_choice(incompatible_kexts, target_darwin_version)

        if force_load is None:
            option = self.resolve_kext_choice(choice)
        else:
            self._kext_choice_plans[choice.key] = choice
            option = choice.option(1) if force_load else choice.default

        self.log_kext_choice(choice, option)

        return set(option.kexts)
