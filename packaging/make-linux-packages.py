#!/usr/bin/env python3
"""Repackage the audited bundle as a .deb and an .rpm.

Both formats carry the same tree the release archive contains, byte for byte, at
``/opt/blackdream``, and then put six things where a system package has to put them: a
launcher on ``PATH``, the desktop entry, the icons, the notices, and -- the reason this
script exists -- the ACPI helper and its polkit action, owned by root.

That last pair cannot work in an unpacked archive. polkit binds its authorization prompt
to one path and refuses to trust a helper the calling user could edit, so ``README.md``
has to tell testers to run two ``sudo install`` commands themselves. A package manager
installs those files as root with the modes already set, so the step happens by itself.

Nothing here recompiles or post-processes a file. PyInstaller's output is copied
verbatim, and the RPM's ``%__os_install_post`` is switched off, because
``verify-artifacts.py`` measured the bundle's glibc floor from those exact bytes -- a
strip script that changed them would make the audit describe a package that was never
checked. The DEB is built with ``--root-owner-group`` for the same reason: the build user
in CI is not root, and a helper owned by whoever ran the build is a helper polkit will
not authorize.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = "blackdream"
BUNDLE = "BlackDream"

#: Installed on ``PATH`` rather than symlinked, so the process's own executable is the
#: one inside ``/opt/blackdream`` and the bundle finds ``_internal`` beside it.
LAUNCHER = """#!/bin/sh
exec /opt/{app}/{bundle} "$@"
"""

DESCRIPTION = """BlackDream checks a machine's macOS compatibility, builds an OpenCore EFI
folder, and edits the resulting config.plist, without a terminal. The three sections are
Installer, Build EFI and Configure EFI. Downloaded tools are verified against pinned
digests before they run, and nothing is ever written to a disk this machine boots from."""


def system_files(bundle: Path):
    """``(source inside the bundle, install path, mode)`` for everything outside /opt.

    One list feeds both formats, so a DEB and an RPM built from the same bundle cannot
    disagree about what they own.
    """
    hardware = bundle / "_internal" / "blackdream" / "hardware"
    files = [
        (hardware / "dump_acpi_tables.py", "/usr/lib/blackdream/dump_acpi_tables.py", 0o755),
        (hardware / "com.blackdream.dumpacpi.policy",
         "/usr/share/polkit-1/actions/com.blackdream.dumpacpi.policy", 0o644),
        (bundle / "share/applications/blackdream.desktop",
         "/usr/share/applications/blackdream.desktop", 0o644),
    ]
    icons = bundle / "share/icons"
    for source in sorted(icons.rglob("*")):
        if source.is_file():
            # The bundle carries the sizes directly under share/icons; a desktop
            # environment only looks them up inside an icon theme, so the
            # installed copy goes under hicolor.
            relative = source.relative_to(icons)
            if relative.parts[0] != "hicolor":
                relative = Path("hicolor") / relative
            files.append((source, "/usr/share/icons/" + relative.as_posix(), 0o644))
    for document in ("LICENSE", "README.md", "THIRD-PARTY.md", "RELEASE-NOTES.md"):
        files.append((bundle / document,
                      "/usr/share/doc/{}/{}".format(APP, document), 0o644))
    return files


def stage_tree(bundle: Path, stage: Path) -> int:
    """Copy the bundle to ``/opt/blackdream`` verbatim and lay the system files beside it.
    Returns the installed size in KiB, which is what both package formats want."""
    shutil.copytree(bundle, stage / "opt" / APP, symlinks=True)
    for source, target, mode in system_files(bundle):
        destination = stage / target.lstrip("/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        destination.chmod(mode)
    launcher = stage / "usr/bin" / APP
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(LAUNCHER.format(app=APP, bundle=BUNDLE), encoding="utf-8")
    launcher.chmod(0o755)
    # The build host's umask decides the modes of everything copied so far, and an
    # installed tree should not inherit it: a 775 root-owned directory under /usr is
    # group-writable on a machine whose group the caller may share. Bytes are untouched.
    for path in sorted(stage.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
    total = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file())
    return total // 1024 + 1


def require(tool: str, package: str) -> str:
    found = shutil.which(tool)
    if found is None:
        raise SystemExit("{} is needed to build the packages; install the {} package "
                         "on the build host".format(tool, package))
    return found


def run(command: list) -> None:
    finished = subprocess.run(command, capture_output=True, text=True)
    if finished.returncode != 0:
        raise SystemExit("{} failed:\n{}{}".format(
            command[0], finished.stdout, finished.stderr))


def make_rpm(stage: Path, out: Path, version: str, arch: str, summary: str,
             min_glibc: str, size: int) -> Path:
    top = stage.parent / "rpmbuild"
    for directory in ("SPECS", "BUILD", "BUILDROOT", "RPMS", "SOURCES"):
        (top / directory).mkdir(parents=True, exist_ok=True)
    spec = top / "SPECS" / "{}.spec".format(APP)
    spec.write_text("""%global debug_package %{{nil}}
