"""Where the untouched upstream clone sits, for the differential tests.

``test_engine_equivalence``, ``test_versions`` and ``diff_engine`` compare the vendored
engine against pristine OpCore Simplify at the pinned commit. The clone is a development
input, not part of the release, so its location is derived from the repository layout --
it sits beside the checkout -- and ``BLACKDREAM_PRISTINE`` overrides it. Every one of
these tests skips when the clone is missing, so a fresh checkout still passes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"


def pristine_root() -> Path:
    override = os.environ.get("BLACKDREAM_PRISTINE")
    if override:
        return Path(override)
    return REPO.parent / "OpCore-Simplify"


def is_available() -> bool:
    return (pristine_root() / "Scripts").is_dir()


def insert_paths() -> None:
    """Put the source tree, the clone and this directory on ``sys.path``."""
    for entry in (str(REPO / "src"), str(pristine_root()), str(TESTS)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
