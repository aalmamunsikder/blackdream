#!/usr/bin/env python3
"""Headless end-to-end build: report -> plan -> gather -> EFI -> verify.

This is the harness CI runs. It is not a second implementation: every stage is
the same ``Pipeline`` method the window calls, so a change that breaks here
breaks the application too. After the build it calls ``ocvalidate`` when a path
is supplied and always runs the pipeline's own post-build integrity check.

    tools/e2e_build.py --report Report.json --acpi-dir tables/ --output /tmp/EFI

Network access is required on the first run; later runs reuse the artifact
cache selected by ``XDG_DATA_HOME`` (or the platform's per-user data root).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="e2e_build.py",
        description="Build an EFI folder headlessly and verify it.")
    parser.add_argument("--report", required=True, metavar="PATH",
                        help="Report.json to build from")
    parser.add_argument("--output", required=True, metavar="DIR",
                        help="Folder the EFI is written into")
    parser.add_argument("--acpi-dir", metavar="DIR",
                        help="Folder of dumped ACPI tables, when the report has no DSDT")
    parser.add_argument("--macos", metavar="VERSION",
                        help="Darwin major or option name; defaults to the suggested version")
    parser.add_argument("--ocvalidate", metavar="PATH",
                        help="OpenCore ocvalidate binary to run after the build")
    parser.add_argument("--json", action="store_true",
                        help="Print the summary as one JSON object")
    return parser


def choose_version(options, wanted):
    """Resolve ``--macos`` against the choices the report actually offers."""
    if wanted is None:
        return next(option for option in options if option.is_suggested)
    probe = str(wanted).strip()
    for option in options:
        if probe in (option.value, str(option.darwin_major), option.name):
            return option
    raise SystemExit("macOS version {!r} is not offered for this report; choices: {}".format(
        wanted, ", ".join("{} ({})".format(option.name, option.value) for option in options)))


def _print_engine_errors(sink) -> None:
    for level, message in sink.logs:
        if level in ("warning", "error"):
            print("{}: {}".format(level, message), file=sys.stderr)


def _ocvalidate(path: str, config) -> dict:
    import subprocess

    process = subprocess.run(
        [path, str(config)], capture_output=True, text=True, timeout=120)
    output = (process.stdout + process.stderr).strip()
    return {
        "exit_code": process.returncode,
        "output": output,
        "ok": process.returncode == 0 and "No issues found" in output,
    }


def run(args) -> dict:
    sys.path.insert(0, str(ROOT / "src"))

    from blackdream.core.pipeline import Pipeline
    from ocengine.runtime import RecordingSink, set_sink

    sink = RecordingSink()
    set_sink(sink)

    started = time.monotonic()
    pipeline = Pipeline()
    analysis = pipeline.analyze(pipeline.load_report(args.report))
    choice = choose_version(pipeline.version_choices(analysis), args.macos)
    plan = pipeline.configure(analysis, choice.value, acpi_dir=args.acpi_dir)
    selected = [kext.name for kext in pipeline.kexts.kexts if kext.checked]

    pipeline.gather_artifacts(plan)
    result = Path(pipeline.build(plan, args.output))

    summary = {
        "ok": True,
        "report": str(Path(args.report).resolve()),
        "macos_version": choice.value,
        "macos_name": choice.name,
        "requires_oclp": choice.requires_oclp,
        "smbios_model": plan.smbios_model,
        "selected_kexts": selected,
        "checked_at_build": [kext.name for kext in pipeline.kexts.kexts if kext.checked],
        "efi": str(result),
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }

    if args.ocvalidate:
        validation = _ocvalidate(args.ocvalidate, result / "EFI" / "OC" / "config.plist")
        summary["ocvalidate"] = validation
        if not validation["ok"]:
            summary["ok"] = False
    return summary


def main(argv=None) -> int:
    args = _parser().parse_args(argv)

    from ocengine.fatal import EngineError
    from ocengine import runtime

    try:
        summary = run(args)
    except EngineError as error:
        # The sink holds the warnings that led up to the failure; print them
        # before the error so a CI log explains how the build got there.
        _print_engine_errors(runtime.current_sink())
        print("error: {}".format(error.code), file=sys.stderr)
        print(error.title, file=sys.stderr)
        if error.detail:
            print(error.detail, file=sys.stderr)
        for item in error.remediation:
            print("  - {}".format(item), file=sys.stderr)
        return 1
    except SystemExit:
        raise
    except Exception:
        _print_engine_errors(runtime.current_sink())
        traceback.print_exc()
        return 1

    _print_engine_errors(runtime.current_sink())

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("macOS {} ({}) · SMBIOS {}".format(
            summary["macos_name"], summary["macos_version"], summary["smbios_model"]))
        print("{} kexts selected, {} still selected at build time".format(
            len(summary["selected_kexts"]), len(summary["checked_at_build"])))
        print("EFI: {}".format(summary["efi"]))
        if "ocvalidate" in summary:
            print("ocvalidate: {}".format(
                "No issues found" if summary["ocvalidate"]["ok"] else "FAILED"))
        print("elapsed: {:.1f}s".format(summary["elapsed_seconds"]))

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
