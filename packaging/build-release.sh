#!/usr/bin/env bash
# Produce the beta artifacts: test suite, one-directory bundle, wheel, sdist,
# archive, checksums, and an audit of what the artifacts actually contain.
#
#   packaging/build-release.sh              # everything
#   packaging/build-release.sh --no-tests   # skip the suite
#   packaging/build-release.sh --bundle-only
#
# Run it on the platform whose artifact you want. PyInstaller cannot cross-build a
# Windows or macOS app from Linux, so the Windows and macOS betas have to be built
# on Windows and macOS; the spec and this script are written so the same command
# works there.
#
# The bundle is not code-signed and not notarized. On macOS that means Gatekeeper
# blocks the first launch until the user overrides it, and that fact belongs in the
# release notes rather than being discovered by a tester.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-}"
if [[ -z "$PY" && -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"; fi
if [[ -z "$PY" ]]; then PY="$(command -v python3)"; fi

RUN_TESTS=1
BUNDLE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --no-tests) RUN_TESTS=0 ;;
    --bundle-only) BUNDLE_ONLY=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

LABEL="$("$PY" -c 'import sys; sys.path.insert(0, "src"); import blackdream; print(blackdream.RELEASE_LABEL)')"
VERSION="$("$PY" -c 'import sys; sys.path.insert(0, "src"); import blackdream; print(blackdream.__version__)')"
case "$(uname -s)" in
  Linux) OS=linux ;;
  Darwin) OS=macos ;;
  *) OS=windows ;;
esac
# The interpreter's own architecture, not the kernel's: a Windows ARM64 runner reports
# whatever uname likes, and the bundle embeds whichever Python is building it.
ARCH="$("$PY" -c 'import platform; print(platform.machine())' \
       | tr "[:upper:]" "[:lower:]" | sed -e 's/x86_64/amd64/' -e 's/aarch64/arm64/')"
PLATFORM_TAG="${OS}-${ARCH}"
OUT="$ROOT/dist/release"
BUNDLE="$ROOT/dist/BlackDream"
APP_NAME="BlackDream-${LABEL}-${PLATFORM_TAG}"
# The oldest glibc a Linux build is allowed to require; verify-artifacts.py measures the
# finished bundle against it and the packages state it as a dependency.
MIN_GLIBC="2.35"

# PyInstaller puts the launcher in a different place on every platform, and macOS
# wraps the directory in a .app.
case "$OS" in
  linux)   LAUNCHER="$BUNDLE/BlackDream" ;;
  macos)   LAUNCHER="$BUNDLE/BlackDream.app/Contents/MacOS/BlackDream" ;;
  windows) LAUNCHER="$BUNDLE/BlackDream.exe" ;;
esac

step() { printf '\n== %s\n' "$1"; }

if [[ "$RUN_TESTS" == 1 ]]; then
  step "test suite"
  QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q
fi

step "icons"
"$PY" packaging/make_icons.py

step "bundle"
"$PY" -m PyInstaller --noconfirm --distpath dist --workpath build packaging/blackdream.spec

# The notices belong where a person unpacking an archive will find them, not only
# inside _internal where the spec also puts them.
step "notices"
case "$OS" in
  linux)
    NOTICE_DIR="$BUNDLE"
    mkdir -p "$BUNDLE/share/applications"
    cp packaging/linux/blackdream.desktop "$BUNDLE/share/applications/"
    rm -rf "$BUNDLE/share/icons"
    cp -r packaging/icons/hicolor "$BUNDLE/share/icons"
    ;;
  macos)
    NOTICE_DIR="$BUNDLE/BlackDream.app/Contents/Resources"
    ;;
  windows)
    NOTICE_DIR="$BUNDLE"
    ;;
esac
mkdir -p "$NOTICE_DIR"
for document in LICENSE README.md docs/THIRD-PARTY.md docs/RELEASE-NOTES.md; do
  cp "$document" "$NOTICE_DIR/"
done

# One frame on the offscreen platform: this proves the relocated bundle finds its
# data files and builds the window, without needing a display to be attached.
step "bundle smoke test"
QT_QPA_PLATFORM=offscreen "$LAUNCHER" --smoke

if [[ "$BUNDLE_ONLY" == 1 ]]; then
  printf '\nbundle ready: %s\n' "$BUNDLE"
  exit 0
fi

step "wheel and sdist"
rm -rf "$OUT"
mkdir -p "$OUT"
"$PY" -m build --wheel --sdist --outdir "$OUT"

step "archive"
if [[ "$OS" == windows ]]; then
  ARCHIVE="$OUT/${APP_NAME}.zip"
  rm -f "$ARCHIVE"
  ( cd "$(dirname "$BUNDLE")" && "$PY" -m zipfile -c "$ARCHIVE" "$(basename "$BUNDLE")" )
else
  ARCHIVE="$OUT/${APP_NAME}.tar.gz"
  tar -czf "$ARCHIVE" -C "$(dirname "$BUNDLE")" "$(basename "$BUNDLE")"
fi

# A package is the only artifact that can hand polkit a root-owned helper at the path its
# action names. It carries the same bundle bytes as the archive, so it is built from the
# same directory, after the archive, and audited with everything else below.
if [[ "$OS" == linux ]]; then
  step "deb and rpm"
  "$PY" packaging/make-linux-packages.py --bundle "$BUNDLE" --out "$OUT" \
        --version "$VERSION" --min-glibc "$MIN_GLIBC"
fi


step "checksums"
(
  cd "$OUT"
  rm -f SHA256SUMS.txt
  for artifact in *; do
    [[ -f "$artifact" && "$artifact" != SHA256SUMS.txt ]] || continue
    sha256sum "$artifact" >> SHA256SUMS.txt
  done
  cat SHA256SUMS.txt
)

# Open the finished artifacts and check them against what the release claims: no
# run-time binary inside the wheel or the sdist, every notice where a tester will find
# it, and every checksum matching the bytes next to it.
step "artifact audit"
"$PY" packaging/verify-artifacts.py --root dist

printf '\nversion %s (%s)\nartifacts in %s\n' "$LABEL" "$VERSION" "$OUT"
