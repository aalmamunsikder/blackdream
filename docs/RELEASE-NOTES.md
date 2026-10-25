# BlackDream 0.9.0-beta.4

Released 2026-10-25 · pre-release · MIT licensed · no account, no telemetry, no ads,
no update check.

This is the fourth build distributed outside the development machine. It is a **beta**:
it asks for reports, it does not promise coverage. The feature set is frozen at what
`docs/UI-MOCKUP-SPEC.md` v3.7 marks *built*; anything labelled *concept* or *planned* is
not in this binary.

## What is new in beta 4

* **Dependency advisories** (`Configure EFI`, `Dependencies…`). Reads the kext, driver,
  boot-arg and quirk relationships the open `config.plist` already claims and reports the
  ones it does not keep: a kext whose `MaxKernel` excludes the release you selected, a
  boot-arg naming a kext that is not injected, `OpenRuntime.efi` missing from `UEFI` while
  its pairing quirk is on, a duplicate entry, two graphics kexts that both claim the same
  hardware, a quirk pair the engine never derives apart. Every row cites the rule it came
  from and the file and line that rule was read at, so a tester can check the claim rather
  than take it. `Copy` and `Save as text…` export the report with the same citation block
  it shows on screen. `Dismiss` hides one advisory hereafter and `Go to key` closes the
  dialog with that key selected in the tree. There is no `Apply`, `Fix` or `Reorder`
  button: this reports relationships, it does not edit them. Dismissals are the only write
  and they go to `advisor-dismissals.json` in BlackDream's own state folder, never into
  `config.plist`.
* **Every vendor notice keeps its own name.** In beta 3 the bundle's `licenses/` folder
  held a single `VENDOR_NOTICE.txt`, so installing one notice over another left a file
  whose name promised more than its bytes delivered. Each notice now lives in its own
  directory, and the packaging check computes a digest of what is actually installed.
* **No label is ever cut to fit its control.** The window's minimum width and a platform
  font a few per cent wider than the reference one used to meet in a squeezed toolbar:
  `Changes…` drew as `hanges`, and later CI runs found `Generate serials`, `Presets…`,
  `Schema preview…` and `Validate again` losing their last letters. The rail is now a floor
  that grows by the pixels its labels need, and every action row takes a second line
  instead of compressing a button. Every frame in `docs/screenshots` is 1536 px wide and
  could not show this; the measurement happens at the smallest window and is re-run with
  a manufactured wider font on all three platforms.

## Carried from beta 3

Beta 3 added six surfaces around the analysis the app already produces: two comparisons,
two local stores, one checklist and one preview. They are unchanged in beta 4. Every one of
them reads. None of them grades a device, writes a file, mounts a disk, boots anything,
uploads anything or claims that a clean result proves a boot.

* **Compare releases** (`Compatibility`, `Compare releases…`). One row per graded device,
  one column per selectable macOS release, so the trade-off between 10.13 and Tahoe is
  visible at once instead of one release at a time. Each cell is the label the `Status`
  column already shows for that device, produced by the same function with the same OCLP
  range — the grid cannot disagree with the table above it, and nothing is re-graded.
  `Copy` and `Save as text…` export the grid. The dialog states plainly that these are
  compatibility ranges, not a firmware, hardware or boot test.
* **Compare reports** (`Compatibility`, `Compare reports…`). Pick a second `Report.json`
  and the app diffs the two files exactly as they were recorded. It keeps two kinds of
  change apart: a *hardware* change moves a field such as `Processor Name`, `Device ID`
  or `PCI Path`, while a *reading* change is the same hardware whose stored compatibility
  verdict differs. That distinction matters — a verdict that changed between two reports
  can come from a different engine or database version rather than from the machine — and
  neither side is re-analysed here. A file that is not a JSON object is refused with the
  reason, not shown as a half comparison.
* **Profiles** (`Compatibility`, `Profiles…`). A profile is five fields: a name, a report
  path, an EFI folder, a release and an update stamp. It stores no serial, MLB, UUID or
  ROM value, so a profile cannot carry one machine's identity onto another. `Use` loads
  that report and selects the release the profile named once the version options exist;
  if the report has moved, the app says so with its path and changes nothing else. The
  list lives in `profiles.json` in BlackDream's own state folder, written atomically, and
  is never synced or uploaded.
