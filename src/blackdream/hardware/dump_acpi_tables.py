#!/usr/bin/python3
"""Dump the firmware ACPI tables, so the app has a DSDT to patch.

This file runs as root.  It is reached through polkit (``pkexec`` with the
``com.blackdream.dumpacpi`` action) because ``/sys/firmware/acpi/tables`` is
``0400 root:root`` on every Linux we have measured, and there is no unprivileged
route to a DSDT: ``/dev/mem`` is behind ``CONFIG_STRICT_DEVMEM``, and the tables
are not in ``efivarfs``.

It deliberately accepts **no arguments and no environment overrides**.  pkexec
documents that it does no validation of ``ARGUMENTS``, and that a program whose
required authorization can be retained must never trust user input -- so a
helper that took an output path would be a way to overwrite root-owned files.
Instead it makes a directory of its own, fills it, and hands ownership of that
directory to the user who asked.

The shebang is an absolute interpreter path: PATH under pkexec is a minimal
reconstructed one, and privileged code should not depend on it.
"""

import os
import re
import shutil
import stat
import sys
import tempfile

TABLE_DIR = "/sys/firmware/acpi/tables"

#: A firmware table is a few hundred kilobytes; the largest we measured here was
#: a 245 KB DSDT.  The cap is for a corrupted sysfs attribute, not a real file.
MAX_TABLE_BYTES = 8 << 20

# Kernel table names are a normalised ACPI signature plus an index for repeats:
# ``DSDT``, ``SSDT1``, ``APIC``.  No dots (which would allow ``..``), no slashes,
# no leading dash (which would look like an option).
_NAME = re.compile(r"^[A-Z][A-Za-z0-9]{1,15}(-?[0-9]{1,3})?$")


class DumpFailed(Exception):
    """Something the calling user could act on went wrong."""


def table_names(source=TABLE_DIR):
    """Readable table file names in ``source``, sorted, symlinks excluded.

    Sub-directories (``data``, ``dynamic``) are not tables and are skipped: the
    engine accepts a folder of raw AML and finds the DSDT by signature.
    """
    names = []
    for entry in sorted(os.listdir(source)):
        path = os.path.join(source, entry)
        if not _NAME.match(entry):
            continue
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        names.append(entry)
    return names


def dump_into(dest_dir, source=TABLE_DIR):
    """Copy every table in ``source`` into ``dest_dir`` as ``<NAME>.aml``.

    Returns the names written.  A table that cannot be read is skipped rather
    than fatal: a machine with an unreadable optional table still has a DSDT,
    and a partial folder builds.  Nothing here touches the network or executes a
    program, and no name that reaches ``open`` comes from the caller.
    """
    try:
        names = table_names(source)
    except OSError as exc:
        raise DumpFailed("cannot read {}: {}".format(source, exc))
    if not names:
        raise DumpFailed("{} holds no ACPI tables.".format(source))

    written = []
    for name in names:
        src = os.path.join(source, name)
        try:
            with open(src, "rb") as handle:
                data = handle.read(MAX_TABLE_BYTES + 1)
        except OSError as exc:
            print("skipped {}: {}".format(name, exc), file=sys.stderr)
            continue
        if len(data) > MAX_TABLE_BYTES:
            print("skipped {}: larger than {} bytes".format(name, MAX_TABLE_BYTES),
                  file=sys.stderr)
            continue
        if len(data) < 4:
            print("skipped {}: not an ACPI table".format(name), file=sys.stderr)
            continue
        # The first four bytes are the signature; the engine reads them back out
        # of the file, so the extension is for the user and the picker only.
        with open(os.path.join(dest_dir, "{}.aml".format(name)), "wb") as handle:
            handle.write(data)
        written.append(name)

    if not written:
        raise DumpFailed("no ACPI table could be read from {}.".format(source))
    if not any(name.startswith("DSDT") for name in written):
        raise DumpFailed("the firmware exposed no DSDT; every table is a supplement "
                         "to it, so there is nothing to patch.")
    return written


def _caller_ids():
    """The uid/gid of whoever asked for the dump.

    pkexec scrubs the environment and sets ``PKEXEC_UID``; ``sudo`` sets
    ``SUDO_UID``/``SUDO_GID``.  Either is enough to hand the folder back, and
    without one the files would stay root-owned and unreadable, so this refuses
    rather than leaving a directory nobody can use.
    """
    uid = os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID")
    gid = os.environ.get("SUDO_GID") or uid
    try:
        uid, gid = int(uid), int(gid)
    except (TypeError, ValueError):
        raise DumpFailed("cannot tell which user asked for the dump.") from None
    if uid == 0:
        raise DumpFailed("asked by root, so there is no user to hand the tables to.")
    return uid, gid


def main():
    if os.geteuid() != 0:
        raise DumpFailed("must run as root: use pkexec, or sudo -- {} reads "
                         "{}.".format(os.path.basename(__file__), TABLE_DIR))
    uid, gid = _caller_ids()

    dest = tempfile.mkdtemp(prefix="blackdream-acpi-")
    try:
        written = dump_into(dest)
        os.chmod(dest, stat.S_IRWXU)                      # 0700, then handed over
        for entry in os.listdir(dest):
            os.chmod(os.path.join(dest, entry), stat.S_IRUSR | stat.S_IWUSR)  # 0600
        shutil.chown(dest, user=uid, group=gid)
        for entry in os.listdir(dest):
            shutil.chown(os.path.join(dest, entry), user=uid, group=gid)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    # The one thing on stdout: the app reads this line, moves the files into the
    # report folder it owns, and removes the directory.
    print(dest)
    print("{} ACPI tables written to {}".format(len(written), dest), file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DumpFailed as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
