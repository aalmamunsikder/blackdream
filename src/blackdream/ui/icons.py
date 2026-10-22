"""Line icons for the shell, kept as inline SVG.

The wheel ships ``src/blackdream`` as a package, so a ``:/icons`` resource tree or a
data directory would each need packaging work that a string does not. Every drawing
is a 24x24 stroke icon with ``{color}`` substituted at render time, which is also
what lets one icon follow the theme without a second copy.

Pixmaps are rendered at 2x and tagged with that ratio: Qt then draws them at their
logical size, crisp on both a 1x screenshot and a HiDPI screen.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_DPR = 2.0

_SVG = {
    "pulse": '<polyline points="2.5,12 7,12 9.5,6 13.5,18 16,12 21.5,12"/>',
    "build": '<polygon points="12,2.5 2.5,7 12,11.5 21.5,7"/><polyline points="2.5,12 12,16.5 21.5,12"/><polyline points="2.5,16.5 12,21 21.5,16.5"/>',
    "logs": '<polyline points="4,17 10,11 4,5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "help": '<circle cx="12" cy="12" r="9.2"/><path d="M9.2 9.2a2.9 2.9 0 0 1 5.6 1c0 1.9-2.8 2.4-2.8 4"/><line x1="12" y1="17.2" x2="12.01" y2="17.2"/>',
    "heart": '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8z"/>',
    "share": '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.6" y1="13.5" x2="15.4" y2="17.5"/><line x1="15.4" y1="6.5" x2="8.6" y2="10.5"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "file": '<path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8z"/><polyline points="14,2.5 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    "layers": '<polygon points="12,2.5 2.5,7 12,11.5 21.5,7"/><polyline points="2.5,12 12,16.5 21.5,12"/><polyline points="2.5,16.5 12,21 21.5,16.5"/>',
    "folder": '<path d="M21.5 18.5a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2h5l2 3h8a2 2 0 0 1 2 2z"/>',
    "play": '<polygon points="6.5,4 19.5,12 6.5,20" fill="{color}" stroke="none"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7,10 12,15 17,10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "external": '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15,3 21,3 21,9"/><line x1="10" y1="14" x2="21" y2="3"/>',
    "check": '<polyline points="4,12.5 9.5,18 20,6.5"/>',
    "check-circle": '<circle cx="12" cy="12" r="10" fill="{color}" stroke="none"/><polyline points="7.6,12.2 10.7,15.3 16.4,8.8" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "x-circle": '<circle cx="12" cy="12" r="10" fill="{color}" stroke="none"/><line x1="8.6" y1="8.6" x2="15.4" y2="15.4" stroke="#ffffff" stroke-width="2" stroke-linecap="round"/><line x1="15.4" y1="8.6" x2="8.6" y2="15.4" stroke="#ffffff" stroke-width="2" stroke-linecap="round"/>',
    "alert-circle": '<circle cx="12" cy="12" r="10" fill="{color}" stroke="none"/><line x1="12" y1="6.6" x2="12" y2="13" stroke="#ffffff" stroke-width="2.1" stroke-linecap="round"/><circle cx="12" cy="17" r="1.15" fill="#ffffff" stroke="none"/>',
    "dot": '<circle cx="12" cy="12" r="9" fill="none" stroke="{color}" stroke-width="1.6" stroke-dasharray="2.4 2.6"/><circle cx="12" cy="12" r="2.2" fill="{color}" stroke="none"/>',
    "spinner": '<circle cx="12" cy="12" r="9" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-dasharray="43 14" transform="rotate(-50 12 12)"/>',
    "minus": '<circle cx="12" cy="12" r="10" fill="{color}" stroke="none"/><line x1="7.8" y1="12" x2="16.2" y2="12" stroke="#ffffff" stroke-width="2" stroke-linecap="round"/>',
    "search": '<circle cx="10.8" cy="10.8" r="7"/><line x1="21" y1="21" x2="16.2" y2="16.2"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "chevron-right": '<polyline points="9,18 15,12 9,6"/>',
    "chevron-down": '<polyline points="6,9 12,15 18,9"/>',
    "x": '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
    "copy": '<rect x="9" y="9" width="12.5" height="12.5" rx="2"/><path d="M5.5 15H4.5a2 2 0 0 1-2-2V4.5a2 2 0 0 1 2-2H14a2 2 0 0 1 2 2v1"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17,21 17,13 7,13 7,21"/><polyline points="7,3 7,8 15,8"/>',
    "clock": '<circle cx="12" cy="12" r="9.2"/><polyline points="12,6.6 12,12 15.6,14"/>',
    "gauge": '<path d="M20.8 15.5a9.2 9.2 0 1 0-17.6 0"/><line x1="12" y1="12" x2="16.4" y2="7.6"/><circle cx="12" cy="12" r="1.3" fill="{color}" stroke="none"/>',
    "steps": '<line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/><circle cx="4" cy="6" r="1.4" fill="{color}" stroke="none"/><circle cx="4" cy="12" r="1.4" fill="{color}" stroke="none"/><circle cx="4" cy="18" r="1.4" fill="{color}" stroke="none"/>',
    "cpu": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9.2" y="9.2" width="5.6" height="5.6" rx="1"/><path d="M9 1.8v3.2M15 1.8v3.2M9 19v3.2M15 19v3.2M1.8 9h3.2M1.8 15h3.2M19 9h3.2M19 15h3.2"/>',
    "gpu": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="8" cy="12" r="2.2"/><circle cx="16" cy="12" r="2.2"/>',
    "monitor": '<rect x="2.5" y="4" width="19" height="12.5" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="16.5" x2="12" y2="21"/>',
    "speaker": '<polygon points="11,5 6,9 2.5,9 2.5,15 6,15 11,19"/><path d="M15.2 8.6a5 5 0 0 1 0 6.8"/><path d="M18.2 5.6a9.2 9.2 0 0 1 0 12.8"/>',
    "wifi": '<path d="M2.5 9a14.5 14.5 0 0 1 19 0"/><path d="M5.8 12.6a9.5 9.5 0 0 1 12.4 0"/><path d="M9 16a4.8 4.8 0 0 1 6 0"/><line x1="12" y1="19.6" x2="12.01" y2="19.6"/>',
    "globe": '<circle cx="12" cy="12" r="9.2"/><line x1="2.8" y1="12" x2="21.2" y2="12"/><path d="M12 2.8a14 14 0 0 1 3.6 9.2 14 14 0 0 1-3.6 9.2 14 14 0 0 1-3.6-9.2A14 14 0 0 1 12 2.8z"/>',
    "drive": '<rect x="2.5" y="4" width="19" height="6.8" rx="1.8"/><rect x="2.5" y="13.2" width="19" height="6.8" rx="1.8"/><line x1="6" y1="7.4" x2="6.01" y2="7.4"/><line x1="6" y1="16.6" x2="6.01" y2="16.6"/>',
    "usb": '<circle cx="12" cy="20" r="1.5"/><line x1="12" y1="18.4" x2="12" y2="4"/><polyline points="9.6,6.4 12,4 14.4,6.4"/><path d="M12 10.5l4 2.8v2.2"/><rect x="14.4" y="15.5" width="3.6" height="2.8" rx="0.8"/><path d="M12 13.5l-4 2.6v1.6"/><circle cx="8" cy="18.9" r="1.4"/>',
    "bluetooth": '<polyline points="6.6,6.8 17.4,17.2 12,22 12,2 17.4,6.8 6.6,17.2"/>',
    "sd": '<path d="M6 2.5h8.5l5 5V21.5H6z"/><path d="M9 2.5v5M12 2.5v5M15 2.5v5"/>',
    "fingerprint": '<path d="M12 4.5a7.5 7.5 0 0 1 7.5 7.5"/><path d="M4.5 12a7.5 7.5 0 0 1 5-7.1"/><path d="M8 20a12 12 0 0 0 1.4-5.7A2.6 2.6 0 0 1 12 11.7a2.6 2.6 0 0 1 2.6 2.6c0 1.3-.2 2.6-.6 3.8"/><path d="M16 19.4a15 15 0 0 0 1-5.4 5 5 0 0 0-10 0c0 1.7-.2 3.4-.7 5"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2.5H20v19H6.5A2.5 2.5 0 0 1 4 19V5a2.5 2.5 0 0 1 2.5-2.5z"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    "info": '<circle cx="12" cy="12" r="9.2"/><line x1="12" y1="11" x2="12" y2="16.5"/><circle cx="12" cy="7.8" r="1" fill="{color}" stroke="none"/>',
    "alert-triangle": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13.5"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "eye": '<path d="M1.8 12S5.5 5 12 5s10.2 7 10.2 7-3.7 7-10.2 7S1.8 12 1.8 12z"/><circle cx="12" cy="12" r="3"/>',
    "wave": '<path d="M2 12h3l2.5-6 4 12 3-8 1.8 4H22"/>',
}

# BD letterforms traced from Liberation Sans Bold (SIL OFL 1.1) and embedded as paths,
# so the mark is identical on every platform without shipping or loading a font.
_LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
<defs>
 <linearGradient id="bd" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="#6b78f4"/>
  <stop offset="0.5" stop-color="#4338ca"/>
  <stop offset="1" stop-color="#1c1749"/>
 </linearGradient>
</defs>
<rect width="48" height="48" rx="14" fill="url(#bd)"/>
<rect x="0.7" y="0.7" width="46.6" height="46.6" rx="13.3" fill="none" stroke="#ffffff" stroke-opacity="0.2" stroke-width="1.1"/>
<g transform="translate(6.33 32.58) scale(0.04678)"><path fill="#ffffff" d="M360.72 -104.62 C348.23 -45.55 323.24 -27.33 298.26 -9.11 L35.66 0.00 L35.66 -366.70 L203.52 -366.70 C282.16 -358.94 305.15 -343.41 328.13 -327.88 C333.86 -236.18 322.32 -221.87 310.78 -207.55 C321.89 -180.05 337.42 -164.87 352.95 -149.68 M262.34 -264.16 C257.09 -292.35 246.59 -299.29 236.09 -306.23 L112.44 -309.70 L112.44 -218.88 L200.39 -218.88 C237.83 -222.65 247.63 -230.20 257.44 -237.74 M283.67 -110.61 C259.04 -162.14 209.77 -162.14 112.44 -162.14 L112.44 -57.00 L212.62 -57.00 C255.26 -61.47 266.62 -70.40 277.99 -79.33 Z"/></g>
<g transform="translate(23.04 32.58) scale(0.04678)"><path fill="#ffffff" d="M362.53 -186.08 C355.11 -115.25 340.28 -87.05 325.45 -58.86 C219.05 0.00 184.00 0.00 35.66 0.00 L35.66 -366.70 L168.39 -366.70 C277.95 -351.13 311.78 -319.98 345.61 -288.84 M285.23 -186.08 C275.00 -255.52 254.52 -276.26 234.05 -296.99 L112.44 -307.36 L112.44 -59.34 L177.50 -59.34 C236.65 -70.71 256.09 -93.44 275.52 -116.17 Z"/></g>
</svg>"""


