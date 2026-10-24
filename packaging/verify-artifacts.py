#!/usr/bin/env python3
"""Read the finished artifacts back and refuse the build if they say something false.

``build-release.sh`` produces a bundle, a wheel, an sdist, an archive and a checksum
index. Every claim in ``README.md`` and ``docs/RELEASE-NOTES.md`` about what ships lives
in those files, and the only way to know is to open them:

* No runtime binary may be inside the wheel or the sdist. ``iasl``, ``macserial``,
  ``ocvalidate`` and Hardware Sniffer are fetched at run time, verified against a pinned
  digest and installed into the per-user tools directory. The same bytes sitting in a
  source archive would make the notices in ``docs/THIRD-PARTY.md`` untrue -- and ``tools/``
  on a development machine is exactly where those binaries accumulate.
* No fetched tool may sit inside the bundle either: same reason, plus the rule that a
  binary must never land where Python could import it.
* Every license text and vendor notice has to be where a tester will find it, inside the
  wheel, inside the sdist and next to the launcher -- and inside the bundle each one has
  to be there by its bytes, not by its file name, because two vendors name theirs alike.
* A .deb or .rpm has to install the ACPI helper as root-owned and world-unwritable at the
  path the polkit action names -- an unpacked archive cannot, which is why they exist.
* ``SHA256SUMS.txt`` has to describe the bytes that are actually there.

Run from anywhere::

    python packaging/verify-artifacts.py [--root dist]

Exits non-zero with one line per problem.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from blackdream import RELEASE_LABEL, __version__  # noqa: E402
from blackdream.hardware.acpi import INSTALLED_HELPER  # noqa: E402

#: Byte sequences that mean "this is an executable", not "this is a source file".
MAGICS = (b"\x7fELF", b"MZ", b"\xfe\xed\xfa\xce", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")

#: Oldest glibc the Linux bundle is allowed to require.
#:
#: PyInstaller copies the build host's own ``libglib-2.0``, ``liblcms2``, ``libmount`` and
#: friends into the bundle, and those carry versioned references to the glibc they were
#: compiled against. A bundle built on a 2026 distro therefore asks for 2026 symbols and
#: will not start on the Ubuntu or Debian release the tester is actually running, however
#: portable the Python inside it looks. The floor is measured from the finished bundle
#: rather than assumed, and a build that misses it is refused.
SUPPORTED_GLIBC = (2, 35)

TOOLS = ("iasl", "macserial", "macserial.exe", "macserial.linux",
         "ocvalidate", "ocvalidate.exe", "ocvalidate.linux")

#: Text a tester has to be able to find next to the launcher.
BUNDLE_NOTICES = ("LICENSE", "README.md", "THIRD-PARTY.md", "RELEASE-NOTES.md")

SOURCE_NOTICES = (
    "src/ocengine/VENDOR_NOTICE.txt",
    "src/ocengine/LICENSE.upstream.BSD-3-Clause",
    "src/blackdream/hardware/sniffer/VENDOR_NOTICE.txt",
    "src/blackdream/hardware/sniffer/LICENSE.upstream.BSD-3-Clause",
    "src/blackdream/data/OpenCore-LICENSE.txt",
    "src/blackdream/data/OCAT-LICENSE.txt",
)

#: The names those texts go by inside a bundle, which is where two of them collide.
NOTICE_NAMES = frozenset(Path(name).name for name in SOURCE_NOTICES)


def required_notices(artifact: Path):
    """Which notices this artifact itself has to carry."""
    if artifact.suffix == ".whl":
        # A wheel's README is its METADATA description, not a file inside the archive.
        # Everything else has to be reachable by name -- in ``.dist-info/licenses`` or
        # as a package file beside the code it covers.
        return ("LICENSE", "THIRD-PARTY.md") + tuple(Path(n).name for n in SOURCE_NOTICES)
    return BUNDLE_NOTICES + tuple(Path(n).name for n in SOURCE_NOTICES)


def is_executable(head: bytes) -> bool:
    return any(head.startswith(magic) for magic in MAGICS)


def archive_members(path: Path):
    """Yield ``(name, first bytes)`` for every file in a wheel, zip or tarball."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if not info.is_dir():
                    with archive.open(info) as handle:
                        yield info.filename, handle.read(8)
    else:
        with tarfile.open(path, "r:*") as archive:
            for info in archive.getmembers():
                # A .app is a tree of symlinks -- Python.framework/Versions/Current,
                # the Frameworks crosslinks -- and following one asks tarfile for a
                # member it may not carry. A link is not a file the audit has a
                # question about, so it is skipped rather than resolved.
                if not info.isfile():
                    continue
                handle = archive.extractfile(info)
                if handle is not None:
                    yield info.name, handle.read(8)