* **Build history** (`Build progress`, `History…`). The last 100 builds this app made on
  this machine, newest first, with the timestamp, release, result, output folder, and
  whether that folder and its manifest are still where they were recorded. A folder you
  moved or deleted is shown as `Folder missing` and its `Open folder` stays disabled —
  the row is never rewritten or quietly pruned, because the history's job is to say what
  happened, not what still exists. `Copy history` and `Save as text…` export it.
* **Before the first boot** (`Help`). A card of six advice rows — a spare drive, firmware
  settings, a way back, the OpenCore picker, verbose boot, a recovery plan — and a
  `Copy the checklist` button. It is advice and nothing else: BlackDream has no boot
  button, starts no reboot, and writes no firmware or NVRAM.
* **Schema preview** (`Configure EFI`, `Schema preview…`). Compares the open
  `config.plist` with the pinned OpenCore 1.0.8 sample and shows what a migration *would*
  do: keys missing from the file, keys not in the schema, keys whose type changed. A
  projection is then built from safe additions only — scalars and empty containers, never
  an invented array — and OpenCore's own `ocvalidate` is run on that projection in the
  background, with its result shown as written. There is no `Migrate`, `Apply` or `Fix`
  button, `config.plist` is untouched, and the note written when the dialog closes says so.

## What is in this release

Three sections, in the order the workflow runs:

1. **Installer** — choose a macOS release (High Sierra 10.13, Mojave 10.14, Catalina
   10.15, Big Sur 11, Monterey 12, Ventura 13, Sonoma 14, Sequoia 15, Tahoe 26),
   download Apple's recovery image for it, verify the signed chunklist and every image
   chunk, then copy the image and a complete EFI folder onto a mounted FAT32 USB drive
   you picked. The write replaces only `EFI` and `com.apple.recovery.boot`.
2. **Build EFI** — `Compatibility`, `Build` and `Logs`. Open or drop a `Report.json`, or
   collect one on this machine, see the per-device verdicts for the chosen release, and
   generate the EFI folder with live stages, transfer rates and cancellation. The release
   matrix, report comparison, profiles and build history above live here.
3. **Configure EFI** — the built `config.plist` in the window: key tree with search,
   inline scalar editing, add/remove/move entries, 12 preset ACPI and Kernel patch
   entries, `data` values edited as hex or printable text, `ocvalidate` results inline,
   `macserial` SMBIOS serials behind a confirmation, undo/redo with a `Changes…` review,
   atomic `Save` with `config.plist.bak`, and `Revert` back to the bytes on disk. The
   dependency advisories and the schema preview above live here.

Plus `Settings` (theme, storage paths, safety statements), `Help` (quick start,
shortcuts, troubleshooting, the first-boot checklist, `Copy environment info`,
`Save diagnostic bundle…`) and `Donate` (ways to help that do not involve money; no
payment link exists yet).

Carried over from beta 2, unchanged in behaviour: the `Folder checks` card (`Run checks`,
`Verify manifest`, `Save report…`), clickable `ocvalidate` lines that select the key they
name, and the privacy-safe diagnostic bundle.

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
* The new comparison and advisory surfaces read and never write. A release matrix or a
  report comparison cannot change a verdict, a schema preview cannot change a config, and
  a dependency advisory offers no `Apply`, `Fix` or `Reorder`. The one write the advisor
  makes is a dismissal, in its own state file.
* Profiles and build history are local files in BlackDream's state folder, next to the
  artifact cache. They are not uploaded, not synced, and a profile deliberately has no
  field for an SMBIOS identity value.
* Downloaded tools (`iasl`, `macserial`, `ocvalidate`, Hardware Sniffer) are verified
  against pinned SHA-256 digests before they run, and are never executed from a
  directory Python imports from.
* An unhandled error in the window is written to the crash-report folder listed by
  `Help ▸ Copy environment info`; the five newest reports are kept.

## Tested on / not tested on

