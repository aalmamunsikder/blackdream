"""Device contention resolution for the partitioned hardware report.

Converted from the upstream terminal menu (OpCore-Simplify f0e1e44,
``Scripts/hardware_customizer.py``). The partitioning rules are untouched; only
the interleaved menu is gone. Each former menu is now two pieces:

* a pure builder that computes the selectable candidates and the default the
  terminal would have picked, returned as data, and
* an ``apply_*`` method that mutates the hardware state for a caller-supplied
  choice.

``hardware_customization()`` keeps its signature and its 3-tuple return, so the
orchestrator is unchanged, and it takes the automatic default for every menu it
used to block on. The menus it resolved are left on the instance
(``selection_menus``, ``bios_firmware_prompt``) so a GUI can present them and
re-apply a different choice.
"""

from dataclasses import dataclass, field

from ocengine.datasets import os_data
from ocengine.datasets import pci_data
from ocengine import compatibility_checker
from ocengine import utils

# The hardware report types this module partitions or disables. Everything else
# is carried through untouched.
CUSTOMIZED_DEVICE_TYPES = ("BIOS", "GPU", "Sound", "Biometric", "Network", "Storage Controllers", "Bluetooth", "SD Controller")

# Device types that may expose several mutually exclusive candidates.
CONTENDED_DEVICE_TYPES = ("GPU", "Network", "Bluetooth")

# Menu numbering is 1-based, matching the numbers the terminal printed.
DEFAULT_CHOICE = 1


@dataclass
class DeviceCandidate:
    """One numbered option of a device contention menu."""

    names: list[str]
    indices: list[int]
    compatibility: tuple | None = None
    oclp_compatibility: tuple | None = None
    device_id: str | None = None

    @property
    def label(self):
        return " + ".join(self.names)


@dataclass
class DeviceSelectionMenu:
    """Everything a GUI needs to present one contended device type."""

    device_type: str
    mode: str
    devices: dict
    candidates: list[DeviceCandidate]
    question: str
    prompt: str
    notes: list[str] = field(default_factory=list)
    default_choice: int = DEFAULT_CHOICE

    @property
    def candidate(self):
        """The candidate the automatic default selects."""
        return self.candidates[self.default_choice - 1]

    def to_dict(self):
        return {
            "device_type": self.device_type,
            "mode": self.mode,
            "question": self.question,
            "prompt": self.prompt,
            "notes": list(self.notes),
            "default_choice": self.default_choice,
            "devices": sorted(self.devices),
            "candidates": [
                {
                    "choice": index,
                    "names": list(candidate.names),
                    "indices": list(candidate.indices),
                    "label": candidate.label,
                    "compatibility": list(candidate.compatibility) if candidate.compatibility else None,
                    "oclp_compatibility": list(candidate.oclp_compatibility) if candidate.oclp_compatibility else None,
                    "device_id": candidate.device_id,
                }
                for index, candidate in enumerate(self.candidates, start=1)
            ],
        }


@dataclass
class BiosFirmwarePrompt:
    """The Legacy/UEFI question the terminal asked when the report said Legacy."""

    question: str
    notes: list[str] = field(default_factory=list)
    options: dict = field(default_factory=dict)
    default_choice: str = "yes"
    detected_firmware_type: str | None = None

    def to_dict(self):
        return {
            "question": self.question,
            "notes": list(self.notes),
            "options": dict(self.options),
            "default_choice": self.default_choice,
            "detected_firmware_type": self.detected_firmware_type,
            "firmware_type": self.options.get(self.default_choice),
        }


