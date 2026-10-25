"""The build pipeline, without a terminal.

Upstream drove everything from a menu loop in ``OpCore-Simplify.py``: pick a report,
grade it, choose a version, customise, build. The order those calls have to happen in
is the actual domain knowledge, and it is reproduced here exactly -- what is removed is
the ``input()`` between them. Every step now returns data or raises, and the GUI is the
thing that asks questions.

Two deliberate departures from the reference:

* ``acpi_dir`` is an explicit input. Upstream recovered it by prompting for a folder
  when the DSDT could not be found next to the report; a GUI supplies it up front,
  and its absence is a typed failure rather than a blinking cursor.
* ``result_dir`` is injected. Upstream wrote ``Results/`` beside its own source, which
  inside a packaged application is the read-only, code-signed bundle.
"""

from __future__ import annotations

import dataclasses
import plistlib
import shutil
from pathlib import Path
from typing import Any, Callable

from ocengine import utils as ocengine_utils
from ocengine.acpi_guru import ACPIGuru
from ocengine.compatibility_checker import CompatibilityChecker
from ocengine.config_prodigy import ConfigProdigy
from ocengine.datasets import gpu_data, kext_data
from ocengine.fatal import EngineError
from ocengine.gathering_files import gatheringFiles
from ocengine.hardware_customizer import HardwareCustomizer
from ocengine.kext_maestro import KextMaestro
from ocengine.report_validator import ReportValidator
from ocengine.smbios import SMBIOS

from blackdream.core import preflight, versions


class Cancelled(Exception):
    """Raised by a cancel token when the user asks a running stage to stop."""


class ReportRejected(EngineError):
    code = "report.rejected"
    title = "This hardware report cannot be used"


class NotConfigured(EngineError):
    code = "pipeline.not_configured"
    title = "Select a hardware report first"
    remediation = ("Collect hardware from this machine, or load a Report.json, "
                   "before building.",)


class BuildNotReady(EngineError):
    code = "pipeline.build_not_ready"
    title = "The build is missing something it needs"


class BuildVerificationFailed(EngineError):
    code = "pipeline.verification_failed"
    title = "The EFI folder failed its own integrity check"
    remediation = (
        "Do not copy this EFI to a disk; it is incomplete.",
        "Build again, and report the listed problems together with the engine log.",
    )


class CancelToken:
    """Cooperative cancellation. Stages call ``check()`` between units of work."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        if self._cancelled:
            raise Cancelled()


@dataclasses.dataclass
class Analysis:
    """Device verdicts for one report, before any user choice."""

    report: dict[str, Any]
    native_range: tuple[str, str]
    oclp_range: tuple[str, str] | None
    log: list[tuple[str, str]]


@dataclasses.dataclass
class Plan:
    """Everything a build needs, after the user has made their choices."""

    analysis: Analysis
    macos_version: str
    needs_oclp: bool
    hardware_report: dict[str, Any]
    disabled_devices: dict[str, Any]
    smbios_model: str
    acpi_dir: str | None


_STEPS = (
    "Copying EFI base to results folder",
    "Applying ACPI patches",
    "Copying kexts and snapshotting to config.plist",
    "Generating config.plist",
    "Cleaning up unused drivers, resources, and tools",
)

# Written into every output folder the build creates. Its presence is what lets a
# retry replace that folder; anything else is someone's directory and is kept.
OUTPUT_MARKER = ".blackdream-build.json"

#: The steps WhateverXe cannot have performed for the user. The graphics package
#: writes the target's /Library and rebuilds its AuxKC, which is outside this
#: application's EFI-only boundary, so it is handed off as text.
WHATEVERXE_HANDOFF = """WhateverXe 0.5.0 - what still has to happen on the Mac
=========================================================

This EFI loads WhateverXe.kext after Lilu, the Mod AMFIPass build, the boot arguments
-allow3d -disablegfxfirmware, and csr-active-config 03080000 (0x803). It does not
contain WhateverGreen, which must not be enabled alongside WhateverXe.

