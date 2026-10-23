#!/usr/bin/env python3
"""Render the platform icon files from the mark the window already paints.

``blackdream.ui.icons.logo_svg()`` is the only icon artwork in this repository. The
``.ico``, the ``.icns``, the hicolor PNGs and the scalable SVG are build products of
this script, which keeps four platform formats from disagreeing with the app: an icon
checked in by hand is an icon that can be edited out of sync with the logo.

Run from anywhere; paths are resolved from this file::

    python packaging/make_icons.py

The ``.ico`` carries PNG-compressed entries. Vista and later accept that, and it keeps
a 256 px entry from adding a megabyte of raw BMP to the executable. The ``.icns`` uses
the modern PNG-backed entry types (``ic07`` and up) rather than the deprecated JPEG
ones.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

from blackdream.ui.icons import logo_svg  # noqa: E402

OUT = ROOT / "packaging" / "icons"
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
HICOLOR_SIZES = (16, 32, 48, 64, 128, 256, 512)
#: macOS entry type -> pixel edge. ic11/ic12 are the 2x pairs of 16 and 32.
ICNS_ENTRIES = ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024),
                (b"ic11", 32), (b"ic12", 64), (b"ic13", 512), (b"ic14", 1024))


def render(size: int, svg: str) -> bytes:
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def write_icns(path: Path, payloads: dict[int, bytes]) -> None:
    entries = [(code, payloads[size]) for code, size in ICNS_ENTRIES if size in payloads]
    body = b"".join(
        code + struct.pack(">I", 8 + len(data)) + data for code, data in entries)
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def write_ico(path: Path, payloads: dict[int, bytes]) -> None:
    images = [(size, payloads[size]) for size in ICO_SIZES if size in payloads]
    offset = 6 + 16 * len(images)
    directory = b""
    body = b""
    for size, data in images:
        # width, height, colour count, reserved, planes, bits, byte length, offset
        directory += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                                 len(data), offset)
        offset += len(data)
        body += data
    path.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + directory + body)


def main() -> int:
    app = QGuiApplication(sys.argv[:1])
    svg = logo_svg()
    payloads = {size: render(size, svg) for size in PNG_SIZES}

    png_dir = OUT / "png"
    png_dir.mkdir(parents=True, exist_ok=True)
    for size, data in payloads.items():
        (png_dir / "{}.png".format(size)).write_bytes(data)

    hicolor = OUT / "hicolor"
    for size in HICOLOR_SIZES:
        directory = hicolor / "{}x{}".format(size, size) / "apps"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "blackdream.png").write_bytes(payloads[size])
    scalable = hicolor / "scalable" / "apps"
    scalable.mkdir(parents=True, exist_ok=True)
    (scalable / "blackdream.svg").write_text(svg, encoding="utf-8")

    (OUT / "blackdream.png").write_bytes(payloads[512])
    write_icns(OUT / "blackdream.icns", payloads)
    write_ico(OUT / "blackdream.ico", payloads)

    for name in ("blackdream.ico", "blackdream.icns", "blackdream.png",
                 "hicolor/scalable/apps/blackdream.svg"):
        path = OUT / name
        print("{}  {:,} bytes".format(path.relative_to(ROOT), path.stat().st_size))
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
