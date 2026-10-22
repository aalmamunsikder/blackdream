"""Application entry point.

Nothing here builds an EFI folder; it parses arguments and shows the window. Two
rules matter more than the wiring:

* The window installs its own sink as it is constructed, before any engine object
  exists, because the engine logs while it is being constructed -- and those
  messages are the first thing needed when start-up fails.
* No engine work runs on the GUI thread.

There is deliberately no CLI for the build itself. ``--report`` and ``--output`` only
pre-fill the window's fields; the user still presses the button. Upstream shipped a
terminal menu because that was the only UI available, not because anyone asked for one.
"""

from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtWidgets import QApplication

from blackdream import __version__
from blackdream.ui.main_window import MainWindow


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blackdream", description="BlackDream OpenCore EFI builder")
    parser.add_argument("--report", metavar="PATH",
                        help="Report.json to load when the window opens")
    parser.add_argument("--output", metavar="DIR", help="Folder to write the EFI into")
    parser.add_argument("--acpi-dir", metavar="DIR",
                        help="Folder of ACPI tables, when no DSDT ships with the report")
    parser.add_argument("--smoke", action="store_true",
                        help="Build the window, render one frame, exit 0. For CI and packaging.")
    parser.add_argument("--version", action="version", version="blackdream {}".format(__version__))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.smoke and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("BlackDream")
    app.setOrganizationName("BlackDream")
    app.setApplicationDisplayName("BlackDream")

    window = MainWindow()

    if args.output:
        window.set_output_dir(args.output)
    if args.acpi_dir:
        window.set_acpi_dir(args.acpi_dir)
    if args.report:
        window.set_report(args.report)

    if args.smoke:
        window.show()
        app.processEvents()
        print("blackdream {} smoke ok: platform={}".format(
            __version__, app.platformName()))
        return 0

    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