1. Boot the target macOS with this EFI first.
2. Install WhateverXe Graphics {graphics} from
   https://github.com/b00t0x/WhateverXe-Graphics/releases
   It writes the signed graphics stack under /Library and rebuilds the AuxKC.
   BlackDream does not download or run this package.
3. Set DVMT Pre-Allocated to 96 MB in firmware. If the board fixes it at 60 MB,
   add -igfxdvmt to boot-args and set framebuffer-patch-enable = 01000000 and
   framebuffer-stolenmem = 0000C003 (Data) on the iGPU.
4. Internal-panel brightness needs SSDT-PNLF, which this build includes on laptops.
5. Do not use -yTileDisable with the Display 13 backend.

WhateverXe and its graphics package are experimental and BSD-3 licensed, and cover
only the Xe-LP GPUs listed in the project's README. Read its known issues before
relying on them: https://github.com/b00t0x/WhateverXe
"""


#: The steps the NullMoth driver cannot have performed for the user. Its kexts and
#: Metal plugin live in /Library and the AuxKC -- inside the target macOS, not the
#: ESP -- so the build hands the installation off as text and never runs it.
NULLMOTH_HANDOFF = """NullMoth NVIDIA driver {version} - what still has to happen on the Mac
======================================================================

This EFI carries the driver's OpenCore prerequisites: Lilu and AMFIPass, boot-args
nvfb=1 nvaccel=1 nvfbheads=4 -nvkmsnosmooth amfi_get_out_of_my_way=0x1 amfi=0x80
ipc_control_port_options=0 (plus nvrmsettle=10000 on Turing, and gfxrst=4 when
WhateverGreen is enabled), csr-active-config 430A0000 (0x0A43), SecureBootModel
Disabled, and an IONDRVSupport exclude unless the built-in panel runs on an Intel
firmware framebuffer. It does not contain the driver itself. NVRM, NVAccel, NVRMFB
and NVRMAGDC load from /Library/Extensions and the AuxKC; do not add them to
Kernel/Add or EFI/OC/Kexts.

1. Boot the target macOS with this EFI first, then install on that system.
   Download 1401-Mac-{version}.dmg (the app) or nullmoth-nvidia-{version}.tar.gz from
   {releases}
   The tarball's SHA-256 is {sha256}. BlackDream downloads and runs neither.
2. In firmware: Above 4G Decoding On, CSM Off. Keep this EFI's ResizeGpuBars
   and ResizeAppleGpuBars values; the driver sizes the BAR itself after macOS
   starts, and forced resizing can stop firmware before the picker.
3. The macOS install must be x86_64. When macOS asks, allow the extensions in
   System Settings > Privacy & Security, then reboot once more.
4. The first start with the driver can pause for up to a minute at "PCI
   configuration end" while the GPU comes up.
5. This EFI carries no nv_disable=1, -wegnoegpu, agdpmod=pikera, WhateverGreen
   NVIDIA patch or NVIDIA DeviceProperties for the card. The vendor says none
   are needed; remove any you add back.
6. On an AMD CPU, the vendor requires Algrey's Fix PAT rather than Shaneee's;
   its installer switches that pair when it finds them.
7. Verify: kmutil showloaded --list-only | grep nullmoth (four lines), and
   system_profiler SPDisplaysDataType (Metal: supported).
8. Uninstall: sudo ./uninstall.sh && sudo shutdown -r now, or choose the 1401
   Remove NVIDIA driver entry in the OpenCore picker.