def is_archive(path: Path) -> bool:
    """``path.suffix`` is ``.gz`` for a ``.tar.gz``, so extensions are matched by name."""
    return path.name.endswith((".whl", ".tar.gz", ".tgz", ".zip"))


def is_package(path: Path) -> bool:
    """A Linux .deb or .rpm: the same bundle, plus the files a package has to own."""
    return path.suffix in (".deb", ".rpm")


#: What a package must own beyond the bundle itself. The helper and its polkit action are
#: the point of the format: an unpacked archive cannot offer a root-owned helper.
PACKAGE_FILES = ("BlackDream", "dump_acpi_tables.py", "com.blackdream.dumpacpi.policy",
                 "blackdream.desktop", "LICENSE", "THIRD-PARTY.md", "RELEASE-NOTES.md",
                 "README.md")

#: The only trees a package may own. Both formats are staged from one list in
#: ``make-linux-packages.py``, and an uninstall removes exactly what the package owns --
#: so a path below a home directory in that list is a package that would take away the
#: profiles, the build history, the artifact cache, or a folder the user chose to build
#: into. The app writes all of those itself and none of them belong to a package manager.
PACKAGE_PREFIXES = ("/opt/blackdream", "/usr/bin/blackdream", "/usr/lib/blackdream",
                    "/usr/share/applications/blackdream.desktop",
                    "/usr/share/polkit-1/actions/com.blackdream.dumpacpi.policy",
                    "/usr/share/doc/blackdream", "/usr/share/icons/hicolor",
                    # Not a tree BlackDream writes into: rpm fills it with symlinks derived
                    # from the ELF binaries it just packaged, and removes exactly those on
                    # uninstall. It names the package's own files and nothing else, so it is
                    # allowed by name rather than by opening up all of /usr/lib.
                    "/usr/lib/.build-id")


def is_owned_path(name: str) -> bool:
    """Whether a package may list this path at all.

    A directory entry for an ancestor of an allowed tree -- ``/usr``, ``/usr/bin``,
    ``/opt`` -- is created by both formats and owned by nobody, so it counts as allowed.
    Anything that is not below, above or equal to one of ``PACKAGE_PREFIXES`` is not.
    """
    clean = "/" + name.strip("/")
    if clean == "/":
        return True  # the archive's own root entry, which names nothing
    for prefix in PACKAGE_PREFIXES:
        if clean == prefix or clean.startswith(prefix + "/"):
            return True
        if prefix.startswith(clean + "/"):
            return True  # an ancestor directory both formats list: /usr, /usr/bin, /opt
    return False


def require(tool: str, package: str) -> str:
    found = shutil.which(tool)
    if found is None:
        raise SystemExit("{} is needed to read {} back; install the {} package on the "
                         "build host".format(tool, tool, package))
    return found