def _render(svg: str, size: float, color: str = "#ffffff") -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg.replace("{color}", color).encode("utf-8")))
    pixmap = QPixmap(int(round(size * _DPR)), int(round(size * _DPR)))
    pixmap.setDevicePixelRatio(_DPR)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def _document(fragment: str) -> str:
    """Wrap a fragment in a root that carries the stroke style.

    The attributes live on the root so every child inherits them: writing them per
    element meant each new icon silently rendered as a solid black blob whenever
    ``{stroke}`` was forgotten. Children that need a fill (the filled status dots,
    the play triangle) still override ``fill`` and ``stroke`` on themselves.
    """
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            'fill="none" stroke="{color}" stroke-width="1.7" '
            'stroke-linecap="round" stroke-linejoin="round">' + fragment + '</svg>')


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 18) -> QPixmap:
    return _render(_document(_SVG[name]), size, color)


def icon(name: str, color: str, size: int = 18) -> QIcon:
    return QIcon(pixmap(name, color, size))


@lru_cache(maxsize=8)
def logo(size: int = 40) -> QPixmap:
    return _render(_LOGO, size)


@lru_cache(maxsize=256)
def tile(name: str, color: str, background: str, size: int = 28) -> QPixmap:
    """An icon on a rounded tinted square, for table rows and file fields."""
    from blackdream.ui.theme import qcolor

    pixmap = QPixmap(int(round(size * _DPR)), int(round(size * _DPR)))
    pixmap.setDevicePixelRatio(_DPR)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(qcolor(background))
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.28, size * 0.28)
    inner = size * 0.58
    offset = (size - inner) / 2.0
    renderer = QSvgRenderer(QByteArray(_document(_SVG[name]).replace("{color}", color)
                                       .encode("utf-8")))
    renderer.render(painter, QRectF(offset, offset, inner, inner))
    painter.end()
    return pixmap


def clear_caches() -> None:
    """Drop every cached rendering. Tests swap palettes and themes in one process."""
    pixmap.cache_clear()
    logo.cache_clear()
    tile.cache_clear()