NullMoth's driver, kexts and Metal plugin are PolyForm Noncommercial 1.0.0, the
shader translator is LGPL-3.0, and the GSP firmware is NVIDIA's. Personal,
research, educational and non-profit use only; commercial use is not allowed.
Most testing is on an RTX 5060, so other Turing-and-newer cards are less proven.
Read the project's notes before relying on it: https://github.com/nullmoth/nvidia-macos-driver
"""


class Pipeline:
    """One Pipeline is one session: its engine objects own their own state copies."""

    def __init__(self) -> None:
        self.utils = ocengine_utils.Utils()
        self.validator = ReportValidator()
        self.compatibility = CompatibilityChecker()
        self.hardware = HardwareCustomizer()
        self.smbios = SMBIOS()
        self.acpi = ACPIGuru()
        self.kexts = KextMaestro()
        self.config = ConfigProdigy()
        self.gatherer = gatheringFiles()

    def load_report(self, report_path: str | Path) -> dict[str, Any]:
        path = str(self.utils.normalize_path(str(report_path)))
        is_valid, errors, _warnings, data = self.validator.validate_report(path)
        if not is_valid or errors:
            raise ReportRejected(
                detail="{}: {}".format(Path(path).name, "; ".join(errors)),
                remediation=("Collect the hardware report again, or export a fresh one "
                             "with Hardware Sniffer.",),
            )
        return data

    def analyze(self, report: dict[str, Any]) -> Analysis:
        """Grade every device class. Raises a FatalIncompatibility subclass if the
        machine cannot run macOS at all."""
        preflight.check(report)
        graded, native, oclp = self.compatibility.check_compatibility(report)
        return Analysis(report=graded, native_range=native, oclp_range=oclp, log=[])

    def version_choices(self, analysis: Analysis) -> list[versions.VersionOption]:
        suggested = versions.suggest(analysis.report, analysis.native_range)
        return versions.options(analysis.native_range, analysis.oclp_range, suggested=suggested)

    def configure(self, analysis: Analysis, macos_version: str,
                  acpi_dir: str | None = None) -> Plan:
        """Apply the automatic pass: device contention, SMBIOS model, ACPI patch
        selection, kext selection. Overrides are applied afterwards by the GUI."""
        hardware_report, disabled_devices, needs_oclp = self.hardware.hardware_customization(
            analysis.report, macos_version)
        smbios_model = self.smbios.select_smbios_model(hardware_report, macos_version)

        if not self.acpi.ensure_dsdt():
            if not acpi_dir:
                raise BuildNotReady(
                    detail="No DSDT is loaded and no ACPI table folder was supplied.",
                    remediation=(
                        "Point the report at the ACPI folder inside the exported SysReport.",
                        "Or press Read ACPI tables on the Compatibility view to read this "
                        "machine's firmware.",
                    ),
                )
            self.acpi.select_acpi_tables(self.utils.normalize_path(acpi_dir))

        self.acpi.select_acpi_patches(hardware_report, disabled_devices)
        needs_oclp = self.kexts.select_required_kexts(
            hardware_report, macos_version, needs_oclp, self.acpi.patches)
        self.smbios.smbios_specific_options(
            hardware_report, smbios_model, macos_version, self.acpi.patches, self.kexts)

        return Plan(analysis=analysis, macos_version=macos_version, needs_oclp=needs_oclp,
                    hardware_report=hardware_report, disabled_devices=disabled_devices,
                    smbios_model=smbios_model, acpi_dir=acpi_dir)

    def gather_artifacts(self, plan: Plan, token: CancelToken | None = None) -> None:
        """Download the OpenCore base and the selected kexts. Network-bound, so it is
        a separate stage the UI can show progress for and cancel."""
        if token is None:
            token = CancelToken()
        token.check()
        # The engine filters on `checked` itself; passing the whole catalogue keeps
        # this call identical to the reference orchestrator's.
        self.gatherer.gather_bootloader_kexts(self.kexts.kexts, plan.macos_version)
        token.check()

    def build(self, plan: Plan, result_dir: str | Path,
              token: CancelToken | None = None) -> Path:
        """Emit a complete EFI folder. Mirrors the reference sequence step for step."""
        if token is None:
            token = CancelToken()

        result = Path(result_dir)
        stage = self.utils.progress_bar
        stage("Building OpenCore EFI", list(_STEPS), 0)
        self._create_output_dir(result)

        cache = Path(self.kexts.ock_files_dir)
        if not cache.exists():
            raise BuildNotReady(
                detail="The artifact cache at {} has not been populated.".format(cache),
                remediation=("Run the download stage first; it fetches OpenCorePkg and the kexts.",))

        shutil.copytree(cache / "OpenCorePkg", str(result), dirs_exist_ok=True)

        config_file = result / "EFI" / "OC" / "config.plist"
        config_data = self.utils.read_file(str(config_file))
        if not config_data:
            raise BuildNotReady(detail="{} is missing from the OpenCore base.".format(config_file))

        token.check()
        stage("Building OpenCore EFI", list(_STEPS), 1)
        config_data["ACPI"]["Add"] = []
        config_data["ACPI"]["Delete"] = []
        config_data["ACPI"]["Patch"] = []
        if self.acpi.ensure_dsdt():
            self.acpi.hardware_report = plan.hardware_report
            self.acpi.disabled_devices = plan.disabled_devices
            self.acpi.acpi_directory = str(result / "EFI" / "OC" / "ACPI")
            self.acpi.smbios_model = plan.smbios_model
            self.acpi.lpc_bus_device = self.acpi.get_lpc_name()

            for patch in self.acpi.patches:
                token.check()
                if not patch.checked:
                    continue
                if patch.name == "BATP":
                    patch.checked = getattr(self.acpi, patch.function_name)()
                    from ocengine.datasets import kext_data
                    index = kext_data.kext_index_by_name.get("ECEnabler")
                    self.kexts.kexts[index].checked = patch.checked
                    continue

                acpi_load = getattr(self.acpi, patch.function_name)()
                if not isinstance(acpi_load, dict):
                    continue
                config_data["ACPI"]["Add"].extend(acpi_load.get("Add", []))
                config_data["ACPI"]["Delete"].extend(acpi_load.get("Delete", []))
                config_data["ACPI"]["Patch"].extend(acpi_load.get("Patch", []))

        config_data["ACPI"]["Patch"].extend(self.acpi.dsdt_patches)
        config_data["ACPI"]["Patch"] = self.acpi.apply_acpi_patches(config_data["ACPI"]["Patch"])

        token.check()
        stage("Building OpenCore EFI", list(_STEPS), 2)
        kexts_directory = str(result / "EFI" / "OC" / "Kexts")
        self.kexts.install_kexts_to_efi(plan.macos_version, kexts_directory)
        config_data["Kernel"]["Add"] = self.kexts.load_kexts(
            plan.hardware_report, plan.macos_version, kexts_directory)

        token.check()
        stage("Building OpenCore EFI", list(_STEPS), 3)
        self.config.genarate(plan.hardware_report, plan.disabled_devices, plan.smbios_model,
                             plan.macos_version, plan.needs_oclp, self.kexts.kexts, config_data)
        self.utils.write_file(str(config_file), config_data)

        token.check()
        stage("Building OpenCore EFI", list(_STEPS), 4)
        self._prune(result, config_data)
        self._write_whateverxe_handoff(result)
        self._write_nullmoth_handoff(result)
        self._verify_output(result)

        stage("Building OpenCore EFI", list(_STEPS), len(_STEPS), done=True)
        return result

    @staticmethod
    def _create_output_dir(result: Path) -> None:
        """Create the output folder, replacing only a folder this app created.

        ``rmtree`` on the user's chosen path used to be unconditional: pointing it
        at a mounted ESP's EFI folder would delete a working bootloader. A marker
        written at creation time records ownership, so an interrupted BlackDream
        build can be retried while any other folder is left untouched.
        """
        if result.exists():
            if not (result / OUTPUT_MARKER).is_file():
                try:
                    is_empty = not any(result.iterdir())
                except OSError as error:
                    raise BuildNotReady(detail=(
                        "{} cannot be inspected: {}".format(result, error))) from error
                if not is_empty:
                    raise BuildNotReady(
                        detail=("{} already exists and was not created by BlackDream, "
                                "so it was not deleted.").format(result),
                        remediation=(
                            "Choose an empty folder, or the output folder of an earlier "
                            "BlackDream build.",
                            "If the existing folder is disposable, remove it yourself and "
                            "build again.",
                        ),
                    )
            else:
                shutil.rmtree(result)

        result.mkdir(parents=True, exist_ok=True)
        (result / OUTPUT_MARKER).write_text(
            '{"tool": "BlackDream", "format": 1}\n', encoding="utf-8")

    def _write_whateverxe_handoff(self, result: Path) -> None:
        """Leave the steps this build cannot take beside the EFI it did produce."""
        index = kext_data.kext_index_by_name.get("WhateverXe")
        if index is None or not self.kexts.kexts[index].checked:
            return
        note = result / "WhateverXe-Graphics.txt"
        note.write_text(
            WHATEVERXE_HANDOFF.format(graphics=gpu_data.WHATEVERXE_GRAPHICS_VERSION),
            encoding="utf-8")
        self.utils.log_message(
            "WhateverXe: this EFI is complete, but the graphics stack is installed "
            "on the target afterwards. Read {}.".format(note.name), level="warning")

    def _write_nullmoth_handoff(self, result: Path) -> None:
        """Leave the driver's on-target installation beside the EFI, not in it."""
        if not self.kexts.nullmoth_gpu:
            return
        note = result / "NullMoth-NVIDIA-Driver.txt"
        note.write_text(NULLMOTH_HANDOFF.format(
            version=gpu_data.NULLMOTH_DRIVER_VERSION,
            releases=gpu_data.NULLMOTH_RELEASES_URL,
            sha256=gpu_data.NULLMOTH_TARBALL_SHA256), encoding="utf-8")
        self.utils.log_message(
            "NullMoth: this EFI carries the prerequisites for the {}; the driver "
            "itself is installed on the target. Read {}.".format(
                self.kexts.nullmoth_gpu, note.name), level="warning")

    @staticmethod
    def _prune(result: Path, config_data: dict[str, Any]) -> None:
        """Delete drivers, picker variants, tools and audio that config.plist does not
        reference, so the emitted folder is exactly what will be booted."""
        oc = result / "EFI" / "OC"
        removals = []

        def config_path(value: Any) -> str:
            # Config entries always use "/"; the filesystem listing uses the
            # host separator. Compare in the config's form or Windows would
            # prune every nested entry it was supposed to keep.
            return str(value).replace("\\", "/")

        loaded = {config_path(entry.get("Path"))
                  for entry in config_data.get("UEFI", {}).get("Drivers", [])}
        removals += [str(oc / "Drivers" / name) for name, _kind
                     in _listing(oc / "Drivers", ".efi") if config_path(name) not in loaded]

        audio = oc / "Resources" / "Audio"
        if audio.exists():
            removals.append(str(audio))

        variant = config_data.get("Misc", {}).get("Boot", {}).get("PickerVariant")
        if variant in (None, "Auto"):
            variant = "Acidanthera/GoldenGate"
        variant = config_path(variant)

        image_dir = oc / "Resources" / "Image"
        for name, kind in _listing(image_dir, None, "dir"):
            path = image_dir / name
            try:
                contents = ", ".join(p.name for p in path.iterdir())
            except OSError:
                continue
            if ".icns" in contents and variant not in config_path(name):
                removals.append(str(path))

        loaded_tools = {config_path(entry.get("Path"))
                        for entry in config_data.get("Misc", {}).get("Tools", [])}
        removals += [str(oc / "Tools" / name) for name, _kind
                     in _listing(oc / "Tools", ".efi") if config_path(name) not in loaded_tools]

        manifest = result / "manifest.json"
        if manifest.exists():
            removals.append(str(manifest))

        for target in removals:
            try:
                if Path(target).is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    Path(target).unlink(missing_ok=True)
            except OSError as error:
                ocengine_utils.Utils().log_message(
                    "Failed to remove {}: {}".format(target, error), level="warning")

    @staticmethod
    def _verify_output(result: Path) -> None:
        """Prove the emitted tree satisfies config.plist, then let the build return.

        ``ocvalidate`` checks the config in isolation; it cannot see whether the
        files a config points at survived pruning, and a build must not report
        success while a reference dangles. Everything checked here is local.
        """
        efi = result / "EFI"
        oc = efi / "OC"
        kexts_root = oc / "Kexts"
        problems = []

        for required in (efi / "BOOT" / "BOOTx64.efi", oc / "OpenCore.efi",
                         oc / "config.plist"):
            if not required.is_file():
                problems.append("missing {}".format(required.relative_to(result)))

        try:
            with open(oc / "config.plist", "rb") as handle:
                config = plistlib.load(handle)
        except Exception as error:
            raise BuildVerificationFailed(detail=(
                "The generated config.plist cannot be read back: {}".format(error))) from error

        for entry in config.get("ACPI", {}).get("Add", []):
            relative = entry.get("Path", "")
            if relative and not (oc / "ACPI" / relative).is_file():
                problems.append("ACPI/Add references missing {}".format(relative))

        enabled = []
        identifiers = {}
        for entry in config.get("Kernel", {}).get("Add", []):
            bundle_path = entry.get("BundlePath", "")
            bundle = kexts_root / bundle_path
            if not bundle.is_dir():
                problems.append("Kernel/Add references missing {}".format(bundle_path))
                continue

            plist_path = bundle / entry.get("PlistPath", "Contents/Info.plist")
            try:
                with open(plist_path, "rb") as handle:
                    info = plistlib.load(handle)
            except Exception as error:
                problems.append("cannot read {}: {}".format(plist_path, error))
                continue

            executable = entry.get("ExecutablePath")
            if executable and not (bundle / executable).is_file():
                problems.append("{} has no {}".format(bundle_path, executable))

            if not entry.get("Enabled"):
                continue
            identifier = info.get("CFBundleIdentifier")
            if identifier in identifiers:
                problems.append("duplicate enabled identifier {}: {} and {}".format(
                    identifier, identifiers[identifier], bundle_path))
            identifiers[identifier] = bundle_path
            enabled.append((bundle_path, info))

        identifier_position = {}
        for index, (_bundle_path, info) in enumerate(enabled):
            identifier_position.setdefault(info.get("CFBundleIdentifier"), index)
        for index, (bundle_path, info) in enumerate(enabled):
            for library in (info.get("OSBundleLibraries") or {}):
                later = identifier_position.get(library)
                if later is not None and later > index:
                    problems.append("{} loads before {}".format(bundle_path, library))

        for entry in config.get("UEFI", {}).get("Drivers", []):
            relative = entry.get("Path", "") if isinstance(entry, dict) else entry
            if relative and not (oc / "Drivers" / relative).is_file():
                problems.append("UEFI/Drivers references missing {}".format(relative))

        for entry in config.get("Misc", {}).get("Tools", []):
            relative = entry.get("Path", "")
            if relative and not (oc / "Tools" / relative).is_file():
                problems.append("Misc/Tools references missing {}".format(relative))

        if problems:
            raise BuildVerificationFailed(detail=(
                "{} problem(s) in {}: {}".format(
                    len(problems), result, "; ".join(sorted(set(problems))))))


def _listing(directory: Path, extension_filter: str | None = None,
             type_filter: str | None = None) -> list[tuple[str, str]]:
    """The engine's own relative-path listing, so pruning matches its view."""
    if not directory.is_dir():
        return []
    return ocengine_utils.Utils().find_matching_paths(
        str(directory), extension_filter=extension_filter, type_filter=type_filter)
