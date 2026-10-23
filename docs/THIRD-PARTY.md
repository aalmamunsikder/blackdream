# Third-party code and data

BlackDream is MIT licensed. Everything it ships or runs that is not its own code is
listed here with the license it arrives under. Files named below ship inside the
package, the wheel and the application bundle, so the notices travel with the binary.

## OpCore Simplify (vendored engine)

- Project: <https://github.com/lzhoang2801/OpCore-Simplify>
- License: BSD-3-Clause — `src/ocengine/LICENSE.upstream.BSD-3-Clause`
- Pinned commit: `f0e1e441bb455c33e9695a9c9c50e8ca931d4de8` (`main`)
- Vendored as `src/ocengine`. `src/ocengine/VENDOR_NOTICE.txt` records the pinned
  commit, every group of modifications (interface changes, determinism, download
  integrity, and four proven defects that are fixed here and not upstream), and the
  procedure for re-landing them on a newer upstream commit.
- None of it comes from upstream's `add-gui-support` branch, which is AGPL-3.0-only;
  no AGPL code is used, linked or derived from.

## Hardware Sniffer (vendored Linux collector, Windows CLI)

- Project: <https://github.com/lzhoang2801/Hardware-Sniffer>
- License: BSD-3-Clause — `src/blackdream/hardware/sniffer/LICENSE.upstream.BSD-3-Clause`
- Pinned tag: `2.1.1`, commit `2e0fa16020279a7a13575813ace94537362e262a`
- The Linux identifier and collection layer is vendored under
  `src/blackdream/hardware/sniffer`; `src/blackdream/hardware/sniffer/VENDOR_NOTICE.txt`
  explains why it is vendored rather than shelled out to (upstream publishes only
  Windows `.exe` assets).
- On Windows the released `Hardware-Sniffer-CLI.exe` is downloaded at run time by the
  engine and its digest verified before it is executed; the executable is never
  installed next to a Python module.

## usb.ids

- Project: <http://www.linux-usb.org/usb-ids.html>, maintained by Stephen J. Gowdy
- License: dual GPL-2.0-or-later **or** BSD-3-Clause; this project uses the
  BSD-3-Clause option, the same option the vendored Hardware Sniffer data chooses.
- File: `src/blackdream/hardware/sniffer/datasets/usb.ids`, version `2024.07.04`.
  It is data used to turn a vendor/product id into a human-readable device name.

## OpenCorePkg 1.0.8

- Project: <https://github.com/acidanthera/OpenCorePkg>
- License: BSD-3-Clause, reproduced in `src/blackdream/data/OpenCore-LICENSE.txt`
- Used for:
  - `src/blackdream/data/OpenCore-1.0.8-Sample.plist` — the schema defaults the
    config editor offers when a key is added. Shipped in the application data.
  - `ocvalidate` — the validator the Configure EFI section runs against the
    in-memory document and the saved file. It is resolved from the app tools
    directory, or fetched once from the pinned release archive.
  - `macserial` — the SMBIOS serial generator the Configure page calls. It is
    resolved like `iasl`; every candidate is refused unless its own bytes match
    the member pin in the vendored engine (`MACSERIAL_ASSETS`).

The release archive is
`https://github.com/acidanthera/OpenCorePkg/releases/download/1.0.8/OpenCore-1.0.8-RELEASE.zip`
with SHA-256
`2011e8b7216ecb2645d97ea710df965947edd406846e92050b9bc4190be6d27b`.
The editor pins each platform's validator by the SHA-256 of its own bytes:

| Platform | Member | SHA-256 |
| --- | --- | --- |
| macOS | `Utilities/ocvalidate/ocvalidate` | `c76f907d5caad299889a2314ae68f03cd8538ad53f65a3c2c7c95ae0d0bb0b38` |
| Linux | `Utilities/ocvalidate/ocvalidate.linux` | `3411f3b7e645f94c7ba602687d42ce6bf4e5ee560f50c3f2ca134e26dfe394ab` |
| Windows | `Utilities/ocvalidate/ocvalidate.exe` | `f459053cefdf1b2ff8c1d74d61d9dc5bb30ce72a4fcbf15bb29333e77d8d045f` |

The binaries live in the app-managed tools directory, never in the package
directory or on Python's import path. A member whose bytes do not match the
table above is refused before it is executed.

`Installer` follows the same recovery-service protocol as OpenCorePkg's
`Utilities/macrecovery` and performs the same signature check against Apple's
embedded EFI ROM public key. It is a reimplementation from the published behaviour of
that tool, not a copy of its source; no `macrecovery` file ships.

## OpenCore Auxiliary Tools

The Configure EFI editor was designed after studying OCAT
(<https://github.com/ic005k/OCAuxiliaryTools>, MIT). The 12 patch entries in
`src/blackdream/core/config_presets.py` are adapted from OCAT's
`Database/preset/PreSet.plist` and trimmed to the fields the pinned OpenCore
1.0.8 schema requires; each is checked against that sample by
`tests/test_config_presets.py` and validated with `ocvalidate`. The MIT license
and copyright notice are reproduced in
`src/blackdream/data/OCAT-LICENSE.txt`, which ships with the application.

No OCAT source code, other assets, or binaries are shipped or executed by
BlackDream.

## iasl (ACPI compiler, fetched at run time)

- Project: <https://github.com/open-acpica/acpica> — the ACPI Specification
  reference implementation
- License: dual GPL-2.0-or-later **or** the BSD-3-Clause Intel license; upstream
  distributes builds through `acidanthera/MaciASL` and the mirrors the engine names
  in `src/ocengine/dsdt.py`
- BlackDream does not ship an `iasl` binary. The engine resolves it from the
  app-managed tools directory or downloads it, and refuses to run a copy whose pinned
  digest does not match.

## Runtime dependencies

| Project | License | Ships as |
| --- | --- | --- |
| [PySide6 / Qt 6](https://www.qt.io/qt-licensing-terms) | LGPL-3.0 (commercial alternative available); Qt itself additionally BSD-3-Clause, MIT and Zlib components | Python package, bundled into the application |
| [shiboken2](https://doc.qt.io/pyside6/shibokenmodule.html) | LGPL-3.0 | Python package, bundled |
| [certifi](https://github.com/certifi/python-certifi) | MPL-2.0 | Python package; its CA bundle is the trust store for every HTTPS request |
| [Python 3](https://docs.python.org/3/license.html) | PSF License (Python Software Foundation) | interpreter, bundled in the application |

PySide6 is used under its LGPL-3.0 terms: it is linked dynamically as distributed by
its own wheels, the user can replace it by installing a different PySide6 build into
the same environment, and the application's own sources are available under MIT.

## Build tooling (not shipped)

| Project | License | Role |
| --- | --- | --- |
| [PyInstaller](https://pyinstaller.org) | GPL-2.0-or-later with the PyInstaller licensing exception | creates the one-directory bundle; the exception covers the bootloader output |
| [hatchling](https://hatch.pypa.io) | MIT | builds the wheel and sdist |
| [pytest](https://docs.pytest.org) | MIT | runs the test suite |

## Font outlines in the application icon

`src/blackdream/ui/icons.py` embeds the `BD` lettermark as SVG path data traced from
the glyph outlines of [Liberation Sans Bold](https://pagure.io/liberation-fonto),
which is under the SIL Open Font License 1.1. The outlines are static path data in the
source; no font file is shipped, loaded or linked, and the mark renders identically
wherever the app runs.
