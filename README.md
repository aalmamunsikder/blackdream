# BlackDream

**Beta 1 · version `0.9.0-beta.1`** (package version `0.9.0b1`)

An OpenCore EFI builder you can run without a terminal. BlackDream takes a hardware
report, tells you whether the machine can run the macOS release you picked, builds the
EFI folder, and then edits the `config.plist` it just wrote — validation, presets and
SMBIOS serials included — inside the same window.

It is pre-release software. It writes to folders and to a USB volume you choose; it
never formats, mounts, or opens a block device. Read
[docs/RELEASE-NOTES.md](docs/RELEASE-NOTES.md) before you point it at a drive you care
about.

## The three sections

| Section | What it does |
| --- | --- |
| **Installer** | Picks a macOS release (High Sierra 10.13 through Tahoe 26), downloads Apple's recovery image, verifies every chunk against Apple's signed chunklist, and copies the image plus a built EFI folder onto a mounted FAT32 USB drive you selected. |
| **Build EFI** | Loads or collects a hardware report, shows per-device verdicts for the selected release, and generates the EFI folder through the OpenCore engine with live stages, transfer rates and cancellation. Tabs: `Compatibility`, `Build`, `Logs`. |
| **Configure EFI** | Opens the built `config.plist` as a key tree, edits it in memory, adds/removes/moves entries, inserts preset ACPI and Kernel patches, edits `data` values as hex or printable text, runs OpenCore's own `ocvalidate`, generates serials with `macserial`, and writes only when you press `Save`. |

`Settings`, `Help` and `Donate` sit at the bottom of the sidebar. `Help` has a
`Copy environment info` button whose text is what a bug report should carry.

## What this beta has actually been run on

* **Linux x86_64** — the packaged build in `dist/`, CPython 3.14, Qt 6.12, X11 and
  Wayland sessions. Every workflow below was exercised here.
* **Windows and macOS** — the code paths exist and are unit-tested on Linux against
  recorded fixtures, but no Windows or macOS machine has run this beta build. Treat the
  `.spec` output for those platforms as unverified until someone installs it.

The automated suite in `tests/` covers the safety rules described below; it does not
cover real firmware, real drives, or the platform installers. `docs/RELEASE-NOTES.md`
records how many tests passed for this specific build.

## Running it

Unpack the release archive and run the binary inside:

```sh
tar -xzf BlackDream-0.9.0-beta.1-linux-x86_64.tar.gz
./BlackDream/BlackDream
```

Or install the wheel into a Python 3.11+ environment with PySide6 available:

```sh
pip install blackdream-0.9.0b1-py3-none-any.whl
blackdream
```

Building from a checkout: `pip install -e ".[dev]"`, then `blackdream`. Building the
directory bundle: `packaging/build-release.sh` (see below). Useful flags: `--smoke`
renders one frame and exits, which is what packaging uses to prove the bundle starts.

On Linux a desktop entry is provided at `packaging/linux/blackdream.desktop`.

## Reading ACPI tables on Linux needs one extra step

The hardware scan itself is unprivileged. The DSDT is not: `/sys/firmware/acpi/tables`
is root-only, and a build that lacks it cannot patch ACPI. BlackDream ships a helper for
that single read, and polkit — not the app — asks for authorization in its own window.
BlackDream never has a password field and never asks for `sudo` inside itself.

The helper is only used when it is installed where the calling user cannot edit it:

```sh
sudo install -m 0755 -o root -g root \
    BlackDream/_internal/blackdream/hardware/dump_acpi_tables.py \
    /usr/lib/blackdream/dump_acpi_tables.py
sudo cp BlackDream/_internal/blackdream/hardware/com.blackdream.dumpacpi.policy \
    /usr/share/polkit-1/actions/
```

Without it, point **ACPI tables** at a folder of `.aml` tables you dumped another way,
or export a report with the tables included. Declining the authorization window is not
a hardware failure and is never reported as one.

## Where things live

| | Linux | Windows | macOS |
| --- | --- | --- | --- |
| Data root | `$XDG_DATA_HOME/blackdream` or `~/.local/share/blackdream` | `%LOCALAPPDATA%\blackdream` | `~/Library/Application Support/blackdream` |
| Recovery image cache | `<root>/cache/<board id>` | same | same |
| Downloaded tools | `<root>/tools` | same | same |
| Crash reports | `<root>/logs/crashes` | same | same |

Settings → Storage shows the real paths for your machine. Downloads and saved logs go
where you point them.

## Rules the app will not break

* Nothing is written to a USB volume until Apple's signed chunklist and every image
  chunk verify, and the target volume's identity is re-checked immediately before the
  write. Only `EFI` and `com.apple.recovery.boot` are replaced, and a failure part-way
  through puts the previous trees back.
* No drive is preselected. The write button stays disabled until the image is verified,
  a complete EFI folder is chosen, and a target volume is chosen.
* Build output is a folder. A non-empty folder that BlackDream did not create is
  refused rather than deleted; an existing output is replaced only when the build marker
  proves it belongs to the app.
* `config.plist` is never touched by editing, validating or generating serials. `Save`
  writes atomically and keeps the previous bytes as `config.plist.bak`; `ocvalidate` runs
  on a temporary copy. Unknown keys, key order and value types survive a round trip.
* Runtime binaries (`iasl`, `macserial`, `ocvalidate`, Hardware Sniffer) are installed
  into the tools directory and verified against pinned SHA-256 digests before they run,
  and never next to a module Python could import.
* No account, no telemetry, no ads, no update check. The engine log never contains a
  generated serial, MLB, UUID or ROM.

## Reporting a problem

Include: the version line and `Copy environment info` output from `Help`, which workflow
you attempted, what you expected versus what happened, whether it repeats, and the engine
log saved from `Logs`. If a crash happened, attach the file from the crash-report folder
named in the environment info. Review a `Report.json` before you share it publicly — it
describes your machine. Do not post SMBIOS serial, MLB, UUID or ROM values.

There is no feedback form inside the app and no upload: send the report to whoever gave
you this build.

## Building a release

```sh
packaging/build-release.sh             # tests, bundle, wheel, sdist, archive, checksums
packaging/build-release.sh --no-tests  # skip the suite
packaging/build-release.sh --bundle-only
```

The script runs the suite, renders the icons from the in-app mark, builds the
one-directory bundle with PyInstaller, drops the license texts beside the launcher and
into `_internal/licenses`, smoke-tests the relocated bundle, builds the wheel and the
sdist, archives the bundle and writes `SHA256SUMS.txt` for everything in
`dist/release/`. `packaging/verify-artifacts.py` then reads the finished artifacts back
and refuses the build if a runtime binary leaked into them or a notice is missing.

Windows and macOS artifacts have to be built on their own platform;
`packaging/blackdream.spec` carries the `.ico`/`.icns` wiring and the app bundle metadata
for those runs. Only the Linux path of this script has actually been executed. Icons are
generated from the in-app vector mark by `packaging/make_icons.py`.

## License and credit

BlackDream is MIT licensed ([LICENSE](LICENSE)). It carries a vendored BSD-3-Clause copy
of the OpCore Simplify engine (`src/ocengine`, pinned commit and the exact list of
modifications in `src/ocengine/VENDOR_NOTICE.txt`), BSD-3-Clause OpenCore assets, MIT
preset and patch data from OpenCore Auxiliary Tools, BSD-3-Clause Windows identifier
tables from Hardware Sniffer, and `usb.ids` under its BSD-3-Clause option. The full list,
including the runtime dependencies, is [docs/THIRD-PARTY.md](docs/THIRD-PARTY.md).
