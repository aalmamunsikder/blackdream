"""Running engine work off the GUI thread, with a way to stop it.

The engine is synchronous and can spend minutes on one call -- downloading,
compiling ACPI tables, disassembling a DSDT. Upstream ran all of that on the
terminal's main thread, which is fine there and fatal in a window: the app would
simply stop painting.

So work goes to a worker thread, and the only control channel back is the
:class:`~blackdream.core.pipeline.CancelToken` the pipeline already accepts. Two
properties of that design are stated here rather than discovered later:

* Cancellation is cooperative. A thread blocked inside ``urlopen`` or ``iasl``
  keeps blocking until that call returns; we then discard its result. Nothing is
  killed mid-syscall, because Python cannot do that safely to a thread holding
  engine state.
* Progress is *not* carried here. Stages, sections and byte counters already
  arrive through the engine sink (``sink.stage`` / ``sink.section`` /
  ``sink.transfer``), so the runner only reports lifecycle. A second progress
  channel would be a second thing to keep in sync.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ocengine.fatal import EngineError

from blackdream.core.pipeline import CancelToken, Cancelled

DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
ABANDONED = "abandoned"


@dataclass(frozen=True)
class Job:
    """One unit of engine work. ``body`` receives the session's cancel token."""

    name: str
    body: Callable[[CancelToken], Any]
    #: Wall-clock budget. On expiry the token is cancelled; the thread is not.
    timeout: float | None = None


@dataclass(frozen=True)
class Outcome:
    job: str
    status: str
    value: Any = None
    error: EngineError | None = None
    #: Seconds spent in the worker, for the log line the UI prints.
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == DONE


class UnexpectedEngineFailure(EngineError):
    """An engine exception that is not one of the typed failures.

    Kept as an ``EngineError`` so the UI has one catch for everything a job can
    raise, and keeps the original type in ``detail`` -- "IndexError: list index
    out of range" is the line that makes a bug report actionable.
    """

    code = "engine.unexpected"
    title = "The engine failed unexpectedly"
    remediation = ("Retry the step. If it repeats, save the log from the Details "
                   "panel before reporting it.",)

    def __init__(self, exc: BaseException):
        self.detail = "{}: {}".format(type(exc).__name__, exc)
        super().__init__()


@dataclass
class JobRunner:
    """Single-flight job runner. ``on_outcome`` fires on whichever thread settles
    first -- the worker, or the timeout watchdog when the worker overruns.

    A Qt host must therefore receive it through a signal, not by touching widgets
    -- Qt queues cross-thread signal delivery onto the receiver's own thread.
    """

    on_outcome: Callable[[Outcome], None] | None = None
    #: How long to wait after cancelling before declaring the thread unreachable.
    grace: float = 5.0
    _thread: threading.Thread | None = field(default=None, repr=False)
    _token: CancelToken | None = field(default=None, repr=False)
    _cancel_requested: bool = field(default=False, repr=False)
    _timed_out: bool = field(default=False, repr=False)
    _settled: bool = field(default=False, repr=False)
    _finished: threading.Event = field(default_factory=threading.Event, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def busy(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, job: Job) -> bool:
        """Begin ``job``. False when one is already running -- the GUI disables
        its buttons, but a caller that ignores the return would otherwise get a
        second thread mutating the same Pipeline.

        An abandoned thread still counts as running: the pipeline object it is
        inside is not safe to re-enter, so the next build has to wait for the
        blocked system call to return rather than corrupt the session.
        """
        with self._lock:
            if self.busy:
                return False
            token = CancelToken()
            self._token = token
            self._cancel_requested = False
            self._timed_out = False
            self._settled = False
            self._finished.clear()
            self._thread = threading.Thread(
                target=self._guard, args=(job, token), name="blackdream-{}".format(job.name),
                daemon=True)
            self._thread.start()
            return True

    def cancel(self) -> bool:
        """Ask the running job to stop. True if there was something to stop."""
        with self._lock:
            token, self._cancel_requested = self._token, True
        if token is None:
            return False
        token.cancel()
        return True

    def run_now(self, job: Job) -> Outcome:
        """Run on the calling thread. Used by tests and by any headless host."""
        token = CancelToken()
        with self._lock:
            self._token, self._cancel_requested, self._timed_out = token, False, False
        return self._execute(job, token)

    # ---- internals ----

    def _guard(self, job: Job, token: CancelToken) -> None:
        watchdog = None
        if job.timeout:
            watchdog = threading.Timer(job.timeout, self._expire, args=(job, token))
            watchdog.daemon = True
            watchdog.start()
        try:
            outcome = self._execute(job, token)
        finally:
            if watchdog is not None:
                watchdog.cancel()
        self._finished.set()
        self._settle(outcome)

    def _expire(self, job: Job, token: CancelToken) -> None:
        with self._lock:
            if self._cancel_requested:
                return
            self._timed_out = True
        # Cooperative only: give the stage a chance to unwind, then stop waiting
        # on it. Nothing is killed mid-syscall.
        if self._finished.wait(self.grace):
            return
        self._settle(Outcome(job=job.name, status=ABANDONED,
                             error=JobAbandoned(job.name, job.timeout, self.grace)))

    def _execute(self, job: Job, token: CancelToken) -> Outcome:
        started = time.monotonic()
        try:
            value = job.body(token)
            status, error, result = DONE, None, value
        except Cancelled:
            status, error, result = (ABANDONED if self._timed_out else CANCELLED), None, None
        except EngineError as exc:
            status, error, result = FAILED, exc, None
        except Exception as exc:  # a bug in the engine must not kill the app
            status, error, result = FAILED, UnexpectedEngineFailure(exc), None
        return Outcome(job=job.name, status=status, value=result, error=error,
                       elapsed=time.monotonic() - started)

    def _settle(self, outcome: Outcome) -> None:
        """Deliver at most once: whoever notices the end first wins."""
        with self._lock:
            if self._settled:
                return
            self._settled = True
            self._token = None
        if self.on_outcome is not None:
            self.on_outcome(outcome)


class JobAbandoned(EngineError):
    """A job whose budget expired and whose worker never unwound in time."""

    code = "job.abandoned"
    title = "That step stopped responding"

    def __init__(self, name, timeout, grace):
        self.detail = (
            "{name} exceeded its {budget} s budget and is still blocked in a system "
            "call {grace} s after cancellation.".format(
                name=name, budget="{:g}".format(timeout or 0),
                grace="{:g}".format(grace)))
        self.remediation = (
            "Its result will be ignored. New steps stay blocked until that call returns, "
            "so if the window hangs, quit and reopen the app.",)
        super().__init__()
