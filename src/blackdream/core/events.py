"""Application-facing alias for the engine event sink.

Definitions live in ``ocengine.runtime``; ``set_sink``/``current_sink`` let a
host install its own listener. The Qt adapter that turns these calls into
``QObject`` signals lives in ``blackdream.ui``.
"""

from ocengine.runtime import (
    EngineSink,
    LoggingSink,
    NullSink,
    RecordingSink,
    Transfer,
    current_sink,
    set_sink,
)

__all__ = [
    "EngineSink",
    "LoggingSink",
    "NullSink",
    "RecordingSink",
    "Transfer",
    "current_sink",
    "set_sink",
]
