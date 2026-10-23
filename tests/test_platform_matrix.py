"""The host OS is a variable, so the platform decisions are tested, not assumed.

Only Linux can run in this environment, so the other hosts are simulated at the
boundary the code actually reads -- ``sys.platform``, ``os.name`` and
``platform.system()``. That covers path roots, toolchain selection, capability
gates and the guidance the window shows. It cannot prove a Windows PE or a Mach-O
executes; that needs the real OS.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from blackdream import hardware  # noqa: E402
from blackdream.hardware import acpi, collect, windows  # noqa: E402
from blackdream.hardware.acpi import TablesUnsupported  # noqa: E402
from blackdream.hardware.collect import CollectionUnsupported  # noqa: E402
from ocengine import dsdt, gathering_files, paths  # noqa: E402


# ---- where the app writes ----

def test_linux_uses_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths._data_root("posix", "linux") == tmp_path / "xdg" / "blackdream"


def test_linux_falls_back_to_the_home_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths._data_root("posix", "linux") == (
        tmp_path / ".local" / "share" / "blackdream")


def test_macos_uses_application_support(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths._data_root("posix", "darwin") == (
        tmp_path / "Library" / "Application Support" / "blackdream")


def test_windows_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert paths._data_root("nt", "win32") == tmp_path / "local" / "blackdream"


def test_windows_falls_back_when_localappdata_is_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths._data_root("nt", "win32") == (
        tmp_path / "AppData" / "Local" / "blackdream")


def test_the_engine_and_the_app_agree_on_the_data_root():
    assert paths.current().tools_dir.parent == paths._data_root()


# ---- iasl, per host ----

@pytest.mark.parametrize("platform,key", [
    ("win32", "win32"), ("darwin", "darwin"), ("linux", "linux"),
    ("linux2", "linux"), ("freebsd14", None),
])
def test_iasl_platform_key_recognises_every_supported_host(monkeypatch, platform, key):
    monkeypatch.setattr(dsdt.sys, "platform", platform)
    assert dsdt._platform_key() == key


@pytest.mark.parametrize("platform,stable,legacy", [
    ("linux", ("iasl-dev", "iasl-stable", "iasl"), ("iasl-legacy",)),
    ("darwin", ("iasl-dev", "iasl-stable", "iasl"), ("iasl-legacy",)),
    ("win32", ("iasl.exe",), ("iasl-legacy.exe",)),
])
def test_an_iasl_asset_and_a_name_allowlist_exist_for_each_host(
        monkeypatch, platform, stable, legacy):
    for variant in ("stable", "legacy"):
        assert (platform, variant) in dsdt.IASL_ASSETS
    monkeypatch.setattr(dsdt.sys, "platform", platform)
    probe = dsdt.DSDT.__new__(dsdt.DSDT)
    assert probe._candidate_names() == stable
    assert probe._candidate_names(legacy=True) == legacy
    assert probe._asset()["install_name"] in stable
    assert probe._asset(legacy=True)["install_name"] in legacy


def test_a_macos_install_never_picks_the_windows_asset(monkeypatch):
    monkeypatch.setattr(dsdt.sys, "platform", "darwin")
    probe = dsdt.DSDT.__new__(dsdt.DSDT)
    asset = probe._asset()
    assert asset["install_name"] == "iasl-stable"
    assert not asset["install_name"].endswith(".exe")


def test_an_unknown_host_refuses_to_guess_an_iasl_source(monkeypatch):
    monkeypatch.setattr(dsdt.sys, "platform", "freebsd14")
    probe = dsdt.DSDT.__new__(dsdt.DSDT)
    assert probe._asset() is None
    assert probe._candidate_names() == ()


# ---- macserial, per host ----

@pytest.mark.parametrize("os_name,platform,names", [
    ("Windows", "win32", ("macserial.exe",)),
    ("Darwin", "darwin", ("macserial",)),
    ("Linux", "linux", ("macserial.linux", "macserial")),
])
def test_every_host_has_a_pinned_macserial(monkeypatch, os_name, platform, names):
    monkeypatch.setattr(gathering_files, "os_name", os_name)
    probe = gathering_files.gatheringFiles.__new__(gathering_files.gatheringFiles)
    assert probe._macserial_platform_key() == platform
    assert probe._macserial_candidate_names() == names
    for name in names:
        assert (platform, name) in gathering_files.MACSERIAL_ASSETS


def test_an_unknown_host_has_no_macserial_build(monkeypatch):
    monkeypatch.setattr(gathering_files, "os_name", "FreeBSD")
    probe = gathering_files.gatheringFiles.__new__(gathering_files.gatheringFiles)
    with pytest.raises(gathering_files.MacserialUnsupportedPlatform):
        probe._macserial_candidate_names()


# ---- capability gates ----

@pytest.mark.parametrize("platform,builtin,windows_scan,acpi_read", [
    ("linux", True, False, True),
    ("linux2", True, False, True),
    ("win32", False, True, False),
    ("darwin", False, False, False),
    ("freebsd14", False, False, False),
])
def test_capabilities_follow_the_host(monkeypatch, platform,
                                      builtin, windows_scan, acpi_read):
    monkeypatch.setattr(sys, "platform", platform)
    assert collect.supported() is builtin
    assert windows.supported() is windows_scan
    assert acpi.supported() is acpi_read
    assert hardware.collect_supported() is (builtin or windows_scan)
    assert hardware.acpi_supported() is acpi_read


def test_the_windows_scan_gets_a_longer_job_deadline(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert hardware.collect_timeout() > windows.SNIFFER_TIMEOUT
    monkeypatch.setattr(sys, "platform", "linux")
    assert hardware.collect_timeout() == 120.0


def test_the_builtin_scan_refuses_other_hosts_without_touching_sysfs(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(CollectionUnsupported):
        collect.ReportCollector().collect(tmp_path)


def test_the_linux_acpi_reader_refuses_other_hosts_before_polkit(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(TablesUnsupported):
        acpi.AcpiDumper().dump(tmp_path)


# ---- the window's own gating and guidance ----

def test_the_window_imports_cleanly_with_the_new_capability_surface():
    from blackdream.ui import main_window
    assert callable(main_window._report_hint)


@pytest.mark.parametrize("platform,supported,hint", [
    ("win32", True,
     "Load a Report.json, or scan this machine with Hardware Sniffer."),
    ("linux", True,
     "Load a Report.json, or collect hardware from this machine."),
    ("darwin", False,
     "Load a Report.json exported by Hardware Sniffer on the target PC."),
])
def test_the_window_names_the_real_way_to_get_a_report(
        monkeypatch, platform, supported, hint):
    from blackdream.ui import main_window
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(main_window.hardware, "collect_supported", lambda: supported)
    assert main_window._report_hint() == hint


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("collect_ok,acpi_ok,collect_visible,acpi_visible", [
    (True, True, True, True),
    (True, False, True, False),
    (False, False, False, False),
])
def test_the_window_draws_only_the_actions_this_host_has(
        monkeypatch, qapp, collect_ok, acpi_ok, collect_visible, acpi_visible):
    from blackdream.ui import main_window
    monkeypatch.setattr(main_window.hardware, "collect_supported", lambda: collect_ok)
    monkeypatch.setattr(main_window.hardware, "acpi_supported", lambda: acpi_ok)
    win = main_window.MainWindow()
    try:
        # 3.0 opens on the Installer; the capability links live on Compatibility.
        win._show_view("Compatibility")
        assert win.collect_button.isVisibleTo(win) is collect_visible
        assert win.acpi_button.isVisibleTo(win) is acpi_visible
    finally:
        win.runner.cancel()
        win._ticker.stop()
