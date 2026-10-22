"""The one subprocess call the collector makes, replacing Hardware Sniffer's ``run.py``.

Upstream's runner is shared with its self-updater, so it carries a ``sudo`` prefix
mode, streamed ``print`` of child output, and no timeout.  None of that belongs in
a GUI: this takes a fixed argv list, never a shell, never elevates, and always
bounds the wait.  The return shape ``(stdout, stderr, returncode)`` is the one
``linux.py`` already expects.
"""

import subprocess

_TIMEOUT_SECONDS = 20


def run(argv):
    try:
        completed = subprocess.run(
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        # A missing probe binary is a normal condition here: lspci and lsusb both
        # come from util-linux package sets that a minimal distro may not install,
        # and the caller falls back to sysfs naming.
        return "", "", 1
    return (
        completed.stdout.decode("utf-8", errors="replace"),
        completed.stderr.decode("utf-8", errors="replace"),
        completed.returncode,
    )