def package_listing(path: Path):
    """``(install path, mode string, owner)`` for every file a package installs, read back
    with the host's own tooling rather than a reimplementation of two archive formats."""
    if path.suffix == ".deb":
        listed = subprocess.run([require("dpkg-deb", "dpkg"), "-c", str(path)],
                                capture_output=True, text=True, check=False)
        rows = [line.split() for line in listed.stdout.splitlines() if line.strip()]
        # ``-rwxr-xr-x root/root 123 2026-10-23 12:00 ./usr/bin/blackdream``
        return [(row[5].lstrip("."), row[0], row[1].split("/")[0])
                for row in rows if len(row) > 5]
    listed = subprocess.run([require("rpm", "rpm"), "-qvl", str(path)],
                            capture_output=True, text=True, check=False)
    if listed.returncode != 0:
        raise SystemExit("rpm -qvl {} failed: {}".format(path.name, listed.stderr))
    rows = [line.split() for line in listed.stdout.splitlines() if line.strip()]
    # ``-rwxr-xr-x    1 root     root     123 Oct 23 2026 /usr/bin/blackdream``
    # The field after the mode is the link count; owner and group follow it. A
    # symlink's line appends ``-> target``, so the path is found by shape.
    entries = []
    for row in rows:
        if len(row) < 4:
            continue
        name = next((field for field in row if field.startswith("/")), None)
        if name is None:
            continue
        entries.append((name, row[0], row[2]))
    return entries


def audit_package(path: Path, problems: list) -> None:
    """A .deb or .rpm is the only artifact that can give polkit what it wants: the helper
    at the path the action names, owned by root and writable by nobody else. Read the
    package's own manifest back and check exactly that."""
    if __version__ not in path.name:
        problems.append("{} is not the version the package reports".format(path.name))
    entries = package_listing(path)
    if not entries:
        problems.append("{} could not be read back".format(path.name))
        return
    basenames = {Path(name).name: name for name, _mode, _owner in entries}
    for tool in TOOLS:
        if tool in basenames:
            problems.append("{} ships the run-time tool {}".format(path.name, tool))
    for wanted in PACKAGE_FILES:
        if wanted not in basenames:
            problems.append("{} installs no {}".format(path.name, wanted))
    outside = sorted({name for name, _mode, _owner in entries
                      if not is_owned_path(name)})
    if outside:
        problems.append("{} owns {}, which is not a tree BlackDream's own files "
                        "live in; an uninstall would take it away".format(
                            path.name, ", ".join(outside[:3])))
    for name, mode, owner in entries:
        leaf = Path(name).name
        # A helper that the calling user could edit, or that belongs to the account that
        # built the package, is one polkit will not authorize. These two checks are the
        # reason the packages exist at all. Only the installed path counts: the bundle
        # carries its own copy under /opt, which polkit never looks at.
        if name == INSTALLED_HELPER.as_posix():
            if not mode.endswith("rwxr-xr-x"):
                problems.append("{} installs {} as {}, which polkit will refuse".format(
                    path.name, name, mode))
            if owner != "root":
                problems.append("{} installs {} owned by {}, which polkit will "
                                "refuse".format(path.name, name, owner))
        if leaf == "com.blackdream.dumpacpi.policy" and "w" in mode[-3:]:
            problems.append("{} installs the polkit action world-writable".format(path.name))
        if name.endswith("/BlackDream") and not mode.endswith("x"):
            problems.append("{} installs the launcher as {}".format(path.name, mode))


def is_source_artifact(path: Path) -> bool:
    """A wheel, or the sdist -- not the unpacked-application archive beside them."""
    return path.suffix == ".whl" or (path.name.startswith("blackdream-")
                                     and path.name.endswith(".tar.gz"))


def audit_release(release: Path, problems: list):
    built = []
    for artifact in sorted(release.iterdir()):
        if artifact.name == "SHA256SUMS.txt" or not artifact.is_file():
            continue
        if is_package(artifact):
            built.append(artifact)
            audit_package(artifact, problems)
            continue
        if not is_archive(artifact):
            problems.append("{} is not an artifact this audit understands".format(
                artifact.name))
            continue
        built.append(artifact)
        source = is_source_artifact(artifact)
        entries = list(archive_members(artifact))
        names = [Path(name).name for name, _head in entries]
        for name, head in entries:
            if Path(name).name in TOOLS:
                problems.append("{} ships the run-time tool {}".format(artifact.name, name))
            if source and is_executable(head):
                problems.append("{} ships {}: an executable does not belong in a "
                                "source artifact".format(artifact.name, name))
        for notice in required_notices(artifact):
            if notice not in names:
                problems.append("{} carries no {}".format(artifact.name, notice))
        if artifact.suffix == ".whl":
            check_wheel_metadata(artifact, problems)
        elif not source:
            # The application archive is the one thing a tester names in a bug report.
            if RELEASE_LABEL not in artifact.name:
                problems.append("{} is not named for the release label".format(
                    artifact.name))
    return built