# Without this, rpm's own strip and compress scripts rewrite the bundle after the audit
# has measured it.
%global __os_install_post %{{nil}}

Name:     {app}
Version:  {version}
Release:  1
Summary:  {summary}
# MIT for this app, BSD-3-Clause for the vendored engine and OpenCore notices, LGPL-3.0
# for the PySide6 shared libraries inside the bundle.
License:  MIT and BSD-3-Clause and LGPL-3.0
BuildArch: {arch}
# The bundle's own ELF files carry versioned glibc references, and rpm reads them; this
# states the floor the audit measured so a too-old host refuses the install.
Requires: glibc >= {min_glibc}

%description
{description}

%install
rm -rf %{{buildroot}}
mkdir -p %{{buildroot}}
cp -a %{{_sourcedir}}/{stage_dir}/. %{{buildroot}}/
# The DEB control file lives in the same staged tree; it is not content.
rm -rf %{{buildroot}}/DEBIAN

%files
%defattr(-,root,root,-)
/opt/{app}
/usr/bin/{app}
/usr/lib/{app}
/usr/share/applications/{app}.desktop
/usr/share/polkit-1/actions/com.blackdream.dumpacpi.policy
/usr/share/doc/{app}
/usr/share/icons/hicolor
""".format(app=APP, version=version, summary=summary, arch=arch,
           min_glibc=min_glibc, description=DESCRIPTION, stage_dir=stage.name),
                     encoding="utf-8")
    require("rpmbuild", "rpm")
    run(["rpmbuild", "-bb", "--define", "_topdir {}".format(top),
         "--define", "_sourcedir {}".format(stage.parent), str(spec)])
    built = sorted((top / "RPMS").rglob("*.rpm"))
    if len(built) != 1:
        raise SystemExit("rpmbuild produced {} packages, expected 1".format(len(built)))
    return built[0].rename(out / built[0].name)


def make_deb(stage: Path, out: Path, version: str, arch: str, summary: str,
             min_glibc: str, size: int) -> Path:
    control = stage / "DEBIAN" / "control"
    control.parent.mkdir(parents=True, exist_ok=True)
    wrapped = "\n".join(" " + line for line in DESCRIPTION.splitlines())
    control.write_text("""Package: {app}
Version: {version}
Architecture: {arch}
Maintainer: BlackDream contributors
Section: utils
Priority: optional
Installed-Size: {size}
Depends: libc6 (>= {min_glibc})
Description: {summary}
{wrapped}
""".format(app=APP, version=version, arch=arch, summary=summary, size=size,
           min_glibc=min_glibc, wrapped=wrapped), encoding="utf-8")
    target = out / "{}_{}_{}.deb".format(APP, version, arch)
    run([require("dpkg-deb", "dpkg"), "--root-owner-group", "--build", str(stage),
         str(target)])
    return target


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", type=Path, default=ROOT / "dist" / BUNDLE)
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "release")
    parser.add_argument("--version", required=True,
                        help="numeric version, e.g. 0.9.0b1 -- the release label has a "
                             "dash, which neither format accepts")
    parser.add_argument("--min-glibc", default="2.35")
    parser.add_argument("--format", choices=("deb", "rpm"), action="append",
                        default=None,
                        help="repeatable; the default is both")
    args = parser.parse_args(argv)

    if not sys.platform.startswith("linux"):
        raise SystemExit("these are Linux packages")
    if not (args.bundle / BUNDLE).is_file():
        raise SystemExit("no bundle launcher at {}".format(args.bundle / BUNDLE))
    if not (args.bundle / "share/icons").is_dir():
        raise SystemExit("{} carries no share/icons; build-release.sh copies the desktop "
                         "entry and icons into the bundle before this runs".format(
                             args.bundle))
    machine = platform.machine().lower()
    arch = {"x86_64": ("amd64", "x86_64"), "aarch64": ("arm64", "aarch64")}.get(machine)
    if arch is None:
        raise SystemExit("no package architecture name for {}".format(machine))
    summary = tomllib.loads((ROOT / "pyproject.toml").read_text(
        encoding="utf-8"))["project"]["description"]

    args.out.mkdir(parents=True, exist_ok=True)
    work = args.out.parent / "pkg"
    shutil.rmtree(work, ignore_errors=True)
    stage = work / "root"
    stage.mkdir(parents=True)
    try:
        size = stage_tree(args.bundle.resolve(), stage)
        for kind in args.format or ("rpm", "deb"):
            if kind == "rpm":
                built = make_rpm(stage, args.out, args.version, arch[1], summary,
                                 args.min_glibc, size)
            else:
                built = make_deb(stage, args.out, args.version, arch[0], summary,
                                 args.min_glibc, size)
            print("built {}".format(built.name))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
