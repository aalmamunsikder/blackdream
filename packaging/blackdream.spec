# -*- mode: python ; coding: utf-8 -*-
"""One-directory PyInstaller build for the BlackDream window.

Build from the repository root:

    .venv/bin/python -m PyInstaller --noconfirm \
        --distpath dist --workpath build packaging/blackdream.spec

The app is one directory, not one file: the engine downloads and caches
artifacts beside the per-user data root at run time, and a one-file executable
unpacks itself to a temporary directory on every launch, which would turn every
start into an extraction and make the bundled data files harder to inspect.

Runtime tools (``iasl``, ``macserial``) are deliberately not bundled. The engine
resolves them through ``ocengine.paths.tools_dirs()`` -- operator-provisioned
directories first, then the per-user tools directory -- and refuses anything on
Python's import path. A binary shipped inside ``_MEIPASS`` would sit on that
path, so packaging one would fight the trust rule rather than satisfy it.

The license texts and vendor notices go into ``_internal/licenses`` so the terms
travel with the binary, and the icon comes from ``packaging/icons``, which
``packaging/make_icons.py`` renders from the mark the window itself paints.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
ICONS = ROOT / "packaging" / "icons"
sys.path.insert(0, str(SRC))

from blackdream import RELEASE_LABEL, __version__  # noqa: E402  (path above)

# The version resource wants dotted numbers; the label a human reads has a beta
# suffix in it. Both come from the one constant in the package, so a release bump
# cannot leave the bundle claiming a different version than the About card.
NUMERIC_VERSION = __version__.split("b")[0].split("rc")[0].split("a")[0]

# Regenerate with ``python packaging/make_icons.py`` if these are missing; the
# artwork lives in ``blackdream.ui.icons``, not in these files.
if sys.platform == "win32":
    ICON = str(ICONS / "blackdream.ico")
elif sys.platform == "darwin":
    ICON = str(ICONS / "blackdream.icns")
else:
    ICON = None

datas = []
for package in ("ocengine", "blackdream", "certifi"):
    datas += collect_data_files(package)

# The notices have to travel with the binary, not just with the source: the
# bundled engine is BSD-3, its presets and identifier tables are MIT and BSD-3,
# and PySide6 is LGPL-3. ``docs/THIRD-PARTY.md`` is the index that ties each of
# them to the file that carries its text.
for document in ("LICENSE", "README.md", "docs/THIRD-PARTY.md",
                 "docs/RELEASE-NOTES.md", "src/ocengine/VENDOR_NOTICE.txt",
                 "src/ocengine/LICENSE.upstream.BSD-3-Clause",
                 "src/blackdream/hardware/sniffer/VENDOR_NOTICE.txt",
                 "src/blackdream/hardware/sniffer/LICENSE.upstream.BSD-3-Clause"):
    source = ROOT / document
    if source.is_file():
        datas.append((str(source), "licenses"))

# Qt modules the window never imports. PySide6's hook otherwise collects every
# module installed in the environment, including the WebEngine runtime, which
# is larger than the rest of the application combined.
excludes = [
    "tkinter",
    "pytest",
    "_pytest",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtRemoteObjects",
    "PySide6.QtNetworkAuth",
]

a = Analysis(
    [str(SRC / "blackdream" / "ui" / "app.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BlackDream",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
    version=NUMERIC_VERSION if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BlackDream",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="BlackDream.app",
        icon=ICON,
        bundle_identifier="org.blackdream.app",
        version=NUMERIC_VERSION,
        info_plist={
            "CFBundleDisplayName": "BlackDream",
            "CFBundleName": "BlackDream",
            "CFBundleShortVersionString": RELEASE_LABEL,
            "CFBundleVersion": NUMERIC_VERSION,
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
