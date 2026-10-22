import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures
from blackdream.core import preflight
from ocengine.fatal import GpuMissingFromReport, StorageControllerMissing


@pytest.mark.parametrize("builder", [
    lambda: {**fixtures.coffee_lake_laptop(), "GPU": {}},
    lambda: {k: v for k, v in fixtures.coffee_lake_laptop().items() if k != "GPU"},
])
def test_absent_or_empty_gpu_is_rejected(builder):
    with pytest.raises(GpuMissingFromReport):
        preflight.check(builder())


@pytest.mark.parametrize("builder", [
    lambda: {**fixtures.coffee_lake_laptop(), "Storage Controllers": {}},
    lambda: {k: v for k, v in fixtures.coffee_lake_laptop().items() if k != "Storage Controllers"},
])
def test_absent_or_empty_storage_is_rejected(builder):
    with pytest.raises(StorageControllerMissing):
        preflight.check(builder())


@pytest.mark.parametrize("name", sorted(fixtures.ALL_HEALTHY) + sorted(fixtures.ALL_FATAL))
def test_preflight_passes_every_fixture_it_should(name):
    report = getattr(fixtures, name)()

    if name == "gpu_missing_from_report":
        with pytest.raises(GpuMissingFromReport):
            preflight.check(report)
    else:
        preflight.check(report)
