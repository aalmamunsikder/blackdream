"""An unhandled exception has to leave something behind in a windowed build.

The hook is the last line of defence for a ``console=False`` bundle: stderr is
attached to nothing, so a traceback that is not written down is simply gone, and a
beta report about "it closed" cannot be acted on.
"""

from __future__ import annotations

import itertools
import os
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ocengine.paths import EnginePaths  # noqa: E402

from blackdream import RELEASE_LABEL  # noqa: E402
from blackdream.core import crash_log  # noqa: E402


@pytest.fixture
def log_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ocengine.paths._current",
        EnginePaths(cache_dir=tmp_path / "cache", tools_dir=tmp_path / "tools",
                    log_dir=tmp_path / "logs"))
    return tmp_path


def raise_something():
    try:
        raise ValueError("the drive went away")
    except ValueError:
        return sys.exc_info()


def reports():
    directory = str(crash_log.report_dir())
    if not os.path.isdir(directory):
        return []
    return sorted(os.listdir(directory))


def test_report_dir_is_under_the_per_user_log_root(log_root):
    assert crash_log.report_dir() == log_root / "logs" / "crashes"


def test_a_report_carries_the_version_the_type_and_the_traceback(log_root):
    exc_type, exc, tb = raise_something()

    path = crash_log.write(exc_type, exc, tb)

    assert path is not None and os.path.isfile(path)
    text = open(path, encoding="utf-8").read()
    assert RELEASE_LABEL in text
    assert "ValueError: the drive went away" in text
    assert "raise_something" in text
    assert "Traceback" in text


def test_two_crashes_in_the_same_second_leave_two_reports(log_root):
    exc_type, exc, tb = raise_something()

    first = crash_log.write(exc_type, exc, tb)
    second = crash_log.write(exc_type, exc, tb)

    assert first != second
    assert os.path.basename(first).startswith("crash-")
    assert os.path.basename(first).endswith(".txt")
    assert len(reports()) == 2


def test_only_the_newest_reports_survive(log_root, monkeypatch):
    exc_type, exc, tb = raise_something()
    # A never-repeating stand-in for the clock, so 12 crashes look like 12 seconds.
    monkeypatch.setattr(crash_log.time, "strftime",
                        lambda _format: "{:08d}".format(next(itertools.count())))

    written = [os.path.basename(crash_log.write(exc_type, exc, tb)) for _ in range(12)]

    kept = reports()
    assert len(kept) == crash_log.MAX_REPORTS
    assert written[-1] in kept
    assert written[0] not in kept


def test_a_directory_that_cannot_be_written_is_not_another_crash(log_root):
    exc_type, exc, tb = raise_something()
    blocker = log_root / "logs"
    blocker.write_text("not a directory", encoding="utf-8")

    assert crash_log.write(exc_type, exc, tb) is None


def test_install_replaces_both_hooks(log_root, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", lambda *args: None)
    monkeypatch.setattr(threading, "excepthook", lambda args: None)

    crash_log.install()

    assert sys.excepthook is crash_log._hook
    assert threading.excepthook is crash_log._thread_hook


def test_the_hook_writes_and_does_not_raise(log_root, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    exc_type, exc, tb = raise_something()

    crash_log._hook(exc_type, exc, tb)

    assert len(reports()) == 1


def test_a_keyboard_interrupt_is_left_to_the_default_handler(log_root, monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *args: calls.append(args))
    monkeypatch.setattr(sys, "stderr", None)

    crash_log._hook(KeyboardInterrupt, KeyboardInterrupt(), None)

    assert len(calls) == 1
    assert reports() == []


def test_a_worker_thread_failure_is_written_down(log_root, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    crash_log.install()

    def body():
        raise RuntimeError("worker exploded")

    thread = threading.Thread(target=body, name="job-runner")
    thread.start()
    # The interpreter runs the hook before the thread signals it is finished, so
    # joining is enough; no need to poll for the file to appear.
    thread.join()

    assert len(reports()) == 1
    text = open(os.path.join(str(crash_log.report_dir()), reports()[0]),
                encoding="utf-8").read()
    assert "RuntimeError: worker exploded" in text
    assert "job-runner" in text
