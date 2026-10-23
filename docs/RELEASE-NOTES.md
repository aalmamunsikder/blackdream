# BlackDream 0.9.0-beta.1

Released 2026-10-23 · pre-release · MIT licensed · no account, no telemetry, no ads,
no update check.

This is the first build distributed outside the development machine. It is a **beta**:
it asks for reports, it does not promise coverage. The feature set is frozen at what
`docs/UI-MOCKUP-SPEC.md` v3.4 marks *built*; anything labelled *concept* or *planned* is
not in this binary.

## What is in this release

Three sections, in the order the workflow runs:

1. **Installer** — choose a macOS release (High Sierra 10.13, Mojave 10.14, Catalina
   10.15, Big Sur 11, Monterey 12, Ventura 13, Sonoma 14, Sequoia 15, Tahoe 26),
   download Apple's recovery image for it, verify the signed chunklist and every image
   chunk, then copy the image and a complete EFI folder onto a mounted FAT32 USB drive
   you picked. The write replaces only `EFI` and `com.apple.recovery.boot`.
2. **Build EFI** — `Compatibility`, `Build` and `Logs`. Open or drop a `Report.json`, or
   collect one on this machine, see the per-device verdicts for the chosen release, and
   generate the EFI folder with live stages, transfer rates and cancellation.
3. **Configure EFI** — the built `config.plist` in the window: key tree with search,
   inline scalar editing, add/remove/move entries, 12 preset ACPI and Kernel patch
   entries, `data` values edited as hex or printable text, `ocvalidate` results inline,
   `macserial` SMBIOS serials behind a confirmation, atomic `Save` with
   `config.plist.bak`, and `Revert` back to the bytes on disk.

Plus `Settings` (theme, storage paths, safety statements), `Help` (quick start,
shortcuts, troubleshooting, `Copy environment info`) and `Donate` (ways to help that do
not involve money; no payment link exists yet).

## Safety behaviour you should know before you test

* Nothing reaches a USB volume until the image verifies, and the volume's identity is
  re-checked at the moment of the write. A drive swapped behind the confirmation dialog
  is refused. If the second half of the swap fails, the first half is put back.
* BlackDream never formats a drive, never mounts anything, never opens a block device,
  and never writes to this machine's own EFI partition.
* Build output is a folder. A non-empty folder the app did not create is refused;
  a previous BlackDream build is replaced only when its marker proves ownership.
* Editing, validating and generating serials change only the in-memory document. The
  file is written when, and only when, you press `Save`.
* Downloaded tools (`iasl`, `macserial`, `ocvalidate`, Hardware Sniffer) are verified
  against pinned SHA-256 digests before they run, and are never executed from a
  directory Python imports from.
* An unhandled error in the window is written to the crash-report folder listed by
  `Help ▸ Copy environment info`; the five newest reports are kept.

## Tested on / not tested on

| Environment | Status |
| --- | --- |
| Linux x86_64, CPython 3.14, Qt 6.12, X11 and Wayland | **this is the build being shipped**; all three workflows exercised, 634 automated tests |
| Windows 10/11 | code paths present, unit-tested against recorded fixtures on Linux; **no native run of this beta artifact** |
| macOS 12+ | code paths present, `LSMinimumSystemVersion` 12.0; **no native run of this beta artifact** |
| CPython 3.11–3.13 | syntax-verified against the 3.11 grammar; **not executed** |

Hardware coverage in this cycle is one real desktop machine plus the synthetic and
recorded report corpus. Verdicts for devices nobody has reported are the weakest part
of the product.

## Known issues and limitations

* **The Linux ACPI helper is not installed for you.** In an unpacked bundle the helper is
  user-writable, so polkit will refuse it. Follow the two `sudo install` / `sudo cp`
  commands in `README.md`, or point **ACPI tables** at `.aml` tables you exported
  elsewhere. Declining the authorization window is reported as a refusal, never as a
  hardware fault.
* **Only FAT32 volumes appear as installer targets**, and only if they are already
  mounted and writable by your session. An NTFS or ext4 stick is not offered, because
  firmware on the target machine has to read the volume.
* **Apple decides which releases still exist.** Each choice in the release picker asks
  for a recovery image by board id and serial; if Apple stops serving one, the download
  fails with the reason rather than substituting another release's image.
* **First use of `ocvalidate`, `macserial` or `iasl` needs the network** and writes into
  the per-user tools directory. Offline machines can pre-seed that directory (see
  `README.md`).
* **Presets are 12 entries**, the ACPI and Kernel patches adapted from OCAT's preset
  library. The library is not fetched and has no update channel.
* **There is no undo stack** in the config editor. `Revert` reloads the file on disk and
  discards unsaved edits; that is the only way back.
* **`Show as text` is a view of bytes, not an encoding guess.** Printable ASCII shows as
  text, everything else as `\xNN`. UTF-8 strings are not decoded.
* No device overrides, no standalone SMBIOS editor, no first-run download wizard, no
  base-config library, no EFI backup browser. These are concepts in the specification,
  not features of this binary.

## How to report a problem

Include, in this order:

1. the version line and the `Help ▸ Copy environment info` output,
2. which workflow you attempted (Installer, Compatibility, Build, Configure, other),
3. what you expected versus what happened, and whether it repeats,
4. the exact error code shown on the red card, if any,
5. the engine log saved from `Logs`, and the crash-report file if the app closed,
6. whether your `Report.json` names your machine before you attach it publicly.

Do not post SMBIOS serial, MLB, UUID or ROM values. There is no form inside the app and
nothing is uploaded; send the report to whoever gave you this build.

## Checksums

Every build publishes three files into `dist/release/`, named:

| Name | What it is |
| --- | --- |
| `BlackDream-0.9.0-beta.1-<os>-<arch>.tar.gz` | the application bundle: unpack it and run the launcher inside. `.zip` on Windows |
| `blackdream-0.9.0b1-py3-none-any.whl` | the wheel, for a machine that already has Python 3.11 or newer |
| `blackdream-0.9.0b1.tar.gz` | the source distribution |

`SHA256SUMS.txt` in the same folder gives the SHA-256 of each of them, and
`packaging/verify-artifacts.py` recomputes every digest in that file from the bytes on
disk and fails the build on any mismatch. The sums file is deliberately *not* inside the
archive: a document that quoted its own checksum could not be written by the build that
produces it, so the notes name the files and the checksums file carries the digests.

Verify the archive you downloaded before unpacking it. The bundle is not code-signed and
not notarized; macOS and Windows will warn you about that on first launch.
