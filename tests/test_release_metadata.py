"""Everything a stranger receives with the beta has to agree with the rest.

A release is not only code: it is a version string repeated in the About card, the wheel
metadata, the spec, the README and the release notes; a set of license texts that have to
travel with the binary; icons rendered from the app's own mark; and one shell script that
is the actual build gate. Each of those has a second copy somewhere else, and a beta
whose notes promise a checksum that does not exist is worse than no notes.

These tests are about the release surface, not the engine. They read files rather than
build anything, so they run in the ordinary suite and fail before a distributor notices.
"""

from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from blackdream import PRERELEASE, RELEASE_LABEL, __version__  # noqa: E402

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
README = (ROOT / "README.md").read_text(encoding="utf-8")
SPEC = (ROOT / "packaging" / "blackdream.spec").read_text(encoding="utf-8")
SCRIPT = (ROOT / "packaging" / "build-release.sh").read_text(encoding="utf-8")
DESKTOP = (ROOT / "packaging" / "linux" / "blackdream.desktop").read_text(encoding="utf-8")
NOTES = (ROOT / "docs" / "RELEASE-NOTES.md").read_text(encoding="utf-8")
THIRD_PARTY = (ROOT / "docs" / "THIRD-PARTY.md").read_text(encoding="utf-8")
ICONS = ROOT / "packaging" / "icons"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_the_label_is_the_version_a_person_reads():
    """``0.9.0b1`` is what a package index wants; ``0.9.0-beta.1`` is what the About
    card, the notes and the archive name want. One source, two spellings."""
    assert RELEASE_LABEL == __version__.replace("b", "-beta.", 1)
    assert PRERELEASE is True


def test_the_bundle_version_comes_from_the_same_constants():
    numeric = __version__.split("b")[0].split("rc")[0].split("a")[0]
    assert re.fullmatch(r"\d+\.\d+\.\d+", numeric), "a version resource wants three numbers"
    # The spec derives both spellings from the package instead of carrying a fourth
    # copy of the version.
    assert "from blackdream import RELEASE_LABEL, __version__" in SPEC
    assert "NUMERIC_VERSION = __version__" in SPEC
    assert '"CFBundleShortVersionString": RELEASE_LABEL' in SPEC


def test_the_wheel_reads_the_version_from_the_package():
    assert PYPROJECT["project"]["dynamic"] == ["version"]
    assert PYPROJECT["tool"]["hatch"]["version"]["path"] == "src/blackdream/__init__.py"


def test_the_project_declares_itself_a_beta():
    classifiers = PYPROJECT["project"]["classifiers"]
    assert "Development Status :: 4 - Beta" in classifiers
    for operating_system in ("Linux", "MacOS", "Microsoft"):
        assert any(entry.startswith("Operating System") and operating_system in entry
                   for entry in classifiers), operating_system


def test_every_classifier_is_one_pypi_accepts():
    """A made-up classifier is not a cosmetic defect: it fails the wheel build, which
    is the last thing anyone wants to discover while packaging a release. ``Environment
    :: MacOS :: MacOS X`` and ``User Interface :: Graphical`` both looked plausible and
    both are refused."""
    try:
        from trove_classifiers import classifiers as valid
    except ImportError:  # pragma: no cover - dev extra not installed
        pytest.skip("trove-classifiers is a development dependency")
    invalid = [entry for entry in PYPROJECT["project"]["classifiers"]
               if entry not in valid]
    assert invalid == []


def test_every_declared_license_file_exists():
    for entry in PYPROJECT["project"]["license-files"]:
        assert (ROOT / entry).is_file(), entry


def test_the_readme_and_the_notes_carry_the_same_label_as_the_package():
    assert RELEASE_LABEL in README
    assert NOTES.splitlines()[0].strip() == "# BlackDream {}".format(RELEASE_LABEL)


def test_the_notes_answer_every_question_a_tester_needs():
    """This is the first build outside the development machine, so the notes are the
    support documentation. These are the sections a bug report depends on."""
    headings = {line.lstrip("# ").strip() for line in NOTES.splitlines()
                if line.startswith("## ")}
    for required in ("What is in this release",
                     "Safety behaviour you should know before you test",
                     "Tested on / not tested on",
                     "Known issues and limitations",
                     "How to report a problem",
                     "Checksums"):
        assert required in headings, required
    for platform in ("Linux", "Windows", "macOS"):
        assert platform in NOTES