def check_wheel_metadata(artifact: Path, problems: list) -> None:
    """The wheel's own claims: the version it was built from, the Python it needs, and
    one ``License-File`` entry per file ``pyproject.toml`` declares."""
    with zipfile.ZipFile(artifact) as archive:
        metadata = next((archive.read(name).decode("utf-8", "replace")
                         for name in archive.namelist()
                         if name.endswith(".dist-info/METADATA")), None)
    if metadata is None:
        problems.append("{} has no METADATA".format(artifact.name))
        return
    if "Version: {}".format(__version__) not in metadata:
        problems.append("{} is not the version the package reports".format(artifact.name))
    declared = re.findall(r"^License-File: (.+)$", metadata, re.MULTILINE)
    expected = tomllib.loads((ROOT / "pyproject.toml").read_text(
        encoding="utf-8"))["project"]["license-files"]
    if sorted(declared) != sorted(expected):
        problems.append("{} carries {}, pyproject declares {}".format(
            artifact.name, len(declared), len(expected)))
    summary = [line for line in metadata.splitlines() if line.startswith("Summary: ")]
    if not summary or "OpenCore" not in summary[0]:
        problems.append("{} lost its description".format(artifact.name))
    if "Requires-Python: >=3.11" not in metadata:
        problems.append("{} does not state the Python it needs".format(artifact.name))


def audit_bundle(bundle: Path, problems: list) -> None:
    if not bundle.is_dir():
        problems.append("no bundle at {}".format(bundle))
        return
    # Linux and Windows put the launcher's directory at the top; on macOS the .app is
    # that directory, and Resources is where "next to the binary" means there.
    roots = [bundle, bundle / "Contents" / "Resources",
             bundle / "BlackDream.app" / "Contents" / "Resources"]
    for notice in BUNDLE_NOTICES:
        if not any((root / notice).is_file() for root in roots):
            problems.append("nothing next to the launcher is a {}".format(notice))
    inside = set()
    notices_by_name = {}
    for path in bundle.rglob("*"):
        if not path.is_file():
            continue
        inside.add(path.name)
        if path.name in NOTICE_NAMES:
            notices_by_name.setdefault(path.name, []).append(path)
    # Two vendors call their notice ``VENDOR_NOTICE.txt``, so finding that name in the
    # bundle says nothing about whether the text under it matches this source tree.
    # Compare bytes: a name check passes a stale or truncated copy, and which copy a
    # single-directory collection keeps is not something the build promises.
    for notice in SOURCE_NOTICES:
        source = ROOT / notice
        if not source.is_file():
            problems.append("{} has gone from the source tree".format(notice))
            continue
        wanted = hashlib.sha256(source.read_bytes()).hexdigest()
        if not any(hashlib.sha256(carried.read_bytes()).hexdigest() == wanted
                   for carried in notices_by_name.get(Path(notice).name, ())):
            problems.append("bundle carries no copy of {}".format(notice))
    for tool in TOOLS:
        if tool in inside:
            problems.append("bundle ships {} instead of fetching and verifying it".format(tool))
    if not any(path.name == "licenses" and path.is_dir() for path in bundle.rglob("*")):
        problems.append("bundle has no licenses directory inside _internal")
    # The one thing in the bundle that a tester is told to install by hand. If it is not
    # there, the README's instruction is a dead end and the ACPI step silently degrades to
    # "export the tables somewhere else" on every platform that has no package.
    helper = next((path for path in bundle.rglob("dump_acpi_tables.py")
                   if path.parent.name == "hardware"
                   and path.parent.parent.name == "blackdream"), None)
    if helper is None:
        problems.append("bundle carries no dump_acpi_tables.py, so nothing can be "
                        "installed to {}".format(INSTALLED_HELPER))


