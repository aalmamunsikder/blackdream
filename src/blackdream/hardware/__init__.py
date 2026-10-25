"""End-to-end input for the engine: everything read off the machine it runs on.

Two host capabilities are deliberately separate:

* ``collect_supported`` -- writing a Report.json from this machine. Linux scans
  itself; Windows runs the digest-verified Hardware Sniffer CLI; macOS has no
  collector, because the tool upstream uses is Windows-only and a native scan has
  not been measured. Loading a report is possible everywhere.
* ``acpi_supported`` -- reading the firmware tables from this machine. Linux reads
  sysfs through a polkit helper; Windows reads the same tables in user mode through
  the Win32 firmware-table calls. macOS has neither, so its ACPI folder picker takes
  tables exported on the target machine.

``collect_hardware`` dispatches to the backend for this host, so the UI does not
carry platform branches of its own.
"""

from . import acpi as acpi_backend
from . import acpi_windows as acpi_windows_backend
from . import collect as collect_backend
from . import windows as windows_backend
from .acpi import (
    AcpiDumper,
    Dumped,
    TablesDumpFailed,
    TablesHelperMissing,
    TablesRefused,
    TablesTimedOut,
    TablesUnsupported,
    helper_source,
    policy_source,
    trusted_helper,
)
from .acpi_windows import WindowsAcpiDumper
from .collect import (
    REPORT_FILE,
    Collected,
    CollectionRejected,
    CollectionUnsupported,
    ReportCollector,
    reconcile_report,
)
from .windows import CollectionFailed, CollectionTimedOut, WindowsCollector


def collect_supported() -> bool:
    """Whether this host can produce a Report.json without an external export."""
    return windows_backend.supported() or collect_backend.supported()


def acpi_supported() -> bool:
    """Whether the app can read firmware tables from this host."""
    return acpi_backend.supported() or acpi_windows_backend.supported()


def collect_timeout() -> float:
    """How long the GUI job waits for a scan, including the tool download."""
    if windows_backend.supported():
        return windows_backend.SNIFFER_TIMEOUT + 60
    return 120.0


def collect_hardware(out_dir, is_cancelled=None) -> Collected:
    """Scan this machine with the backend this host has, or raise typed."""
    if windows_backend.supported():
        return windows_backend.WindowsCollector().collect(
            out_dir, is_cancelled=is_cancelled)
    return collect_backend.ReportCollector().collect(out_dir)


def dump_acpi(out_dir, is_cancelled=None) -> Dumped:
    """Read this machine's firmware tables with the backend this host has."""
    if acpi_windows_backend.supported():
        return acpi_windows_backend.WindowsAcpiDumper().dump(
            out_dir, is_cancelled=is_cancelled)
    return acpi_backend.AcpiDumper().dump(out_dir, is_cancelled=is_cancelled)


__all__ = [
    "AcpiDumper",
    "Collected",
    "CollectionFailed",
    "CollectionRejected",
    "CollectionTimedOut",
    "CollectionUnsupported",
    "Dumped",
    "REPORT_FILE",
    "ReportCollector",
    "TablesDumpFailed",
    "TablesHelperMissing",
    "TablesRefused",
    "TablesTimedOut",
    "TablesUnsupported",
    "WindowsAcpiDumper",
    "WindowsCollector",
    "acpi_supported",
    "collect_hardware",
    "collect_supported",
    "collect_timeout",
    "dump_acpi",
    "helper_source",
    "policy_source",
    "reconcile_report",
    "trusted_helper",
]
