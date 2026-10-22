"""Runtime boundary for the engine: event sink + registry.

Kept inside ``ocengine`` on purpose. The engine raises and emits; the app
consumes. If these types lived in ``blackdream.core``, every vendored module
would import upward into the application layer and the file-level rebase onto
upstream (see VENDOR_NOTICE.txt) would become a merge of two codebases.

The registry is process-wide so no engine call site needs a signature change --
that is the whole reason it exists. A GUI, a CLI escape hatch, and the headless
test harness each install a sink at startup instead of threading one through
25 modules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass


@dataclass(frozen=True)
class Transfer:
    """Byte-level progress for one download, replacing the carriage-return bar."""

    product: str
    done_bytes: int
    total_bytes: int | None
    bytes_per_second: float

    @property
    def fraction(self) -> float | None:
        if not self.total_bytes:
            return None
        return min(1.0, self.done_bytes / self.total_bytes)


class EngineSink:
    """No-op base. Override only what a given host needs.

    The engine used to express all of this as terminal control codes:
    ``head()`` -> section, ``progress_bar()`` -> stage, the ``resource_fetcher``
    ``end="\\r"`` meter -> transfer, and ``request_input()`` gates -> notify.
    """

    def log(self, level: str, message: str) -> None:
        pass

    def section(self, title: str) -> None:
        """A named phase boundary. Replaces clear-screen-plus-Unicode-banner."""

    def stage(self, name: str, index: int, total: int, state: str = "running") -> None:
        """One step of a multi-stage job: pending, running, or done.

        Was a checklist redrawn by clearing the screen on every tick, which read
        as a flash rather than progress.
        """

    def transfer(self, event: Transfer) -> None:
        pass

    def notify(self, title: str, body: str = "", level: str = "info") -> None:
        """Non-blocking replacement for the "press Enter to continue" gates."""

    def warning(self, title: str, body: str = "") -> None:
        self.notify(title, body, level="warning")

    def error(self, title: str, body: str = "") -> None:
        self.notify(title, body, level="error")


class NullSink(EngineSink):
    """Default when nothing is listening."""


class RecordingSink(EngineSink):
    """Captures every event, for assertions in the headless harness."""

    def __init__(self) -> None:
        self.logs: list[tuple[str, str]] = []
        self.sections: list[str] = []
        self.stages: list[tuple[str, int, int, str]] = []
        self.transfers: list[Transfer] = []
        self.notifications: list[tuple[str, str, str]] = []

    def log(self, level: str, message: str) -> None:
        self.logs.append((level, message))

    def section(self, title: str) -> None:
        self.sections.append(title)

    def stage(self, name: str, index: int, total: int, state: str = "running") -> None:
        self.stages.append((name, index, total, state))

    def transfer(self, event: Transfer) -> None:
        self.transfers.append(event)

    def notify(self, title: str, body: str = "", level: str = "info") -> None:
        self.notifications.append((level, title, body))

    def messages_at_or_above(self, level: str) -> list[str]:
        order = {"debug": 10, "info": 20, "warning": 30, "error": 40}
        threshold = order.get(level, 0)
        return [msg for msg_level, msg in self.logs if order.get(msg_level, 0) >= threshold]


class LoggingSink(EngineSink):
    """Routes engine chatter into the standard logging tree."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("ocengine")

    def log(self, level: str, message: str) -> None:
        self.logger.log(getattr(logging, str(level).upper(), logging.INFO), message)

    def section(self, title: str) -> None:
        self.logger.info("--- %s ---", title)

    def stage(self, name: str, index: int, total: int, state: str = "running") -> None:
        self.logger.info("[%d/%d] %s (%s)", index + 1, total, name, state)

    def transfer(self, event: Transfer) -> None:
        if event.fraction is None:
            self.logger.info("%s: %d bytes", event.product, event.done_bytes)
        else:
            self.logger.info("%s: %.0f%% @ %.0f KB/s", event.product,
                             event.fraction * 100, event.bytes_per_second / 1024)

    def notify(self, title: str, body: str = "", level: str = "info") -> None:
        self.logger.log(getattr(logging, level.upper(), logging.INFO), "%s: %s", title, body)


_sink: EngineSink = NullSink()


def set_sink(sink: EngineSink) -> EngineSink:
    """Install the active sink, returning the previous one."""
    global _sink
    previous = _sink
    _sink = sink or NullSink()
    return previous


def current_sink() -> EngineSink:
    return _sink