| Environment | Status |
| --- | --- |
| Linux x86_64, CPython 3.14, Qt 6.12, X11 and Wayland | the bundle is built and smoke-tested on glibc 2.35; 923 automated tests |
| Windows 10/11 | the bundle is built and smoke-tested natively on a Windows runner; **no full workflow run on real hardware** |
| macOS 14+ on Intel | the `.app` is built and smoke-tested natively on an Intel macOS runner; Apple Silicon runs the same Intel bundle under Rosetta 2; **no full workflow run on real hardware** |
| CPython 3.11–3.13 | syntax-verified against the 3.11 grammar; **not executed** |

Hardware coverage in this cycle is one real desktop machine plus the synthetic and
recorded report corpus. Verdicts for devices nobody has reported are the weakest part
of the product.

macOS 14 is the floor because PySide6 6.12 ships `macosx_14_0` wheels. The build reads
`LSMinimumSystemVersion` from the Qt framework it is about to bundle rather than typing
a number, so the promise in `Info.plist` is one the bundled Qt can keep.

## What to test

Six journeys, in this order. Each one ends in something you can look at, so a partial
run is still a report. Do them on a machine you own or are allowed to break, and keep the
destructive ones on a stick you can afford to reformat — never your only boot drive.

1. **Report → verdicts.** Open a `Report.json`, or collect one on this machine, choose a
   macOS release, then read a device row and open its details. Change the release and
   confirm the `Status` column changes with it. `Compare releases…` should agree with
   that column for every release it lists.
2. **ACPI → build → folder.** Resolve whatever the ACPI card asks for, build the EFI
   folder, and open it when the last stage finishes. All five stages should appear, in
   order, with timings that move. Then start a build and cancel it: the active stage ends
   as cancelled, the later ones stay pending, and no error card appears.
3. **Edit → validate → save → backup.** Open the built `config.plist`, change one
   reversible value, run validation, save, and confirm `config.plist.bak` sits beside it
   with the previous bytes. Edit something else and press `Revert` — the on-disk version
   comes back. Now edit the file in another program while it is open and save again from
   BlackDream: it should ask before overwriting, with `Cancel` as the default answer.
4. **Installer, up to the write.** Download a release and let it verify. Select a FAT32
   stick you do not mind losing and read the confirmation: it should name that volume and
   say only `EFI` and `com.apple.recovery.boot` are replaced. Write it, then check that
   everything else on the stick is where you left it.
5. **Advisories → dismiss.** Open a built `config.plist`, choose a release on `Build EFI`,
   then open `Configure EFI ▸ Dependencies…`. Does every row name a key and a rule you can
   find in the open config? Is a finding right or wrong for the machine you are testing?
   Press `Dismiss` on one, reopen the dialog, and confirm it is under `Show dismissed` and
   that `config.plist`'s bytes did not change.
6. **The failure paths on purpose.** Load a file that is not a report. Load a report whose
   hardware cannot run macOS. Change a `config.plist` outside the app and let it notice.
   Unplug the USB stick mid-write. A refusal should read as a refusal, with a reason, and
   should never leave the previous report's devices on screen.

The weakest part of this build is verdict coverage for hardware nobody has reported, so a
report from an unusual machine — a laptop with an Optimus GPU, a board with Intel VMD on,
a storage controller macOS has never heard of — is worth more than another successful
launch. Long device names and empty ACPI folders are equally useful.

## Known issues and limitations

* **The Linux ACPI helper needs the package, not the archive.** The `.deb` and `.rpm`
  install it root-owned at the path polkit authorizes, and that is the whole reason they
  exist. From an unpacked archive the helper is user-writable, so polkit will refuse it:
  follow the two `sudo install` / `sudo cp` commands in `README.md`, or point **ACPI
  tables** at `.aml` tables you exported elsewhere. Declining the authorization window is
  reported as a refusal, never as a hardware fault.
* **Only FAT32 volumes appear as installer targets**, and only if they are already
  mounted and writable by your session. An NTFS or ext4 stick is not offered, because
  firmware on the target machine has to read the volume.
* **Apple decides which releases still exist.** Each choice in the release picker asks
  for a recovery image by board id and serial; if Apple stops serving one, the download
  fails with the reason rather than substituting another release's image.
* **The release matrix is only as good as the ranges behind it.** It lays the same
  compatibility tuples out per release, so an ungraded device reads `Not graded` in every
  column. It says nothing about firmware, GPUs that need a kext, or whether the machine
  boots.
