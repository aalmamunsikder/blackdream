"""SMBIOS model selection and serial generation.

Converted from the upstream terminal menu (OpCore-Simplify f0e1e44,
``Scripts/smbios.py``). ``select_smbios_model()`` was already a pure decision
ladder and is unchanged. The picker that used to sit on top of it is now split
into ``build_smbios_model_menu()`` (pure, returns the categorized list and the
defaults as data) and ``apply_smbios_model_choice()`` (applies a caller-supplied
choice). ``customize_smbios_model()`` keeps its signature for the orchestrator and
takes the menu's own default, which leaves the selection untouched.
"""

from dataclasses import dataclass, field

from ocengine.datasets.mac_model_data import mac_devices
from ocengine.datasets import kext_data
from ocengine.datasets import os_data
from ocengine import gathering_files
from ocengine import run
from ocengine import utils
import os
import uuid
import random
import platform

os_name = platform.system()


@dataclass
class SmbiosModelEntry:
    """One row of the former SMBIOS picker.

    ``index`` is the 1-based number the terminal menu used, so it still maps
    straight onto ``mac_devices[index - 1]``.
    """

    index: int
    name: str
    cpu: str
    cpu_generation: str
    discrete_gpu: str | None
    category: str
    is_supported: bool
    is_selected: bool
    is_default: bool


@dataclass
class SmbiosModelMenu:
    """Everything a GUI needs to present the SMBIOS picker."""

    title: str
    default_smbios_model: str
    selected_smbios_model: str
    macos_version: str
    macos_name: str
    is_laptop: bool
    show_all_models: bool
    entries: list[SmbiosModelEntry] = field(default_factory=list)
    incompatible_indices: list[int] = field(default_factory=list)
    header: str = ""
    note_lines: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)

    @property
    def selectable_names(self):
        """Model names the menu actually offered for this view."""
        return [entry.name for entry in self.entries]

    @property
    def default_selection(self):
        """What the menu resolves to without a human: the current selection.

        An empty entry only redrew the menu, so the deterministic outcome of the
        old loop is the same model it was entered with.
        """
        return self.selected_smbios_model

    def to_dict(self):
        return {
            "title": self.title,
            "default_smbios_model": self.default_smbios_model,
            "selected_smbios_model": self.selected_smbios_model,
            "macos_version": self.macos_version,
            "macos_name": self.macos_name,
            "is_laptop": self.is_laptop,
            "show_all_models": self.show_all_models,
            "header": self.header,
            "note_lines": list(self.note_lines),
            "options": list(self.options),
            "entries": [
                {
                    "index": entry.index,
                    "name": entry.name,
                    "cpu": entry.cpu,
                    "cpu_generation": entry.cpu_generation,
                    "discrete_gpu": entry.discrete_gpu,
                    "category": entry.category,
                    "is_supported": entry.is_supported,
                    "is_selected": entry.is_selected,
                    "is_default": entry.is_default,
                }
                for entry in self.entries
            ],
        }


