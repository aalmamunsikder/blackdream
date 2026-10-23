"""Golden compatibility verdicts, captured from the pristine upstream engine.

Baseline recorded on 2026-10-22 by running ``Scripts.compatibility_checker`` from
the untouched upstream clone (pinned ``f0e1e44``, located by ``tests/pristine.py``)
with stdin stubbed, over the fixtures in ``tests/fixtures.py``. Upstream signalled
a fatal verdict by printing ANSI colour and calling ``sys.exit(0)``; ours raises a
typed ``FatalIncompatibility`` and emits plain text to the sink. The device verdicts
themselves must not drift.
"""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ocengine import runtime
from ocengine.compatibility_checker import CompatibilityChecker
from ocengine.fatal import (
    CpuNoSse4,
    GpuUnsupported,
    NoCompatibleStorage,
    StorageIntelVmdEnabled,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixtures

# Pristine upstream verdicts. Tuple is (min_native, max_native) darwin versions.
HEALTHY_BASELINE = {
    "alder_lake_desktop": ("21.2.0", "25.99.99"),
    "coffee_lake_laptop": ("17.0.0", "25.99.99"),
    "raven_ridge_amd_laptop": ("19.0.0", "25.99.99"),
}

FATAL_BASELINE = {
    "cpu_without_sse4": CpuNoSse4,
    "gpu_unsupported": GpuUnsupported,
    "intel_vmd_storage": StorageIntelVmdEnabled,
    "no_compatible_storage": NoCompatibleStorage,
}


@pytest.fixture
def sink():
    previous = runtime.current_sink()
    recorder = runtime.RecordingSink()
    runtime.set_sink(recorder)
    yield recorder
    runtime.set_sink(previous)


def evaluate(report):
    """Run the checker the way the pipeline does, with the terminal gate removed."""
    with mock.patch("builtins.input", lambda *args, **kwargs: ""):
        return CompatibilityChecker().check_compatibility(json.loads(json.dumps(report)))


@pytest.mark.parametrize("name", sorted(HEALTHY_BASELINE))
def test_healthy_report_grades_as_upstream(name, sink):
    _report, native, ocl = evaluate(getattr(fixtures, name)())

    assert tuple(native) == HEALTHY_BASELINE[name]
    assert ocl is None
    assert sink.messages_at_or_above("error") == []


@pytest.mark.parametrize("name,expected", sorted(FATAL_BASELINE.items()))
def test_fatal_report_raises_typed_instead_of_exiting(name, expected, sink):
    with pytest.raises(expected) as caught:
        evaluate(getattr(fixtures, name)())

    error = caught.value
    assert error.recoverable is expected.recoverable
    assert error.detail
    assert error.remediation


def test_engine_never_writes_to_stdout(sink, capsys):
    """Every engine message must reach the sink; stdout stays empty."""
    evaluate(fixtures.coffee_lake_laptop())

    assert capsys.readouterr().out == ""
    assert sink.logs
    assert not any("\x1b[" in message for _level, message in sink.logs)


def test_empty_gpu_section_is_an_upstream_hole(sink):
    """Upstream gates each check on ``report.get(section)``, so a present-but-empty
    ``GPU`` dict skips grading entirely and the build proceeds for a machine with no
    graphics. Vendored grading stays byte-faithful; ``blackdream.core.preflight`` is
    what rejects this shape before the engine runs.
    """
    _report, native, _ocl = evaluate(fixtures.gpu_missing_from_report())

    assert tuple(native) == HEALTHY_BASELINE["coffee_lake_laptop"]