* **A report comparison compares recordings, not machines.** If one `Report.json` was
  written by an older engine, its verdict differences appear as recorded reading changes.
  The dialog names that boundary instead of hiding it, and nothing here re-grades either
  file.
* **Profiles and history are per machine and per user.** They are local files, not a
  sync feature; a profile copied to another machine will usually name a report path that
  does not exist, and the app will refuse it with that path.
* **History stops at 100 entries** and records what the app itself built. A folder you
  made with another tool, or an older build whose record fell off the end, is not there.
* **The first-boot checklist is general advice.** It is not your motherboard's guide:
  Secure Boot enrolment, the boot-menu key and NVRAM behaviour differ per board, and
  BlackDream cannot read or change any of them.
* **Dependency advisories read the config, not the machine.** A rule sees only what the
  open `config.plist` claims, plus the release you selected — no firmware, ACPI dump or
  device verdict — so a clean result means "no relationship this ruleset knows is broken",
  never "this EFI boots". A false positive is as useful to report as a miss; the exported
  text carries the rule citation. A dismissal is recorded against the ruleset it was made
  under, so changing a rule's meaning makes its findings visible again.
* **Schema preview is a reading, not a migrator.** It projects scalar and empty-container
  additions only, so a missing array or dictionary is listed rather than created, and it
  applies nothing. A real migration would need a review and a save, and no such button
  exists yet.
* **First use of `ocvalidate`, `macserial` or `iasl` needs the network** and writes into
  the per-user tools directory. Offline machines can pre-seed that directory (see
  `README.md`). Running the schema preview on a large config means running `ocvalidate`
  once more on the projection.
* **Presets are 12 entries**, the ACPI and Kernel patches adapted from OCAT's preset
  library. The library is not fetched and has no update channel.
* **Undo history lives in memory and is bounded.** It keeps the 100 newest edits, is
  discarded when the file is reloaded, and `Save` starts a new baseline. `Revert` still
  reloads the bytes on disk and discards every unsaved edit.
* **Folder checks read files, not firmware.** A clean report says the referenced files
  exist and the manifest matches; it does not test this machine's firmware, its hardware
  or whether macOS boots. A boot test remains the only proof of a boot.
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
6. `Help ▸ Save diagnostic bundle…` already redacts identity values and the home folder;
   read the preview before attaching it,
7. whether your `Report.json` names your machine before you attach it publicly.

Do not post SMBIOS serial, MLB, UUID or ROM values. There is no form inside the app and
nothing is uploaded: the channel is outside the product. Open an issue in the repository
this build came from and use its **Beta report** template, which asks for the seven things
above in this order — or, if you got the build somewhere else, send it back that way. The
`README.md` sitting beside these notes names the tracker.

## Checksums

Every build publishes these files into `dist/release/`:

| Name | What it is |
| --- | --- |
| `BlackDream-0.9.0-beta.4-<os>-<arch>.tar.gz` | the application bundle: unpack it and run the launcher inside. `.zip` on Windows; on macOS the archive contains `BlackDream.app` |
| `blackdream_0.9.0b4_<arch>.deb` | Debian/Ubuntu package: `/opt/blackdream`, a launcher on `PATH`, the desktop entry, and the ACPI helper installed as root |
| `blackdream-0.9.0b4-1.<arch>.rpm` | the same tree for Fedora/openSUSE; `Requires: glibc >= 2.35` |
| `blackdream-0.9.0b4-py3-none-any.whl` | the wheel, for a machine that already has Python 3.11 or newer |
| `blackdream-0.9.0b4.tar.gz` | the source distribution |

A Linux bundle needs glibc 2.35 or newer. That is not a preference: the build measures
the versioned symbols inside the shipped Qt and glib libraries and refuses to publish a
bundle that asks for more, so Ubuntu 22.04, Debian 12, Fedora 36 and everything newer
can run it.

`SHA256SUMS.txt` in the same folder gives the SHA-256 of each of them, and
`packaging/verify-artifacts.py` recomputes every digest in that file from the bytes on
disk and fails the build on any mismatch. The sums file is deliberately *not* inside the
archive: a document that quoted its own checksum could not be written by the build that
produces it, so the notes name the files and the checksums file carries the digests.

Verify the archive you downloaded before unpacking it. The bundle is not code-signed and
not notarized; macOS and Windows will warn you about that on first launch.