class SMBIOS:
    def __init__(self):
        self.g = gathering_files.gatheringFiles()
        self.run = run.Run().run
        self.utils = utils.Utils()
        self.last_smbios_menu = None

    def check_macserial(self, retry_count=0, try_downloading=True):
        """Locate a verified macserial binary, downloading OpenCorePkg if it is missing.

        Resolution mirrors ``DSDT``'s lazy ``iasl`` lookup: the binary is found
        through ``paths.tools_dirs()`` and pin-checked by ``gathering_files`` before
        it is ever returned, so the package directory -- which sits on Python's
        import path -- is never consulted and a remote-named or tampered file is
        refused. The download is delegated to ``gathering_files``, which this
        conversion does not own beyond that install step.

        Nothing here catches what the resolver raises, so a tampered binary surfaces
        as ``MacserialVerificationFailed`` and an unusable platform as
        ``MacserialUnsupportedPlatform`` rather than a bare ``Exception``, and a
        missing binary the retries cannot recover becomes ``MacserialUnavailable``.
        ``utils`` turns any surviving blocking read into ``InteractivePrompt`` and
        any surviving termination into ``ExitRequested``.
        """
        max_retries = 3

        macserial_path = self.g.find_macserial()
        if macserial_path:
            return macserial_path

        if not try_downloading:
            raise gathering_files.MacserialUnavailable(detail=(
                "No verified macserial was found in the tools directories and "
                "downloading was declined. Set BLACKDREAM_TOOLS_DIR to a directory "
                "holding a pinned macserial, or allow the OpenCorePkg download."))

        if retry_count >= max_retries:
            raise gathering_files.MacserialUnavailable(detail=(
                "Failed to find macserial after {} attempts.".format(max_retries)))

        current_history = self.utils.read_file(self.g.download_history_file)

        if current_history and isinstance(current_history, list):
            new_history = [item for item in current_history if item.get("product_name") != "OpenCorePkg"]
            if len(new_history) != len(current_history):
                self.utils.write_file(self.g.download_history_file, new_history)

        self.g.gather_bootloader_kexts([], "")
        return self.check_macserial(retry_count + 1, try_downloading=try_downloading)
        
    def generate_random_mac(self):
        random_mac = ''.join([format(random.randint(0, 255), '02X') for _ in range(6)])
        return random_mac

    def generate_smbios(self, smbios_model):
        macserial = self.check_macserial()

        random_mac_address = self.generate_random_mac()

        output = self.run({
            "args":[macserial, "-g", "--model", smbios_model]
        })
        
        if not output or output[-1] != 0 or not output[0] or " | " not in output[0]:
            serial = []
        else:
            serial = output[0].splitlines()[0].split(" | ")

        return {
            "MLB": "A" + "0"*15 + "Z" if not serial else serial[-1],
            "ROM": random_mac_address,
            "SystemProductName": smbios_model,
            "SystemSerialNumber": "A" + "0"*10 + "9" if not serial else serial[0],
            "SystemUUID": str(uuid.uuid4()).upper(),
        }
    
    def smbios_specific_options(self, hardware_report, smbios_model, macos_version, acpi_patches, kext_maestro):
        for patch in acpi_patches:
            if patch.name == "MCHC":
                patch.checked = "Intel" in hardware_report.get("CPU").get("Manufacturer") and not "MacPro" in smbios_model

        selected_kexts = []

        if "MacPro7,1" in smbios_model:
            selected_kexts.append("RestrictEvents")

        if smbios_model in (device.name for device in mac_devices[31:34] + mac_devices[48:50] + mac_devices[51:61]):
            selected_kexts.append("NoTouchID")

        for name in selected_kexts:
            kext_maestro.check_kext(kext_data.kext_index_by_name.get(name), macos_version, "Beta" in os_data.get_macos_name_by_darwin(macos_version))
    
    def select_smbios_model(self, hardware_report, macos_version):
        platform = "NUC" if "NUC" in hardware_report.get("Motherboard").get("Name") else hardware_report.get("Motherboard").get("Platform")
        codename = hardware_report.get("CPU").get("Codename")

        smbios_model = "MacBookPro16,2" if "Laptop" in platform else "iMacPro1,1" if self.utils.parse_darwin_version(macos_version) < self.utils.parse_darwin_version("25.0.0") else "MacPro7,1"

        if codename in ("Lynnfield", "Clarkdale") and "Xeon" not in hardware_report.get("CPU").get("Processor Name") and self.utils.parse_darwin_version(macos_version) < self.utils.parse_darwin_version("19.0.0"):
            smbios_model = "iMac11,1" if codename == "Lynnfield" else "iMac11,2"
        elif codename in ("Beckton", "Westmere-EX", "Gulftown", "Westmere-EP", "Clarkdale", "Lynnfield", "Jasper Forest", "Gainestown", "Bloomfield"):
            smbios_model = "MacPro5,1" if self.utils.parse_darwin_version(macos_version) < self.utils.parse_darwin_version("19.0.0") else "MacPro6,1"
        elif ("Sandy Bridge" in codename or "Ivy Bridge" in codename) and self.utils.parse_darwin_version(macos_version) < self.utils.parse_darwin_version("22.0.0"):
            smbios_model = "MacPro6,1"

        if platform != "Laptop" and list(hardware_report.get("GPU").items())[-1][-1].get("Device Type") != "Integrated GPU":
            return smbios_model
        
        if codename in ("Arrandale", "Clarksfield"):
            smbios_model = "MacBookPro6,1"
        elif "Sandy Bridge" in codename:
            if "Desktop" in platform:
                smbios_model = "iMac12,2"
            elif "NUC" in platform:
                smbios_model = "Macmini5,1" if int(hardware_report.get("CPU").get("Core Count")) < 4 else "Macmini5,3"
            elif "Laptop" in platform:
                smbios_model = "MacBookPro8,1" if int(hardware_report.get("CPU").get("Core Count")) < 4 else "MacBookPro8,2"
        elif "Ivy Bridge" in codename:
            if "Desktop" in platform:
                smbios_model = "iMac13,1" if "Integrated GPU" in list(hardware_report.get("GPU").items())[0][-1].get("Device Type") else "iMac13,2"
            elif "NUC" in platform:
                smbios_model = "Macmini6,1" if int(hardware_report.get("CPU").get("Core Count")) < 4 else "Macmini6,2"
            elif "Laptop" in platform:
                smbios_model = "MacBookPro10,2" if int(hardware_report.get("CPU").get("Core Count")) < 4 else "MacBookPro10,1"
        elif "Haswell" in codename:
            if "Desktop" in platform:
                smbios_model = "iMac14,4" if "Integrated GPU" in list(hardware_report.get("GPU").items())[0][-1].get("Device Type") else "iMac15,1"
            elif "NUC" in platform:
                smbios_model = "Macmini7,1"
            elif "Laptop" in platform:
                smbios_model = "MacBookPro11,1" if int(hardware_report.get("CPU").get("Core Count")) < 4 else "MacBookPro11,5"
        elif "Broadwell" in codename:
            if "Desktop" in platform:
                smbios_model = "iMac16,2" if "Integrated GPU" in list(hardware_report.get("GPU").items())[0][-1].get("Device Type") else "iMac17,1"
            elif "NUC" in platform:
                smbios_model = "iMac16,1"
            elif "Laptop" in platform:
                smbios_model = "MacBookPro12,1" if int(hardware_report.get("CPU").get("Core Count")) < 4 else "MacBookPro11,5"
        elif "Skylake" in codename:
            smbios_model = "iMac17,1"
            if "Laptop" in platform:
                smbios_model = "MacBookPro13,1" if int(hardware_report.get("CPU").get("Core Count")) < 4 else "MacBookPro13,3"
        elif "Amber Lake" in codename or "Kaby Lake" in codename:
            smbios_model = "iMac18,1" if "Integrated GPU" in list(hardware_report.get("GPU").items())[0][-1].get("Device Type") else "iMac18,3"
            if "Laptop" in platform:
                smbios_model = "MacBookPro14,1" if int(hardware_report.get("CPU").get("Core Count")) < 4 else "MacBookPro14,3"
        elif "Cannon Lake" in codename or "Whiskey Lake" in codename or "Coffee Lake" in codename or "Comet Lake" in codename:
            smbios_model = "Macmini8,1"
            if "Desktop" in platform:
                smbios_model = "iMac18,3" if self.utils.parse_darwin_version(macos_version) < self.utils.parse_darwin_version("18.0.0") else "iMac19,1"
                if "Comet Lake" in codename:
                    smbios_model = "iMac20,1" if int(hardware_report.get("CPU").get("Core Count")) < 10 else "iMac20,2"
            elif "Laptop" in platform:
                if "-8" in hardware_report.get("CPU").get("Processor Name"):
                    smbios_model = "MacBookPro15,2" if int(hardware_report.get("CPU").get("Core Count")) < 6 else "MacBookPro15,3"
                else:
                    smbios_model = "MacBookPro16,3" if int(hardware_report.get("CPU").get("Core Count")) < 6 else "MacBookPro16,1"
        elif "Ice Lake" in codename:
            smbios_model = "MacBookAir9,1"

        return smbios_model

    def build_smbios_model_menu(self, hardware_report, selected_smbios_model, macos_version, show_all_models=False):
        """Pure: categorize every model the picker would have listed. No I/O.

        Returns a ``SmbiosModelMenu``. Filtering, numbering, category grouping
        and the compatibility test are the terminal menu's, verbatim; only the
        color wrapping and the input loop are gone.
        """
        default_smbios_model = self.select_smbios_model(hardware_report, macos_version)
        is_laptop = "Laptop" == hardware_report.get("Motherboard").get("Platform")

        entries = []
        incompatible_models_by_index = []

        for index, device in enumerate(mac_devices, start=1):
            isSupported = self.utils.parse_darwin_version(device.initial_support) <= self.utils.parse_darwin_version(macos_version) <= self.utils.parse_darwin_version(device.last_supported_version)
            if device.name not in (default_smbios_model, selected_smbios_model) and not show_all_models and (not isSupported or (is_laptop and not device.name.startswith("MacBook")) or (not is_laptop and device.name.startswith("MacBook"))):
                incompatible_models_by_index.append(index - 1)
                continue

            category = ""
            for char in device.name:
                if char.isdigit():
                    break
                category += char

            entries.append(SmbiosModelEntry(
                index=index,
                name=device.name,
                cpu=device.cpu,
                cpu_generation=device.cpu_generation,
                discrete_gpu=device.discrete_gpu,
                category=category,
                is_supported=isSupported,
                is_selected=device.name == selected_smbios_model,
                is_default=device.name == default_smbios_model,
            ))

        options = []
        if not show_all_models:
            options.append("A. Show all models")
        else:
            options.append("C. Show compatible models only")
        if selected_smbios_model != default_smbios_model:
            options.append("R. Restore default SMBIOS model ({})".format(default_smbios_model))
        # The blank line is the separator the terminal menu drew before "B. Back".
        options.append("")
        options.append("B. Back")

        return SmbiosModelMenu(
            title="Customize SMBIOS Model",
            default_smbios_model=default_smbios_model,
            selected_smbios_model=selected_smbios_model,
            macos_version=macos_version,
            macos_name=os_data.get_macos_name_by_darwin(macos_version),
            is_laptop=is_laptop,
            show_all_models=show_all_models,
            entries=entries,
            incompatible_indices=incompatible_models_by_index,
            header="List of {} SMBIOS:".format("available" if show_all_models else "compatible"),
            note_lines=[
                "Note:",
                "- Lines in gray indicate mac models that are not officially supported by {}.".format(os_data.get_macos_name_by_darwin(macos_version)),
            ],
            options=options,
        )

    def smbios_model_menu_lines(self, menu):
        """Render the picker as plain text, same wording, no colors.

        Category headers are emitted where the entry list changes category, which
        is exactly where the terminal drew them.
        """
        contents = ["", menu.header]
        current_category = None

        for entry in menu.entries:
            if entry.category != current_category:
                current_category = entry.category
                category_header = "Category: {}".format(current_category if current_category else "Uncategorized")
                contents.append("")
                contents.append(category_header)
                contents.append("=" * len(category_header))

            checkbox = "[*]" if entry.is_selected else "[ ]"
            contents.append("{} {:2}. {:15} - {:10} {:20}{}".format(
                checkbox,
                entry.index,
                entry.name,
                entry.cpu,
                "({})".format(entry.cpu_generation),
                "" if not entry.discrete_gpu else " - {}".format(entry.discrete_gpu),
            ))

        contents.append("")
        contents.extend(menu.note_lines)
        contents.append("")
        contents.extend(menu.options)

        return contents

    def log_smbios_model_menu(self, menu):
        for line in self.smbios_model_menu_lines(menu):
            if line:
                self.utils.log_message(line)

    def apply_smbios_model_choice(self, menu, choice):
        """Apply one picker choice.

        Returns ``(selected_smbios_model, show_all_models)``: the two values the
        terminal loop carried between redraws. ``choice`` is a 1-based entry
        number, a model name, or one of ``"a"``/``"c"``/``"r"``/``"b"``. A numbered
        choice or name that the compatible-only view hides leaves the selection
        unchanged, as the terminal's silent redraw did, so reaching such a model
        takes ``"a"`` or a rebuild with ``show_all_models=True`` first. ``"q"`` is
        gone with the menu it belonged to, and anything unrecognized or out of
        range raises ``ValueError``.
        """
        if isinstance(choice, int):
            return self._apply_smbios_index_choice(menu, choice)

        option = str(choice).strip().lower()

        if option.isdigit():
            return self._apply_smbios_index_choice(menu, int(option))

        if option in ("a", "all"):
            return menu.selected_smbios_model, True

        if option in ("c", "compatible"):
            return menu.selected_smbios_model, False

        if option in ("r", "restore", "restore default"):
            if menu.selected_smbios_model != menu.default_smbios_model:
                return menu.default_smbios_model, menu.show_all_models
            return menu.selected_smbios_model, menu.show_all_models

        if option in ("b", "back", ""):
            return menu.selected_smbios_model, menu.show_all_models

        model_indices = {device.name.lower(): position for position, device in enumerate(mac_devices, start=1)}
        if option in model_indices:
            # Same rule as a numbered choice: hidden by the compatible-only filter
            # means unchanged, visible means selected.
            return self._apply_smbios_index_choice(menu, model_indices[option])

        raise ValueError("Unknown SMBIOS option: {!r}".format(choice))

    def _apply_smbios_index_choice(self, menu, number):
        index = number - 1

        if not 0 <= index < len(mac_devices):
            raise ValueError("Invalid SMBIOS option: {!r}".format(number))

        if not menu.show_all_models and index in menu.incompatible_indices:
            # The old menu simply redrew without touching the selection.
            return menu.selected_smbios_model, menu.show_all_models

        return mac_devices[index].name, menu.show_all_models
    
    def customize_smbios_model(self, hardware_report, selected_smbios_model, macos_version):
        """Present the SMBIOS picker and take its automatic default.

        The terminal redrew the menu on an empty entry, so the only deterministic
        outcome without a human is the unchanged selection -- the same result as
        pressing "B. Back" immediately. The list it would have shown is kept on
        ``self.last_smbios_menu`` so a GUI can present it and re-apply through
        ``apply_smbios_model_choice()``.
        """
        menu = self.build_smbios_model_menu(hardware_report, selected_smbios_model, macos_version)
        self.last_smbios_menu = menu

        self.utils.head(menu.title)
        self.log_smbios_model_menu(menu)

        return menu.default_selection