class HardwareCustomizer:
    def __init__(self):
        self.compatibility_checker = compatibility_checker.CompatibilityChecker()
        self.utils = utils.Utils()
        self.selection_menus = {}
        self.bios_firmware_prompt = None

    def hardware_customization(self, hardware_report, macos_version):
        self.hardware_report = hardware_report
        self.macos_version = macos_version
        self.customized_hardware = {}
        self.disabled_devices = {}
        self.selected_devices = {}
        self.selection_menus = {}
        self.bios_firmware_prompt = None
        needs_oclp = False

        self.utils.head("Hardware Customization")

        for device_type, devices in self.hardware_report.items():
            if not device_type in CUSTOMIZED_DEVICE_TYPES:
                self.customized_hardware[device_type] = devices
                continue

            self.customized_hardware[device_type] = {}

            if device_type == "BIOS":
                self.customized_hardware[device_type] = devices.copy()
                if devices.get("Firmware Type") != "UEFI":
                    self.bios_firmware_prompt = self.build_bios_firmware_prompt(devices)
                    self.log_bios_firmware_prompt(self.bios_firmware_prompt)
                    self.apply_bios_firmware_choice(self.bios_firmware_prompt)
                continue

            for device_name in devices:
                device_props = devices[device_name].copy()
                if device_props.get("OCLP Compatibility") and self.utils.parse_darwin_version(device_props.get("OCLP Compatibility")[0]) >= self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version(device_props.get("OCLP Compatibility")[-1]):
                    self.customized_hardware[device_type][device_name] = device_props
                    needs_oclp = True
                    continue

                device_compatibility = device_props.get("Compatibility", (os_data.get_latest_darwin_version(), os_data.get_lowest_darwin_version()))

                try:
                    is_compatible = self.utils.parse_darwin_version(device_compatibility[0]) >= self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version(device_compatibility[-1])
                except:
                    is_compatible = False

                if is_compatible:
                    self.customized_hardware[device_type][device_name] = device_props
                else:
                    self.disabled_devices["{}: {}{}".format(device_props["Device Type"] if not "Unknown" in device_props.get("Device Type", "Unknown") else device_type, device_name, "" if not device_props.get("Audio Endpoints") else " ({})".format(", ".join(device_props.get("Audio Endpoints"))))] = device_props

                if self.customized_hardware[device_type].get(device_name) and self.customized_hardware[device_type][device_name].get("OCLP Compatibility"):
                    del self.customized_hardware[device_type][device_name]["OCLP Compatibility"]

            if not self.customized_hardware[device_type]:
                del self.customized_hardware[device_type]
            else:
                if device_type in CONTENDED_DEVICE_TYPES:
                    self._handle_device_selection(device_type if device_type != "Network" else "WiFi")

        if self.selected_devices:
            self.utils.head("Device Selection Summary")
            for line in self.device_selection_summary_lines():
                if line:
                    self.utils.log_message(line)
            # Was a "press Enter" gate that closed the summary table.
            self.utils.notify(
                "Device selection summary",
                "All other devices of the same type have been disabled.",
            )

        return self.customized_hardware, self.disabled_devices, needs_oclp

    def build_bios_firmware_prompt(self, bios_props):
        """Pure: the Legacy/UEFI question as data. No I/O, no blocking.

        Upstream blocked on a terminal read until the answer was yes or no.
        "(Yes/no)" is the prompt's own default, and UEFI is what the build path
        assumes, so the automatic choice is ``yes``.
        """
        return BiosFirmwarePrompt(
            question="Build EFI for UEFI? (Yes/no): ",
            notes=[
                "*** BIOS Firmware Type is not UEFI",
                "Do you want to build the EFI for UEFI?",
                "If yes, please make sure to update your BIOS and enable UEFI Boot Mode in your BIOS settings.",
                "You can still proceed with Legacy if you prefer.",
            ],
            options={"yes": "UEFI", "no": "Legacy"},
            default_choice="yes",
            detected_firmware_type=bios_props.get("Firmware Type"),
        )

    def log_bios_firmware_prompt(self, prompt):
        for line in prompt.notes:
            if line:
                self.utils.log_message(line)

    def apply_bios_firmware_choice(self, prompt, choice=None):
        """Apply a firmware type answer and return the resulting value."""
        if choice is None:
            choice = prompt.default_choice

        choice = str(choice).strip().lower()
        if choice not in prompt.options:
            self.utils.log_message("Invalid selection, please try again.", level="warning")
            raise ValueError("Invalid selection, please try again.")

        firmware_type = prompt.options[choice]
        self.customized_hardware.setdefault("BIOS", {})["Firmware Type"] = firmware_type
        return firmware_type

    def _get_device_combinations(self, device_indices):
        devices = sorted(list(device_indices))
        n = len(devices)
        all_combinations = []

        if n == 0:
            return []
        
        for i in range(1, 1 << n):
            current_combination = []
            for j in range(n):
                if (i >> j) & 1:
                    current_combination.append(devices[j])
            
            if 1 <= len(current_combination) <= n:
                all_combinations.append(current_combination)

        all_combinations.sort(key=lambda combo: (len(combo), combo))

        return all_combinations

    def _handle_device_selection(self, device_type):
        devices = self._get_compatible_devices(device_type)

        if len(devices) > 1:
            device_groups, notes = self.analyze_device_contention(device_type, devices)
            menu = self.build_device_selection_menu(device_type, devices, device_groups, notes)

            self.selection_menus[device_type] = menu
            self.log_device_selection_menu(menu)
            self.apply_device_selection(menu)

    def analyze_device_contention(self, device_type, devices):
        """Pure: group competing devices and collect the advisory wording.

        Returns ``(device_groups, notes)``. ``device_groups`` is ``None`` unless
        the type is a GPU set that has to be offered as combinations.
        """
        notes = ["*** Multiple {} Devices Detected".format(device_type)]

        if device_type == "WiFi" or device_type == "Bluetooth":
            notes.append(f"macOS works best with only one {device_type} device enabled.")
            return None, notes

        if device_type != "GPU":
            return None, notes

        _apu_index = None
        _navi_22_indices = set()
        _navi_indices = set()
        _intel_gpu_indices = set()
        _other_indices = set()

        for index, (gpu_name, gpu_props) in enumerate(devices.items()):
            gpu_manufacturer = gpu_props.get("Manufacturer")
            gpu_codename = gpu_props.get("Codename")
            gpu_type = gpu_props.get("Device Type")

            if gpu_manufacturer == "AMD":
                if gpu_type == "Integrated GPU":
                    _apu_index = index
                    continue
                elif gpu_type == "Discrete GPU":
                    if gpu_codename.startswith("Navi"):
                        if gpu_codename == "Navi 22":
                            _navi_22_indices.add(index)
                        else:
                            _navi_indices.add(index)
                        continue
            elif gpu_manufacturer == "Intel":
                _intel_gpu_indices.add(index)
                continue

            _other_indices.add(index)

        if _apu_index or _navi_22_indices:
            notes.append("Multiple active GPUs can cause kext conflicts in macOS.")

        device_groups = []
        if _apu_index:
            device_groups.append({_apu_index} | _other_indices)
        if _navi_22_indices:
            device_groups.append(_navi_22_indices | _other_indices)
        if _navi_indices or _intel_gpu_indices or _other_indices:
            device_groups.append(_navi_indices | _intel_gpu_indices | _other_indices)

        return device_groups, notes

    def _get_compatible_devices(self, device_type):
        compatible_devices = {}
        
        if device_type == "WiFi":
            hardware_category = "Network"
        else:
            hardware_category = device_type
        
        for device_name, device_props in self.customized_hardware.get(hardware_category, {}).items():
            if device_type == "WiFi":
                device_id = device_props.get("Device ID")

                if device_id not in pci_data.WirelessCardIDs:
                    continue

            compatible_devices[device_name] = device_props
        
        return compatible_devices

    def build_device_selection_menu(self, device_type, devices, device_groups=None, notes=None):
        """Pure: enumerate every selectable candidate for a contended type.

        The combination set is the same bitmask power set upstream computed, in
        the same order, so the 1-based numbering of the old menu is preserved.
        ``default_choice`` is candidate 1: an empty entry was rejected and
        re-prompted by the terminal, so the first listed option is the only
        deterministic choice.
        """
        candidates = []

        if device_groups:
            question = "Please select a {} combination configuration:".format(device_type)
            valid_combinations = []

            for group in device_groups:
                device_combinations = self._get_device_combinations(group)
                for device_combination in device_combinations:
                    group_devices = []
                    group_compatibility = None
                    group_indices = set()
                    has_oclp_required = False
                    
                    for index in device_combination:
                        device_name = list(devices.keys())[index]
                        device_props = devices[device_name]
                        group_devices.append(device_name)
                        group_indices.add(index)
                        compatibility = device_props.get("Compatibility")
                        if compatibility:
                            if group_compatibility is None:
                                group_compatibility = compatibility
                            else:
                                if self.utils.parse_darwin_version(compatibility[0]) < self.utils.parse_darwin_version(group_compatibility[0]):
                                    group_compatibility = (compatibility[0], group_compatibility[1])
                                if self.utils.parse_darwin_version(compatibility[1]) > self.utils.parse_darwin_version(group_compatibility[1]):
                                    group_compatibility = (group_compatibility[0], compatibility[1])
                        
                        if device_props.get("OCLP Compatibility"):
                            has_oclp_required = True

                    if has_oclp_required and len(device_combination) > 1:
                        continue

                    if group_devices and (group_devices, group_indices, group_compatibility) not in valid_combinations:
                        valid_combinations.append((group_devices, group_indices, group_compatibility))

            valid_combinations.sort(key=lambda x: (len(x[0]), x[2][0]))

            for group_devices, group_indices, group_compatibility in valid_combinations:
                oclp_compatibility = None

                if len(group_devices) == 1:
                    device_props = devices[group_devices[0]]
                    if device_props.get("OCLP Compatibility"):
                        candidate_oclp = device_props.get("OCLP Compatibility")
                        if self.utils.parse_darwin_version(candidate_oclp[0]) > self.utils.parse_darwin_version(group_compatibility[0]):
                            oclp_compatibility = (candidate_oclp[0], os_data.get_lowest_darwin_version())

                candidates.append(DeviceCandidate(
                    names=list(group_devices),
                    indices=sorted(group_indices),
                    compatibility=group_compatibility,
                    oclp_compatibility=oclp_compatibility,
                ))

            prompt = "Select a {} combination (1-{}): ".format(device_type, len(candidates))
            mode = "combination"
        else:
            question = "Please select which {} device you want to use:".format(device_type)

            for index, device_name in enumerate(devices, start=1):
                device_props = devices[device_name]
                compatibility = device_props.get("Compatibility")
                oclp_compatibility = None

                if device_props.get("OCLP Compatibility"):
                    candidate_oclp = device_props.get("OCLP Compatibility")
                    if self.utils.parse_darwin_version(candidate_oclp[0]) > self.utils.parse_darwin_version(compatibility[0]):
                        oclp_compatibility = (candidate_oclp[0], os_data.get_lowest_darwin_version())

                candidates.append(DeviceCandidate(
                    names=[device_name],
                    indices=[index - 1],
                    compatibility=compatibility,
                    oclp_compatibility=oclp_compatibility,
                    device_id=device_props.get("Device ID", "Unknown"),
                ))

            prompt = "Select a {} device (1-{}): ".format(device_type, len(candidates))
            mode = "single"

        return DeviceSelectionMenu(
            device_type=device_type,
            mode=mode,
            # Snapshot: a later choice has to be able to re-enable what an
            # earlier one disabled, and the disabled devices leave the report.
            devices={name: devices[name] for name in devices},
            candidates=candidates,
            question=question,
            prompt=prompt,
            notes=list(notes or []),
            default_choice=DEFAULT_CHOICE,
        )

    def device_selection_menu_lines(self, menu):
        """Render the old menu body as plain text, same wording, no colors."""
        lines = ["", *menu.notes, "", menu.question, ""]

        for index, candidate in enumerate(menu.candidates, start=1):
            lines.append("{}. {}".format(index, candidate.label))

            if menu.mode == "combination":
                if candidate.compatibility:
                    lines.append("   Compatibility: {}".format(self.compatibility_checker.show_macos_compatibility(candidate.compatibility)))
            else:
                lines.append("   Device ID: {}".format(candidate.device_id))
                lines.append("   Compatibility: {}".format(self.compatibility_checker.show_macos_compatibility(candidate.compatibility)))

            if candidate.oclp_compatibility:
                lines.append("   OCLP Compatibility: {}".format(self.compatibility_checker.show_macos_compatibility(candidate.oclp_compatibility)))

            lines.append("")

        return lines

    def log_device_selection_menu(self, menu):
        for line in self.device_selection_menu_lines(menu):
            if line:
                self.utils.log_message(line)

    def apply_device_selection(self, menu, choice=None):
        """Apply one contention choice and return the enabled device names.

        ``choice`` is forwarded to ``resolve_device_candidate``: a 1-based menu
        number, a device name, the full set of a combination's names, or ``None``
        for the automatic default.
        """
        candidate = self.resolve_device_candidate(menu, choice)

        device_type = menu.device_type
        devices = menu.devices
        hardware_category = "Network" if device_type == "WiFi" else device_type
        selected_devices = list(candidate.names)

        # Restore the snapshot first so a changed choice can re-enable devices an
        # earlier one disabled. This is a no-op on the first application.
        current_devices = self.customized_hardware.setdefault(hardware_category, {})

        for device_name, device_props in devices.items():
            current_devices[device_name] = device_props
            self.disabled_devices.pop("{}: {}".format(hardware_category, device_name), None)

        for device in devices:
            if device not in selected_devices:
                self._disable_device(device_type, device, devices[device])

        self.selected_devices[device_type] = {name: devices[name] for name in selected_devices}

        return selected_devices

    def resolve_device_candidate(self, menu, choice=None):
        """Map a caller choice onto one enumerated candidate.

        ``choice`` may be ``None`` (the menu's default), a 1-based menu number as
        an int or digit string, one device name, or the full set of device names a
        combination lists. The old menu answered an invalid entry by reprinting the
        list and re-asking; with no terminal to re-ask, this rejects instead.
        """
        if choice is None:
            choice = menu.default_choice

        if isinstance(choice, str) and choice.strip().isdigit():
            choice = int(choice.strip())

        if isinstance(choice, int):
            if 1 <= choice <= len(menu.candidates):
                return menu.candidates[choice - 1]
            self._reject_device_option()

        names = sorted({choice} if isinstance(choice, str) else set(choice))
        for candidate in menu.candidates:
            if sorted(candidate.names) == names:
                return candidate

        self._reject_device_option()

    def _reject_device_option(self):
        self.utils.log_message("Invalid option. Please try again.", level="warning")
        raise ValueError("Invalid option. Please try again.")

    def device_selection_summary_lines(self):
        """The summary table the old menu printed before its Enter gate."""
        lines = [
            "Selected devices:",
            "",
            "Type          Device                                     Device ID",
            "------------------------------------------------------------------",
        ]

        for device_type, device_dict in self.selected_devices.items():
            for device_name, device_props in device_dict.items():
                device_id = device_props.get("Device ID", "Unknown")
                lines.append("{:<13} {:<42} {}".format(device_type, device_name[:38], device_id))

        lines.append("")
        lines.append("All other devices of the same type have been disabled.")

        return lines

    def _disable_device(self, device_type, device_name, device_props):
        if device_type == "WiFi":
            device_id = device_props.get("Device ID")
            if not device_id or device_id not in pci_data.WirelessCardIDs:
                return

            hardware_category = "Network"
        else:
            hardware_category = device_type

        if (hardware_category in self.customized_hardware and device_name in self.customized_hardware[hardware_category]):
            del self.customized_hardware[hardware_category][device_name]
            
            if not self.customized_hardware[hardware_category]:
                del self.customized_hardware[hardware_category]
        
        self.disabled_devices["{}: {}".format(hardware_category, device_name)] = device_props
