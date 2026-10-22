"""Where a runtime binary may be looked up, and where a download may be written.

``iasl`` and ``macserial`` are both fetched at run time and then executed, so the
directory they land in is the one place a download can turn into code execution.
These tests pin the policy that ``ocengine.paths`` now owns for both of them.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ocengine import dsdt, paths  # noqa: E402

PACKAGE_DIR = os.path.dirname(os.path.abspath(dsdt.__file__))


def test_the_package_directory_is_never_an_install_target(monkeypatch):
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", PACKAGE_DIR)
    assert paths.is_on_import_path(PACKAGE_DIR) is True
    # tools_dirs() still lists it -- dsdt logs a refusal per directory, and a
    # silent omission would hide an operator's mistake. What must never happen is
    # the install target or the lookup resolving to it.
    assert paths.install_tools_dir() != PACKAGE_DIR
    assert paths.is_on_import_path(paths.install_tools_dir()) is False


def test_a_binary_inside_an_import_path_directory_is_never_executed(monkeypatch, tmp_path):
    planted = tmp_path / "pkg"
    planted.mkdir()
    binary = planted / "iasl"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(planted))
    monkeypatch.setattr(paths, "_current", paths.EnginePaths(
        cache_dir=tmp_path / "cache", tools_dir=tmp_path / "empty-tools"))
    sys.path.append(str(planted))
    try:
        assert paths.is_on_import_path(str(planted)) is True
        assert dsdt.DSDT().check_iasl(try_downloading=False) is None
    finally:
        sys.path.remove(str(planted))


def test_a_directory_inside_the_source_tree_is_refused_too(monkeypatch):
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", os.path.dirname(PACKAGE_DIR))
    assert paths.is_on_import_path(os.path.dirname(PACKAGE_DIR)) is True
    assert paths.install_tools_dir() != os.path.dirname(PACKAGE_DIR)


def test_an_ordinary_writable_directory_is_accepted(monkeypatch, tmp_path):
    target = tmp_path / "tools"
    target.mkdir()
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(target))
    assert paths.install_tools_dir() == str(target.resolve())


def test_the_operator_override_wins_and_is_listed_first(monkeypatch, tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(first))
    monkeypatch.setattr(paths, "_current", paths.EnginePaths(
        cache_dir=tmp_path / "cache", tools_dir=second))
    dirs = paths.tools_dirs(create=True)
    assert dirs[0] == str(first.resolve())
    assert str(second.resolve()) in dirs


def test_trailing_slashes_do_not_produce_duplicate_entries(monkeypatch, tmp_path):
    target = tmp_path / "tools"
    target.mkdir()
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", "{}/".format(target))
    real = str(target.resolve())
    assert paths.tools_dirs().count(real) == 1


def test_the_user_tools_dir_is_created_only_when_asked(monkeypatch, tmp_path):
    target = tmp_path / "not-yet"
    monkeypatch.setattr(paths, "_current", paths.EnginePaths(
        cache_dir=tmp_path / "cache", tools_dir=target))
    assert target not in (p for p in [target] if target.is_dir())
    paths.tools_dirs()
    assert not target.exists()
    assert str(target.resolve()) in paths.tools_dirs(create=True)
    assert target.is_dir()


def test_guru_and_dsdt_resolve_from_the_same_directories(monkeypatch, tmp_path):
    target = tmp_path / "tools"
    target.mkdir()
    monkeypatch.setenv("BLACKDREAM_TOOLS_DIR", str(target))
    monkeypatch.setattr(paths, "_current", paths.EnginePaths(
        cache_dir=tmp_path / "cache", tools_dir=target))
    assert dsdt.DSDT()._tools_dirs() == paths.tools_dirs()
    assert paths.install_tools_dir() in dsdt.DSDT()._tools_dirs()


def test_is_on_import_path_covers_sys_path_entries(tmp_path):
    sys.path.append(str(tmp_path))
    try:
        assert paths.is_on_import_path(str(tmp_path / "sub" / "dir")) is True
        assert paths.is_on_import_path(str(tmp_path)) is True
    finally:
        sys.path.remove(str(tmp_path))
    assert paths.is_on_import_path(str(tmp_path)) is False
