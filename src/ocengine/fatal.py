"""Typed engine failures.

The vendored engine aborted with ``sys.exit(0)`` from inside compatibility
checking (upstream ``Scripts/compatibility_checker.py:90,103,224,317,339,363``).
That is survivable in a terminal but fatal in a GUI: the user drops a report and
the application vanishes. Each site raises instead, so the UI can render a
blocking-but-recoverable screen and keep the session alive.

Defined here rather than in ``blackdream.core`` because the engine raises these
and the application catches them -- see the layering note in ``runtime.py``.
"""

from __future__ import annotations


class EngineError(Exception):
    """Base for failures the UI is expected to present rather than crash on.

    Subclasses carry the static wording; an instance may override ``detail`` and
    ``remediation`` with per-occurrence context (which prompt fired, which device
    failed) so the screen can be specific without a class per situation.
    """

    code = "engine.error"
    title = "Engine error"
    detail = ""
    remediation: tuple[str, ...] = ()
    recoverable = True

    def __init__(self, detail: str = "", remediation: tuple[str, ...] = ()):
        if detail:
            self.detail = detail
        if remediation:
            self.remediation = tuple(remediation)
        super().__init__(self.title)

    def __str__(self) -> str:
        return self.title


class InteractivePrompt(EngineError):
    """Engine code still tried to read from a terminal.

    There is no terminal. Every surviving call site is a conversion that was
    missed, so this raises loudly instead of returning an empty string that would
    silently drive a menu into its default branch.
    """

    code = "engine.interactive_prompt"
    title = "The engine tried to prompt for terminal input"


class ExitRequested(EngineError):
    """Engine code still tried to terminate the process."""

    code = "engine.exit_requested"
    title = "The engine tried to exit the program"


class FatalIncompatibility(EngineError):
    """A device verdict that makes a macOS install impossible as configured.

    ``recoverable`` separates "fix this setting or re-export the report" (retry in
    place) from "this machine cannot run macOS" (still a screen, never a quit).
    """


class CpuNoSse4(FatalIncompatibility):
    code = "cpu.no_sse4"
    title = "CPU lacks the SSE4.x instruction set"
    detail = "macOS requires SSE4.2 on every supported CPU. This processor predates that."
    remediation = (
        "Every Intel CPU from Nehalem onward, and every AMD CPU macOS targets, supports SSE4.x.",
        "If this report came from a virtual machine, pass through host CPU features and re-export.",
    )
    recoverable = False


class GpuMissingFromReport(FatalIncompatibility):
    code = "gpu.absent"
    title = "No GPU found in the hardware report"
    detail = "The report contains no graphics device, so no display can be driven during install."
    remediation = (
        "Re-export the hardware report with the GPU information included.",
        "On a desktop, confirm the display is plugged into the GPU you intend to boot from.",
    )


class GpuUnsupported(FatalIncompatibility):
    code = "gpu.unsupported"
    title = "No macOS-compatible GPU on this system"
    detail = ("Every graphics device in the report is unsupported by macOS, "
              "including via OpenCore Legacy Patcher.")
    remediation = (
        "Check the Compatibility screen for which device was rejected and why.",
        "A supported discrete GPU, or an iGPU from Iron Lake through Ice Lake, is required.",
    )
    recoverable = False


class StorageControllerMissing(FatalIncompatibility):
    code = "storage.absent"
    title = "No storage controller found in the hardware report"
    detail = "Without a storage controller the internal drives are invisible to the installer."
    remediation = (
        "Re-export the hardware report with storage controller information.",
        "On Intel 11th gen and newer, disable Intel VMD in BIOS first.",
    )


class StorageIntelVmdEnabled(FatalIncompatibility):
    code = "storage.intel_vmd"
    title = "Intel VMD storage controller is enabled"
    detail = "macOS has no driver for Intel VMD, so the NVMe drives behind it are unreachable."
    remediation = (
        "Disable Intel VMD in the BIOS storage/VMD setup menu.",
        "Switch the SATA controller mode to AHCI if that option is exposed.",
        "Re-export the hardware report afterwards.",
    )


class NoCompatibleStorage(FatalIncompatibility):
    code = "storage.no_compatible"
    title = "No macOS-compatible storage controller"
    detail = "Every PCI storage controller with attached drives in this report is unsupported."
    remediation = (
        "The boot disk must sit behind a storage controller macOS already drives.",
        "Western Digital NVMe drives are commonly a safe choice.",
    )


FATAL_BY_CODE: dict[str, type[FatalIncompatibility]] = {
    cls.code: cls
    for cls in (
        CpuNoSse4,
        GpuMissingFromReport,
        GpuUnsupported,
        StorageControllerMissing,
        StorageIntelVmdEnabled,
        NoCompatibleStorage,
    )
}
