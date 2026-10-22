"""Application-facing alias for engine failure types.

Definitions live in ``ocengine.fatal`` so the vendored engine never imports the
application layer; this module exists so UI and CLI code has one obvious place
to import from.
"""

from ocengine.fatal import (
    CpuNoSse4,
    EngineError,
    ExitRequested,
    FATAL_BY_CODE,
    FatalIncompatibility,
    GpuMissingFromReport,
    GpuUnsupported,
    InteractivePrompt,
    NoCompatibleStorage,
    StorageControllerMissing,
    StorageIntelVmdEnabled,
)

__all__ = [
    "CpuNoSse4",
    "EngineError",
    "ExitRequested",
    "FATAL_BY_CODE",
    "FatalIncompatibility",
    "GpuMissingFromReport",
    "GpuUnsupported",
    "InteractivePrompt",
    "NoCompatibleStorage",
    "StorageControllerMissing",
    "StorageIntelVmdEnabled",
]
