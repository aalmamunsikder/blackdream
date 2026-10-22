"""Per-session state: the vendored catalogues must not be written by a build.

`kext_data.kexts` and `acpi_patch_data.patches` are module-level lists, so binding an
instance to them directly makes every selection a process-global mutation: a second
build in the same process would inherit the first one's checked set, and a retried
build could not be reset. Both are deep-copied per instance now.

The copies are addressed through `kext_data.kext_index_by_name`, which maps name to an
integer index into the module list, so these tests also pin the invariant that makes
that safe: order preserved, same name at the same index.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ocengine import runtime
from ocengine.acpi_guru import ACPIGuru
from ocengine.datasets import acpi_patch_data, kext_data
from ocengine.kext_maestro import KextMaestro


@pytest.fixture(autouse=True)
def quiet_sink():
    previous = runtime.current_sink()
    runtime.set_sink(runtime.NullSink())
    yield
    runtime.set_sink(previous)


@pytest.fixture
def pristine_kexts():
    snapshot = [(kext.name, kext.checked) for kext in kext_data.kexts]
    yield
    assert [(kext.name, kext.checked) for kext in kext_data.kexts] == snapshot


def test_index_by_name_still_addresses_the_session_copy():
    maestro = KextMaestro()

    for name, index in kext_data.kext_index_by_name.items():
        assert maestro.kexts[index].name == name


def test_kext_catalogue_is_not_shared_between_instances(pristine_kexts):
    first = KextMaestro()
    second = KextMaestro()
    index = kext_data.kext_index_by_name["Lilu"]

    first.kexts[index].checked = "SENTINEL"

    assert second.kexts[index].checked is not first.kexts[index].checked
    assert kext_data.kexts[index].checked != "SENTINEL"


def test_kext_selection_is_reproducible_from_a_fresh_instance(pristine_kexts):
    """A retried build starts from the dataset defaults, not from the last run."""
    used = KextMaestro()
    for kext in used.kexts:
        kext.checked = True

    fresh = KextMaestro()

    assert [kext.checked for kext in fresh.kexts] == [
        kext.checked for kext in kext_data.kexts]


def test_acpi_patch_catalogue_is_not_shared():
    first = ACPIGuru()
    second = ACPIGuru()

    first.patches[0].checked = "SENTINEL"

    assert second.patches[0].checked is not True
    assert acpi_patch_data.patches[0].checked is not "SENTINEL"


def test_acpi_patch_count_and_dispatch_targets_survive_the_copy():
    guru = ACPIGuru()

    assert len(guru.patches) == len(acpi_patch_data.patches) == 26
    assert [patch.name for patch in guru.patches] == [patch.name for patch in acpi_patch_data.patches]
    for patch in guru.patches:
        assert hasattr(guru, patch.function_name), patch.function_name
