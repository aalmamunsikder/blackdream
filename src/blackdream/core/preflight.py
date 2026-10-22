"""Report-shape checks that run before the vendored compatibility engine.

The engine grades each device class behind ``if report.get(section)``, so a section
that is present but empty is skipped silently and a build is produced for hardware
that cannot boot macOS. The validator cannot catch this either: an empty dict satisfies
a ``required`` check. These two shapes are rejected here instead of in the engine so
that upstream grading stays byte-faithful and rebaseable.
"""

from ocengine.fatal import GpuMissingFromReport, StorageControllerMissing


def check(hardware_report: dict) -> None:
    if not hardware_report.get("GPU"):
        raise GpuMissingFromReport(
            detail=(
                "The report has no graphics device"
                + (" (the GPU section is empty)." if "GPU" in hardware_report else " section.")
            )
        )

    if not hardware_report.get("Storage Controllers"):
        raise StorageControllerMissing(
            detail=(
                "The report has no storage controller"
                + (" (the Storage Controllers section is empty)."
                   if "Storage Controllers" in hardware_report else " section.")
            )
        )
