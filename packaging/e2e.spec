# -*- mode: python ; coding: utf-8 -*-
"""Console bundle of ``tools/e2e_build.py``, for verifying a packaged build.

The window has no build CLI on purpose, so a packaged build cannot be driven
through it. This binary runs the same ``Pipeline`` methods as the window from a
frozen interpreter, which is what proves the bundle's data files, CA store,
engine modules and external-tool lookup work outside the source checkout.

    .venv/bin/python -m PyInstaller --noconfirm \
        --distpath dist --workpath build packaging/e2e.spec
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

datas = []
for package in ("ocengine", "blackdream", "certifi"):
    datas += collect_data_files(package)

a = Analysis(
    [str(ROOT / "tools" / "e2e_build.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The harness is Qt-free; excluding the binding keeps this bundle to the
    # engine and the data files it reads.
    excludes=["tkinter", "pytest", "_pytest", "PySide6"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="blackdream-e2e",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="blackdream-e2e",
)