def test_no_unfilled_placeholder_survives_into_a_release_document():
    for name in ("README.md", "docs/RELEASE-NOTES.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"[«»]", text), "{} still holds a placeholder".format(name)


def test_notices_for_vendored_code_travel_with_every_artifact():
    """A new vendored component has to be credited, declared to the wheel, and copied
    into the bundle. Missing any one of the three is a licensing defect."""
    declared = set(PYPROJECT["project"]["license-files"])
    copied_into_bundle = set(re.findall(r'"(src/[^"]+)"', SPEC))
    notices = sorted(ROOT.glob("src/**/LICENSE*")) + sorted(
        ROOT.glob("src/**/VENDOR_NOTICE.txt"))
    assert notices, "the vendored engine lost its notices"
    for notice in notices:
        relative = notice.relative_to(ROOT).as_posix()
        assert relative in THIRD_PARTY, "{} is not credited".format(relative)
        # Package data under ``src/blackdream/data`` rides along with the wheel and the
        # bundle through the normal data-file collection, not an explicit listing.
        inside_package_data = relative.startswith("src/blackdream/data/")
        assert (relative in declared or relative in copied_into_bundle
                or inside_package_data), "{} does not ship".format(relative)


def test_ico_entries_are_pngs_at_the_sizes_the_app_rendered():
    data = (ICONS / "blackdream.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    offset = 6 + 16 * count
    sizes = []
    for index in range(count):
        entry = 6 + index * 16
        # A 256 px edge is stored as the byte 0, which is how the format says "256".
        sizes.append(data[entry] or 256)
        assert struct.unpack("<HH", data[entry + 4:entry + 8]) == (1, 32)
        length, start = struct.unpack("<II", data[entry + 8:entry + 16])
        assert start == offset, "entry {} overlaps its neighbour".format(index)
        assert data[offset:offset + 8] == PNG_MAGIC
        offset += length
    assert offset == len(data), "the last entry runs past the end of the file"
    assert sorted(sizes) == [16, 24, 32, 48, 64, 128, 256]


def test_icns_carries_the_modern_png_entries():
    data = (ICONS / "blackdream.icns").read_bytes()
    assert data[:4] == b"icns"
    total = struct.unpack(">I", data[4:8])[0]
    assert total == len(data), "the header length disagrees with the file"
    codes = []
    position = 8
    while position < total:
        length = struct.unpack(">I", data[position + 4:position + 8])[0]
        assert data[position + 8:position + 16] == PNG_MAGIC
        codes.append(data[position:position + 4].decode("ascii"))
        position += length
    assert position == total
    assert sorted(codes) == sorted(["ic07", "ic08", "ic09", "ic10",
                                    "ic11", "ic12", "ic13", "ic14"])


def test_hicolor_icons_and_the_scalable_mark_agree_with_the_app():
    from blackdream.ui.icons import logo_svg

    for size in (16, 32, 48, 64, 128, 256, 512):
        path = ICONS / "hicolor" / "{}x{}".format(size, size) / "apps" / "blackdream.png"
        assert path.is_file(), path
        assert path.read_bytes()[:8] == PNG_MAGIC
    svg = (ICONS / "hicolor" / "scalable" / "apps" / "blackdream.svg").read_text(
        encoding="utf-8")
    assert svg.strip() == logo_svg().strip()


def test_the_desktop_entry_launches_the_installed_command():
    keys = {}
    for line in DESKTOP.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            keys[key.strip()] = value.strip()
    assert keys["Type"] == "Application"
    assert keys["Terminal"] == "false"
    assert keys["Exec"].split()[0] in PYPROJECT["project"]["scripts"]
    assert keys["Icon"] == "blackdream"
    assert "System" in keys["Categories"]
    # An entry inside an unpacked archive must not name this machine.
    assert not re.search(r"/home/|/Users/|[A-Za-z]:\\\\", DESKTOP)


def test_the_release_script_parses_and_runs_the_gates_in_order():
    subprocess.run(["bash", "-n", str(ROOT / "packaging" / "build-release.sh")],
                   check=True, capture_output=True)
    assert SCRIPT.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in SCRIPT
    steps = ["test suite", "icons", "bundle", "notices", "bundle smoke test",
             "wheel and sdist", "archive", "checksums", "artifact audit"]
    positions = [SCRIPT.index('step "{}"'.format(step)) for step in steps]
    assert positions == sorted(positions), "the gates do not run in order"
    for platform in ("linux", "macos", "windows"):
        assert platform in SCRIPT, "no launcher path for {}".format(platform)
    assert 'QT_QPA_PLATFORM=offscreen "$LAUNCHER" --smoke' in SCRIPT


def test_the_packaging_scripts_are_executable():
    assert os.access(ROOT / "packaging" / "build-release.sh", os.X_OK)
    assert os.access(ROOT / "packaging" / "make_icons.py", os.X_OK)
    assert os.access(ROOT / "packaging" / "verify-artifacts.py", os.X_OK)


def test_the_sdist_carries_source_and_not_the_pre_seeded_tools():
    """``tools/`` is where this machine keeps its downloaded ``iasl``, ``macserial`` and
    ``ocvalidate``. Naming the directory in the include list would ship those binaries in
    the source archive, which ``docs/THIRD-PARTY.md`` says does not happen."""
    targets = PYPROJECT["tool"]["hatch"]["build"]["targets"]
    include = targets["sdist"]["include"]
    for required in ("/LICENSE", "/README.md", "/pyproject.toml", "/src", "/tests",
                     "/docs", "/packaging"):
        assert required in include, required
    assert "/tools" not in include
    for entry in include:
        if entry.startswith("/tools/"):
            assert Path(entry).name in ("e2e_build.py", ".gitkeep"), entry
    assert targets["sdist"]["exclude"] == ["/docs/screenshots"]
    assert targets["wheel"]["packages"] == ["src/blackdream", "src/ocengine"]


def test_the_bundle_carries_the_notices_the_spec_claims():
    """The spec copies the notices into ``_internal/licenses``. If one of those paths
    stops existing, PyInstaller skips it in silence and the bundle loses a notice."""
    copied = re.findall(r'"((?:src|docs)/[^"]+|LICENSE|README\.md)"', SPEC)
    assert copied, "the spec copies no notices at all"
    for entry in copied:
        assert (ROOT / entry).is_file(), "{} named by the spec is gone".format(entry)


def test_the_notes_describe_every_name_the_build_publishes():
    """A tester arrives at a folder of files and has to know which is which.

    The notes describe the naming *scheme* instead of listing the files, because a
    scheme is true for the Linux build and for the Windows build, and one copy of the
    document ships inside both.
    """
    release = ROOT / "dist" / "release"
    if not release.is_dir():
        pytest.skip("no artifacts have been built on this machine")
    published = sorted(p.name for p in release.iterdir()
                       if p.is_file() and p.name != "SHA256SUMS.txt")
    assert published, "dist/release holds nothing but, maybe, a checksums file"
    scheme = (r"BlackDream-{}-(?:linux|macos|windows)-(?:amd64|arm64)\.(?:tar\.gz|zip)"
              .format(re.escape(RELEASE_LABEL)),
              r"blackdream-{}-py3-none-any\.whl".format(re.escape(__version__)),
              r"blackdream-{}\.tar\.gz".format(re.escape(__version__)))
    for pattern in scheme:
        assert any(re.fullmatch(pattern, name) for name in published), \
            "the notes promise something matching {}, and nothing does".format(pattern)
    for name in published:
        assert any(re.fullmatch(pattern, name) for pattern in scheme), \
            "{} is a name the notes do not describe".format(name)


def test_the_notes_quote_no_checksum_of_the_build_that_carries_them():
    """The property that makes a checksum claim in a shipped document impossible to keep
    true: ``RELEASE-NOTES.md`` is inside the archive and the sdist, so any digest written
    into it changes the digest of the file that contains it. ``SHA256SUMS.txt`` sits
    beside the artifacts instead, and ``verify-artifacts.py`` recomputes it."""
    assert not re.search(r"\b[0-9a-f]{64}\b", NOTES), \
        "the notes carry a digest that no build can keep true"


def test_the_test_count_in_the_notes_is_the_suite_that_actually_exists():
    """The notes tell a tester how many automated tests ran for this build, so the
    number is measured here by collecting the suite the way the release script runs it.
    A hand-typed count goes stale on the next commit, which is how a release note came
    to advertise a number of tests the suite no longer had."""
    claimed = re.search(r"([\d,]+) automated tests", NOTES)
    assert claimed, "the notes no longer state a test count in the form this test reads"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=str(ROOT), env=env, capture_output=True, text=True)
    assert collected.returncode == 0, collected.stdout[-2000:] + collected.stderr[-2000:]
    measured = re.search(r"(\d+) tests? collected", collected.stdout)
    assert measured, collected.stdout[-2000:]
    assert int(claimed.group(1).replace(",", "")) == int(measured.group(1)), \
        "the notes say {}, the suite collects {}".format(claimed.group(1), measured.group(1))


@pytest.mark.parametrize("directory", ["src", "packaging", "docs", "tests", "tools"])
def test_no_machine_specific_path_is_shipped_in_the_sources(directory):
    """The wheel and the sdist go to strangers. A path that names this machine's home
    or checkout directory is a leak, not a detail."""
    root = ROOT / directory
    if not root.is_dir():
        pytest.skip("{} is not present".format(directory))
    offenders = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.name == Path(__file__).name:
            continue  # this file names the forbidden strings in order to forbid them
        if path.suffix not in (".py", ".md", ".toml", ".spec", ".sh", ".desktop",
                               ".txt", ".policy", ".yaml", ".json"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in ("/data/BlackDream", "aalmamun"):
            if pattern in text:
                offenders.append("{}: {}".format(path.relative_to(ROOT), pattern))
    assert offenders == []
