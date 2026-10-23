"""Writing down the exceptions nobody caught.

A ``console=False`` build has no terminal: stderr is attached to nothing, so an
unhandled exception in a Qt slot would end the process with no evidence at all. The
engine's own failures reach the log view, but a defect in the window itself has to
leave something behind for a beta report to be written against.

Reports go to a directory the user already knows how to reach -- the same per-user root
as the artifact cache -- and are named with the moment they happened, because the
question asked of a crash is always "which one was this". Only the newest few survive,
so a crash loop cannot fill a disk with identical tracebacks.

Nothing here raises. A crash handler that crashes is worse than no crash handler, and
the directories it writes to are chosen by the user's environment: the home directory
may be read-only, full, or missing.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback

from blackdream import RELEASE_LABEL
from ocengine import paths

#: Crash reports kept before the oldest is discarded.
MAX_REPORTS = 5

# Worker threads can fail at the same instant, so the sequence that keeps two
# reports in the same second apart is handed out under a lock.
_lock = threading.Lock()
_sequence = 0


def report_dir():
    return paths.current().log_dir / "crashes"


def _header(exc_type, exc, thread=None) -> str:
    from platform import platform as system_platform

    return "\n".join((
        "BlackDream {}".format(RELEASE_LABEL),
        "Time: {}".format(time.strftime("%Y-%m-%dT%H:%M:%S%z")),
        "Platform: {}".format(system_platform()),
        "Process: {} ({})".format(os.getpid(), getattr(sys, "frozen", "source")),
        # Which thread died matters: a traceback from a worker describes a job,
        # one from the GUI thread describes the window.
        "Thread: {}".format(thread if thread is not None else "main"),
        "Exception: {}: {}".format(exc_type.__name__, exc),
        "",
    ))


def write(exc_type, exc, tb, thread=None) -> str | None:
    """Persist one report, returning its path or None when nothing could be written."""
    global _sequence
    directory = report_dir()
    try:
        os.makedirs(directory, exist_ok=True)
        with _lock:
            _sequence += 1
            sequence = _sequence
        # The seconds alone would let two crashes in the same second overwrite
        # each other, which is exactly what a crash loop does. Padded, so that
        # sorting the names as text is sorting them by when they happened.
        name = os.path.join(
            str(directory),
            "crash-{}-{}-{:05d}.txt".format(
                time.strftime("%Y%m%d-%H%M%S"), os.getpid(), sequence))
        body = "".join(traceback.format_exception(exc_type, exc, tb))
        with open(name, "w", encoding="utf-8", errors="replace") as handle:
            handle.write(_header(exc_type, exc, thread) + body)
        _prune(directory)
        return name
    except OSError:
        return None


def _prune(directory) -> None:
    """Keep the newest ``MAX_REPORTS``.

    Ordered by name, not mtime: the name carries the timestamp, and a copied or
    restored file keeps a mtime that no longer says when the crash happened.
    """
    try:
        entries = sorted(entry for entry in os.listdir(directory)
                         if entry.startswith("crash-") and entry.endswith(".txt"))
        for stale in entries[:-MAX_REPORTS] if MAX_REPORTS else entries:
            try:
                os.remove(os.path.join(str(directory), stale))
            except OSError:
                pass
    except OSError:
        pass


def _hook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    report = write(exc_type, exc, tb)
    stream = sys.stderr
    if stream is not None:
        try:
            stream.write("Unhandled error; {}.\n".format(
                "no report could be written" if report is None
                else "report written to " + report))
            stream.flush()
        except OSError:
            pass


def _thread_hook(args) -> None:
    name = args.thread.name if args.thread is not None else "unknown"
    report = write(args.exc_type, args.exc_value, args.exc_traceback, thread=name)
    stream = sys.stderr
    if stream is not None:
        try:
            stream.write("Unhandled error in {}; {}.\n".format(
                name,
                "no report could be written" if report is None
                else "report written to " + report))
            stream.flush()
        except OSError:
            pass


def install() -> None:
    sys.excepthook = _hook
    threading.excepthook = _thread_hook
