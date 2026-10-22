"""Adapting the engine's event sink to a GUI thread.

The engine calls its sink synchronously from whatever thread is doing the work --
now the worker thread, whereas upstream it was the terminal's main thread. Touching
a widget from there is undefined behaviour in Qt, so nothing here touches a widget:
the bridge records events into bounded buffers and the window drains them from its
own thread on a timer.

Bounded on purpose. A build emits thousands of byte-counters and log lines; an
unbounded queue behind a window the user is not looking at is a memory leak with a
nice error message later. Transfers are gauge-like, so only the newest value per
download is kept; logs are queue-like, so the oldest fall off the front.
"""

from __future__ import annotations

import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from ocengine.runtime import EngineSink, Transfer

MAX_LOGS = 4000
MAX_NOTIFICATIONS = 200
#: Log levels worth showing in the panel at all, in the order the filter offers them.
LEVELS = ("debug", "info", "warning", "error")


@dataclass(frozen=True)
class Drain:
    """One timer tick's worth of engine events.

    ``stages`` is ``[(name, total, state)]`` in the order the checklist emitted
    them; ``transfers`` is the newest value seen per product name.
    """

    logs: list = field(default_factory=list)
    dropped_logs: int = 0
    sections: list = field(default_factory=list)
    stages: list = field(default_factory=list)
    transfers: list = field(default_factory=list)
    notifications: list = field(default_factory=list)


class EngineBridge(EngineSink):
    """Thread-safe capture of every engine event a window might render."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._logs: deque = deque(maxlen=MAX_LOGS)
        self._notifications: deque = deque(maxlen=MAX_NOTIFICATIONS)
        self._sections: deque = deque(maxlen=64)
        self._transfers: OrderedDict[str, Transfer] = OrderedDict()
        self._stages: list[tuple[str, int, str]] = []
        self._logs_since = 0
        self._dropped_logs = 0

    # ---- called from the worker thread ----

    def log(self, level: str, message: str) -> None:
        with self._lock:
            if len(self._logs) == self._logs.maxlen:
                self._dropped_logs += 1
            self._logs.append((str(level), str(message)))
            self._logs_since += 1

    def section(self, title: str) -> None:
        with self._lock:
            self._sections.append(str(title))

    def stage(self, name: str, index: int, total: int, state: str = "running") -> None:
        with self._lock:
            # Utils.progress_bar() emits the whole checklist per tick and always
            # starts a tick at index 0, so that is where a new list begins. Anything
            # else would render a torn mixture of two different step sets.
            if index == 0 or not self._stages:
                self._stages = []
            if len(self._stages) == index:
                self._stages.append((str(name), int(total), str(state)))

    def transfer(self, event: Transfer) -> None:
        with self._lock:
            self._transfers[event.product] = event

    def notify(self, title: str, body: str = "", level: str = "info") -> None:
        with self._lock:
            self._notifications.append((str(level), str(title), str(body)))

    # ---- called from the GUI thread ----

    def drain(self) -> Drain:
        """Take everything pending since the last call, for rendering.

        Log lines are returned only once, so a window can append rather than
        re-render. Transfers and stages are the newest state, not a history.
        """
        with self._lock:
            pending = min(self._logs_since, len(self._logs))
            self._logs_since = 0
            dropped, self._dropped_logs = self._dropped_logs, 0
            logs = list(self._logs)[-pending:] if pending else []
            sections = list(self._sections)
            self._sections.clear()
            notifications = list(self._notifications)
            self._notifications.clear()
            transfers = list(self._transfers.values())
            self._transfers.clear()
            stages = list(self._stages)
        return Drain(logs=logs, dropped_logs=dropped, sections=sections, stages=stages,
                     transfers=transfers, notifications=notifications)

    def tail(self, count: int = 200) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._logs)[-count:]

    def reset(self) -> None:
        with self._lock:
            self._logs.clear()
            self._notifications.clear()
            self._sections.clear()
            self._stages = []
            self._transfers.clear()
            self._logs_since = 0
            self._dropped_logs = 0


class JobSignals(QObject):
    """Marshals one job's :class:`Outcome` onto the GUI thread.

    ``Signal(object)`` with the emitter on a worker thread: Qt queues the call and
    runs the receiver in the thread that owns this object, which is the only safe
    way in.
    """

    finished = Signal(object)