def bundle_glibc_floor(bundle: Path):
    """Highest ``GLIBC_x.y`` symbol version any ELF in the bundle asks for, and the file
    that asked for it. Measured with ``objdump`` because the answer is in the binary, not
    in the build recipe."""
    objdump = shutil.which("objdump")
    if objdump is None:
        raise SystemExit("objdump is needed to measure the bundle's glibc floor")
    floor, worst = (0, 0), None
    for path in sorted(bundle.rglob("*")):
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            if not handle.read(4).startswith(b"\x7fELF"):
                continue
        listed = subprocess.run([objdump, "-T", str(path)],
                                capture_output=True, text=True, check=False)
        for match in re.finditer(r"GLIBC_(\d+\.\d+)", listed.stdout):
            version = tuple(int(part) for part in match.group(1).split("."))
            if version > floor:
                floor, worst = version, path
    return floor, worst


def audit_index(release: Path, problems: list) -> int:
    index = release / "SHA256SUMS.txt"
    if not index.is_file():
        problems.append("no SHA256SUMS.txt in {}".format(release))
        return 0
    verified = 0
    for line in index.read_text(encoding="utf-8").splitlines():
        # GNU sha256sum writes two spaces; Git for Windows writes " *" for a binary
        # read, so the separator is not fixed.
        match = re.fullmatch(r"([0-9a-f]{64})\s+\*?(.+)", line)
        if match is None:
            problems.append("malformed checksum line: {!r}".format(line))
            continue
        digest, name = match.group(1), match.group(2).strip()
        path = release / name
        if not path.is_file():
            problems.append("SHA256SUMS.txt lists {}, which is not there".format(name))
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            problems.append("{} does not hold the bytes its checksum claims".format(name))
            continue
        verified += 1
        if name.startswith("BlackDream-") and RELEASE_LABEL not in name:
            problems.append("{} is not named for the release label".format(name))
    return verified


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the release artifacts.")
    parser.add_argument("--root", type=Path, default=ROOT / "dist",
                        help="directory holding release/ and the bundle (default: dist)")
    args = parser.parse_args()

    release = args.root / "release"
    problems: list = []
    built = audit_release(release, problems) if release.is_dir() else []
    if not release.is_dir():
        problems.append("no release directory at {}".format(release))
    verified = audit_index(release, problems) if release.is_dir() else 0
    # PyInstaller writes dist/BlackDream on Linux and Windows; a macOS BUNDLE is created
    # at the top of dist as dist/BlackDream.app. Anything else in dist/ is a leftover
    # from another build.
    bundle = args.root / ("BlackDream.app" if sys.platform == "darwin" else "BlackDream")
    audit_bundle(bundle, problems)

    # The floor only means something for the Linux bundle; on the other two platforms
    # there is no glibc in the artifact to measure.
    floor = None
    if sys.platform.startswith("linux") and bundle.is_dir():
        floor, worst = bundle_glibc_floor(bundle)
        if floor > SUPPORTED_GLIBC:
            problems.append(
                "the bundle needs glibc {}.{}, because PyInstaller copied {} from this "
                "build host, but the release supports {}.{}: build it on a host with an "
                "older glibc, or use --bundle-only for a local test bundle".format(
                    floor[0], floor[1], worst.name, *SUPPORTED_GLIBC))

    for line in problems:
        print("FAIL  {}".format(line), file=sys.stderr)
    if problems:
        return 1

    print("artifacts say what the release notes say")
    for artifact in built:
        print("  {:<56} {:>12,} bytes".format(artifact.name, artifact.stat().st_size))
    print("  {:<56} {:>12,} entries".format("checksums verified", verified))
    print("  {:<56} {:>12,} files".format(str(bundle),
                                          sum(1 for _ in bundle.rglob("*"))))
    if floor is not None:
        print("  {:<56} glibc {}.{} (supports {}.{})".format(
            "measured bundle floor", floor[0], floor[1], *SUPPORTED_GLIBC))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
