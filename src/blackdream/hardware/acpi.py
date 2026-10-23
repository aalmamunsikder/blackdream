"""Getting the firmware ACPI tables, which is the one Linux step that needs root.

The scan in :mod:`blackdream.hardware.collect` is unprivileged because sysfs exposes
PCI, DMI and sound information to anyone.  It cannot reach a DSDT:
``/sys/firmware/acpi/tables`` is ``0400 root:root``, and the engine needs the table
itself -- ``ACPIGuru`` disassembles it, applies the vendor pre-patches, and compiles
its SSDTs against it.  So a build on Linux stops here unless the app can cross that
line, which is why the helper below exists.

Two properties of polkit shape this module.  ``pkexec`` does not validate arguments,
and its documentation warns that a helper whose authorization can be retained must
never trust user input, so :mod:`blackdream.hardware.dump_acpi_tables` takes none: it
makes a directory of its own and prints the path.  And when no agent is reachable,
``pkexec`` registers a *textual* agent on ``/dev/tty`` -- over SSH, or in a session
with no desktop agent, that is a hang rather than an error.  So the internal agent is
switched off, and the call is polled with a timeout and a cancel check.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ocengine.fatal import EngineError
from ocengine.utils import Utils

from .dump_acpi_tables import TABLE_DIR
from blackdream.core.pipeline import Cancelled

ACPI_SUBDIR = "ACPI"
HELPER_NAME = "dump_acpi_tables.py"
POLICY_NAME = "com.blackdream.dumpacpi.policy"
#: Where the packaged helper belongs.  Anywhere the calling user can write is refused
#: by :func:`trusted_helper`, because root would be running editable code.
INSTALLED_HELPER = Path("/usr/lib") / "blackdream" / HELPER_NAME
HELPER_ENV = "BLACKDREAM_ACPI_HELPER"
HELPER_PREFIX = "blackdream-acpi-"

#: Documented pkexec return values: the dialog was closed (126), or authorization was
#: not obtained / an error occurred (127).  Anything else is the helper's own code.
DISMISSED = 126
REFUSED = 127

POLL_SECONDS = 0.5
DEFAULT_TIMEOUT = 240.0

_TABLE_FILE = re.compile(r"^(?P<name>[A-Z][A-Za-z0-9]{1,15}(-?[0-9]{1,3})?)\.aml$")


class TablesUnsupported(EngineError):
    code = "acpi.unsupported"
    title = "These firmware tables cannot be read from inside the app"
    detail = "Dumping tables from sysfs is a Linux feature; this is {}.".format(sys.platform)
    remediation = ("Point the ACPI tables folder at a folder of .aml tables exported by "
                   "Hardware Sniffer.",)


class TablesHelperMissing(EngineError):
    code = "acpi.helper_missing"
    title = "The helper that reads firmware tables is not installed"
    remediation = ("Install it where only root can change it: sudo install -m 0755 -o root "
                   "-g root «helper» " + INSTALLED_HELPER.as_posix(),
                   "then register its action: sudo cp «policy» /usr/share/polkit-1/actions/",
                   "Or run the helper yourself with sudo, and point the ACPI tables folder "
                   "at the directory it prints.")


class TablesRefused(EngineError):
    code = "acpi.refused"
    title = "Reading the ACPI tables was not authorised"
    remediation = ("Nothing was read, written, or sent.",
                   "Try again and accept the system authentication window, or point the "
                   "ACPI tables folder at tables you dumped another way.")


class TablesDumpFailed(EngineError):
    code = "acpi.dump_failed"
    title = "The firmware tables could not be read"
    remediation = ("Try again. If it repeats, this machine does not expose a readable DSDT "
                   "even to root.",
                   "Point the ACPI tables folder at a folder of .aml tables exported by "
                   "Hardware Sniffer instead.")


class TablesTimedOut(EngineError):
    code = "acpi.timed_out"
    title = "No answer to the authorisation window"
    remediation = ("The system authentication window may be behind this one. Nothing was "
                   "read; the request is safe to repeat.",)

    def __init__(self, timeout: float) -> None:
        self.detail = "The authorisation request waited {:g} s and was withdrawn.".format(
            timeout)
        super().__init__()


@dataclass(frozen=True)
class Dumped:
    acpi_dir: Path
    tables: tuple[str, ...]


def supported() -> bool:
    return sys.platform.startswith("linux")


def package_dir() -> Path:
    return Path(os.path.dirname(os.path.realpath(__file__)))


def helper_source() -> Path:
    """The helper shipped inside this package -- user-writable in a checkout."""
    return package_dir() / HELPER_NAME


def policy_source() -> Path:
    return package_dir() / POLICY_NAME


def trusted_helper() -> Path | None:
    """The helper root may be asked to execute, or None if there is no such file.

    Trust here is ownership and mode, not location: the file must exist, be executable,
    be owned by root, and not be writable by group or other.  Otherwise whoever owns it
    could edit it between the prompt and the read and have root run the edit.  A source
    checkout and an unpacked archive both fail that test, which is why the packaged
    install puts the helper under ``/usr/lib`` and why
    :class:`TablesHelperMissing` hands the user the ``install`` command instead of
    trying anyway.
    """
    configured = os.environ.get(HELPER_ENV)
    candidates = ([Path(configured)] if configured else []) + [INSTALLED_HELPER,
                                                               helper_source()]
    for candidate in candidates:
        try:
            info = os.stat(candidate)
        except OSError:
            continue
        if not os.access(candidate, os.X_OK):
            continue
        if info.st_uid == 0 and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return candidate.resolve()
    return None


class AcpiDumper:
    """Runs the privileged helper and adopts the folder it produces.

    ``helper`` and ``pkexec`` are injectable so the tests can drive a fake helper
    without asking polkit anything; :func:`trusted_helper` stays the only path used
    in production.
    """

    def __init__(self, utils: Utils | None = None, timeout: float = DEFAULT_TIMEOUT,
                 helper: str | Path | None = None, pkexec: str = "pkexec") -> None:
        self.utils = utils or Utils()
        self.timeout = timeout
        self._helper = Path(helper) if helper is not None else None
        self.pkexec = pkexec

    @property
    def helper(self) -> Path:
        if self._helper is not None:
            return self._helper
        helper = trusted_helper()
        if helper is None:
            raise TablesHelperMissing(detail=(
                "No root-owned {} was found; this build carries the helper at "
                "{}.".format(INSTALLED_HELPER.name, helper_source())))
        return helper

    def dump(self, out_dir: str | Path,
             is_cancelled: Callable[[], bool] | None = None) -> Dumped:
        if not supported():
            raise TablesUnsupported()

        helper = self.helper
        sink = self.utils.sink
        sink.section("Reading ACPI tables")
        sink.log("info", "Asking the system for permission to read {}.".format(TABLE_DIR))
        sink.notify("Reading ACPI tables",
                    "A system authentication window may ask for administrator rights.")

        code, out, err = self._run([self.pkexec, "--disable-internal-agent", str(helper)],
                                   is_cancelled)
        if code == DISMISSED:
            raise TablesRefused(detail="The authentication window was closed.")
        if code == REFUSED:
            raise TablesRefused(detail=_tail(err) or "polkit refused the request.")
        if code != 0:
            raise TablesDumpFailed(detail=_tail(err) or
                                   "The helper exited with code {}.".format(code))

        source = _announced_dir(out)
        tables = _dumped_tables(source)
        if not tables:
            raise TablesDumpFailed(detail="{} holds no ACPI tables.".format(source))

        destination = Path(self.utils.normalize_path(str(out_dir))) / ACPI_SUBDIR
        destination.mkdir(parents=True, exist_ok=True)
        for name in tables:
            shutil.move(str(source / (name + ".aml")), str(destination / (name + ".aml")))
        # The helper made this directory in its own temp root and handed it over. The
        # tables now live with the report they describe, so no copy of the firmware is
        # left sitting in a world-readable place owned by this user.
        shutil.rmtree(str(source), ignore_errors=True)
        sink.log("info", "{} ACPI tables read from firmware".format(len(tables)))
        sink.log("info", "ACPI tables written to {}".format(destination))
        return Dumped(acpi_dir=destination, tables=tuple(tables))

    def _run(self, argv: list[str],
             is_cancelled: Callable[[], bool] | None) -> tuple[int, str, str]:
        """Wait for the helper, checking for a stop as it goes.

        Cancelling while the authentication request is outstanding is genuinely safe:
        pkexec has not started the helper yet, so there is nothing to unwind.
        """
        if shutil.which(argv[0]) is None:
            raise TablesHelperMissing(detail=(
                "{} is not installed. It comes with polkit on every system that has one."
                .format(argv[0])))
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, errors="replace")
        except OSError as exc:
            raise TablesDumpFailed(detail="Could not start {}: {}".format(argv[0], exc))

        deadline = time.monotonic() + self.timeout
        while True:
            try:
                out, err = proc.communicate(timeout=POLL_SECONDS)
                return proc.returncode, out, err
            except subprocess.TimeoutExpired:
                if is_cancelled is not None and is_cancelled():
                    _kill(proc)
                    raise Cancelled() from None
                if time.monotonic() >= deadline:
                    _kill(proc)
                    raise TablesTimedOut(self.timeout) from None


def _kill(proc: subprocess.Popen) -> None:
    """Stop the client. An authenticated helper that had already started keeps its own
    temp directory; nothing is left writable by root in a shared path."""
    proc.kill()
    try:
        proc.communicate(timeout=POLL_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _tail(text: str) -> str:
    """The helper's own reason, which it writes to stderr and never to stdout."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _announced_dir(out: str) -> Path:
    """The directory the helper printed, verified rather than trusted.

    It must be absolute, real, and named like a dump, so a malfunctioning helper cannot
    direct the app to move files out of somewhere else.
    """
    lines = [line.strip() for line in (out or "").splitlines() if line.strip()]
    if not lines:
        raise TablesDumpFailed(detail="The helper reported no folder.")
    path = Path(lines[-1])
    if not path.is_absolute() or not path.name.startswith(HELPER_PREFIX):
        raise TablesDumpFailed(detail="The helper reported an unexpected folder: {}"
                                      .format(path))
    if not path.is_dir():
        raise TablesDumpFailed(detail="{} does not exist.".format(path))
    return path


def _dumped_tables(source: Path) -> list[str]:
    """Table names in a dump folder, from the ``<NAME>.aml`` files the helper wrote."""
    names = []
    for entry in sorted(os.listdir(source)):
        match = _TABLE_FILE.match(entry)
        if match and (source / entry).is_file():
            names.append(match.group("name"))
    return names
