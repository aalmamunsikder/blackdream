# BlackDream — UI mockup specification

**Version:** 3.10 · **Date:** 2026-10-25 · **Status:** every screen marked *built* is running code today

3.0 is the shipped app window. It uses the **native window frame and title bar** on every platform
and shows the real `File` / `View` / `Help` menu bar. Inside that client area the app paints its own
**blue-silk wallpaper**, edge to edge: the frosted 200 px sidebar and a translucent content veil sit
over it, and the glass cards sit over those. Nothing is painted behind the desktop window, inset
from the window edge, or around its corners; there is no painted desktop, no floating panel and no
fake window controls.

3.0 divides the workflow into three sections. `Installer` downloads Apple's recovery image, verifies
every chunk against Apple's signed chunklist, and copies it plus a built EFI folder to a mounted
FAT32 USB drive. `Build EFI` holds the six original views — Compatibility, Build and Logs — exactly
as 2.6 shipped them. `Configure EFI` edits the built `config.plist` in the window: a schema-aware tree
of every key, inline scalar editing, OpenCore's own `ocvalidate` for checking, and OpenCore's
`macserial` for SMBIOS serials. The editor never mounts a disk, and it only writes when the user
presses `Save`. The installer never formats a drive.

3.1 makes the installer's macOS release a choice: High Sierra 10.13 through Tahoe 26. Apple's
service has no version parameter — a release is requested as a Mac model Apple still serves it for —
so each choice downloads that release's recovery image and caches it separately. `Tahoe` tracks
Apple's unified latest image and is the default.

3.2 removes the external OpenCore Auxiliary Tools hand-off. The Configure page is now BlackDream's
own editor: `config.plist` carries the file, the save/validate/serial actions and the live status;
`Sections` scopes the key tree; `Keys` carries the tree, the add/remove/move toolbar and a key
search; `Selected entry` edits the selected key; and `Validation` keeps the `ocvalidate` result
inline. The editor preserves the
document's key order and any value it does not understand, keeps a `config.plist.bak` on every save,
and runs `ocvalidate` on a temporary copy so validation never touches the file. Serials come from
the pinned `macserial` binary and are written to the document only after a confirmation; nothing is
written to disk until `Save`. No OCAT download, no OCAT process and no OCAT update check remain.

3.3 brings the two remaining OCAT conveniences into that editor. The `Keys` card header carries a
`Presets…` button that inserts one of 12 ready-made ACPI and Kernel patch entries from OpenCore
Auxiliary Tools' MIT-licensed preset library, each checked against the pinned OpenCore 1.0.8
schema; insertion appends to the document in memory, never writes the file, and reports an entry
that is already present instead of duplicating it. A `data` value's text dialog gains a
`Show as text` view: printable ASCII is shown as-is and every other byte as a `\xNN` escape, so the
round trip is lossless for all 256 byte values. There is still no separate ASCII/HEX mode switch in
the editor chrome; the view lives inside the dialog.

3.4 is the beta packaging pass, and it changes one string of copy. A packaged build has no terminal,
so an unhandled exception in the window is written to `«data root»/logs/crashes` instead of
vanishing; only the five newest reports are kept. `Diagnostics` names that folder in its sentence and
adds a `Crash reports: «path»` line to the copied summary, because a beta report without a path a
tester can paste is not actionable. Everything else on every screen is unchanged from 3.3.

3.5 adds four read-only helpers around the file and the folder the app already builds. The Build
view gains a `Folder checks` card: `Run checks` verifies required files and every path in
`config.plist`, `Verify manifest` compares the folder with the manifest written at build time, and
`Save report…` exports either result as text. The Configure editor gains `Undo`, `Redo` and
`Changes…` in the `Keys` toolbar; history is snapshot-based, bounded at 100 edits, and never writes
the file, while `Changes since the file was opened` lists every edit with its before and after
values. The `Validation` card now shows ocvalidate's lines as a clickable list: choosing one selects
the key it names, and the app's own explanation appears in the note without replacing or recounting
the validator's line. `Help` adds `Save diagnostic bundle…`: the dialog previews the exact scrubbed
text, defaults `Report.json` to off, and writes a local `.txt` or `.zip` that the user attaches
themselves. Every one of these surfaces is read-only, local and explicit; none writes an EFI
partition, mounts a disk, uploads anything or claims that a clean result proves a boot.

3.6 adds six more surfaces of the same kind: two comparisons, two local stores, one checklist and
one preview. None of them grades anything, and none of them writes.

`Compare releases…` in the `macOS version` card opens **Hardware compatibility by macOS release** —
one row per graded device, one column per selectable release. Each cell is the label
`verdicts.target_status` already returns for the device table, called with the same OCLP range, so
the grid cannot disagree with the table above it. The engine is not called again.

`Compare reports…` in the fields card picks a second `Report.json` and opens **Compare hardware
reports**. Both files are read exactly as recorded on disk, and the diff keeps two kinds of change
apart: a *hardware* change moves a device field such as `Processor Name`, `Device ID` or `PCI Path`;
a *reading* change is the same hardware recorded with a different stored compatibility verdict. That
split is the point — a verdict that differs between two reports can come from a different engine or
database version rather than from this machine, and neither side is re-graded here.

`Profiles…` stores local shortcuts: a name, a report path, an EFI folder, a release and an update
stamp — five fields, and deliberately no serial, MLB, UUID or ROM value, so a profile cannot carry
one machine's identity onto another. `Use` loads that report and selects the release the profile
named as soon as the version options exist; a report that has moved is refused with its path in the
error card. `Save current`, `Rename…` and `Remove` change the list in place, and the store is a
local `profiles.json` written atomically.

`History…` in the `Build progress` header opens **Build history**: the last 100 builds this app made
on this machine, newest first, each with its timestamp, release, result, output folder, and whether
that folder and its manifest are still where they were recorded. A moved or deleted folder prints
`Folder missing` and its `Open folder` stays disabled — the row is never rewritten or pruned.
`Succeeded`, `Failed` and `Cancelled` are written from the job outcome, once per build.

**Before the first boot** is a fifth `Help` card: six advice steps — a spare drive, firmware
settings, a way back, the picker, verbose boot, a recovery plan — and a `Copy the checklist` button.
It starts nothing and has no boot action; the copied text ends with the same sentence the card
prints.

`Schema preview…` in the `Validation` header compares the open `config.plist` with the pinned
OpenCore 1.0.8 sample and shows what a migration *would* do: keys missing from the file, keys not in
the schema, keys whose type changed, and `ocvalidate`'s own verdict on the projected document. Only
scalars and empty containers are projected — a missing array is listed, never invented — and `Save
as text…` exports the review. Nothing is applied, and the note written after the dialog closes says
so.

3.7 adds one more reading of the same kind. `Dependencies…`, beside the two above in the
`Validation` header, opens **Dependency advisories**: the kext, driver, boot-arg and quirk
relationships the open file already claims, checked against the engine's own tables and cited line by
line. A row is a relationship that does not hold — a plugin listed before its parent, a kext enabled
against another in the same conflict group, a `MaxKernel` that excludes the release being targeted, a
boot-arg whose kext is not selected — and each row states its trigger, its evidence, the key path it
argues about, its confidence, and the `file:line` in this repository the rule was read from. There is
no `Fix`, `Apply` or `Reorder` button anywhere in it: this release explains, and the user edits with
the `Keys` tree. `Dismiss` hides one advisory hereafter, and the only thing it writes is a key in
`advisor-dismissals.json` in this app's own state directory — never in `config.plist`.

Inside the client area the material is glass on a lit blue canvas: a frosted 200 px sidebar,
translucent cards with a 1 px lighter top edge, fields a step below them, a blue gradient primary
button and progress fill, and a dark console in both themes. The structure below — eight views,
shared cards, one log widget, one progress card — is unchanged. Anything describing a rounded panel
inset from the window edge, painted traffic lights, a custom drag region, a hidden menu strip or a
flat neutral canvas is 2.5 or older and is wrong.

3.8 makes one more Intel iGPU reachable, through a named third-party patch. Xe-LP parts — Tiger
Lake, Alder Lake-N/S and Raptor Lake-S/HX — are recognised from the report's device id and graded
from `macOS Big Sur 11` to the newest release through **WhateverXe**, instead of being rejected as
unsupported. The build selects `WhateverXe` and the Mod `AMFIPass` with it and leaves
`WhateverGreen` out; `config.plist` carries `-allow3d -disablegfxfirmware` and
`csr-active-config 03080000`. The devices table prints the range as
`macOS Big Sur 11 to macOS Tahoe 26 with WhateverXe` and the `Status` column says
`Limited support`, never `Supported`, because the graphics stack is installed on the target after
the first boot. That step — WhateverXe Graphics 0.2.0, DVMT, SSDT-PNLF — is written as
`WhateverXe-Graphics.txt` beside the built EFI; the app does not download or run it. The
`Dependencies…` dialog also checks the plist's WhateverXe requirements: the two boot arguments, the
`0x803` SIP value, the Mod `AMFIPass`, and a `-yTileDisable` that the project says not to use.

3.9 adds the NVIDIA half of that story. Turing-and-later discrete GeForce cards — GTX 16,
RTX 20/30/40/50, TITAN RTX and Quadro RTX — are recognised from the report's device id and graded
from `macOS Sequoia 15.5` to the newest release through **NullMoth** NVIDIA driver 2.5.4, instead
of ending the check as an unsupported GPU. The build adds the driver's boot arguments, sets
`csr-active-config 430A0000`, disables `SecureBootModel`, selects `AMFIPass` and the
`IONDRVSupport` block, and stops at the EFI boundary: the driver itself installs into the target's
`/Library` and rebuilds its AuxKC. The devices table prints the range as
`macOS Sequoia 15.5 to macOS Tahoe 26 with NullMoth` and the `Status` column says
`Limited support`. That remaining step is written as `NullMoth-NVIDIA-Driver.txt` beside the built
EFI; the app does not download or run it. The `Dependencies…` dialog also checks the plist's
NullMoth requirements: the seven boot arguments, the `0xA43` SIP bits, `AMFIPass`, the
IONDRVSupport exclusion, and any NVRM kext wrongly injected into the EFI. The version card
also stops calling a patch-dependent range `Native support`, so the headline cannot
contradict the row.

3.10 makes `Read ACPI tables` a Windows feature as well. A scan through Hardware Sniffer runs
without elevation, and the tool's own `acpidump` step therefore writes no tables in the app's
normal path; a report arrived with an empty ACPI folder and the build stopped at
`pipeline.build_not_ready`. The app now reads the firmware tables itself through the Windows
firmware table API — `EnumSystemFirmwareTables` and `GetSystemFirmwareTable` for the DSDT and the
enumerated tables, `HKLM\HARDWARE\ACPI` for the SSDT instances — and writes them into the same
`ACPI` subfolder the Linux helper produces. The read is user-mode, opens no authentication window,
downloads nothing, and touches no driver. When Hardware Sniffer does export tables, they are still
adopted first; the in-process read is the fallback. The button is now drawn on Windows too, its
tooltip there reads `Read the firmware tables from this machine; no administrator rights needed`,
and the S6 build card's second bullet names the button without naming a platform.

2.1 added three utility views at the bottom of the sidebar — `Settings`, `Help` and `Donate`. They are
pages, not modals: the same header, the same cards, and the same theme. Settings carries the theme
picker, storage paths and about copy; Help carries the workflow, shortcuts, troubleshooting and a
diagnostics copy button; Donate lists non-money ways to help, and says plainly that funding is not
open yet.

This document describes every screen well enough to produce high-fidelity mockups. It is written for
a design tool or a chat model that will render the UI, so it states exact regions, exact copy, and
exact component states rather than adjectives.

### How to use this with an image model

1. Attach the real screenshots — they exist, they are not concepts. The window frames are
   rendered by the running app at 1536 × 1024; the dialogs are rendered at their own size:
   - `docs/screenshots/01-empty.png` · `02-compatibility-checked.png`
   - `docs/screenshots/03-device-details.png` · `04-build-view.png`
   - `docs/screenshots/05-logs-view.png` · `06-dark-compatibility.png`
   - `docs/screenshots/07-fatal-gpu.png` · `08-settings.png`
   - `docs/screenshots/09-help.png` · `10-donate.png`
   - `docs/screenshots/11-installer.png` · `12-configure.png`
   - `docs/screenshots/13-build-folder-checks.png` · `14-configure-history.png`
   - `docs/screenshots/15-diagnostics-bundle.png` · `16-compare-releases.png`
   - `docs/screenshots/17-compare-reports.png` · `18-profiles.png`
   - `docs/screenshots/19-build-history.png` · `20-schema-preview.png`
   - `docs/screenshots/21-dependency-advisories.png`
2. Paste this whole file as context.
3. Ask for one screen at a time, naming the section *and* the view, e.g.
   *"Render screen S4 (Fatal incompatibility card) on the Compatibility view at 1440×940, light
   theme, using the exact copy from §16."*
4. Then paste the §16 block on its own and add: *"Every visible string must appear verbatim in this
   allowlist. If you need a string that is not in it, do not write one — leave the element out."*
5. Check the result against the §17 reject list before accepting it.

> **§16 is the only permitted string source.** §10 is prose describing the same set; if they ever
> disagree, §16 wins, because §16 is checked against the running code by
> `tests/test_mockup_spec_allowlist.py`.

---

## 1. Product

**One line:** a desktop app that turns an exported hardware report into a bootable OpenCore EFI
folder, with no terminal.

| | |
|---|---|
| Form factor | Single native-framed desktop window; inside the client area, a blue-silk wallpaper holds a 200 px frosted rail, a translucent content veil and the card column |
| Window default size | Opens at 1440 × 940 or the available screen minus 80 px, whichever is smaller; minimum 1160 × 700 |
| Chrome | The platform's own title bar, window buttons and resize borders. A `QMenuBar` (`File` · `View` · `Help`) is visible on every platform; macOS draws it in the system bar outside the window. No painted window controls |
| Themes | `System` (follows the desktop), `Light`, `Dark`; each resolves to its own wallpaper, veil and glass palette |
| Surfaces | Wallpaper **inside** the window, a frosted sidebar and content veil above it, and translucent cards, fields and a dark log above those. No desktop wallpaper outside the window, no floating panel, no inset band and no drop shadows |
| Platforms | macOS 14+, Windows 10/11, Linux (X11 + Wayland) |
| Engine | Vendored OpCore Simplify (BSD-3), driven headless |
| Navigation | 200 px sidebar with three workflow sections: `Installer` · `Build EFI` · `Configure EFI`, plus three utility views at the bottom: `Settings` · `Help` · `Donate`. 200 px is the reference width, not a ceiling: on a platform whose font is wider the rail grows by the pixels its labels need, so no item ever loses a letter. `Build EFI` shows three segment tabs: `Compatibility` · `Build` · `Logs` |
| Input model | Report file is dropped or picked; paths are never typed |
| Output | An EFI **folder**. Nothing is mounted, written to, or repaired |

### Non-goals (v1) — a mockup that shows these is wrong

- No command-line interface, no console window, no `$` prompt. The log pane is a read-only text
  surface inside the window.
- No writing to, mounting, or repairing an EFI partition. The only administrator prompt is polkit's
  own window for reading ACPI tables on Linux, and it is drawn outside the app's frame.
- No account, no sign-in, no telemetry banner, no update dialog.
- No multi-window wizard, no stepper, no "Next". The three workflow sections are views of one session.
- No modal Settings or About screen. 2.1 moved both into the Settings view.
- No status bar. 1.1 had one; 2.0 removed it, and completion is shown in the build card instead.
- No painted window chrome outside or around the client area: no desktop wallpaper, no inset floating
  panel around the app, no fake traffic lights and no custom drag region. The blue-silk wallpaper is
  **inside** the window only. The platform draws the frame, title bar, window buttons and resize
  borders. The menu bar is always visible — the system bar on macOS, a strip at the top of the window
  on Windows and Linux.
- No dark-mode-only design; `System`, `Light` and `Dark` all ship (§4).

---

## 2. Why the window looks like this

The upstream tool is a numbered text menu. Three things about that do not survive contact with a
GUI, and they drive every layout decision below:

1. **A dozen device verdicts do not fit in a scrollback.** They become a table, and the table is the
   largest object on screen. It gained a fourth column — the one judgement a build needs: *does this
   device work on the release the user picked?* — but that column is derived from the engine's own
   compatibility tuples, never a second opinion (§7.5).
2. **A build takes minutes and produces no stdout.** Silence reads as a hang, so the window shows
   the engine's own five-stage checklist, a current-task box, byte counters, transfer rate and log
   lines as they happen.
3. **A fatal incompatibility must not close the app.** Upstream exits. Here it is a red card inside
   the same window. A **rejected report also clears the previous session** (§8), so the card never
   describes one machine while the table describes another.

There is one window with eight views, and no wizard. A view groups the controls for one part of the
same session; it is not a step. Nothing is enabled or disabled because of which view is open, and
the error card sits above the page stack, so no view change can hide a failure.

---

## 3. Layout

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ File   View   Help                                                                            │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│  BD  BlackDream           Hardware Compatibility                                             │
│      OpenCore, made…      Review what macOS can run on this machine, then build the EFI…     │
│                                                                                              │
│  WORKFLOW                 │ [Compatibility] Build  Logs                        │
│  ▸ Installer              ┌ Hardware report (Report.json)  ✓   [Browse…] ┐                   │
│  ▸ Build EFI              │ ACPI tables folder             ·   [Browse…] │                   │
│  ▸ Configure EFI          │ Output folder                  ✓   [Browse…] │                   │
│                           └ Collect hardware  Read ACPI tables ──────────┘                   │
│                           ┌ macOS version ───────────────────────────────┐                   │
│                           │ [macOS Tahoe 26 · suggested              ▾] │                   │
│                           │ [Native support: macOS Monterey 12 - …]      │                   │
│                           └──────────────────────────────────────────────┘                   │
│                           ┌ Check compatibility ┬ Build EFI folder ──────┐                   │
│                           │ Cancel              │ Open EFI folder        │                   │
│                           └─────────────────────┴────────────────────────┘                   │
│                           ┌ Detected devices ────────── [Search] [View …]┐                   │
│                           │ Device  Class  macOS support  Status         │                   │
│                           │ … rows with class tiles and coloured statuses│                   │
│                           └──────────────────────────────────────────────┘                   │
│                           ┌ Build progress ──────────────── Not started ─┐                   │
│                           │ [──────────────] 0%                           │                   │
│                           │ five stages                   Ready to build  │                   │
│                           │                               [metrics]       │                   │
│                           └──────────────────────────────────────────────┘                   │
│  ⚙ Settings               ┌ Engine log ─────────── [Info and above] [Save]┐                   │
│  ? Help                   │ 23:08:29  INFO  …                            │                   │
│  ♡ Donate                 └──────────────────────────────────────────────┘                   │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The diagram is the **Compatibility** view, the densest screen. The other views rearrange the *same
widget instances* — nothing is duplicated:

| View | Cards, in order |
|---|---|
| `Installer` | `macOS installer` (release picker and image download) · `USB drive` (target, identity and the guarded write). Nothing else shares this page: the installer never mounts the EFI session cards |
| `Compatibility` | Two columns (40 : 60) above a full-width log. Left, top → bottom: the **setup card** (three path rows and the two capability links, untitled) · `macOS version` · the **actions card** (2 × 2 buttons, untitled). Right: `Detected devices` (grows) · `Build progress`; while details are open, `Device details` replaces `Build progress` in that slot. Bottom: `Engine log` across both columns |
| `Build EFI` | Top row: the actions card (natural height) · `Build progress` (grows). Bottom: `Engine log` filling the rest. The top row stacks below 900 px |
| `Logs` | `Engine log` only, taking the full content height; no scroll area |
| `Configure EFI` | Top: `config.plist`, a compact file card across the content width. Then a three-column row: `Sections` (206 px fixed rail) · `Keys` (grows; tree, add/remove/move toolbar and key search) · `Selected entry` (268 px fixed inspector). Bottom: `Validation` across the content width, its header carrying three outline buttons — `Schema preview…` · `Dependencies…` · `Validate again`. The page header's action slot carries the validation chip · schema chip · `Open config…` · `Validate` · `Save`. No session cards |
| `Settings` | Top row: `Appearance` (2) · `About` (3). Bottom row: `Storage` (3) · `Downloads and safety` (3) |
| `Help` | Top row: `Quick start` (3) · `Keyboard shortcuts` (2). Bottom row: `Troubleshooting` (3) · `Diagnostics` (2) |
| `Donate` | `Support the project` full width, then a 2 × 2 grid: `Test on real hardware` · `Send a compatibility report` · `Share the app` · `Funding` |

- **Utility pages own their cards.** `Installer`, `Configure EFI`, `Settings`, `Help` and `Donate` never mount the session cards; the devices table, progress card and log stay in the `Build EFI` section. This is why a build running in the background cannot make the Installer page sprout an EFI progress bar.
- **Shell:** one window with the platform's own frame and title bar. The client area is the app's own
  blue-silk wallpaper, edge to edge, holding the frosted 200 px sidebar and a translucent content
  column. Nothing is inset, rounded or shadowed at the window edge, and the platform owns moving,
  resizing and the window buttons.
- **Menu bar:** `File` (`Open Report…`, `Open ACPI Folder…`, `Quit`), `View` (the three sections and
  three utility views, a `Build` submenu for `Compatibility` / `Build` / `Logs`, then `Toggle Theme`)
  and `Help` (`Keyboard Shortcuts`, `About BlackDream`). It is visible on every platform — the system
  bar at the top of the screen on macOS, a frosted strip at the top of the window on Windows and
  Linux. The wallpaper starts below it and never paints behind it. It repeats existing actions and
  shortcuts; the sidebar remains the primary navigation.
- **Header:** page title 30 px / 700 and subtitle 13 px muted on the left, in ordinary content. There
  is no theme button; the theme lives in `Settings > Appearance`, and `Toggle Theme` remains in the
  `View` menu. The search is a 204 × 28 pill in the `Detected devices` card header (§7.5). On
  `Configure EFI` alone, the header's right edge carries the page action slot: the validation and
  schema chips, then `Open config…`, `Validate` and the primary `Save` (§15).
- **Sidebar:** 200 px wide at the reference font, frosted, with 13 px left/right padding and 14 px
  top/bottom, and a 1 px right border. On a platform whose font is wider the rail grows by the few
  pixels its longest label needs — 200 px is a floor, and a label is never clipped to keep it. Top:
  a 46 px `BD` mark with `BlackDream` / `OpenCore, made simple.` beside it. Then
  a `WORKFLOW` caption and the three section buttons (40 px minimum height): `Installer`,
  `Build EFI`, `Configure EFI`. A stretch, then `Settings` / `Help` / `Donate` (34 px) at the bottom.
  Every item is icon + text, muted when idle; the active item is a blue gradient pill
  (`navCheckedTop` → `navCheckedBottom`) with white text and a white icon. All six are one exclusive
  group: opening a utility view unchecks the workflow nav, and vice versa. Inside `Build EFI`, three
  segment tabs (`Compatibility` · `Build` · `Logs`) switch sub-views; the sidebar keeps `Build EFI`
  checked while any of them is open, and returning to the section restores the last sub-view.
- **Cards** ride in one page column; stretches are listed above. Cards in a row share a height and
  pack their content to the top. A card with no growing child is padded with a trailing stretch so
  its content never floats mid-card. Cards scroll with the page when the window is short.
- **The layout bends before it clips.** The two dashboard columns stack below an 800 px split
  viewport — and above it when the panes' own floors no longer fit, which a wider platform font can
  bring up to the window floor; the `Build EFI` top row stacks below 900 px. The 40 : 60 split
  exists because at the 1160 px floor the four device-table headers only fit when the devices card
  keeps most of the row. The table gives width to the support column first, shrinking it from
  266 px until the row fits, but never below its own header plus the 8 px inset each side: 90 px is
  a guard, and the measured floor is what a font 6 % wider than the reference one still prints in
  full. The device column never falls below 165 px and the table never scrolls sideways; when the
  row cannot hold the support header at all, the card claims the width it needs and the two columns
  stack rather than elide a header. The version combo sizes to its content rather than its longest
  entry, so a long macOS name does not widen the card on a theme change. The floor is 1160 × 700;
  below that the window refuses to shrink, and a short window scrolls the page.
- **No numbered cards.** The ① ② ③ badges never shipped; no card or button carries a number, and
  nothing is a wizard step.
- **During a job the window follows the work:** the build jobs show `Build EFI`, an installer job
  stays on `Installer`, a config job stays on `Configure EFI`. The user is never asked to go look.
- **No status bar.** The bottom edge of the client area is card content; the platform frame is the
  resize grip.

---

## 4. Visual language

`System` follows the desktop and resolves to one of the two columns below. The client area is the
app's own blue-silk wallpaper; the frosted sidebar and the translucent content veil are the first
glass layer, and the cards are the second. Every value is read from
`src/blackdream/ui/theme.py`. A mockup may use either column, but must not mix them.

**The canvas** is painted, not shipped: a diagonal `wallTop` → `wallMid` → `wallBottom` gradient, a
radial `wallGlow` bloom, five cubic `wallRibbons` strokes in two widths, and a `wallShade` vignette.
It is cached per size, theme and device-pixel ratio and clipped to the client area, so it never
reaches the native title bar or the desktop. The content column adds the `contentVeil` gradient, and
the sidebar a `sidebarFill` gradient, over the silk.

| Token | Light | Dark | Used for |
|---|---|---|---|
| `windowBg` | `#eef1f6` | `#12161d` | native dialog background; never the in-app canvas |
| `wallTop` / `wallMid` / `wallBottom` | `#1a5be0` / `#4b90f7` / `#0a3aa8` | `#0a1c40` / `#123a72` / `#050d20` | the silk gradient, top-left to bottom-right |
| `wallGlow` / `wallShade` | `#d6efff` / `#041c56` | `#2f6bd8` / `#00060f` | the central light bloom / the edge vignette |
| `wallRibbons` | five strokes: `#a9d2ff` 78 · `#eef7ff` 92 · `#0c3fb4` 58 · `#ffffff` 52 · `#0a2f94` 46 | five strokes: `#2f6bd8` 62 · `#5f93e8` 46 · `#020817` 120 · `#8fb6ff` 34 · `#01040d` 110 | cubic ribbon strokes; the trailing number is the stroke alpha |
| `contentVeil` | `rgba(248,252,255,188)` → `rgba(225,238,255,136)` | `rgba(16,25,43,168)` → `rgba(6,11,21,132)` | the translucent glass over the wallpaper in the content column |
| `sidebarFill` / `sidebarBg` / `sidebarBorder` | `rgba(244,250,255,204)` → `rgba(226,240,255,184)` / `rgba(236,245,255,206)` / `rgba(255,255,255,150)` | `rgba(13,20,34,208)` → `rgba(6,10,18,192)` / `rgba(9,12,17,190)` / `rgba(255,255,255,30)` | the frosted rail's vertical fill, its solid fallback, and its 1 px right border |
| `menuBarFill` / `menuBarBorder` | `rgba(240,247,255,242)` → `rgba(222,237,255,232)` / `rgba(30,75,160,34)` | `rgba(15,24,42,242)` → `rgba(9,15,27,232)` / `rgba(255,255,255,26)` | the menu strip above the wallpaper / its bottom rule |
| `cardFill` / `cardBg` / `cardBorder` / `cardHighlight` | `rgba(255,255,255,196)` → `rgba(247,251,255,154)` / `rgba(255,255,255,178)` / `rgba(30,55,95,40)` / `rgba(255,255,255,245)` | `rgba(42,51,71,220)` → `rgba(28,35,50,194)` / `rgba(35,42,58,205)` / `rgba(255,255,255,40)` / `rgba(255,255,255,58)` | every card: vertical glass fill, solid fallback, border, lighter top edge |
| `hairline` | `rgba(30,60,110,30)` | `rgba(255,255,255,20)` | menu separators, header rules |
| `fieldBg` / `fieldBorder` | `rgba(255,255,255,178)` / `rgba(120,150,200,82)` | `rgba(255,255,255,16)` / `rgba(255,255,255,46)` | path rows, combos, disabled primary |
| `controlBg` | `rgba(255,255,255,205)` | `rgba(255,255,255,26)` | search pill, version combo, browse buttons |
| `buttonBg` / `buttonHoverBg` | `rgba(255,255,255,180)` / `rgba(255,255,255,240)` | `rgba(255,255,255,22)` / `rgba(255,255,255,40)` | outline buttons, chips, icon buttons |
| `menuBg` | `#fbfdff` | `#1c2230` | menu popups, combo lists, tooltips (opaque so text never smears) |
| `text` / `muted` / `faint` | `#0c1c33` / `#4d5f7a` / `#7f8da3` | `#eef2fa` / `#a6b2c7` / `#79869b` | body / hints and secondary / timestamps and disabled |
| `accent` / `accentSoft` / `accentDeep` | `#1f6bff` / `#3f86ff` / `#124fd0` | `#6fa4ff` / `#4f8dff` / `#2f63d0` | links, focus rings, table selection, gradient ends |
| `primaryTop` / `primaryBottom` / `primaryEdge` | `#2f7cff` / `#1d5ef0` / `#1450d8` | `#3f86ff` / `#2564f0` / `#1f52c8` | the one primary button (left → right) |
| `primaryHoverTop` / `primaryHoverBottom` | `#4a8dff` / `#2a6bff` | `#5f9bff` / `#3575ff` | primary hover |
| `navCheckedTop` / `navCheckedBottom` / `navCheckedEdge` | `#3f8bff` / `#2467f2` / `#1b55d0` | `#3f7dff` / `#265fe8` / `#1d4ec0` | the checked sidebar item (left → right, white text and icon) |
| `navHover` / `selection` | `rgba(255,255,255,132)` / `rgba(52,110,255,50)` | `rgba(255,255,255,28)` / `rgba(80,130,255,90)` | hover / selected table row and menu item |
| `rowHover` / `rowAlt` | `rgba(255,255,255,150)` / `rgba(255,255,255,60)` | `rgba(255,255,255,16)` / `rgba(255,255,255,6)` | table row hover / alternating row |
| `rowFailBg` / `rowWarnBg` | `rgba(255,120,120,38)` / `rgba(255,190,90,36)` | `rgba(220,70,80,70)` / `rgba(220,160,50,58)` | a `Not supported` / `Limited support` row |
| `grid` / `groove` / `scrollHandle` | `rgba(70,100,150,46)` / `rgba(90,120,170,55)` / `rgba(70,90,125,110)` | `rgba(255,255,255,26)` / `rgba(255,255,255,24)` / `rgba(255,255,255,46)` | table rule / progress groove / scrollbar |
| `ok` / `okBg` / `okBorder` | `#178a4c` / `rgba(214,246,226,215)` / `rgba(31,170,90,90)` | `#86d9a5` / `rgba(34,92,60,192)` / `rgba(90,190,125,80)` | Supported status, the summary banner, done stages |
| `warn` / `warnBg` / `warnBorder` | `#9a5a06` / `rgba(252,236,196,210)` / `rgba(220,160,40,95)` | `#f0c274` / `rgba(110,78,24,180)` / `rgba(235,180,90,80)` | Limited support, checking state, WARN log text |
| `fail` / `failBg` / `failBorder` | `#d92d20` / `rgba(255,214,214,190)` / `rgba(230,80,70,95)` | `#f2a0a8` / `rgba(110,36,44,180)` / `rgba(240,120,132,90)` | Not supported, rejected report, failing stage |
| `unknown` / `unknownBg` / `unknownBorder` | `#5e6b80` / `rgba(120,130,150,26)` / `rgba(120,130,150,70)` | `#a3a9b8` / `rgba(255,255,255,22)` / `rgba(255,255,255,40)` | Not graded, empty path state |
| `tileIcon` / `tileBg` | `#1f6bff` / `rgba(31,107,255,30)` | `#8fb5ff` / `rgba(100,150,255,45)` | fallback icon tile and summary icon |
| `classTints` | CPU `#1f6bff` · GPU `#e2447a` · Audio `#dd7a24` · Ethernet `#1296b8` · Wi-Fi `#b8890b` · Storage `#1f9a5b` · USB `#3f7fe0` · Bluetooth `#4b6bdd` · SD card `#c95f38` · Display `#5a63d6` · Biometric `#a84bb8` | the same keys, lightened (`#8fb5ff`, `#ff9cc7`, …) | device-class icon glyphs, each on a 12 % tint of its own hue |
| `taskBg` / `taskBorder` | `rgba(255,255,255,210)` / `rgba(255,255,255,220)` | `rgba(255,255,255,14)` / `rgba(255,255,255,30)` | current-task box |
| `metricBg` | `rgba(255,255,255,150)` | `rgba(255,255,255,10)` | the three metric tiles |
| `errorBg` / `errorFg` / `errorBorder` / `errorCode` | `rgba(255,235,236,240)` / `#8c1d24` / `rgba(220,38,38,110)` / `#9a666c` | `rgba(74,28,34,220)` / `#f2b0b6` / `rgba(240,120,132,90)` / `#c88a90` | the error card and rejected summary |
| `logBg` / `logFg` / `logMuted` / `logBorder` / `logSelection` | `#171a26` / `#dfe3ec` / `#7d8496` / `rgba(255,255,255,20)` / `rgba(96,130,214,120)` | `#0e1117` / `#d7dae1` / `#7d8496` / `rgba(255,255,255,20)` / `rgba(96,130,214,110)` | the console, dark in both themes |

- **Typography:** a prioritized system stack, never a bundled or downloaded font:
  `SF Pro Text` → `SF Pro Display` → `Segoe UI Variable Text` → `Segoe UI` → `Inter` → `Noto Sans` →
  `Ubuntu` → `DejaVu Sans`, set once at 10 pt on the window. Base 13 px body. Page title 30 px / 700;
  subtitle 13 px muted. Brand 16 px / 700, brand hint 10 px muted. Card title 16 px / 700, card hint
  11 px muted. Path label 11 px / 600, path value 12 px / 500. Step label 12 px / 500, percentage
  16 px / 700. Detail key 11 px / 600, detail value 12 px / 500. Task name 13 px / 600, task detail
  11 px muted. Metric label 10 px muted, metric value 13 px / 600. Stage name 12 px, stage time
  11 px faint. Log pane monospace
  (`SF Mono` / `Menlo` / `Cascadia Mono` / `Consolas` / `DejaVu Sans Mono`) at 12 px.
- **Shapes:** card 16 px, path row 13 px, search
  pill 14 px, nav item 10 px, button 9 px (outline 8 px, chip 7 px, primary 10 px), task box 12 px,
  metric 9 px, summary 12 px, error card 10 px, progress bar 5 px (task bar 4 px), log pane 14 px,
  scrollbar handle 3 px. The app draws no window radius; the platform frame owns the window corners.
  A status is **not** a pill: it is a 15 px icon plus a coloured word, with a tinted row behind it.
- **Depth is material, not a shadow.** The wallpaper's light, the translucent veil and rail, and each
  card's gradient fill plus 1 px border and lighter top edge build the layers. The app draws no
  shadow around any surface. Qt has no `box-shadow`, and `QGraphicsDropShadowEffect` would repaint
  the whole card subtree on every log line.
- **A combo list is the rounded view itself.** On Windows and Linux the popup window is transparent,
  frameless and shadowless, so the platform cannot draw a square plate behind the list's 10 px
  radius; the first and last rows sit inside the same radius. macOS keeps its native menu-style
  popup.
- **Gradients are the material.** The wallpaper, content veil, sidebar fill and card fills are
  gradients. The functional gradients are the primary button (`primaryTop` → `primaryBottom`, left
  to right; hover uses the `primaryHover…` pair), the checked sidebar item (`navCheckedTop` →
  `navCheckedBottom`, white text and icon) and the progress fill (`accentSoft` → `primaryBottom`).
  Header text, status words and unchecked nav items carry no gradient. The app logo keeps its own
  indigo gradient. There is no violet in the chrome.
- **Device icons are colour-coded by class.** CPU, GPU, audio, Ethernet, Wi-Fi, storage, USB,
  Bluetooth, SD card, display and biometric glyphs each get a hue from `classTints` on a tint of the
  same hue (`icons.tile`). They are decorative: the class name is always in the next column.
- **Density:** 12 px between cards in a column, 16 px between the two dashboard columns, 14 px on
  the `Build EFI` top row, 10–12 px card padding, path rows 52 px, nav 40 px / 34 px, table rows
  29 px, stage rows 26 px. No hero areas, no illustrations, no empty-state artwork.
- **Logo:** the 46 px mark is a white `BD` lettermark on a 48-unit tile with a deep indigo gradient
  (`#6b78f4` → `#4338ca` → `#1c1749`) and a 20% white rim. The letter outlines are embedded paths,
  not a font lookup, so the mark is identical on every platform.
- **Icons:** every icon is a stroke SVG from `src/blackdream/ui/icons.py`, drawn on a 24 × 24
  viewBox with a 1.7 px round stroke, rendered at 2× device pixel ratio and recoloured from the
  palette. They appear in the nav (18 px primary / 17 px utility), card link buttons, path-row tiles
  (28 px), utility row tiles (28 px), device class tiles (24 px), stage rows (16 px), status words
  (15 px), metric tiles (16 px), field state (16 px), the search pill (13 px) and the log tools.
  The utility views add `heart` (Donate), `share` (Share the app) and `shield` (safety and ACPI
  advice). Icons are decorative beside text, never the only signal, and no icon is drawn at an
  unlisted size.
- **Focus is always visible.** Buttons, inputs, combos, sidebar items and the primary action take an
  `accent` border on keyboard focus; the primary button inverts it to a 2 px white border because its
  fill is already accent.
- **The log pane is dark in both themes.** It is a console docked inside a card: `logBg` fill,
  `logFg` text, a 14 px radius and a faint light top edge. The light theme does not turn it white —
  that read as a second card, not a console.

---

## 5. Screen inventory

| ID | Screen / state | View | Status |
|---|---|---|---|
| S1 | Empty — waiting for a report | Compatibility | built |
| S2 | Checking compatibility (in flight) | Compatibility | built |
| S3 | Verdicts + version picker ready | Compatibility | built |
| S4 | Fatal incompatibility card | Compatibility | built |
| S5 | Report rejected (bad or missing file) | Compatibility | built |
| S6 | Build blocked: no ACPI source | Build EFI | built |
| S7 | Build in progress (stages + downloads) | Build EFI | built |
| S8 | Build finished | Build EFI | built |
| S9 | Cancelled mid-build | the view the job ran on | built |
| S10 | Unexpected engine failure | the view the job ran on | built |
| S11 | About | Settings (card) | built |
| S12 | Device & kext overrides | Compatibility | **planned** |
| S13 | SMBIOS / serial editor | Compatibility | **planned** |
| S14 | Collect hardware from this machine (Linux, Windows) | Compatibility | built |
| S15 | First run: fetching OpenCore base | Build EFI | **planned** |
| S16 | Read ACPI tables (Linux, needs administrator) | Compatibility | built |
| S17 | Settings | Settings | built |
| S18 | Help | Help | built |
| S19 | Donate | Donate | built |
| S20 | Installer idle: release picker, no image, no drive selected | Installer | built |
| S21 | Installer downloading / writing (progress, cancel) | Installer | built |
| S22 | Installer written (drive named, eject advice) | Installer | built |
| S23 | Configure EFI with no built config | Configure EFI | built |
| S24 | Configure EFI ready: a config.plist open in the editor | Configure EFI | built |
| S25 | Build EFI folder checks: required files and config paths verified | Build EFI | built |
| S26 | Configure EFI history: unsaved edits, Changes… dialog open | Configure EFI | built |
| S27 | Help: diagnostic bundle preview and save | Help | built |
| S28 | Compatibility: release matrix dialog, every device against every release | Compatibility | built |
| S29 | Compatibility: report comparison dialog, hardware and reading changes apart | Compatibility | built |
| S30 | Compatibility: profiles dialog — local report / folder / release shortcuts | Compatibility | built |
| S31 | Build: build-history dialog, with vanished folders named, not pruned | Build EFI | built |
| S32 | Help: the first-boot checklist card and its copy button | Help | built |
| S33 | Configure EFI: schema preview dialog, pinned-sample diff plus validator verdict | Configure EFI | built |
| S34 | Configure EFI: dependency advisor dialog, cited rules and dismissals kept outside the plist | Configure EFI | built |

Only S1–S11, S14, S16–S34 may be presented as current product. S12, S13 and S15 must
be labelled *concept*. S14 and S16 follow host capability, not a platform guess: `Collect hardware`
is drawn on Linux and Windows, `Read ACPI tables` on Linux and Windows as well, and each is absent
rather than disabled where its capability is missing. A macOS frame shows neither; a Windows frame
shows both, because the Windows build reads the firmware tables in-process without elevation.
`Settings`, `Help` and `Donate` are one screen each, not modal overlays. `Installer` and
`Configure EFI` are full views with their own cards; neither borrows a session card.

`Logs` is not a screen and gets no ID: it is the same log card at full height with the other cards
removed, and the error card stays visible above it.

S28–S31, S33 and S34 are modal dialogs opened from a link or a card header, not pages in the
sidebar; S32
is a card on the existing `Help` page. Each is mounted only when it can answer: `Compare releases…`
needs a finished analysis and a version picker, `Compare reports…` a report on disk, `Schema
preview…` and `Dependencies…` an open `config.plist`. `Profiles…` and `History…` are always
available, because an empty list is a truthful answer about this machine.

---

## 6. S1 · Empty

3.0 opens on the `Installer` view at S20; this screen is the empty state of `Build EFI`, reached
from the sidebar. No splash, no dialog.

- **Shell and sidebar:** the native window frame and visible menu bar over the in-window blue-silk
  canvas; the frosted 200 px rail with the `BD` mark, `BlackDream` and `OpenCore, made simple.`; the
  `Build EFI` item checked as a blue gradient pill, with its `Compatibility` segment tab lit;
  `Settings`, `Help` and `Donate` at the bottom. The wallpaper shows through the rail and the content
  veil, never outside the window. No painted lights and no custom drag strip.
- **Header:** `Hardware Compatibility` / `Review what macOS can run on this machine, then build the
  EFI folder.` No theme button; the theme is chosen in `Settings`. The search pill lives in the
  `Detected devices` header, empty with placeholder `Search devices…` and the `Ctrl K` / `⌘ K`
  keycap.
- **Setup card (untitled):** three 52 px path rows. `Hardware report (Report.json)` with a file tile,
  empty path, a hollow dot state icon and `Browse…`; `ACPI tables folder` with a layers tile, empty
  path, hollow dot, `Browse…`; `Output folder` with a folder tile, a **pre-filled** real per-user
  path and an `ok` check-circle whose tooltip is `Will be created`, e.g.
  `~/.local/share/blackdream/builds/20261022-1147` (macOS
  `~/Library/Application Support/blackdream/builds/…`, Windows
  `%LOCALAPPDATA%\blackdream\builds\…`), and `Browse…`. Under them, two text links:
  `Collect hardware` — **drawn on Linux and Windows** — and `Read ACPI tables` — **drawn on Linux
  and Windows** (a Linux read asks through polkit's window, a Windows read asks for nothing).
  Each is absent, never disabled, where its capability is missing.
- **`macOS version`:** a 30 px monitor tile and an empty 34 px combo on one row, then the summary
  panel in its *empty* style (neutral field fill, muted text):
  `Load a Report.json, or collect hardware from this machine.` on Linux,
  `Load a Report.json, or scan this machine with Hardware Sniffer.` on Windows, and
  `Load a Report.json exported by Hardware Sniffer on the target PC.` where no scan can run. Below it
  the note `Support ranges come from the report's own compatibility data.`
- **Actions card (untitled):** a 2 × 2 grid of equal buttons. Row one: primary
  `Check compatibility` (enabled) and outline `Build EFI folder` (disabled). Row two: outline
  `Cancel` (visible but disabled) and outline `Open EFI folder` (disabled). There is no path row in
  this card; the output row lives in the setup card.
- **`Detected devices`:** hint `No report loaded yet.`; the compact search pill and a `View details`
  chip in the header; the empty note
  `Load a report to see this machine's devices and what macOS does with them.`; the table shows its
  four headers and no rows. Minimum table height 150 px.
- **`Device details`:** not mounted yet. `View details` opens it in the right column in place of
  `Build progress`; it carries seven detail keys (`Device`, `Class`, `macOS support`, `Vendor`,
  `Device ID`, `Subsystem`, `Current status`), each with an em dash value, and a full-width
  `Recommendation` row showing `Select a device to see the engine's verdict for it.`;
  `Copy details` and `Show engine verdict` are disabled.
- **`Build progress`:** right-aligned step label `Not started`; a 0 % bar and `0%`; the five build
  stages already listed as pending — hollow dot icon, muted name, `—` time; the task box reads
  `Waiting to start` / `Nothing is downloading.` over an empty 5 px bar. The three metric tiles read
  `Elapsed time —`, `Downloaded 0 B`, `Speed —`.
- **`Engine log`:** full width below both columns; filter `Info and above`, `Save log…`, copy icon;
  the pane is empty and dark.
- Error card hidden. The whole window is a valid drop target for a `.json` file.

---

## 7. S2/S3 · Report loaded → verdicts

### 7.1 Loading (S2)

The layout does not change. The report row state becomes the amber alert icon with the tooltip
`Checking…`; the summary reads `Checking <filename>…` in the neutral empty style; the previous
report's devices, selection, details, version list, task text and summary note are **cleared before
the check starts**, because an engine run mutates its own kext and ACPI copies. Every control
disables except `Cancel`, which becomes visible and enabled. The log streams `== Checking
compatibility ==`. Do not draw a spinner over the window — the log is the progress indicator, and a
spinner icon appears only as the running stage mark.

### 7.2 Path rows

A 52 px rounded row: a 28 px tinted icon tile, a stacked 11 px label and 12 px value, a 16 px state
icon, and a `Browse…` button. The path is read-only and elided in the **middle** (`/home/…/Report.
json`) with the full path in its tooltip; the middle is elided so both the home directory and the
filename stay readable. A dropped file lands in the same field. Never an editable field: a mistyped
path produces a failure the user cannot see the cause of.

State icons are `dot`, `check-circle`, `alert-circle`, `x-circle`, coloured unknown / ok / warn /
fail. The tooltip is the state's sentence, so colour never carries the state alone:

| Icon | Meaning | Tooltips |
|---|---|---|
| `dot` | nothing chosen | `No path chosen` · `No folder chosen` |
| `check-circle` | the path checks out | `Graded` · `Exists and is writable` · `Will be created` · `Replaces a previous BlackDream build` · `«n» .aml file(s) found` |
| `alert-circle` | chosen but unusable, or in flight | `Checking…` · `No .aml files here` |
| `x-circle` | the path is wrong | `Rejected` · `Folder does not exist` · `Not writable` · `Folder is not empty` |

`Will be created` is not a warning: the build makes the folder, so a path whose nearest existing
ancestor is writable is genuinely fine. `Replaces a previous BlackDream build` means the folder
carries this app's build marker and will be rebuilt in place; any other non-empty folder is refused
(`Folder is not empty`) rather than deleted, so pointing the build at a mounted ESP cannot erase a
working bootloader. These icons mirror only what the filesystem says; whether a
table disassembles or a report validates is the engine's answer and arrives as a verdict or a card.

### 7.3 Summary panel

A rounded 12 px panel below `Detected support`. Once graded it takes its **ok** style — soft green
fill, green text, green border — in every later state, not only when the answer is good:

```
Native support: macOS Monterey 12 - macOS Tahoe 26
With OpenCore Legacy Patcher: macOS Big Sur 11 - macOS Tahoe 26
```

The second line appears only when the machine needs OCLP for some release. When any graded device
reaches the range through a third-party patch — `WhateverXe` or `NullMoth` — the first line reads
`Support: <range>` instead of `Native support: <range>`, because that range depends on the driver
being installed on the target. While a report is checking, or after it was rejected, the panel uses
the neutral style; after rejection it uses the **error** style (red fill, red text) with
`Compatibility check failed.`

The note under the panel is one or more sentences: `Status is computed for <selected release>.`,
plus `The engine suggests <release>.` when the engine's suggestion differs from the selection, plus
`Needs OpenCore Legacy Patcher.` when the selection requires OCLP.

### 7.4 Version picker

Label `macOS version`, one 40 px combo, one option per selectable major release, oldest first. The
engine's recommendation is preselected. A badged item is

```
macOS Tahoe 26  ·  suggested, needs OCLP
```

— the name, **two spaces**, a middle dot, **two spaces**, then the badges joined by `, ` in this
order: `suggested`, `needs OCLP`. Never brackets, never a star, never a slider or a card grid.

Changing the selection recomputes the Status column and the summary note immediately. The combo is
disabled while any job runs.

### 7.5 Devices table

Four headers, always: `Device` · `Class` · `macOS support` · `Status`. The first column stretches
with a 165 px floor; `Class` is fixed at 72 px; `macOS support` shrinks first, from 266 px down to
its own header plus the 8 px inset each side — 110 px in the reference font, where the 1160 px
window floor leaves it about 142 px; a wider platform font raises that floor and the dashboard
stacks before the header elides, with 90 px as the guard it never goes below. `Status` is at least
100 px and grows to its widest rendered word plus padding. Rows are
29 px, single-selection, never sortable, and not striped. A `Limited support` row takes
`rowWarnBg` and a `Not supported` row `rowFailBg`, across all four columns. The table scrolls its
own rows with a 150 px minimum height; the vertical scrollbar's width is part of the column
calculation, so the status word never hides under it.

**Row anatomy.** A 24 px rounded tinted tile with a class icon, then the device name. Long names are
shown in full wherever the column allows and always in the tooltip. The class is one plain word:

`CPU` · `GPU` · `Audio` · `Ethernet` · `Wi-Fi` · `Storage` · `USB` · `Bluetooth` · `SD card` ·
`Display` · `Biometric` (fallback: the section name, with a layers icon).

**`macOS support`** is the engine's own sentence, verbatim, and is printed in normal text colour:

| Verdict shape | Meaning |
|---|---|
| `Up to macOS Tahoe 26` | supported through the newest release |
| `macOS Catalina 10.15 to macOS Tahoe 26` | supported in a range |
| `macOS Big Sur 11 to macOS Tahoe 26 with WhateverXe` | supported in a range only through the WhateverXe patch |
| `macOS Sequoia 15.5 to macOS Tahoe 26 with NullMoth` | supported in a range only through the NullMoth NVIDIA driver |
| `Maximum support up to macOS High Sierra 10.13` | capped low |
| `Unsupported` | graded and rejected |
| `Unchecked` | the engine did not grade it |

`Unsupported` is not a blocked build — HDMI audio lands there on almost every healthy laptop. Only
the six fatal conditions in §8 block anything, and they arrive as a card, never as a row.

**Status.** The fourth column is not a pill and has no background of its own: a 15 px status icon
plus a coloured word, aligned left. It answers one question — *will this device work on the release
selected in the `macOS version` card?*

| Label | Tone | Meaning |
|---|---|---|
| `Supported` | ok (green) | native on the selected release |
| `Limited support` | warn (amber) | works on the selected release only through OpenCore Legacy Patcher, the WhateverXe graphics patch or the NullMoth NVIDIA driver |
| `Not supported` | fail (red) | either no release supports it, it is too old for the selection, or it is too new and has no OCLP path |
| `Not graded` | unknown (grey) | the engine carried no compatibility tuple to judge |

The cell's tooltip is the status detail followed by the recommendation, e.g.
`Not supported on macOS Tahoe 26. Last native support is macOS Sequoia 15. Choose macOS Sequoia 15 or
earlier for native support.` Selecting another macOS version changes words, icons, row tints and
tooltips; the `macOS support` column does not change. Icons repeat the text; they never replace it.

The card hint becomes `Detected «n» device«s» from your hardware report.` The table's first row is
selected automatically. `View details` (a chip in the card header) selects the first `Not supported`
row, or the first row when none is unsupported, and opens the details card in the right column under
the table. Its label becomes `Hide details` while open.

### 7.6 Device details

The card rides in the right column under the table, replacing `Build progress` while open; closing
it (`Hide details`) restores the progress card, and switching views remembers the choice. A
two-column grid with 102 px keys: `Device`, `Class`, `macOS support`, `Vendor`, `Device ID`,
`Subsystem`, `Current status`, then a full-width `Recommendation` line. Values default to an em
dash. The recommendation is coloured by the status tone. The card header carries the status label
as a rounded badge, right-aligned.

Two outline buttons at the bottom: `Copy details` puts every `Key: value` pair plus the
recommendation on the clipboard; `Show engine verdict` opens a modal titled `Engine verdict` with
the device name, the engine's support sentence, the status label, the detail and the recommendation.
Both are disabled until a row is selected.

### 7.7 Actions

The actions card is an untitled 2 × 2 grid of equal-width buttons: primary `Check compatibility`
(pulse icon, white) and outline `Build EFI folder` (build icon) on the first row; outline `Cancel`
and outline `Open EFI folder` (folder icon) on the second. All four are always visible. Enablement
follows §11 exactly. `Build EFI folder` stays disabled until a report has been graded;
`Open EFI folder` enables only after a build wrote a folder that still exists; `Cancel` is enabled
only while a job runs.

### 7.8 Build progress

Header: title `Build progress` on the left, the step label right-aligned: `Not started`, or
`Step 2 of 5` while a stage runs, or `Step 5 of 5` when all five are done. Under it a 9 px progress
bar and a 16 px `40%` at the right end. Qt's centred bar text is never drawn; the percentage sits
beside the bar where it never shares a background with the fill.

The five engine stages, in order, are always listed from the start:

```
Copying EFI base to results folder
Applying ACPI patches
Copying kexts and snapshotting to config.plist
Generating config.plist
Cleaning up unused drivers, resources, and tools
```

Each 26 px row is an icon, the name, and an elapsed time on the right (`—` until the stage runs).
The mark set is icons, not glyphs:

| Icon | State |
|---|---|
| `dot` (hollow) | pending |
| `spinner` (open arc) | running |
| `check-circle` | done |
| `x-circle` | failed |
| `minus` | cancelled |

Beside the checklist (3 : 2) is the current-task box: the task name in semibold, a muted detail
line, a 5 px progress bar, and three metric tiles. There is no `CURRENT TASK` caption and no
separate transfer line; the card is compact and the checklist absorbs the extra height when the two
stack. Between stages it reads `Waiting to start` / `Nothing is downloading.` During a transfer the
task name is the product, the detail is `<done> of <total> · <pct>%` (or `<done> of <total>`, or
`<size> downloaded` when the length is unknown), and the small bar follows the transfer. After
analysis it reads `Ready to build` / `Choose a macOS version, then build the EFI folder.` After a
build it reads `EFI folder ready` / the result path and the small bar is full.

Three metric tiles below those lines: `Elapsed time`, `Downloaded`, `Speed`, each with a 16 px
tinted icon. The step position is the header label, not a fourth tile. Formatters, which a mockup
must copy:

- Elapsed: `1.4 s` under a minute, `1:42` under an hour, `1:02:03` above.
- Size: `0 B`, `512 KB`, `1.4 MB`, `2.31 GB` (binary units, one decimal for MB, two for GB).
- Rate: `—` when idle, `904 KB/s` below 1 MiB/s, `1.9 MB/s` at or above it. Stage times never use
  this formatter.
- Step: `«done»/«total»` appears only in the header's `Step «n» of «total»` label.

The card hint is `Step, transfer and timing from the engine.` at rest; `Building your OpenCore EFI
folder.` while one of the three build jobs runs; `The EFI folder is ready.` after the build.

### 7.9 Engine log

The card header carries, right-aligned: a 162 px level combo (`Info and above` · `Warnings and
above` · `Everything`), a `Save log…` chip with a save icon, and a 30 px copy icon whose tooltip is
`Copy the log`. The pane below is dark in both themes, 12 px monospace, no line wrap, a 14 px
radius, minimum 150 px, capped at 4000 lines.

A line is `HH:MM:SS`, a level tag, then the message:

| Tag | Colour | Filter |
|---|---|---|
| `DEBUG` | `#8a8f98` | only under `Everything` |
| `INFO` | `#d8dbe4` | `Info and above`, `Everything` |
| `WARN` | `#e5c07b` | `Warnings and above`, `Everything` |
| `ERROR` | `#e06c75` | `Warnings and above`, `Everything` |

Engine text is untrusted: it is HTML-escaped before display, so a device name full of angle
brackets names itself instead of formatting the window. When the ring buffer drops lines the pane
gets `<n> earlier log lines were dropped` as a warning. `Save log…` writes `[HH:MM:SS] [level]
message` lines to the chosen file.

### 7.10 Folder checks

Below `Engine log` on the Build view, a full-width `Folder checks` card whose hint is `Read the
built folder before you try to boot it.` The header carries three outline buttons: `Run checks`
(tooltip `Check required files and every path config.plist references`), `Verify manifest`
(tooltip `Compare the folder with the manifest written at build time`) and `Save report…`, which
stays disabled until a check has produced a report. The card reads `Not checked yet.` at rest over
the boundary sentence `These checks read the folder. They do not test firmware, hardware or
whether macOS boots.`

`Run checks` analyses the built folder without writing anything: every `ACPI/Add`, `Kernel/Add`,
`UEFI/Drivers` and `Misc/Tools` entry in `config.plist` must point at a file that exists inside the
folder. The first line reports `No issues detected by these checks.` or `«n» errors, «n» warnings`.
Findings appear in a list capped at 112 px, one per row as `[ERROR] «where» · «message»` or
`[WARN] «where» · «message»`; the tooltip carries `Evidence: «evidence»` and `Next: «action»`.
The note under the status names how many files were read and repeats that the checks do not test
firmware, hardware or whether macOS boots. An empty severity list collapses the list entirely.

`Verify manifest` compares the folder with the `.blackdream-manifest.json` written beside it at
build time. The status reads `Every file matches the recorded manifest.` or
`«n» missing, «n» changed, «n» added`, and each difference is one row, `[MISSING]`, `[CHANGED]` or
`[ADDED]` followed by the relative path. The note says a match proves these files are the ones
recorded at build time and does not prove the folder boots. With no build folder the card says
`No EFI folder to check.` over `Build an EFI folder, or choose one on the Installer page.`; with no
manifest it says `There is no manifest to verify.`

`Save report…` writes the last report as plain text, never a screenshot, and the status bar says
`Report saved to «path»`. Every check also writes one log line, `Folder checks: «summary»` or
`Manifest: «summary»`. A clean result is a statement about files, never about booting; the card
never claims the folder will boot.

---

## 8. S4 · Fatal incompatibility, and the rejected-report reset

The error card sits at the top of the content column, above the page stack, spans the content width,
and appears on whichever view is open. It does not close or block the rest of the window; the user
can still load another report. It is hidden again the moment a new job starts.

Card anatomy, in this order:

1. **Title** — bold, `errorFg`
2. **Detail** — regular
3. *This machine cannot run macOS as configured.* — italic, only when the condition is not
   recoverable (`cpu.no_sse4`, `gpu.unsupported`)
4. Bulleted remediation list
5. `code: <machine code>` — muted, last line, always present

The six real fatals, verbatim:

| Code | Title | Detail |
|---|---|---|
| `cpu.no_sse4` | CPU lacks the SSE4.x instruction set | macOS requires SSE4.2 on every supported CPU. This processor predates that. |
| `gpu.absent` | No GPU found in the hardware report | The report contains no graphics device, so no display can be driven during install. |
| `gpu.unsupported` | No macOS-compatible GPU on this system | You cannot install macOS without a supported GPU. Every device in the report was rejected: «device names» |
| `storage.absent` | No storage controller found in the hardware report | Without a storage controller the internal drives are invisible to the installer. |
| `storage.intel_vmd` | Intel VMD storage controller is enabled | macOS has no driver for Intel VMD, so the NVMe drives behind it are unreachable. |
| `storage.no_compatible` | No macOS-compatible storage controller | Every PCI storage controller with attached drives in this report is unsupported. |

Several raise sites replace the class default with report-specific copy: `cpu.no_sse4` names the CPU,
`storage.intel_vmd` names the controller and its device ID, and `storage.no_compatible` lists the
rejected controllers. The card for `gpu.unsupported` on the Compatibility path carries:

```
• Check the Compatibility screen for which device was rejected and why.
• A supported discrete GPU, or an iGPU from Iron Lake through Ice Lake, is required.
```

**When the compatibility job itself fails, the whole page resets.** This is not optional polish; it
is what keeps one report's data off another report's error:

- report row: red `x-circle`, tooltip `Rejected`;
- summary panel: red, `Compatibility check failed.`;
- note: `No devices were graded. Choose another Report.json and check it again.`;
- device table: empty, hint `No devices were graded from this report.`, note `The engine rejected
  this report before grading any device.`;
- version combo: empty; details: reset; selection: cleared;
- task box: `Compatibility check failed` / the error's title;
- `Build EFI folder`: disabled.

The red card and the cleared page describe the **same machine**. A screenshot that shows a fatal
card together with the previous report's rows is wrong.

---

## 9. S5–S10 · Other failure states

**S5 Report rejected** — `code: report.rejected`, title `This hardware report cannot be used`,
detail begins with the file name and the validator's own reason, e.g. `nothing.json: File not
found`. Bullet: `Collect the hardware report again, or export a fresh one with Hardware Sniffer.`
The page clears exactly as in §8.

**S6 Build blocked, no ACPI source** — raised the moment the user presses Build on a machine with no
readable DSDT and no folder supplied. `code: pipeline.build_not_ready`, title `The build is missing
something it needs`, detail `No DSDT is loaded and no ACPI table folder was supplied.`, bullets:

```
• Point the report at the ACPI folder inside the exported SysReport.
• Or press Read ACPI tables on the Compatibility view to read this machine's firmware.
```

The card appears on the `Build EFI` view, where the button was pressed. The row that fixes it is one
click away on `Compatibility`, and its state icon already says the same thing: a hollow dot with
`No folder chosen`, or an amber alert with `No .aml files here`. There is no focus ring and no
animated pointer — the app does not move the user's window for them.

**S7 Build in progress** — two of five stages `check-circle`, stage three `spinner` and bold, the
step label `Step 3 of 5`, the bar at 40 %, the task box naming the product and its bytes, the Speed
tile live, `Cancel` enabled, the log scrolling.

**S8 Build finished** — all five stages `check-circle`, `Step 5 of 5`, bar 100 %, task name
`EFI folder ready`, task detail the result path, the small task bar full, hint `The EFI
folder is ready.`, `Open EFI folder` enabled, log's last line `Done: <path>`. No confetti, no modal,
no "Success!" screen. The filled card and the enabled button are the whole celebration.

**S9 Cancelled** — the stage in flight becomes `minus`, later stages stay `dot`, the task detail
reads `<step> cancelled.`, the log gets `<step> cancelled` in warn colour, `Cancel` disables again
and the other controls return to their pre-build state. The error card stays hidden: cancelling is
not a failure.

**S10 Unexpected engine failure** — same card anatomy, `code: engine.unexpected`, title `The engine
failed unexpectedly`, detail is the raw exception prefixed with its type, e.g. `IndexError: list
index out of range`, bullet:

```
• Retry the step. If it repeats, save the log from the Details panel before reporting it.
```

Two more cards share the anatomy but have no screen of their own:

**No report loaded** — pressing `Check compatibility` before a file is chosen. `code:
engine.error`, title `Engine error`, detail `Choose a Report.json first. You can drop the file
anywhere in this window.` No bullets. The button is live precisely so it can explain itself.

**Single-flight refusal** — starting a second job while one is still running. `code: engine.error`,
title `Engine error`, detail `The previous step is still finishing. Its engine objects are in use,
so starting another now would corrupt this session.` This is the only state in which the app refuses
an action rather than queueing it, and it is why `Cancel` exists.

A third, rare: `code: job.abandoned`, title `That step stopped responding`, detail `<step> exceeded
its <N> s budget and is still blocked in a system call <G> s after cancellation.`

---

## 10. Microcopy catalogue

Every string the window can produce, verbatim. Use nothing else. §16 is the machine-readable form of
this table.

| Where | String |
|---|---|
| Window title | `BlackDream` |
| Window frame | drawn by the platform: the system title bar, window buttons and resize borders; the app paints no window controls |
| Menu bar | `File` — `Open Report…` · `Open ACPI Folder…` · `Quit`; `View` — the eight view names, a `Build` submenu, then `Toggle Theme`; `Help` — `Keyboard Shortcuts` · `About BlackDream`. Visible everywhere; the system bar outside the window on macOS, a strip at the top of the window on Windows and Linux |
| Sidebar | `BlackDream` · `OpenCore, made simple.` · `WORKFLOW` · `Installer` · `Build EFI` · `Configure EFI` · `Settings` · `Help` · `Donate` |
| Page headings | `Make a macOS Installer` · `Hardware Compatibility` · `Build EFI Folder` · `Engine Log` · `Configure EFI` · `Settings` · `Help` · `Support BlackDream`, with the subtitles in §16 |
| Search | placeholder `Search devices…`; keycap `Ctrl K` / `⌘ K`; lives in the `Detected devices` header and is shown only on `Compatibility` |
| Theme control | `Settings > Appearance` combo `System` · `Light` · `Dark`; no theme button in the header |
| Card titles | `macOS installer` · `USB drive` · `macOS version` · `Detected devices` · `Device details` · `Build progress` · `Engine log` · `Folder checks` · `config.plist` · `Sections` · `Keys` · `Selected entry` · `Validation` · `Appearance` · `About` · `Storage` · `Downloads and safety` · `Quick start` · `Keyboard shortcuts` · `Troubleshooting` · `Diagnostics` · `Before the first boot` · `Support the project` · `Test on real hardware` · `Send a compatibility report` · `Share the app` · `Funding`; the setup and actions cards are untitled |
| Card hints | §16 `card_hints` — the devices hint changes with state; `Appearance`, `Storage` and `Quick start` carry fixed hints |
| Empty notes | `Load a report to see this machine's devices and what macOS does with them.` · `The engine rejected this report before grading any device.` |
| Field labels | `Hardware report (Report.json)` · `ACPI tables folder` · `Output folder` · `EFI folder` |
| Field button | `Browse…` |
| Link buttons | `Collect hardware` · `Read ACPI tables` · `View details` · `Hide details` · `Copy details` · `Show engine verdict` · `Compare reports…` · `Profiles…` · `Compare releases…` |
| Link tooltips | `Scan this machine and write a Report.json` · `Scan this machine with Hardware Sniffer; downloads and runs the verified tool` · `Read the firmware tables from this machine; asks for administrator rights` · `Compare this report with another one, without re-grading either` · `Save this machine's report path and EFI folder as a local profile` · `See every graded device against every selectable macOS release` |
| Buttons | `Check compatibility` · `Build EFI folder` · `Cancel` · `Open EFI folder` · `Save log…` · `Run checks` · `Verify manifest` · `Save report…` · `Download installer` · `Download again` · `Refresh` · `Write installer` · `Save` · `Validate` · `Validate again` · `Generate serials` · `Open config…` · `Undo` · `Redo` · `Changes…` · `Revert` · `Show folder` · `Add key` · `Add item` · `Remove` · `Up` · `Down` · `Apply` · `Edit…` · `Copy environment info` · `Save diagnostic bundle…` · `History…` · `Schema preview…` · `Copy the checklist` · `Save current` · `Use` · `Rename…` · `Open folder` · `Copy history` · `Save as text…` · `Copy` |
| Table headers | `Device` · `Class` · `macOS support` · `Status` — exactly four columns |
| Class labels | `CPU` `GPU` `Audio` `Ethernet` `Wi-Fi` `Storage` `USB` `Bluetooth` `SD card` `Display` `Biometric` |
| Status words | `Supported` · `Limited support` · `Not supported` · `Not graded` |
| Summary | `Load a Report.json, or collect hardware from this machine.` · `Load a Report.json, or scan this machine with Hardware Sniffer.` · `Load a Report.json exported by Hardware Sniffer on the target PC.` · `Checking <file>…` · `Native support: <ranges>` · `With OpenCore Legacy Patcher: <ranges>` · `Compatibility check failed.` |
| Summary note | `Support ranges come from the report's own compatibility data.` · `Status is computed for <release>.` · `The engine suggests <release>.` · `Needs OpenCore Legacy Patcher.` |
| Version items | `<name>` or `<name>  ·  suggested, needs OCLP` (badges joined by `, `) |
| Progress card | `Not started` · `Step <n> of <total>` · `<pct>%` · metric labels `Elapsed time` `Downloaded` `Speed` · `0 B` |
| Task box | `Waiting to start` · `Nothing is downloading.` · `Ready to build` · `Choose a macOS version, then build the EFI folder.` · `Running…` · `Starting…` · `Cancelling…` · `<done> of <total> · <pct>%` · `<size> downloaded` · `EFI folder ready` · `<step> cancelled.` · `<step> failed.` |
| Metrics formatters | `<n>.<d> s` · `M:SS` · `H:MM:SS` · `0 B` · `<n> KB` · `<n>.<d> MB` · `<n>.<dd> GB` · `—` · `<n> KB/s` · `<n>.<d> MB/s` |
| Log filter | `Info and above` · `Warnings and above` · `Everything` |
| Log line | `== <step> ==` · `Graded <n> devices` · `SMBIOS model: <model>` · `<step> finished in <s> s` · `<step> cancelled` · `<step> failed` · `<n> earlier log lines were dropped` · `Done: <path>` · `<n> hardware sections written to <path>` · `<n> ACPI tables read from firmware` |
| Log tools | `Copy the log` · `Save log…` |
| Error card | `code: <code>` · `This machine cannot run macOS as configured.` (italic suffix, only the two unrecoverable fatals) |
| Settings view | `Theme` · `Light` · `Dark` · `Artifact cache` · `Runtime tools` · `BlackDream <version>` · `MIT` / `BSD-3-Clause` about copy · `Pinned SHA-256` · `Folder only` · `No account` |
| Help view | quick-start titles and bodies · shortcut actions · `Troubleshooting` copy · `Copy environment info` · `Save diagnostic bundle…` · `Nothing has been copied or saved.` · `Copied to the clipboard.` · the `Before the first boot` card: six step titles and bodies in §16, `Advice for the first attempt. BlackDream never boots, installs or writes firmware.`, `Copy the checklist`, `Nothing has been copied.` and the copied text's closing `This is advice. BlackDream has no boot button and writes no firmware.` |
| Donate view | `Support the project` summary · `Test on real hardware` · `Send a compatibility report` · `Share the app` · `Funding` · `Donation links are not open yet.` |
| Installer view | `Choose a macOS version` · `macOS <name> <version>` / `macOS Tahoe 26 · latest` · `Not downloaded yet.` · `About 1 GB. A dropped connection resumes where it stopped.` · `Verified · <size>` · `Download installer` / `Download again` · `Write installer` · `Refresh` · USB placeholder and notes in §16 |
| Configure EFI view | Header chips `Not validated` · `Valid` · `Checking…` · `«n» issue(s)` · `OpenCore «version»`; file card status `No built config.plist yet.` · `config.plist is open` · `Unsaved changes` · `Changed on disk.` · `Changed on disk; unsaved edits here.` · `The config.plist could not be read.`; header buttons `Open config…` · `Validate` · `Save`; card buttons `Undo` · `Redo` · `Changes…` · `Generate serials` · `Revert` · `Show folder`; rail `Sections` · `All keys`; key search `Search keys…`; tree headers `Key` · `Value` · `Type`; inspector `Nothing selected` · `Select a key to inspect it.` · `No config.plist is open.` · `On` · `Apply` · `Edit…`; validation `Not checked yet.` · `Checking…` · `Valid` · `«n» issue(s)` and a clickable issue list that says `Select an issue to go to the key it names.` · `Schema preview…` · `Dependencies…` in the `Validation` header, both disabled until a document is open; the toolbar, notes and dialog copy are in §15 and §16 |
| Comparison, profile, history and preview dialogs | `Hardware compatibility by macOS release` · `Compare hardware reports` · `Profiles` · `Build history` · `Schema preview`, with the headers, notes, warnings and boundaries in §16 `read_only_dialogs` and `configure.schema_preview`. Each closes with `Copy` or `Copy history` and `Save as text…`; none of them has an Apply, Migrate, Boot or Write action |
| Dialogs | `Engine verdict`, `Write installer?` / `Installer written`, `Changes since the file was opened`, `Save a diagnostic bundle`, and the editor's own: `Remove from config.plist?`, `Overwrite config.plist?`, `Edit data` / `Edit text`, `Add a key`, `Generate SMBIOS serials`, `Replace SMBIOS values?`. Validation is inline on the page, never a dialog. Settings and About are views in 2.1 |

`<step>` is either a §16.2 engine stage name or a §16 job name — never a string invented to fit the
width of a bar.

---

## 11. Component state matrix

| App state | Report row | ACPI row | Output row | Check | Combo | Build | Cancel | Open folder | Collect/Read ACPI |
|---|---|---|---|---|---|---|---|---|---|
| S1 empty | on | on | on | on | off (empty) | **off** | off | **off** | on |
| S2 checking | off | off | off | off | off | off | **on** | off | off |
| S3 verdicts | on | on | on | on | on | **on** | off | off | on |
| S4/S5 fatal, rejected | on | on | on | on | off | **off** | off | off | on |
| S6 build blocked | on | on | on | on | on | **on** | off | off | on |
| S7 building | off | off | off | off | off | off | **on** | off | off |
| S8 done | on | on | on | on | on | on | off | **on** | on |
| S9 cancelled | on | on | on | on | on | on | off | off | on |
| S10 unexpected | on | on | on | on | on | on | off | off | on |

`on`/`off` here means enabled/disabled, never shown/hidden — no state in this table hides a card or
a button, and the open view never disables a control. `Cancel` is always visible and enabled only
while a job runs; hiding it until then made the 2 × 2 actions grid reflow mid-job. The two optional
link buttons follow host capability: `Collect hardware` is drawn on Linux and Windows,
`Read ACPI tables` on Linux and Windows as well, and neither is drawn where the capability is
missing — a disabled button would promise a feature the build does not have.

`Settings`, `Help` and `Donate` do not change the session state matrix. Their controls stay enabled
while a job runs: the theme picker is local, the diagnostics button only reads paths and the last
error code, and neither touches the engine. Opening one of these views during a build does not move
the window off the build; when the job starts, the window still follows it to `Build EFI`.

`Installer` and `Configure EFI` gate only their own destructive and download controls. `Download
installer` is disabled while any other job runs, and `Write installer` additionally needs a verified
image, a complete EFI folder and a drive the user chose explicitly. In the editor, `Save` needs
unsaved changes, `Validate` and `Generate serials` need an open document, `Revert` needs unsaved or
external changes, and every action is disabled while a config job runs. The release picker is
disabled while an installer job runs; choosing another release swaps the verified image and disables
`Write installer` until that release is on disk. No gate depends on which view is open.

---

## 12. Explicitly not allowed in a mockup

§16 is the machine-readable string allowlist and §17 records drift that generated mockups have
already been caught doing. Both are checked by `tests/test_mockup_spec_allowlist.py`, which parses
§16 and refuses any string that is not a literal in `src/` — so this document cannot quietly fall
behind the code, and a mockup built from it cannot contain a sentence the app would never print.

- A three-column Devices table. 2.0 has four headers, always; the fourth is the target-relative
  `Status` (§7.5). It may only say one of the four labels in §16 — never `Compatible`, `Works`,
  `Best effort`, a bare check mark, or a fifth column such as `In build`.
- A WhateverXe device marked `Supported` or described as native. Apple never shipped an Xe-LP
  driver: the row's range ends in `with WhateverXe` and its status is `Limited support`, because
  the graphics package is installed after the first boot.
- A NullMoth device marked `Supported` or described as native. The driver is a third-party kernel
  extension installed into `/Library`, not Apple firmware support: the row's range ends in
  `with NullMoth` and its status is `Limited support`.
- A coloured pill around the status word. The table draws a 15 px icon and a coloured word with no
  pill background; a `Not supported` or `Limited support` row carries the tone as a full-row tint.
- The `macOS support` column painted red. It is plain text; the status word carries the judgement,
  and `Unsupported` is not necessarily a blocked build.
- A status bar along the bottom edge, or a `Ready` line anywhere. 2.0 removed it.
- A toolbar across the top, a hamburger, or a collapsible rail. The sidebar is the primary
  navigation, and `Settings`, `Help` and `Donate` stay at the bottom of the 200 px rail. The
  `File` / `View` / `Help` menu bar is always visible: the system bar on macOS, a strip at the top of
  the window on Windows and Linux.
- A theme button (sun / moon) in the header. The theme control is the combo in
  `Settings > Appearance`, and `Toggle Theme` remains in the `View` menu.
- A Settings or About modal over the dashboard. 2.1 replaced both with the Settings view; the only
  modals left are `Engine verdict`, the installer write confirmation and its completion notice, the
  configure editor's own confirmations and value editors, and the five read-only dialogs of 3.6
  (`Hardware compatibility by macOS release`, `Compare hardware reports`, `Profiles`, `Build
  history`, `Schema preview`) plus the editor's `Changes since the file was opened` and the bundle
  saver (§15).
- A Donate page with a live payment button, card-number fields, supporter tiers or a licence key.
  Funding is not open; the `Funding` card says so and carries no button. When a real donation URL
  exists, the card gains one button and §16 gains its label in the same change.
- External documentation links on the Help view. The app opens no manual or website; help is the
  in-window copy in §16.
- A `Build steps` card separate from the progress card. Stages, bar, task box and metrics are one
  card: `Build progress`.
- A horizontal numbered stepper, `Next`/`Back`, or any read of the card numbers as a sequence. The
  step label `Step 2 of 5` describes one engine stage; it is not a wizard step.
- Glyph marks (`✓`, `▶`, `✗`, `–`, `·`) in the stage list or path rows. Every state mark is an SVG
  icon from the app's own set; emoji are never used.
- A desktop wallpaper outside the window, a floating inset panel or fake traffic lights. 2.6 keeps
  the native frame and paints the blue-silk wallpaper **inside** the client area only; the rail and
  cards keep their translucency, border and lighter top edge. The platform draws the title bar,
  window buttons and resize borders; there are no painted lights and no custom drag region.
- A flat, neutral canvas with no silk. The client area carries the painted gradient, bloom, ribbons
  and vignette; the content veil and rail are glass over it, not an opaque grey fill.
- A photo wallpaper, heavy blobs, or drop shadows around the window or the cards. The silk is five
  low-alpha cubic strokes, not a texture asset; raised surfaces carry a 1 px lighter top edge and
  never a blur. Qt has no `box-shadow`, and a graphics effect would repaint the subtree on every log
  line.
- A frameless window, a custom drag region, an inset panel or app-painted window buttons. The
  platform draws the title bar, window buttons and resize borders; the menu bar is visible on every
  platform.
- Gradient card headers, gradient nav other than the checked pill, or gradient text. The wallpaper,
  content veil, rail and card fills are material gradients; header text, status words and unchecked
  nav items stay flat. The functional gradients are the primary button, the checked sidebar pill,
  the progress fill and the app logo (§4).
- Icons from a third-party icon font or library, or hand-drawn approximations of the app's icons.
  The set is the inline SVGs in `src/blackdream/ui/icons.py`.
- A tagline other than `OpenCore, made simple.`, or the retired `OpenCore EFI builder.` line. The
  approved mockup's tagline is the one that ships.
- The ① ② ③ setup numbers. No card or button carries a number; the mockup's badges never shipped.
- A "Download OpenCore" button, a mirrors/proxies settings screen, or a picker for the OpenCore
  version — the engine pins these.
- Any mention of writing to the EFI partition, mounting disks, or a terminal prompt. v1 emits a
  folder.
- A drive-formatting step, an `Erase` or `Format` checkbox, or a partition picker. The Installer
  copies `EFI` and `com.apple.recovery.boot` into an already-mounted FAT32 volume, replaces only
  those two items, and leaves every other file alone.
- An installer write that starts before the image is verified. Apple's signed chunklist is checked
  first, then every image chunk while it is copied; the drive never receives an unverified byte.
- A USB dropdown that preselects the first drive. The target is chosen on purpose, the confirmation
  names it, and the volume's identity is re-checked before the first byte is written.
- An OCAT download, an OCAT process, an OCAT update check, or a link that leaves the app for
  editing. 3.3 edits the built `config.plist` in the window; the Configure page has no external
  tool, no release pin and no OCAT attribution card.
- A config editor that writes on every keystroke, or a Save that discards the previous file. Edits
  live in memory until `Save`; `Save` keeps the previous bytes as `config.plist.bak`, and nothing
  else writes the file.
- A config editor that reorders keys, rewrites unknown keys, or drops them. Key order follows the
  file, and a key the pinned sample does not know is shown with its real type and kept on save.
- A dependency advisory with an `Apply`, `Fix` or `Reorder` button. S34 reports relationships the file
  already claims and stops there; the only thing it writes is a dismissal key in the app's own state
  directory, and a mockup that shows a corrected tree has invented an action the code refuses.
- Serial, MLB or UUID values echoed into the engine log. The generated values appear in the tree and
  in the confirmation dialog only.
- A config editor that mounts a disk, writes to the EFI partition, or repairs firmware. It edits one
  file in the output folder the user already chose.
- A tree that hides the document until a build exists. With no build the page still offers
  `Open config…`, and a chosen file loads by the same code path as the built one.
- A macOS installer boot button or an "Install macOS" action. Writing the files is the whole job;
  the USB is booted on the target PC.
- A boot, restart, NVRAM or firmware action on the first-boot checklist. It is six advice rows and a
  copy button; the copied text closes with the sentence that says so.
- A release matrix that re-grades, or a device table with a fifth "matrix" column. 3.6's grid is the
  same `verdicts.target_status` answer laid out per release, and the dialog repeats that it is not a
  boot test.
- A report comparison that says one side is newer, better or re-checked. It diffs what the two files
  recorded and keeps a hardware change apart from a recorded reading change; neither is re-analysed.
- A profile that carries a serial, MLB, UUID or ROM value, or one that silently restores a folder
  the user did not record. Five fields, in `profiles.json`, and a missing report is refused with its
  path.
- A build history that deletes, hides or rewrites a row whose folder has gone. `Folder missing` is
  the honest answer, and `Open folder` stays disabled.
- A `Migrate`, `Apply`, `Fix` or `Repair` button in the schema preview. It shows the pinned-schema
  diff and `ocvalidate`'s verdict on a projection, and writes nothing; the note after it closes says
  the file is untouched.
- An invented array, dict or sample value in a migration projection. A container the file does not
  have is listed as missing, never filled in.
- A password field inside the app's frame, anywhere, ever. The only authentication surface is
  polkit's own window, drawn by the desktop outside this window.
- Free-text entry in the three path fields, or a typed file path anywhere.
- Colour as the only signal: every status, state and error code carries text, and every state icon
  has a tooltip.
- A second log pane on the `Logs` view. The same widget moves and grows; the card area empties.
- `OpenCorePkg: 62% at 1.9 MB/s` below 1 MiB/s. Rates are `KB/s` until they genuinely cross 1 MiB/s;
  the formatter is in §7.8.

---

## 13. Cross-platform notes

| | macOS | Windows | Linux |
|---|---|---|---|
| Window chrome | native title bar, window buttons and resize borders; `File`/`View`/`Help` is the system menu bar at the top of the screen, outside the window | native title bar and window buttons; the menu bar is a strip at the top of the window | native title bar and window buttons; the menu bar is a strip at the top of the window (X11 and Wayland alike) |
| Canvas | the same blue-silk wallpaper inside the client area, below the system menu bar | the same wallpaper below the in-window menu strip | the same wallpaper below the in-window menu strip (X11 and Wayland alike) |
| Drag window | the platform title bar | the platform title bar | the platform title bar (X11 and Wayland alike) |
| Default output | `~/Library/Application Support/blackdream/builds/<stamp>/EFI` | `%LOCALAPPDATA%\blackdream\builds\<stamp>\EFI` | `~/.local/share/blackdream/builds/<stamp>/EFI` |
| Artifact cache | `~/Library/Application Support/blackdream/cache` | `%LOCALAPPDATA%\blackdream\cache` | `$XDG_DATA_HOME/blackdream/cache` |
| Crash reports | `~/Library/Application Support/blackdream/logs/crashes` | `%LOCALAPPDATA%\blackdream\logs\crashes` | `$XDG_DATA_HOME/blackdream/logs/crashes` |
| Search keycap | `⌘ K` | `Ctrl K` | `Ctrl K` |
| Settings / Help shortcuts | `⌘ ,` · `F1` | `Ctrl ,` · `F1` | `Ctrl ,` · `F1` |
| Utility views | same three pages; search only on Compatibility | same | same |
| Drop target | whole window for `.json` | whole window | whole window (Wayland: the file-chooser fallback must be shown) |
| Reveal folder | Finder | Explorer | the session's file manager |
| Collect hardware | absent — load a report exported on the target PC | Hardware Sniffer, downloaded, SHA-256 pinned, run with `-e -o` | local sysfs/DMI scan, no elevation, no network |
| Read ACPI tables | absent | in-process read of the Windows firmware table API; no elevation, no download | privileged helper via polkit's own window |
| Installer image | Apple's recovery service over HTTPS; chunklist verified against Apple's embedded key; image cached under Application Support | same, under `%LOCALAPPDATA%` | same, under `$XDG_DATA_HOME` |
| USB target | mounted FAT32 under `/Volumes`; no formatting, no block-device access | mounted FAT32 drive letters from `Win32_LogicalDisk`; no formatting | mounted FAT32 from `/proc/mounts`; no formatting |
| Config validation | `ocvalidate` from the pinned OpenCorePkg release, digest-verified into the app tools directory and run on a temporary copy | same, PE binary | same, ELF binary |
| Config serials | OpenCore's `macserial` via the same verified toolchain as the build | same | same |
| Config editor | one tree, one set of dialogs and the same atomic save on every platform; `config.plist.bak` is written beside the file | same | same |
| Toolchain | `iasl-stable`/`iasl-legacy` and `macserial`, universal Mach-O, digest-pinned | PE binaries, digest-pinned, installed outside the package | ELF binaries, digest-pinned, installed outside the package |

---

## 14. Accessibility and text rules

- All three failure surfaces (card, summary panel, log) are selectable text; error copy must be
  copy-pasteable, because it is what gets pasted into a bug report.
- Contrast: the error foreground on the error fill and the log foreground on the log fill both
  exceed 7:1 in each theme. Do not lighten them for aesthetics.
- Never colour alone: status cells pair an icon with a word, stage rows pair an icon with a state
  name, field states pair an icon with a tooltip.
- The Devices table gives way from the right: the `macOS support` column shrinks (266 px down to
  its own header's width plus the 8 px inset each side) before the Device column loses anything, so
  a name keeps every pixel the card can spare. It never shrinks past that header, and a font wider
  than the reference one moves the floor with it. When the two dashboard columns cannot both hold
  their floors the split stacks, so the layout bends before a header elides. A name longer than the
  column is elided - the table never scrolls sideways, and no fixed column can promise otherwise
  against a string a report supplied - and the whole name and the whole release range are in the
  row tooltip. A 200 % UI scale changes nothing here: Qt doubles the device pixels and leaves the
  logical geometry, so what fits at 100 % fits at 200 %.
- Engine text is untrusted content: device names come from a report written by another program, and
  remote filenames come from GitHub. Mockups should show long, awkward names
  (`Intel Cannon Lake-HDMI`, `Realtek RTL8821CE-CU4AA_921E PCIe Network Card`) rather than tidy ones.
- No string is ever split across two labels to fake a line break; ranges use ` - ` (hyphen), not an
  en-dash, because the value is also printed to logs.
- No control is ever narrower than its own label. The window's minimum width is fixed, so when the
  platform font is wider than the reference font the rail grows past its 200 px floor and an action
  row takes a second line instead of squeezing a button. The rows that wrap in the running app are
  the Configure page's header action slot, the config card's action row, the Keys toolbar's two rows
  and the Keys and Validation card headers. A mockup should never draw a clipped label. The one
  control that does give up width is the Keys card's search field (down to its 150 px floor): a
  field scrolls the text inside it, and the card between its two fixed-width neighbours can be
  narrower than the field's 190 px maximum — the button beside it wraps instead.
- The theme picker, the diagnostics button and all six sidebar items are keyboard-reachable. The
  theme picker changes the theme immediately; it does not need a Save button, and no utility view
  has one.
- The Installer's write confirmation is a native warning dialog, not a custom page. It names the
  volume, states that `EFI` and `com.apple.recovery.boot` are replaced, states that the drive is not
  formatted, and defaults to `Cancel`. The only authentication surface anywhere remains polkit's
  own window for `Read ACPI tables`; writing an installer asks for no secret.

---

## 15. Host actions, utility screens and planned screens

**S14 Collect hardware from this machine.** A link button with a small waveform icon in the setup
card, below the three path rows, drawn wherever the host can produce a report — Linux and
Windows. On macOS it is absent, not disabled, because no scan exists there: loading a report exported
on the target PC is the only route, and the summary panel says so. Clicking it starts the job
`Collecting hardware`: every control disables, `Cancel` appears, the window stays on `Compatibility`,
the task box names the job, and the log gets `== Collecting hardware ==` followed by `<n> hardware
sections written to <path>` when the scan finishes. On success the report row fills with the written
path, the engine checks it immediately, and the compatibility pipeline runs without a second click.
If the scan also produced ACPI tables, the ACPI row fills with the adopted folder at the same time.

The two host backends differ, and a mockup must not blend them:

- **Linux** scans in-process as the ordinary user. It reads sysfs, procfs and DMI, contacts no
  network, and elevates nothing. It takes about a second and a half, has no progress percentage, and
  must not be drawn as a download or a password prompt. The one DSDT-class path it cannot read
  (`/sys/firmware/acpi/tables/DSDT`, mode `0400 root`) is why the ACPI row stays, and why **S16**
  exists beside it.
- **Windows** downloads Hardware Sniffer at a pinned SHA-256, verifies the archive, installs the
  executable outside the package directory, and runs it with `-e -o <scan folder>`. This is a
  download, and the log says so before it starts; it can take minutes on a large machine. The tool
  writes `Report.json` and, when the firmware is readable, the ACPI tables beside it, which the app
  adopts into `<scan folder>/ACPI` and fills into the ACPI row. It must not be drawn as a local
  in-process scan, and it never asks for an administrator password: the tool runs as the user, and a
  failed table dump downgrades to no ACPI folder rather than a failed report.

**S16 Read ACPI tables.** The link button, under the ACPI row, labelled `Read ACPI tables`,
drawn on Linux and on Windows. On Linux its tooltip is `Read the firmware tables from this
machine; asks for administrator rights` — the tooltip names the cost because the cost is a system
authentication window the user was not expecting. On Windows the tooltip is `Read the firmware
tables from this machine; no administrator rights needed`, because the same read goes through the
Windows firmware table API in-process. Clicking it starts the job `Reading ACPI tables`: controls
disable, `Cancel` appears, the log gets `== Reading ACPI tables ==` and then one line per table, and
the task box names the job. There is no progress bar and no percentage: the wait is a human deciding,
not work being measured.

On success the ACPI row fills with `<report folder>/ACPI` and an ok check-circle with
`<n> .aml file(s) found`. On refusal (`acpi.refused`) or on a machine where the privileged helper is
not installed (`acpi.helper_missing`) the error card says so and the row stays a hollow dot with
`No folder chosen` — a denied authorisation is not a hardware fault and must not be drawn as one.
Those two failures belong to the Linux path; on Windows there is no helper to install and no prompt
to refuse, and an unreadable table set is `acpi.dump_failed` with the row unchanged.
In a source checkout the helper is *never* installed, because root must not execute a file the user
can edit, so this is the state a developer sees first; the card gives the one-time install command
rather than pretending.

On Linux, draw the authentication window as the desktop's own, outside the app's frame, or not at
all. It is polkit's window, not ours, and no BlackDream mockup may contain a password field: the app
never asks for a secret, which is the whole difference from the terminal route it replaces. The
Windows read opens no window at all.

**S20–S22 Installer.** A full view with two cards, in order, and a trailing stretch.

- `macOS installer` carries the hint `Apple's recovery image for the release you pick, verified chunk
  by chunk against Apple's signed chunklist.` Its first row is a 30 px `monitor` tile and a version
  combo, newest first: `macOS Tahoe 26 · latest` (the default), `macOS Sequoia 15`, `macOS Sonoma 14`,
  `macOS Ventura 13`, `macOS Monterey 12`, `macOS Big Sur 11`, `macOS Catalina 10.15`,
  `macOS Mojave 10.14`, `macOS High Sierra 10.13`. The combo is disabled while an installer job runs,
  and the last choice is remembered between launches.
- Below it, a 30 px `download` tile, a 13 px status line and a 12 px muted detail. Idle reads
  `Not downloaded yet.` over `About 1 GB. A dropped connection resumes where it stopped.` and shows
  `Download installer` (primary) beside a disabled `Cancel`. A 5 px task bar sits between the status
  row and the buttons; it is hidden when no job runs.
- Downloading sets the status to `Downloading the recovery image…` and the detail to `Starting…`,
  then to `«done» of «total» · «pct»%`; the bar fills, `Cancel` is the only enabled action, and the
  view never switches away. Cancelling reads `Cancelling…` and then `Cancelled.`. Completion reads
  `Verified · «size»` over `«release» · «product» · SHA-256 «digest»…`, and the button becomes
  `Download again`. A verified cache is reused without a network request for the selected release; a
  dropped connection resumes at the byte it stopped at, and only a fully verified image is cached.
  Images for different releases are cached side by side, so switching the picker never reuses another
  release's bytes.
- The trust chain is visible in the copy and in the log: the session and metadata are HTTPS, the
  chunklist is checked against Apple's embedded EFI-ROM key, and every image chunk is hashed while
  it is copied. An unverified byte never reaches the cache or the drive, and no mockup may show a
  progress bar labelled as verification before that check has passed.
- `USB drive` carries the hint `A mounted FAT32 volume on a USB bus. BlackDream copies files; it
  never formats the drive.` Its first row is a 30 px `usb` tile, a combo of volumes and an outline
  `Refresh`. The view scans once when first opened; drives plugged in later need `Refresh`. The
  combo never preselects a drive: with no scan yet it reads `Plug in a FAT32 USB drive, then
  refresh`; with no drive `No FAT32 USB drive found`; with drives but no choice `Choose a USB
  drive`. The note below reads `No FAT32 USB drive is mounted. Plug one in, then choose Refresh.`,
  `Looking for USB drives…`, `Choose a drive.`, or, once selected, `«device» · «free» GB free of
  «size» GB`.
- The EFI field is a 52 px path row labelled `EFI folder` with a `folder` tile and `Browse…`. It
  starts at the last built EFI folder. Its state is an icon plus tooltip: `Choose the EFI folder
  this app built.`, `A complete OpenCore EFI folder.`, or the missing paths. Browse opens the native
  directory chooser titled `Choose the built EFI folder`.
- Below the field, `EFI and com.apple.recovery.boot on the drive will be replaced. Everything else
  on it is left alone.` precedes the primary `Write installer`. The button is enabled only when a
  verified image, a complete EFI folder and an explicitly chosen volume are all present.
- Writing opens a native warning dialog: title `Write installer?`, text `Write the installer to
  «volume»?`, informative text `EFI and com.apple.recovery.boot will be replaced. Everything else
  on the drive is left alone, and the drive is not formatted.`, an accept button `Write installer`
  and `Cancel`; `Cancel` is the default. On accept the row reports the transfer, then
  `Installer written to «mount».` and a native information dialog titled `Installer written` with
  `The installer is on «mount».\n\nEject the drive before unplugging it.`
- The write stages into the target, then replaces only `EFI` and `com.apple.recovery.boot`. If the
  second replacement fails the first is restored, a cancellation leaves the previous installer
  intact, and unrelated files on the drive are never touched. Nothing is formatted, mounted or
  opened as a block device, and no administrator prompt appears.

**S23–S24 Configure EFI.** A full view: a header action slot, five cards and one inline validation
result. Nothing on this page leaves the window, mounts a disk or writes the file until `Save`.

- **Header action slot** (this page only; hidden on every other view). Right-aligned and
  vertically centred: two 22 px chips, a 4 px gap, then three 36 px buttons — outline
  `Open config…`, outline `Validate`, primary `Save`. The first chip is the validation state
  (`Not validated` neutral, `Checking…` neutral, `Valid` green, `«n» issues` amber); the second
  is the pinned schema, `OpenCore 1.0.8`, always neutral. `Save` is primary-filled but disabled
  unless the document has unsaved edits; `Open config…` is enabled whenever no task is running.
- **`config.plist` card** (full width, compact). Title `config.plist`; hint `Edit the file this
  app built. Nothing is written until you save.` One row: a 30 px `file` tile, then a 13 px
  status over an elided path (the full path is the tooltip), then right-aligned outline buttons
  `Generate serials`, `Revert`, `Show folder`. A 5 px bar is shown only while a config task runs:
  determinate while ocvalidate downloads, reading `Downloading ocvalidate · «done» of «total»`
  (or `Downloading ocvalidate · «size»` before the total is known) in the detail line, and
  indeterminate while ocvalidate runs or macserial generates serials. A muted detail line sits
  under the row. The status is one of `No built config.plist yet.`, `config.plist is open`,
  `Unsaved changes`, `Changed on disk.`, `Changed on disk; unsaved edits here.`,
  `The config.plist could not be read.` The detail is the last operation's note when there is
  one, otherwise the idle sentence for that state (§16 `configure.file.detail`).
- **`Sections` rail** (206 px fixed). Title `Sections`; no hint. A frameless list of 30 px rows,
  15 px icon then label: `All keys` on a `layers` icon, then every top-level key in document
  order with its section icon — `ACPI` pulse, `Booter` play, `DeviceProperties` sliders,
  `Kernel` layers, `Misc` gear, `NVRAM` drive, `PlatformInfo` fingerprint, `UEFI` shield, and
  `file` for any key the app does not know. Selecting a row scopes the tree to that key;
  `All keys` clears the scope. The rail is empty and disabled when no document is open.
- **`Keys` card** (stretch). Title `Keys`; hint `Select a value to edit it. Keys this build does
  not know are kept as they are.` The card header holds the 150–190 px `Search keys…` field
  with its clear button and, to its right, the 30 px outline `Presets…` button. Below it a
  toolbar of 30 px outline buttons in two rows — `Undo`, `Redo`, `Changes…` over
  `Add key`, `Add item`, `Remove`, `Up`, `Down` — because one row of eight is wider than the
  card at the window's minimum width and the labels were clipped there. `Undo` and `Redo`
  carry the edit they will reverse or repeat in their
  tooltip and are disabled when the matching stack is empty. `Changes…` reads
  `Changes («n»)…` while the document differs from the file that was opened, and opens
  `Changes since the file was opened`: a read-only tree with headers `Change` · `Key` · `Before` ·
  `After`, plus `Copy` and `Save as text…`. With no edits it shows one disabled row, spanning the
  table, reading `No edits since the file was opened.` Every cell carries its full text as a
  tooltip, because a long before/after value is elided in place. The history keeps the 100 newest
  snapshots, a save makes
  the saved bytes the new baseline, and undo/redo never re-reads or writes the file. Then the tree,
  headers `Key` · `Value` · `Type`, three columns (Key
  and Value stretch, Type fixed at 88 px), 16 px indentation, inline editing and a checkbox for
  booleans. A checked box is the accent fill with a contrasting tick, not a bare dot. A footer
  line names the selection, e.g. `Kernel > Add  ·  array  ·  15 items`, or
  reads `Select a key to edit it.`; with no file it reads `No config.plist is open.` The tree
  shows one disabled `No config.plist is open.` row when there is no document. The same actions
  are in the tree's context menu as `Add key`, `Add item`, `Insert preset…`, `Remove`, `Move up`,
  `Move down`. `Presets…` and `Insert preset…` are disabled while no document is open or a config
  task runs, and share one dialog: `Insert a preset` lists the 12 entries grouped by target
  (`ACPI > Patch`, `Kernel > Patch`), preselects the current `Sections` rail scope, and shows the
  chosen entry's target, description and whether it arrives enabled. The dialog hint names OpenCore
  Auxiliary Tools as the source. `Insert` appends the entry to the target array, creating
  the array if it is missing, selects the new entry, and notes `Inserted «preset».`; inserting an
  entry that already exists — ignoring only `Comment` and `Enabled` — does not duplicate it and
  notes `That preset is already in «path».` Only the document changes; `Save` still decides when
  the file is written.
- **`Selected entry` inspector** (268 px fixed). Title `Selected entry`. A 28 px type tile, the
  selected key's label (`[0]` for array items), and a muted path line (with the child count for
  a container). The control below
  depends on the type: a scalar gets a value field with `Apply`; a boolean gets one `On`
  checkbox (the checked state is the value); `data` and multiline strings get `Edit…` and open
  the text dialog; a dictionary or array says `Select a child to edit it, or use the Keys
  toolbar.` The hint under the control is `Apply writes the value into the document, not the
  file.` for a scalar, `Data is edited as hexadecimal bytes or printable text.` for data, and
  `This value has multiple lines; edit it in the text dialog.` for multiline strings. With nothing
  selected it reads `Nothing selected` over `Select a key to inspect it.`; with no file, over
  `No config.plist is open.`
- **`Validation` card** (full width). Title `Validation`; the card header carries the 28 px
  outline `Validate again`. One row: an 18 px state icon, a 13 px status and a muted note. When
  `ocvalidate` reports issues they appear below in a clickable monospace list capped at 76 px, one
  row per line exactly as ocvalidate wrote it, with the note `Select an issue to go to the key it
  names.` Selecting a row that names a key selects that key in the tree and appends
  `jumped to «path»` to the note; a line that names no single key stays selectable and explains
  that it is shown as written. States: `Not checked yet.` / `Run Validate to check the in-memory
  config with ocvalidate.` / chip `Not validated`; `Checking…` / `ocvalidate is checking the
  in-memory config.` / chip `Checking…`; `No issues found.` / `Checked in memory; the copy on disk
  is unchanged.` / chip `Valid`; `«n» issues found.` / the same note / chip `«n» issues`, with each
  `OCS:`/`OCV:` line in the list. Any edit, add, remove, move, serial write or revert bumps the
  document revision, so a verdict for the previous document disappears and the card returns to
  `Not checked yet.` — a stale pass is never shown. The app's own explanations never replace the
  validator's line and are never counted as validator errors.
- Validation runs `ocvalidate` on a temporary copy of the in-memory document. It never writes
  the file, and a pass does not imply the file on disk is saved; the note says so.
- `Save` writes atomically, keeps the previous bytes as `config.plist.bak`, and logs
  `Saved «path».` The card then says `Saved. The previous file was kept as config.plist.bak.`
  `Revert` re-reads the file and says `Reverted to the file on disk.` `Open config…` refuses
  while there are unsaved edits and says `Save or revert the current file before opening
  another.` When the file changed on disk, `Save` first asks `Overwrite config.plist?`; the
  accept button is `Overwrite` and `Cancel` is the default.
- `Remove` asks `Remove from config.plist?` with `Remove «path»?` and `The file is not changed
  until you press Save.`; `Generate serials` first picks a model in `Generate SMBIOS serials`,
  then asks `Replace SMBIOS values?` before writing serial, MLB, UUID and ROM into the document
  only. Serial values are never echoed into the engine log.
- The data dialog is `Edit data` with a monospace field and the hint `Hexadecimal bytes. Spaces
  are ignored.` A `Show as text` checkbox switches the same bytes to a text view: printable
  ASCII 0x20–0x7E appears as itself, `\` becomes `\\`, and newline, carriage return, tab and
  every other byte become `\n`, `\r`, `\t` and `\xNN`. Switching back parses the text; a lone
  backslash, an unknown escape, a malformed `\x` or a non-ASCII character keeps the view in text
  mode and shows the error instead of silently changing the bytes. `Apply` submits whichever view
  is active, and the result is always a lossless `data` value; a string value's dialog (`Edit
  text`) has no byte view.
- With no document the card reads `No built config.plist yet.`, the path line reads `Build an
  EFI folder in Build EFI, then return here.` and the detail reads `Build an EFI folder in Build
  EFI, or open any OpenCore config.plist.` `Save`, `Validate`, `Generate serials`, `Revert` and
  `Show folder` are disabled; `Open config…` stays enabled. If a build exists but its file
  cannot be read, the status is `The config.plist could not be read.`, the path is that file and
  the detail is the read error (`The file could not be read: «detail»`); the idle fallback is
  `Open another config.plist, or build the EFI folder again.`
- No `Reset to preset`, `Update Center`, `Base Configs`, or `EFI Backups`, and no standalone
  ASCII↔HEX mode switch in the editor chrome. 3.3 edits one document with one tree and adds only
  the curated 12-entry preset dialog and the in-dialog text view; the reference mockup's wider
  ancillary products are not part of BlackDream.

**S17 Settings.** A full view, not a modal. Four cards in two rows.

- `Appearance` (left, stretch 2) carries one control: a `Theme` label and a `System` / `Light` /
  `Dark` combo. The change applies immediately, is stored in `QSettings` under `appearance/mode`,
  and the hint says `Follows the system by default. Changes apply immediately.` The combo is the
  only theme control in the app: there is no header button, and no Save or Apply button. `View >
  Toggle Theme` flips between an explicit light and dark theme; the combo is how `System` is
  restored.
- `About` (right, stretch 3) is S11: `BlackDream <version>` at 18 px / 800, the graphical-front-end
  paragraph, `BlackDream is MIT licensed. The vendored engine keeps its BSD-3-Clause license.`, and
  `No report is uploaded; the engine only downloads the artifacts a build needs.` No links.
- `Storage` (left, stretch 3) shows `Artifact cache` and `Runtime tools` with their 28 px tile,
  caption and selectable wrapped path. Read-only; no Browse and no Clear.
- `Downloads and safety` (right, stretch 3) carries three icon rows: `Pinned SHA-256` (downloads are
  verified before use), `Folder only` (writes an EFI folder, never mounts or repairs a partition),
  `No account` (no telemetry, no update check). These are statements, not toggles.

No mirrors, proxies, telemetry, update-check, language or launch-at-login controls exist, and a
mockup must not invent them.

**S11 About.** The About card inside Settings, described above. It is no longer a modal.

**S18 Help.** A full view with five cards. `Quick start` is a six-row list with 28 px tiles:
`Make the installer`, `Load a report`, `Choose a release`, `Check compatibility`, `Build the folder`,
`Configure the EFI`; each row is a 13 px title over a 12 px muted sentence, and the hint reads
`Six steps across the three sections in the sidebar.` `Keyboard shortcuts` is a two-column list of
action and keycap: `Search devices`, `Open a report`, `Installer`, `Build EFI`, `Configure EFI`,
`Compatibility`, `Build`, `Logs`, `Settings`, `Help`, `Quit`.
The keycap uses `Ctrl` (`⌘` on macOS) and `F1` for Help. `Troubleshooting` is four icon rows about
the red card, a refused ACPI read, a rejected report and saving the log. `Diagnostics` explains that
the copied summary and the bundle contain the app version, platform, theme, the session log, the
crash report and the last validation result, that nothing is uploaded, and that serial, MLB, UUID
and ROM values are redacted. Its `Copy environment info` button writes the scrubbed summary to the
clipboard, its `Save diagnostic bundle…` button opens `Save a diagnostic bundle`, and the muted note
changes from `Nothing has been copied or saved.` to `Copied to the clipboard.` or
`Saved to «path». Nothing was uploaded.` The bundle dialog lists one checkable row per entry —
`environment.txt`, `engine.log`, the newest crash report, `validation.txt`, `preflight.txt`,
`report-summary.txt` (key names only) and `Report.json`, the last two unchecked by default — over a
monospace preview of the exact text that will be written, and `Save bundle…` writes a `.txt` or
`.zip`. `Report.json` is included only when the user ticks it. No external links.

**S32 First-boot checklist.** The fifth `Help` card, full width below the two rows, titled
`Before the first boot` with the hint `Advice for the first attempt. BlackDream never boots,
installs or writes firmware.` Its six `_InfoRow`s are the six `first_boot.STEPS` in order — `Use a
spare USB drive`, `Check firmware settings`, `Keep a way back`, `Expect the OpenCore picker`, `Use
verbose boot for the first run`, `Plan recovery` — each with a 28 px tile in `usb`, `gear`, `clock`,
`logs`, `book`, `shield`. The card ends with an `outline` `Copy the checklist` button beside a muted
note that starts `Nothing has been copied.` and becomes `Copied to the clipboard.`. The clipboard
text is the six title/body pairs separated by blank lines and ends with `This is advice. BlackDream
has no boot button and writes no firmware.` There is no button here that boots, restarts, writes
NVRAM or touches firmware, and a mockup must not add one.

**S19 Donate.** A full view. `Support the project` runs full width: `BlackDream is free and MIT
licensed. It has no account, no telemetry and no ads.` Below it is a 2 × 2 grid of cards, each with
a 28 px icon tile in its header: `Test on real hardware` (`monitor`), `Send a compatibility report`
(`file`), `Share the app` (`share`), `Funding` (`heart`). The first three give ways to help without
money. `Funding` says `Donation links are not open yet. No payment button is shown until there is a
page behind it.` — and there is no payment button, field, tier or licence key anywhere on the view.
No funding URL exists yet; a mockup that invents one is wrong.

**S28 Release matrix.** `Compare releases…` sits alone in a row under the version combo, objectName
`link`, and is disabled until an analysis has finished and the picker has options. The dialog is
920 × 500: a `rowTitle` heading `«n» device«s» across «n» release«s»`, one wrapped `rowBody` line that
leads with *Each cell is the same status the device table would show for that release.* and ends
with `release_matrix.BOUNDARY`, then a flat `configTree` table — `Device` fixed at 200 px, `Class`
fixed at 76 px, one column per selectable release at `max(104, name + 24)` px and labelled with the
release name, which is also the header's tooltip; the grid scrolls sideways per pixel rather than
eliding a device name. Cells carry
`verdicts.target_status`'s label in the same `_STATUS_TONE` colour the `Status` column of the device
table uses — a 15 %-alpha background wash alone cannot carry a verdict — and only `unsupported`
(`rowFailBg`) and `limited` (`rowWarnBg`) are tinted; `supported` and `unknown` stay on the row
background, because an absence is not a warning. A cell tooltip is the status detail plus its
recommendation. With no
graded device the table shows one inert row, `No graded device to compare.`. `Copy` and
`Save as text…` export the same grid as tab-separated lines and repeat the boundary last. There is no
re-grade, no checkbox and no Apply: the dialog cannot change what the engine said.

**S29 Report comparison.** `Compare reports…` is a `link` in the fields card below the three pickers,
disabled with no report on disk or while a job runs. `QFileDialog.getOpenFileName` starts in the
current report's folder with `Hardware reports (Report.json *.json);;All files (*)`. Both files are
read as stored JSON — never re-analysed — and a file that is not a JSON object is refused by the red
error card with `One of the reports could not be read as a JSON object.`, not by a dialog that shows
half a comparison. The 860 × 500 dialog names both sides (`«before» → «after»`), counts
`«n» hardware change«s» · «n» recorded compatibility change«s» · «n» unchanged` — each noun agreeing
with its own number — prints `report_compare.BOUNDARY`, and lists changes under `Change` `Section`
`Device` `Detail`. Device names are the report's own keys, the same strings the `Detected devices`
table shows, and every device a report records is compared, graded or not: a freshly collected report
carries no verdict at all, and hardware that was never graded is still hardware. The four
kinds stay visibly different: `Added` and `Removed` are devices, `Hardware` is a change in one of the
identity and topology fields (`Processor Name`, `Manufacturer`, `Vendor`, `Device ID`,
`Subsystem ID`, `Subsystem`, `PCI Path`, `Device Type`), and `Reading` is the same hardware whose
stored compatibility verdict differs. `Copy` and `Save as text…` write the same split, with
`Devices before: «n»` and `Devices after: «n»` in the header and the boundary last. No row is marked
better or worse, and neither report is re-graded.

**S30 Profiles.** `Profiles…` is the second `link` in the fields card and is enabled while idle even
with no report, because an empty list is a truthful answer. The 800 × 460 dialog shows
`Local profiles on this machine`, the hint that a profile stores no serial, MLB, UUID or ROM value,
and a `configTree` table of `Name` `Report` `Release` `EFI folder` with the two paths as tooltips.
`Save current` prompts `Save a profile` / `Profile name` and writes the report path, the current EFI
folder, the selected release name and a local ISO timestamp; `Rename…` refuses a name already taken;
`Remove` asks `Remove this profile?` and says the report and folder stay on disk. `Use` is the only
`primary` button and is disabled with no selection; double-clicking a row is the same action. The
muted note reports `Saved «name».` / `Renamed «before» to «after».` / `Removed «name».` and starts as
`Nothing has been copied or saved.` Applying a profile sets a report and then the release once the
version options exist; a profile whose report has moved is refused with its path and changes nothing
else. The store is `profiles.json` in the state folder, written atomically, five fields per record —
a sixth field carrying an identity value is a bug, not a feature.

**S31 Build history.** `History…` is a `chip` in the `Build progress` card header, beside the step
label. The 900 × 480 dialog lists `Builds recorded on this machine`, newest first, under
`When` `Release` `Result` `Output` `Folder` `Manifest`. `When` is the recorded instant in local
`YYYY-MM-DD HH:MM`; `Result` is the stored `succeeded` / `failed` / `cancelled` capitalised; `Folder`
re-checks the path on screen and answers `Folder present` or `Folder missing`; `Manifest` answers
`Recorded`, `Missing` or `Not recorded` after looking both inside the build root and beside it. A
vanished folder is *shown* as missing — the row is never rewritten, pruned or hidden, and opening it
is disabled rather than attempted. `Open folder` needs a live folder; `Copy history` and
`Save as text…` export one tab-separated line per build. With nothing recorded the table shows one
inert row, `No builds have been recorded yet.` Writes are capped at 100 entries in
`build-history.jsonl`, and a history that cannot be written is a warning in the engine log, never a
failed build.

**S33 Schema preview.** `Schema preview…` is an `outline` button in the `Validation` card header,
beside `Validate again`, and is disabled without an open document or while the config runner is busy.
It starts the job `Previewing a schema migration`, shows the indeterminate bar with
`Comparing config.plist with the pinned OpenCore sample…`, and puts the document through
`schema_preview.compare` against the pinned OpenCore 1.0.8 sample: keys the sample has and the file
does not, keys the file has and the schema does not, and keys whose plist type differs. The 880 × 520
dialog reads `Pinned schema: OpenCore «version»`, states that this is a reading and not a repair,
counts the three finding kinds, and lists the findings themselves under `Change` `Key` `Current`
`Pinned`, so the counts line and the rows can never disagree. `Key` is measured against the font
the platform actually renders with and sized to the longest path, up to 520 px, because an elided
key is a different key; `Current` and `Pinned` share what is left.
A projection
is built by copying only scalars and empty containers, so a missing array or dict is named rather
than invented; if it adds anything, `ocvalidate` runs on that projection in the worker and its own
summary and lines appear below the table, unchanged and unrecounted. If the projection adds nothing,
the line reads `Validator not run: the projection adds no keys.` `Copy` and `Save as text…` export
the review, and the caveat and boundary lines are part of the text. Closing the dialog writes
`Schema preview closed. Nothing was written to config.plist.` into the config note. There is no
`Migrate`, `Apply` or `Fix` button anywhere in it, and the file on disk is untouched.

**S34 Dependency advisories.** `Dependencies…` is an `outline` button with the `link` icon in the
same `Validation` header, and — like `Schema preview…` — disabled without an open document or while
the config runner is busy. It starts no job: the rules are arithmetic over the plist, so the answer is
on screen before a worker thread could report back, and it is computed from a copy of the document,
never from the live one. The 860 × 520 dialog is titled `Dependency advisories` and opens with the
file it read, the advisor's own summary line, `Checked against «release».` from the version picker
(or `Checked without a macOS release.` when no report is loaded), and the boundary sentence the export
repeats.

Rows arrive in the advisor's order — errors first, then the confident warnings — under `Severity`
`Where` `Trigger`, with `Severity` fixed at 82 px, `Where` interactive at 300 px and `Trigger`
stretching. The word is coloured (`Error` fail red, `Warning` warn amber, `Note` accent) and the full
`Where` and `Trigger` text is in each cell's tooltip, because an elided key path is a different key.
Selecting a row fills seven caption/value pairs: `Trigger`, `Evidence`, `Key path` (the same
`A > B > C` spelling the `Changes…` dialog uses), `Confidence`, `Advice`, `Rule`, `Source`. `Source`
is a `file:line` inside this repository, and it is the reason the column exists — an advisory nobody
can check is a guess. With nothing to say the table shows one inert row, `No advisories.`

`Go to key` closes the dialog and selects that path in the `Keys` tree, and the config note reads
`Jumped to «path».`; closing without jumping writes `Dependencies checked. Nothing was written to
config.plist.` `Dismiss` hides one advisory hereafter and `Restore` brings it back; both rewrite
`advisor-dismissals.json` in this app's own state directory and say so in the line below the table,
`Kept in «name», not in config.plist.` A dismissal is keyed on the ruleset number, the rule and the
key path with list indices dropped, so it survives the reorder it asked about and a ruleset change
stops honouring it. The `Show dismissed «n»` checkbox is disabled while nothing is dismissed, and
ticking it lists the hidden rows again — a hidden advisory is never deleted. `Copy` and
`Save as text…` export every advisory, dismissed or not, with the boundary line and any
`Not checked: «note»` sentence. There is no `Fix`, `Apply` or `Reorder` button anywhere in it.

**S12 Device & kext overrides** *(concept only)*. Appears between S3 and Build. Same window; the
Devices table gains a per-kext checkbox column and a second table `Kexts` (name, version range, why
it was selected). A `Reset to automatic` button restores the engine's choices. Nothing here may
imply the user can enable an unsupported GPU — overrides narrow the build, they do not defeat the
fatals.

**S13 SMBIOS / serial editor** *(concept only)*. A collapsible section under the version combo:
`SMBIOS model` (combo, pre-filled by the engine), `Serial`, `Board serial`, `System UUID`, `ROM`.
Defaults are generated; the fields exist so a user can reuse a known-good triple. `Generate new`
re-rolls. Serials must never be echoed into the log pane.

**S15 First run** *(concept only)*. The very first Build downloads roughly 25 MB of OpenCore and
kexts. Show S7 with the transfer line and the first stage `spinner`, plus one log line naming each
artifact as it is verified against its pinned digest. No modal, no "welcome".

---

## 16. Allowed strings (machine-readable)

Generated by reading `src/blackdream/ui/main_window.py`, `src/blackdream/ui/theme.py`,
`src/blackdream/core/verdicts.py`, `src/blackdream/core/pipeline.py`,
`src/blackdream/core/job_runner.py`, `src/blackdream/core/installer.py`,
`src/blackdream/core/config_editor.py`, `src/blackdream/core/dependency_advisor.py`,
`src/blackdream/hardware/acpi.py` and `src/ocengine/fatal.py`
on 2026-10-24. Paste this block into the mockup tool and require every visible string to appear in
it. `«…»` marks a value the code fills in at runtime — invent a plausible one, never a new label.

```json
{
  "window": {
    "title": "BlackDream",
    "frameless": false,
    "default_size": [
      1440,
      940
    ],
    "minimum_size": [
      1160,
      700
    ]
  },
  "menus": [
    "File",
    "View",
    "Help"
  ],
  "views": [
    "Installer",
    "Compatibility",
    "Build EFI",
    "Logs",
    "Configure EFI",
    "Settings",
    "Help",
    "Donate"
  ],
  "sections": [
    "Installer",
    "Build EFI",
    "Configure EFI"
  ],
  "build_views": [
    "Compatibility",
    "Build EFI",
    "Logs"
  ],
  "sidebar": {
    "brand": "BlackDream",
    "hint": "OpenCore, made simple.",
    "workflow_label": "WORKFLOW",
    "secondary": [
      "Settings",
      "Help",
      "Donate"
    ]
  },
  "nav_icons": {
    "Installer": "download",
    "Build EFI": "build",
    "Configure EFI": "sliders",
    "Compatibility": "pulse",
    "Logs": "logs",
    "Settings": "gear",
    "Help": "help",
    "Donate": "heart"
  },
  "chrome_icons": {
    "settings": "gear",
    "help": "help",
    "report": "file",
    "acpi": "layers",
    "output": "folder",
    "search": "search",
    "build": "build",
    "reveal": "folder",
    "save": "save",
    "copy": "copy",
    "details": "copy",
    "why": "info",
    "scan": "wave",
    "class_fallback": "layers",
    "donate": "heart",
    "share": "share",
    "safety": "shield"
  },
  "page": {
    "titles": [
      "Make a macOS Installer",
      "Hardware Compatibility",
      "Build EFI Folder",
      "Engine Log",
      "Configure EFI",
      "Settings",
      "Help",
      "Support BlackDream"
    ],
    "subtitles": [
      "Download Apple's recovery image and write it to a USB drive.",
      "Review what macOS can run on this machine, then build the EFI folder.",
      "Watch the engine work and open the folder when it is done.",
      "Every message the engine reported, in order.",
      "Edit the built config.plist, check it with ocvalidate, and generate SMBIOS serials.",
      "Appearance, storage and the rules this app works under.",
      "How the workflow fits together, and what to do when a check fails.",
      "Ways to help that do not cost anything."
    ]
  },
  "search": {
    "placeholder": "Search devices…",
    "shortcut": [
      "Ctrl K",
      "⌘ K"
    ],
    "hidden_views": [
      "Installer",
      "Build EFI",
      "Logs",
      "Configure EFI",
      "Settings",
      "Help",
      "Donate"
    ]
  },
  "card_titles": [
    "macOS installer",
    "USB drive",
    "macOS version",
    "Detected devices",
    "Device details",
    "Build progress",
    "Engine log",
    "Folder checks",
    "config.plist",
    "Sections",
    "Keys",
    "Selected entry",
    "Validation",
    "Appearance",
    "About",
    "Storage",
    "Downloads and safety",
    "Quick start",
    "Keyboard shortcuts",
    "Troubleshooting",
    "Diagnostics",
    "Before the first boot",
    "Support the project",
    "Test on real hardware",
    "Send a compatibility report",
    "Share the app",
    "Funding"
  ],
  "card_hints": [
    "No report loaded yet.",
    "Detected «n» device«s» from your hardware report.",
    "No devices were graded from this report.",
    "Step, transfer and timing from the engine.",
    "Building your OpenCore EFI folder.",
    "The EFI folder is ready.",
    "Read the built folder before you try to boot it.",
    "Follows the system by default. Changes apply immediately.",
    "Where downloads and the tools that read firmware live.",
    "Six steps across the three sections in the sidebar.",
    "Apple's recovery image for the release you pick, verified chunk by chunk against Apple's signed chunklist.",
    "A mounted FAT32 volume on a USB bus. BlackDream copies files; it never formats the drive.",
    "Edit the file this app built. Nothing is written until you save.",
    "Select a value to edit it. Keys this build does not know are kept as they are.",
    "Advice for the first attempt. BlackDream never boots, installs or writes firmware."
  ],
  "empty_notes": [
    "Load a report to see this machine's devices and what macOS does with them.",
    "The engine rejected this report before grading any device."
  ],
  "fields": {
    "labels": [
      "Hardware report (Report.json)",
      "ACPI tables folder",
      "Output folder",
      "EFI folder"
    ],
    "button": "Browse…",
    "editable": false
  },
  "field_icons": {
    "empty": "dot",
    "ok": "check-circle",
    "warn": "alert-circle",
    "error": "x-circle"
  },
  "field_state_tooltips": [
    "No path chosen",
    "No folder chosen",
    "Folder does not exist",
    "No .aml files here",
    "«n» .aml file(s) found",
    "Not writable",
    "Exists and is writable",
    "Will be created",
    "Replaces a previous BlackDream build",
    "Folder is not empty",
    "Checking…",
    "Graded",
    "Rejected",
    "Choose the EFI folder this app built.",
    "A complete OpenCore EFI folder."
  ],
  "links": {
    "buttons": [
      "Collect hardware",
      "Read ACPI tables",
      "View details",
      "Hide details",
      "Copy details",
      "Show engine verdict",
      "Compare reports…",
      "Profiles…",
      "Compare releases…"
    ],
    "tooltips": [
      "Scan this machine and write a Report.json",
      "Scan this machine with Hardware Sniffer; downloads and runs the verified tool",
      "Read the firmware tables from this machine; asks for administrator rights",
      "Compare this report with another one, without re-grading either",
      "Save this machine's report path and EFI folder as a local profile",
      "See every graded device against every selectable macOS release"
    ]
  },
  "buttons": [
    "Check compatibility",
    "Build EFI folder",
    "Cancel",
    "Open EFI folder",
    "Save log…",
    "Run checks",
    "Verify manifest",
    "Save report…",
    "Download installer",
    "Download again",
    "Refresh",
    "Write installer",
    "Save",
    "Validate",
    "Validate again",
    "Generate serials",
    "Open config…",
    "Undo",
    "Redo",
    "Changes…",
    "Revert",
    "Show folder",
    "Add key",
    "Add item",
    "Presets…",
    "Remove",
    "Up",
    "Down",
    "Apply",
    "Edit…",
    "Copy environment info",
    "Save diagnostic bundle…",
    "History…",
    "Schema preview…",
    "Dependencies…",
    "Copy the checklist",
    "Save current",
    "Use",
    "Rename…",
    "Open folder",
    "Copy history",
    "Save as text…",
    "Copy"
  ],
  "log_filter": [
    "Info and above",
    "Warnings and above",
    "Everything"
  ],
  "folder_checks": {
    "title": "Folder checks",
    "hint": "Read the built folder before you try to boot it.",
    "buttons": [
      "Run checks",
      "Verify manifest",
      "Save report…"
    ],
    "tooltips": [
      "Check required files and every path config.plist references",
      "Compare the folder with the manifest written at build time"
    ],
    "idle": "Not checked yet.",
    "boundary": "These checks read the folder. They do not test firmware, hardware or whether macOS boots.",
    "no_folder": "No EFI folder to check.",
    "no_folder_note": "Build an EFI folder, or choose one on the Installer page.",
    "unreadable": "This folder cannot be read.",
    "no_manifest": "There is no manifest to verify.",
    "clean": "No issues detected by these checks.",
    "counts": "«n» error«s», «n» warning«s»",
    "files_note": "Read «n» file«s». These checks do not test firmware, hardware or whether macOS boots.",
    "manifest_match": "Every file matches the recorded manifest.",
    "manifest_counts": "«n» missing, «n» changed, «n» added",
    "manifest_note": "A match proves these files are the ones recorded at build time. It does not prove the folder boots.",
    "save_title": "Save the folder report",
    "saved": "Report saved to «path»"
  },
  "file_dialogs": {
    "report": {
      "caption": "Hardware report",
      "filter": "Hardware reports (Report.json *.json);;All files (*)"
    },
    "acpi": {
      "caption": "ACPI tables folder"
    },
    "output": {
      "caption": "Output folder"
    },
    "efi": {
      "caption": "Choose the built EFI folder"
    },
    "config": {
      "caption": "Open a config.plist",
      "filter": "Property lists (*.plist);;All files (*)"
    }
  },
  "table_headers": [
    "Device",
    "Class",
    "macOS support",
    "Status"
  ],
  "table_header_count": 4,
  "table_geometry": {
    "class_width": 72,
    "device_min_width": 165,
    "support_min_width": 90,
    "support_max_width": 266,
    "status_min_width": 100,
    "row_height": 29,
    "minimum_height": 150
  },
  "class_labels": [
    "CPU",
    "GPU",
    "Audio",
    "Ethernet",
    "Wi-Fi",
    "Storage",
    "USB",
    "Bluetooth",
    "SD card",
    "Display",
    "Biometric"
  ],
  "class_icons": {
    "CPU": "cpu",
    "GPU": "gpu",
    "Audio": "speaker",
    "Ethernet": "globe",
    "Wi-Fi": "wifi",
    "Storage": "drive",
    "USB": "usb",
    "Bluetooth": "bluetooth",
    "SD card": "sd",
    "Display": "monitor",
    "Biometric": "fingerprint",
    "other": "layers"
  },
  "status_words": {
    "keys": [
      "supported",
      "limited",
      "unsupported",
      "unknown"
    ],
    "labels": [
      "Supported",
      "Limited support",
      "Not supported",
      "Not graded"
    ],
    "icons": {
      "supported": "check-circle",
      "limited": "alert-circle",
      "unsupported": "x-circle",
      "unknown": "dot"
    },
    "icon_size": 15,
    "row_tint": {
      "unsupported": "rowFailBg",
      "limited": "rowWarnBg"
    },
    "tooltip": "«detail» «recommendation»"
  },
  "statuses": {
    "supported": {
      "label": "Supported",
      "details": [
        "Supported up to «macOS name».",
        "Supported on «macOS name»."
      ],
      "recommendations": [
        "Choose a release inside the supported range.",
        "No action needed: this device runs natively on the selected release."
      ]
    },
    "limited": {
      "label": "Limited support",
      "details": [
        "Limited support on «macOS name»: runs through OpenCore Legacy Patcher.",
        "Limited support on «macOS name»: graphics run through WhateverXe.",
        "Supported up to «macOS name» through WhateverXe.",
        "Limited support on «macOS name»: graphics run through NullMoth.",
        "Supported up to «macOS name» through NullMoth."
      ],
      "recommendations": [
        "This release needs OpenCore Legacy Patcher for this device.",
        "Install WhateverXe Graphics «version» after the first boot; keep WhateverGreen disabled.",
        "Install the NullMoth NVIDIA driver «version» after the first boot; its kexts load from /Library, not from this EFI."
      ]
    },
    "unsupported": {
      "label": "Not supported",
      "details": [
        "The engine found no macOS release that supports this device.",
        "Not supported on «macOS name». The engine supports this device from «macOS name».",
        "Not supported on «macOS name». Last native support is «macOS name»."
      ],
      "recommendations": [
        "A different device is needed: no macOS release supports this one.",
        "Choose «macOS name» or newer.",
        "Choose «macOS name» or earlier for native support."
      ]
    },
    "unknown": {
      "label": "Not graded",
      "details": [
        "The engine did not grade this device.",
        "The engine did not grade this device for a specific release."
      ],
      "recommendations": [
        "Check that the report carries this device's details.",
        "Select a macOS version to see this device's status."
      ]
    }
  },
  "verdicts": [
    "Up to «macOS name»",
    "«macOS name» to «macOS name»",
    "Maximum support up to «macOS name»",
    "Unsupported",
    "Unchecked"
  ],
  "summary": {
    "empty": "Load a Report.json, or collect hardware from this machine.",
    "empty_windows": "Load a Report.json, or scan this machine with Hardware Sniffer.",
    "empty_no_scan": "Load a Report.json exported by Hardware Sniffer on the target PC.",
    "loading": "Checking «file»…",
    "failed": "Compatibility check failed.",
    "failed_note": "No devices were graded. Choose another Report.json and check it again.",
    "native": "Native support: «ranges»",
    "patched": "Support: «ranges»",
    "oclp": "With OpenCore Legacy Patcher: «ranges»",
    "note": "Support ranges come from the report's own compatibility data.",
    "note_selected": "Status is computed for «macOS name».",
    "note_suggested": "The engine suggests «macOS name».",
    "note_oclp": "Needs OpenCore Legacy Patcher."
  },
  "version_picker": {
    "label": "macOS version",
    "item": "«macOS name»",
    "item_badged": "«macOS name»  ·  «badges»",
    "badges": [
      "suggested",
      "needs OCLP"
    ],
    "badge_join": ", ",
    "spaces_before_badges": 2
  },
  "details": {
    "keys": [
      "Device",
      "Class",
      "macOS support",
      "Vendor",
      "Device ID",
      "Subsystem",
      "Current status",
      "Recommendation"
    ],
    "placeholder": "Select a device to see the engine's verdict for it.",
    "empty_value": "—"
  },
  "progress": {
    "step_position": "Step «n» of «total»",
    "step_not_started": "Not started",
    "step_counts": "«done»/«total»",
    "percent": "«pct»%",
    "metrics": [
      "Elapsed time",
      "Downloaded",
      "Speed"
    ],
    "metric_icons": {
      "elapsed": "clock",
      "downloaded": "download",
      "speed": "gauge"
    },
    "metric_idle": {
      "downloaded": "0 B"
    },
    "task_idle": [
      "Waiting to start",
      "Nothing is downloading."
    ],
    "task_ready": [
      "Ready to build",
      "Choose a macOS version, then build the EFI folder."
    ],
    "task_running": [
      "Running…",
      "Starting…",
      "Cancelling…"
    ],
    "task_done": [
      "EFI folder ready"
    ],
    "task_cancelled": "«step» cancelled.",
    "task_failed": "«step» failed.",
    "transfer": [
      "«done» of «total»",
      "«done» of «total» · «pct»%",
      "«size» downloaded"
    ],
    "rate_units": [
      "KB/s",
      "MB/s",
      "—"
    ]
  },
  "stage_icons": {
    "done": "check-circle",
    "running": "spinner",
    "pending": "dot",
    "failed": "x-circle",
    "cancelled": "minus"
  },
  "stage_states": [
    "done",
    "running",
    "pending",
    "failed",
    "cancelled"
  ],
  "stage_time": "«elapsed»",
  "build_stages": [
    "Copying EFI base to results folder",
    "Applying ACPI patches",
    "Copying kexts and snapshotting to config.plist",
    "Generating config.plist",
    "Cleaning up unused drivers, resources, and tools"
  ],
  "jobs": [
    "Checking compatibility",
    "Collecting hardware",
    "Reading ACPI tables",
    "Selecting patches and kexts",
    "Downloading OpenCore and kexts",
    "Writing the EFI folder",
    "Downloading macOS recovery",
    "Writing the installer",
    "Finding USB drives",
    "Validating config.plist",
    "Generating SMBIOS serials",
    "Previewing a schema migration"
  ],
  "scan_stages": [
    "Gathering PCI devices",
    "Gathering motherboard information",
    "Gathering BIOS information",
    "Gathering CPU information",
    "Gathering GPU information",
    "Gathering monitor information",
    "Gathering network information",
    "Gathering sound information",
    "Gathering USB controllers",
    "Gathering input devices",
    "Gathering storage controllers",
    "Gathering biometric information",
    "Gathering bluetooth information",
    "Gathering sd controller information",
    "Gathering system devices"
  ],
  "log": {
    "title": "Engine log",
    "filters": [
      "Info and above",
      "Warnings and above",
      "Everything"
    ],
    "tags": [
      "INFO",
      "WARN",
      "ERROR",
      "DEBUG"
    ],
    "lines": [
      "== «step» ==",
      "Graded «n» devices",
      "SMBIOS model: «model»",
      "«step» finished in «s» s",
      "«step» cancelled",
      "«step» failed",
      "«n» earlier log lines were dropped",
      "Done: «path»",
      "«count» hardware sections written to «path»",
      "«count» ACPI tables read from firmware",
      "Saved «path».",
      "config.plist: «summary»"
    ],
    "copy_tooltip": "Copy the log",
    "save_caption": "Save log",
    "save_filter": "Log files (*.log);;All files (*)"
  },
  "dialogs": {
    "engine_verdict": {
      "title": "Engine verdict",
      "body": "«device»\n\nEngine verdict: «support»\nStatus: «status»\n\n«detail»\n«recommendation»"
    },
    "write_installer": {
      "title": "Write installer?",
      "text": "Write the installer to «volume»?",
      "informative": "EFI and com.apple.recovery.boot will be replaced. Everything else on the drive is left alone, and the drive is not formatted.",
      "accept": "Write installer"
    },
    "installer_written": {
      "title": "Installer written",
      "body": "The installer is on «mount».\n\nEject the drive before unplugging it."
    },
    "remove_key": {
      "title": "Remove from config.plist?"
    },
    "overwrite_config": {
      "title": "Overwrite config.plist?"
    },
    "edit_value": {
      "titles": [
        "Edit data",
        "Edit text"
      ]
    },
    "add_key": {
      "title": "Add a key"
    },
    "generate_serials": {
      "title": "Generate SMBIOS serials"
    },
    "replace_serials": {
      "title": "Replace SMBIOS values?"
    },
    "insert_preset": {
      "title": "Insert a preset"
    }
  },
  "error_card_suffix": "code: «code»",
  "non_recoverable_line": "<i>This machine cannot run macOS as configured.</i>",
  "cards": [
    {
      "code": "cpu.no_sse4",
      "title": "CPU lacks the SSE4.x instruction set",
      "detail": "macOS requires SSE4.2 on every supported CPU. This processor predates that.",
      "bullets": [
        "Every Intel CPU from Nehalem onward, and every AMD CPU macOS targets, supports SSE4.x.",
        "If this report came from a virtual machine, pass through host CPU features and re-export."
      ],
      "non_recoverable": true
    },
    {
      "code": "gpu.absent",
      "title": "No GPU found in the hardware report",
      "detail": "The report contains no graphics device, so no display can be driven during install.",
      "bullets": [
        "Re-export the hardware report with the GPU information included.",
        "On a desktop, confirm the display is plugged into the GPU you intend to boot from."
      ],
      "non_recoverable": false
    },
    {
      "code": "gpu.unsupported",
      "title": "No macOS-compatible GPU on this system",
      "detail": "You cannot install macOS without a supported GPU. Every device in the report was rejected: «device names»",
      "bullets": [
        "Check the Compatibility screen for which device was rejected and why.",
        "A supported discrete GPU, or an iGPU from Iron Lake through Ice Lake, is required."
      ],
      "non_recoverable": true
    },
    {
      "code": "storage.absent",
      "title": "No storage controller found in the hardware report",
      "detail": "Without a storage controller the internal drives are invisible to the installer.",
      "bullets": [
        "Re-export the hardware report with storage controller information.",
        "On Intel 11th gen and newer, disable Intel VMD in BIOS first."
      ],
      "non_recoverable": false
    },
    {
      "code": "storage.intel_vmd",
      "title": "Intel VMD storage controller is enabled",
      "detail": "macOS has no driver for Intel VMD, so the NVMe drives behind it are unreachable.",
      "bullets": [
        "Disable Intel VMD in the BIOS storage/VMD setup menu.",
        "Switch the SATA controller mode to AHCI if that option is exposed.",
        "Re-export the hardware report afterwards."
      ],
      "non_recoverable": false
    },
    {
      "code": "storage.no_compatible",
      "title": "No macOS-compatible storage controller",
      "detail": "Every PCI storage controller with attached drives in this report is unsupported.",
      "bullets": [
        "The boot disk must sit behind a storage controller macOS already drives.",
        "Western Digital NVMe drives are commonly a safe choice."
      ],
      "non_recoverable": false
    },
    {
      "code": "report.rejected",
      "title": "This hardware report cannot be used",
      "detail": "«file name»: «validator reason»",
      "bullets": [
        "Collect the hardware report again, or export a fresh one with Hardware Sniffer."
      ],
      "non_recoverable": false
    },
    {
      "code": "pipeline.not_configured",
      "title": "Select a hardware report first",
      "detail": "«no report is loaded»",
      "bullets": [
        "Collect hardware from this machine, or load a Report.json, before building."
      ],
      "non_recoverable": false
    },
    {
      "code": "pipeline.build_not_ready",
      "title": "The build is missing something it needs",
      "detail": "No DSDT is loaded and no ACPI table folder was supplied.",
      "bullets": [
        "Point the report at the ACPI folder inside the exported SysReport.",
        "Or press Read ACPI tables on the Compatibility view to read this machine's firmware."
      ],
      "non_recoverable": false
    },
    {
      "code": "acpi.unsupported",
      "title": "These firmware tables cannot be read from inside the app",
      "detail": "Reading the firmware tables is built into the Linux and Windows builds; this is «platform».",
      "bullets": [
        "Point the ACPI tables folder at a folder of .aml tables exported by Hardware Sniffer."
      ],
      "non_recoverable": false
    },
    {
      "code": "acpi.helper_missing",
      "title": "The helper that reads firmware tables is not installed",
      "detail": "«which paths were looked for»",
      "bullets": [
        "Install it where only root can change it: sudo install -m 0755 -o root -g root «helper» /usr/lib/blackdream/dump_acpi_tables.py",
        "then register its action: sudo cp «policy» /usr/share/polkit-1/actions/",
        "Or run the helper yourself with sudo, and point the ACPI tables folder at the directory it prints."
      ],
      "non_recoverable": false
    },
    {
      "code": "acpi.refused",
      "title": "Reading the ACPI tables was not authorised",
      "detail": "«why polkit said no»",
      "bullets": [
        "Nothing was read, written, or sent.",
        "Try again and accept the system authentication window, or point the ACPI tables folder at tables you dumped another way."
      ],
      "non_recoverable": false
    },
    {
      "code": "acpi.dump_failed",
      "title": "The firmware tables could not be read",
      "detail": "«what the helper reported»",
      "bullets": [
        "Try again. If it repeats, this machine does not expose a readable DSDT to this app.",
        "Point the ACPI tables folder at a folder of .aml tables exported by Hardware Sniffer instead."
      ],
      "non_recoverable": false
    },
    {
      "code": "acpi.timed_out",
      "title": "No answer to the authorisation window",
      "detail": "The authorisation request waited «n» s and was withdrawn.",
      "bullets": [
        "The system authentication window may be behind this one. Nothing was read; the request is safe to repeat."
      ],
      "non_recoverable": false
    },
    {
      "code": "engine.unexpected",
      "title": "The engine failed unexpectedly",
      "detail": "«ExceptionType»: «message»",
      "bullets": [
        "Retry the step. If it repeats, save the log from the Details panel before reporting it."
      ],
      "non_recoverable": false
    },
    {
      "code": "job.abandoned",
      "title": "That step stopped responding",
      "detail": "«step» exceeded its «n» s budget and is still blocked in a system call «g» s after cancellation.",
      "bullets": [
        "Its result will be ignored. New steps stay blocked until that call returns, so if the window hangs, quit and reopen the app."
      ],
      "non_recoverable": false
    },
    {
      "code": "engine.error",
      "title": "Engine error",
      "detail": "Choose a Report.json first. You can drop the file anywhere in this window.",
      "bullets": [],
      "non_recoverable": false
    },
    {
      "code": "engine.error",
      "title": "Engine error",
      "detail": "The previous step is still finishing. Its engine objects are in use, so starting another now would corrupt this session.",
      "bullets": [],
      "non_recoverable": false
    }
  ],
  "installer": {
    "cards": [
      "macOS installer",
      "USB drive"
    ],
    "releases": {
      "placeholder": "Choose a macOS version",
      "labels": [
        "macOS «name» «version»",
        "macOS «name» «version» · latest"
      ],
      "names": [
        "High Sierra",
        "Mojave",
        "Catalina",
        "Big Sur",
        "Monterey",
        "Ventura",
        "Sonoma",
        "Sequoia",
        "Tahoe"
      ],
      "versions": [
        "10.13",
        "10.14",
        "10.15",
        "11",
        "12",
        "13",
        "14",
        "15",
        "26"
      ]
    },
    "status": {
      "idle": [
        "Not downloaded yet.",
        "About 1 GB. A dropped connection resumes where it stopped."
      ],
      "verified": "Verified · «size»",
      "product": "«release» · «product» · SHA-256 «digest»…",
      "starting": "Starting…",
      "downloading": "Downloading the recovery image…",
      "writing": "Writing the installer…",
      "cancelling": "Cancelling…",
      "cancelled": "Cancelled.",
      "failed": "The installer task failed.",
      "written": "Installer written to «mount».",
      "busy": "Wait for the other task to finish before downloading."
    },
    "products": [
      "macOS recovery image",
      "recovery chunklist",
      "USB installer"
    ],
    "field": {
      "empty": "Choose the EFI folder this app built.",
      "ok": "A complete OpenCore EFI folder.",
      "missing": "That folder is not a complete OpenCore EFI: missing «paths».",
      "too_small": "«path» is too small to be OpenCore.efi."
    },
    "usb": {
      "placeholders": [
        "Plug in a FAT32 USB drive, then refresh",
        "Choose a USB drive",
        "No FAT32 USB drive found"
      ],
      "notes": [
        "No drive selected.",
        "Choose a drive.",
        "No FAT32 USB drive is mounted. Plug one in, then choose Refresh.",
        "Looking for USB drives…"
      ],
      "capacity": "«device» · «free» GB free of «size» GB",
      "replace_note": "EFI and com.apple.recovery.boot on the drive will be replaced. Everything else on it is left alone.",
      "choose_first": "Choose a drive and a complete EFI folder, and download the installer first.",
      "busy": "Wait for the other task to finish."
    }
  },
  "configure": {
    "cards": [
      "config.plist",
      "Sections",
      "Keys",
      "Selected entry",
      "Validation"
    ],
    "chips": [
      "Not validated",
      "Valid",
      "Checking…",
      "«n» issue",
      "«n» issues",
      "OpenCore «version»"
    ],
    "actions": [
      "Open config…",
      "Validate",
      "Save"
    ],
    "file": {
      "hint": "Edit the file this app built. Nothing is written until you save.",
      "buttons": [
        "Generate serials",
        "Revert",
        "Show folder"
      ],
      "status": {
        "empty": "No built config.plist yet.",
        "empty_path": "Build an EFI folder in Build EFI, then return here.",
        "unreadable": "The config.plist could not be read.",
        "open": "config.plist is open",
        "dirty": "Unsaved changes",
        "external": "Changed on disk.",
        "external_dirty": "Changed on disk; unsaved edits here."
      },
      "detail": {
        "empty": "Build an EFI folder in Build EFI, or open any OpenCore config.plist.",
        "unreadable": "The file could not be read: «detail»",
        "unreadable_idle": "Open another config.plist, or build the EFI folder again.",
        "open": "Every key is editable, and keys this build does not know are kept.",
        "dirty": "Unsaved changes are only in memory until you press Save.",
        "external": "The file changed on disk. Revert to load that version, or save to replace it."
      }
    },
    "sections": {
      "all": "All keys"
    },
    "keys": {
      "hint": "Select a value to edit it. Keys this build does not know are kept as they are.",
      "search": "Search keys…",
      "headers": [
        "Key",
        "Value",
        "Type"
      ],
      "toolbar": [
        "Undo",
        "Redo",
        "Changes…",
        "Add key",
        "Add item",
        "Remove",
        "Up",
        "Down"
      ],
      "menu": [
        "Move up",
        "Move down"
      ],
      "empty": "No config.plist is open.",
      "selection": "Select a key to edit it."
    },
    "inspector": {
      "empty": "Nothing selected",
      "empty_hint": "Select a key to inspect it.",
      "no_file": "No config.plist is open.",
      "bool": "On",
      "apply": "Apply",
      "edit": "Edit…",
      "placeholder": "Value",
      "apply_hint": "Apply writes the value into the document, not the file.",
      "data_hint": "Data is edited as hexadecimal bytes or printable text.",
      "multiline_hint": "This value has multiple lines; edit it in the text dialog.",
      "container_hint": "Select a child to edit it, or use the Keys toolbar."
    },
    "validation": {
      "unchecked": "Not checked yet.",
      "unchecked_note": "Run Validate to check the in-memory config with ocvalidate.",
      "checking": "Checking…",
      "checking_note": "ocvalidate is checking the in-memory config.",
      "checked_note": "Checked in memory; the copy on disk is unchanged.",
      "pass": "No issues found.",
      "issues": [
        "«n» issue found.",
        "«n» issues found."
      ],
      "issue_hint": "Select an issue to go to the key it names.",
      "issue_named": "«message»  ·  jumped to «path»",
      "issue_unnamed": "This line does not name one key. It is shown as ocvalidate wrote it.",
      "issue_tooltip": "Go to «path»"
    },
    "history": {
      "undo": "Undo",
      "redo": "Redo",
      "changes": "Changes…",
      "changes_count": "Changes («n»)…",
      "undo_tooltip": "Undo the last edit in memory",
      "redo_tooltip": "Redo the last undone edit",
      "changes_tooltip": "Review every edit made since the file was opened",
      "dialog_title": "Changes since the file was opened",
      "hint": "These edits live in memory. Nothing is written until you press Save, and config.plist.bak is kept when you do.",
      "headers": [
        "Change",
        "Key",
        "Before",
        "After"
      ],
      "empty": "No edits since the file was opened.",
      "copy": "Copy",
      "save": "Save as text…",
      "saved": "Saved to «path». Nothing was written into the config."
    },
    "transfer": [
      "Downloading ocvalidate · «done» of «total»",
      "Downloading ocvalidate · «size»"
    ],
    "notes": [
      "Checking config.plist with ocvalidate…",
      "Generating SMBIOS serials for «model» with macserial…",
      "Opened «name».",
      "Reverted to the file on disk.",
      "Saved. The previous file was kept as config.plist.bak.",
      "Save cancelled.",
      "The file could not be read.",
      "The file could not be saved.",
      "The config task failed.",
      "«job» cancelled.",
      "Save or revert the current file before opening another.",
      "No SMBIOS models are available.",
      "The generated values could not be applied.",
      "The generated values were not applied.",
      "Generated SMBIOS values for «model».",
      "Added «key».",
      "Added item «n».",
      "Inserted «preset».",
      "That preset is already in «path».",
      "Removed «path».",
      "Moved «path»."
    ],
    "dialogs": {
      "remove": {
        "title": "Remove from config.plist?",
        "text": "Remove «path»?",
        "note": "The file is not changed until you press Save.",
        "accept": "Remove"
      },
      "overwrite": {
        "title": "Overwrite config.plist?",
        "text": "The file changed on disk since it was opened. Overwrite it?",
        "note": "The current version on disk will be kept as config.plist.bak.",
        "accept": "Overwrite"
      },
      "edit": {
        "titles": [
          "Edit data",
          "Edit text"
        ],
        "apply": "Apply",
        "hex_hint": "Hexadecimal bytes. Spaces are ignored.",
        "hex_placeholder": "00 01 02 …",
        "text_toggle": "Show as text",
        "text_hint": "Text view. Printable ASCII is shown as text; other bytes as \\xNN escapes."
      },
      "presets": {
        "title": "Insert a preset",
        "hint": "Ready-made entries from the OpenCore Auxiliary Tools preset library, checked against the pinned OpenCore 1.0.8 schema. Nothing is written until you save.",
        "header": "Preset",
        "empty_title": "Choose a preset",
        "empty_detail": "Select a preset to see what it changes.",
        "target": "Target: «path»",
        "enabled": "Will be inserted enabled.",
        "disabled": "Will be inserted disabled; turn Enabled on to use it.",
        "accept": "Insert"
      },
      "add_key": {
        "title": "Add a key",
        "accept": "Add",
        "labels": [
          "Key",
          "Type",
          "Default"
        ],
        "default_placeholder": "Default value",
        "hint": "Suggested keys and defaults come from the pinned OpenCore 1.0.8 sample.",
        "errors": [
          "Enter a key name.",
          "That key already exists."
        ]
      },
      "serials": {
        "title": "Generate SMBIOS serials",
        "label": "Model",
        "hint": "Serials come from OpenCore's macserial. They are random, and nothing is written until you save.",
        "generate": "Generate",
        "confirm_title": "Replace SMBIOS values?",
        "confirm_text": "Write the new values for «model» into config.plist?",
        "confirm_note": "Nothing is written until you save. They replace the current serial, MLB, UUID and ROM.",
        "detail": "Serial: «serial»\nMLB: «mlb»\nUUID: «uuid»\nROM: «rom»",
        "accept": "Replace"
      }
    },
    "schema_preview": {
      "button": "Schema preview…",
      "tooltip": "Compare this file with the pinned OpenCore sample before any migration",
      "job": "Previewing a schema migration",
      "running": "Comparing config.plist with the pinned OpenCore sample…",
      "closed": "Schema preview closed. Nothing was written to config.plist.",
      "title": "Schema preview",
      "heading": "Pinned schema: OpenCore «version»",
      "hint": "This is a reading, not a repair. Nothing here is applied, and config.plist is not written.",
      "counts": "Missing: «n» · Extra: «n» · Different types: «n»",
      "headers": [
        "Change",
        "Key",
        "Current",
        "Pinned"
      ],
      "kinds": [
        "missing",
        "extra",
        "type"
      ],
      "kind_display": "«kind»",
      "empty": [
        "None",
        "No differences."
      ],
      "validator_not_run": "Validator not run: the projection adds no keys.",
      "validator_ran": "ocvalidate on the projected config: «summary»",
      "copy": "Copy",
      "save": "Save as text…",
      "save_title": "Save the schema preview",
      "save_failed": "The preview could not be saved",
      "filter": "Text files (*.txt);;All files (*)",
      "export": {
        "header": "BlackDream schema preview",
        "sections": [
          "Missing from this config",
          "Not in the pinned schema",
          "Different types"
        ],
        "marks": [
          "[MISSING] «key» = «value»",
          "[EXTRA] «key»",
          "[TYPE] «key»: «current» -> «schema»"
        ],
        "ocvalidate": "ocvalidate on the projected config",
        "not_run": "Not run: the projection adds no keys.",
        "caveat": "A key that is missing from this config may be optional or unnecessary for this machine.",
        "boundary": "This preview changes nothing. A migration would need a review and a save."
      }
    },
    "dependencies": {
      "button": "Dependencies…",
      "tooltip": "Check the kext, driver and quirk relationships this file already claims",
      "icon": "link",
      "title": "Dependency advisories",
      "minimum_size": [860, 520],
      "target": "Checked against «release».",
      "no_target": "Checked without a macOS release.",
      "boundary": "These checks read config.plist. They do not reorder kexts, do not change any quirk, and do not test firmware, hardware or whether macOS boots.",
      "headers": [
        "Severity",
        "Where",
        "Trigger"
      ],
      "severities": [
        "Error",
        "Warning",
        "Note"
      ],
      "fields": [
        "Trigger",
        "Evidence",
        "Key path",
        "Confidence",
        "Advice",
        "Rule",
        "Source"
      ],
      "empty": [
        "None",
        "No advisories."
      ],
      "all_dismissed": "Everything is dismissed. Tick Show dismissed to read them.",
      "go": "Go to key",
      "go_tooltip": "Close this dialog and select that key in the tree",
      "dismiss": "Dismiss",
      "dismiss_tooltip": "Hide this advisory hereafter, in this app's own record file",
      "restore": "Restore",
      "show_dismissed": "Show dismissed",
      "show_dismissed_count": "Show dismissed «n»",
      "kept": "Kept in «name», not in config.plist.",
      "write_failed": "The dismissals could not be saved: «detail»",
      "copy": "Copy",
      "save": "Save as text…",
      "save_title": "Save the dependency report",
      "save_failed": "The report could not be saved",
      "filter": "Text files (*.txt);;All files (*)",
      "closed": "Dependencies checked. Nothing was written to config.plist.",
      "jumped": "Jumped to «path».",
      "store": "advisor-dismissals.json",
      "ruleset": 2,
      "export": {
        "header": "BlackDream dependency advisory",
        "ruleset": "Ruleset: «n»",
        "entries": "Kernel/Add entries: «n»",
        "result": "Result: «summary»",
        "not_checked": "Not checked: «note»",
        "none": "No advisories.",
        "row": "[«SEVERITY»] «where»",
        "evidence": "  Evidence: «evidence»",
        "confidence": "  Confidence: «confidence»",
        "next": "  Next: «advice»",
        "rule": "  Rule: «rule» («source»)"
      }
    }
  },
  "settings": {
    "title": "Settings",
    "cards": [
      "Appearance",
      "About",
      "Storage",
      "Downloads and safety"
    ],
    "appearance": {
      "label": "Theme",
      "choices": [
        "System",
        "Light",
        "Dark"
      ],
      "hint": "Follows the system by default. Changes apply immediately."
    },
    "about": {
      "version": "BlackDream «version»",
      "body": "An OpenCore EFI builder with a graphical front end. Compatibility checking, kext selection, and ACPI patching come from the BSD-3 licensed OpCore Simplify engine.",
      "license": "BlackDream is MIT licensed. The vendored engine keeps its BSD-3-Clause license.",
      "privacy": "No report is uploaded; the engine only downloads the artifacts a build needs."
    },
    "storage": {
      "labels": [
        "Artifact cache",
        "Runtime tools"
      ],
      "hint": "Where downloads and the tools that read firmware live."
    },
    "safety": [
      {
        "title": "Pinned SHA-256",
        "body": "Downloads are verified against pinned SHA-256 digests before the engine uses them.",
        "icon": "shield"
      },
      {
        "title": "Folder only",
        "body": "BlackDream writes an EFI folder. It never mounts, writes to, or repairs an EFI partition.",
        "icon": "folder"
      },
      {
        "title": "No account",
        "body": "No account, no telemetry, and no update check runs in the background.",
        "icon": "fingerprint"
      }
    ]
  },
  "help": {
    "title": "Help",
    "cards": [
      "Quick start",
      "Keyboard shortcuts",
      "Troubleshooting",
      "Diagnostics",
      "Before the first boot"
    ],
    "quick_start_hint": "Six steps across the three sections in the sidebar.",
    "quick_start": [
      {
        "title": "Make the installer",
        "body": "Pick a macOS release, download Apple's recovery image, and write it to a FAT32 USB drive. A dropped connection resumes.",
        "icon": "download"
      },
      {
        "title": "Load a report",
        "body": "Collect hardware on Linux or Windows, or drop a Report.json exported by Hardware Sniffer anywhere in this window.",
        "icon": "file"
      },
      {
        "title": "Choose a release",
        "body": "The version picker marks the engine's suggestion, and any release that needs OpenCore Legacy Patcher.",
        "icon": "monitor"
      },
      {
        "title": "Check compatibility",
        "body": "Every device is graded, and the Status column answers for the release you picked.",
        "icon": "pulse"
      },
      {
        "title": "Build the folder",
        "body": "Pick an output folder and build. The EFI folder is written; nothing is mounted or written to a disk.",
        "icon": "build"
      },
      {
        "title": "Configure the EFI",
        "body": "Edit the built config.plist here, validate it with OpenCore's own checker, and save it back.",
        "icon": "sliders"
      }
    ],
    "shortcuts": [
      {
        "action": "Search devices",
        "keys": "Ctrl K",
        "mac": "⌘ K"
      },
      {
        "action": "Open a report",
        "keys": "Ctrl O",
        "mac": "⌘ O"
      },
      {
        "action": "Installer",
        "keys": "Ctrl 1",
        "mac": "⌘ 1"
      },
      {
        "action": "Build EFI",
        "keys": "Ctrl 2",
        "mac": "⌘ 2"
      },
      {
        "action": "Configure EFI",
        "keys": "Ctrl 3",
        "mac": "⌘ 3"
      },
      {
        "action": "Compatibility",
        "keys": "Ctrl Shift 1",
        "mac": "⌘ Shift 1"
      },
      {
        "action": "Build",
        "keys": "Ctrl Shift 2",
        "mac": "⌘ Shift 2"
      },
      {
        "action": "Logs",
        "keys": "Ctrl Shift 3",
        "mac": "⌘ Shift 3"
      },
      {
        "action": "Settings",
        "keys": "Ctrl ,",
        "mac": "⌘ ,"
      },
      {
        "action": "Help",
        "keys": "F1",
        "mac": "F1"
      },
      {
        "action": "Quit",
        "keys": "Ctrl Q",
        "mac": "⌘ Q"
      }
    ],
    "troubleshooting": [
      {
        "title": "Read the red card first",
        "body": "It names the failure and ends with a code such as acpi.refused. The log keeps the full sequence.",
        "icon": "alert-triangle"
      },
      {
        "title": "A refused ACPI read is not a fault",
        "body": "Nothing was read or written. Try again and accept the system authentication window.",
        "icon": "shield"
      },
      {
        "title": "A rejected report clears the page",
        "body": "Choose another Report.json; the previous machine's devices are removed on purpose.",
        "icon": "info"
      },
      {
        "title": "Save the log before reporting a problem",
        "body": "Save log… writes it to a file, and the copy button puts it on the clipboard.",
        "icon": "save"
      }
    ],
    "diagnostics": {
      "body": "Copy a short summary for a bug report, or build a bundle you can read before you send it: app version, platform, theme, the session log, the crash report and the last validation result. Nothing is uploaded, and serial, MLB, UUID and ROM values are redacted.",
      "lines": [
        "BlackDream «version»",
        "Platform: «system platform»",
        "Theme: «Dark or Light»",
        "Artifact cache: «path»",
        "Runtime tools: «path»",
        "Crash reports: «path»",
        "Last error: «error code or none»"
      ],
      "button": "Copy environment info",
      "idle": "Nothing has been copied or saved.",
      "copied": "Copied to the clipboard.",
      "bundle_button": "Save diagnostic bundle…",
      "bundle": {
        "title": "Save a diagnostic bundle",
        "heading": "Choose what to include",
        "hint": "Nothing is uploaded. The bundle is written to the folder you pick, and you attach it yourself. Serial, MLB, UUID and ROM values are replaced with <redacted>, and your home folder is shortened to ~.",
        "preview": "The text that will be written",
        "save": "Save bundle…",
        "save_title": "Save the diagnostic bundle",
        "filter": "Zip archive (*.zip);;Text file (*.txt)",
        "failed": "The bundle could not be written",
        "saved": "Saved to «path». Nothing was uploaded.",
        "entries": [
          "version, platform, theme and the last error code",
          "this session's log",
          "the newest crash report",
          "the last ocvalidate result",
          "the last folder check",
          "the Report.json key names, not its values",
          "contains hardware details; off unless you choose it"
        ]
      }
    },
    "first_boot": {
      "title": "Before the first boot",
      "hint": "Advice for the first attempt. BlackDream never boots, installs or writes firmware.",
      "steps": [
        {
          "title": "Use a spare USB drive",
          "body": "Write the installer to a stick you can erase. Leave the machine's own disk out of the process until macOS runs.",
          "icon": "usb"
        },
        {
          "title": "Check firmware settings",
          "body": "Turn Secure Boot off or enrol OpenCore the way your board's guide describes, and note every setting you change.",
          "icon": "gear"
        },
        {
          "title": "Keep a way back",
          "body": "Know how to open the firmware boot menu and start the existing system before OpenCore is in the boot path.",
          "icon": "clock"
        },
        {
          "title": "Expect the OpenCore picker",
          "body": "The picker lists the installer and any existing entries. If nothing appears, folder checks are the first place to look.",
          "icon": "logs"
        },
        {
          "title": "Use verbose boot for the first run",
          "body": "Add -v to the boot arguments when a run stops early, so the last line names the driver that failed.",
          "icon": "book"
        },
        {
          "title": "Plan recovery",
          "body": "A second machine and a working macOS installer are the recovery plan. BlackDream never boots, installs or writes firmware.",
          "icon": "shield"
        }
      ],
      "copy": "Copy the checklist",
      "idle": "Nothing has been copied.",
      "copied": "Copied to the clipboard.",
      "boundary": "This is advice. BlackDream has no boot button and writes no firmware."
    }
  },
  "donate": {
    "title": "Support BlackDream",
    "summary_title": "Support the project",
    "summary": "BlackDream is free and MIT licensed. It has no account, no telemetry and no ads.",
    "items": [
      {
        "title": "Test on real hardware",
        "body": "Run the check on a machine you own, then build to a spare disk. Real reports expose firmware the test suite cannot.",
        "icon": "monitor"
      },
      {
        "title": "Send a compatibility report",
        "body": "If a verdict looks wrong, include the engine log and the environment info from Help when you report it.",
        "icon": "file"
      },
      {
        "title": "Share the app",
        "body": "Pass it to someone with the same hardware. A second report on the same model is how device gaps get found.",
        "icon": "share"
      },
      {
        "title": "Funding",
        "body": "Donation links are not open yet. No payment button is shown until there is a page behind it.",
        "icon": "heart"
      }
    ]
  },
  "read_only_dialogs": {
    "release_matrix": {
      "title": "Hardware compatibility by macOS release",
      "heading": "«n» device«s» across «n» release«s»",
      "headers": [
        "Device",
        "Class"
      ],
      "cell": "Each cell is the same status the device table would show for that release. ",
      "boundary": "These statuses use the same compatibility ranges as the device table. They do not test firmware, hardware or whether macOS boots.",
      "empty": "No graded device to compare.",
      "copy": "Copy",
      "save": "Save as text…",
      "save_title": "Save the release comparison",
      "save_failed": "The comparison could not be saved",
      "filter": "Text files (*.txt);;All files (*)",
      "export_header": "BlackDream - Hardware compatibility by macOS release",
      "export_column": "«name»: Supported «n», Limited support «n», Not supported «n», Not graded «n»"
    },
    "report_compare": {
      "title": "Compare hardware reports",
      "heading": "«before» → «after»",
      "counts": "«n» hardware change«s» · «n» recorded compatibility change«s» · «n» unchanged",
      "boundary": "A recorded compatibility change can come from a different engine or database version, not from this machine. Neither side was re-graded.",
      "headers": [
        "Change",
        "Section",
        "Device",
        "Detail"
      ],
      "kinds": {
        "added": "Added",
        "removed": "Removed",
        "hardware": "Hardware",
        "reading": "Reading"
      },
      "hardware_fields": [
        "Processor Name",
        "Manufacturer",
        "Vendor",
        "Device ID",
        "Subsystem ID",
        "Subsystem",
        "PCI Path",
        "Device Type"
      ],
      "empty": [
        "None",
        "No differences."
      ],
      "file_title": "Compare hardware reports",
      "file_filter": "Hardware reports (Report.json *.json);;All files (*)",
      "unreadable": "One of the reports could not be read as a JSON object.",
      "copy": "Copy",
      "save": "Save as text…",
      "save_title": "Save the report comparison",
      "save_failed": "The comparison could not be saved",
      "filter": "Text files (*.txt);;All files (*)",
      "export_header": "BlackDream report comparison",
      "export_counts": [
        "Devices before: «n»",
        "Devices after: «n»",
        "Hardware changes: «n»",
        "Recorded compatibility changes: «n»",
        "Unchanged: «n»"
      ]
    },
    "profiles": {
      "title": "Profiles",
      "heading": "Local profiles on this machine",
      "hint": "A profile keeps a report path, an EFI folder and a release. It stores no serial, MLB, UUID or ROM value, so a profile cannot carry an identity to another machine.",
      "headers": [
        "Name",
        "Report",
        "Release",
        "EFI folder"
      ],
      "fields": [
        "name",
        "report",
        "efi_folder",
        "release",
        "updated"
      ],
      "idle": "Nothing has been copied or saved.",
      "save_current": "Save current",
      "use": "Use",
      "rename": "Rename…",
      "remove": "Remove",
      "save_prompt": "Save a profile",
      "rename_prompt": "Rename a profile",
      "name_label": "Profile name",
      "no_report_title": "No report loaded",
      "no_report": "Load a report before saving a profile.",
      "duplicate_title": "A profile with that name already exists",
      "duplicate": "Choose another name, or remove that profile first.",
      "remove_title": "Remove this profile?",
      "remove_text": "Remove «name»? The report and EFI folder stay on disk.",
      "saved": "Saved «name».",
      "renamed": "Renamed «before» to «after».",
      "removed": "Removed «name».",
      "write_failed": "The profiles could not be saved",
      "missing_report": "The profile's report could not be found: «path»",
      "store": "profiles.json"
    },
    "history": {
      "title": "Build history",
      "heading": "Builds recorded on this machine",
      "hint": "A build folder can be moved or deleted after the fact. The history says what was recorded, not that the folder is still there.",
      "headers": [
        "When",
        "Release",
        "Result",
        "Output",
        "Folder",
        "Manifest"
      ],
      "statuses": [
        "succeeded",
        "failed",
        "cancelled"
      ],
      "folder_states": [
        "Folder present",
        "Folder missing"
      ],
      "manifest_states": [
        "Recorded",
        "Missing",
        "Not recorded"
      ],
      "empty": [
        "None",
        "No builds have been recorded yet."
      ],
      "open_folder": "Open folder",
      "copy": "Copy history",
      "save": "Save as text…",
      "save_title": "Save the build history",
      "save_failed": "The history could not be saved",
      "filter": "Text files (*.txt);;All files (*)",
      "export_header": "BlackDream build history",
      "write_failed": "The build history could not be written: «detail»",
      "store": "build-history.jsonl",
      "max_entries": 100
    }
  }
}
```

## 17. Known drift in AI-generated mockups — check the output against this before accepting it

Each row was produced by a model reading an earlier version of this document or the reference render,
and is contradicted by running code. None is a stylistic choice you can keep.

| Invented by the mockup | Reality |
|---|---|
| Three columns, with the status idea rejected as "a second judgement" | 2.0 deliberately has four. `Status` is not a second opinion: `verdicts.target_status` answers "does this device work on the *selected* release?" from the engine's own tuples. Changing the combo changes the status words and row tints. |
| `Supported ✓` / `Best effort` / `Compatible`, or a coloured pill around the word | Exactly four labels: `Supported`, `Limited support`, `Not supported`, `Not graded`, each a 15 px icon **and** a coloured word with no pill background. The labels are literals in `verdicts.py`; the row tint is carried by the whole row, not by a badge. |
| An `Unsupported` support column painted red, or "Unsupported blocks the build" | The support column is plain text. The status word is coloured, and a `Not supported` row is tinted `rowFailBg`; an unsupported device still does not block a build. Only the six fatal cards do. |
| `Incompatible GPU detected… You can still build an EFI folder` | `gpu.unsupported` is `recoverable = False` and blocks the build. There is no "still buildable" GPU path. Copy is fixed in §16. |
| `Building OpenCorePkg`, `Finalizing EFI folder` | The five names in §7.8. The engine emits exactly those and nothing else. |
| A horizontal numbered stepper, or card numbers ① ② ③ | The app has no card numbers; no card or button carries one. `Step 2 of 5` is a status label on the engine's stage list, not a wizard step. |
| Glyph marks `· ▶ ✓ ✗ –` in the stage list | SVG icons `dot`, `spinner`, `check-circle`, `x-circle`, `minus`. A text tick cannot follow the theme colour or the DPI scale. |
| A `Build steps` card next to the progress bar | One card, `Build progress`: stages, current task, metrics and bar together. |
| `macOS Tahoe 26 [suggested]` with two spaces and brackets | `macOS Tahoe 26  ·  suggested, needs OCLP` — two spaces, a middle dot, two spaces, comma-joined badges. |
| Per-stage timers forbidden | Allowed and built: each stage row has an elapsed time on the right (`—` until it runs). The old rule was 1.1. |
| `OpenCorePkg: 62% at 1904 kB/s` only, never MB/s | The rate formatter prints `KB/s` below 1 MiB/s and `1.9 MB/s` at or above it. Copy §7.8 exactly. |
| `OpenCorePkg: 62% at 1.9 MB/s` for a slow transfer | Below 1 MiB/s it must be whole `KB/s`, e.g. `904 KB/s`. |
| A green `Built completed successfully` card | S8 is a full progress card, an enabled `Open EFI folder`, and `Done: <path>` in the log. No success card, no modal. |
| A bottom status bar reading `Ready` / `EFI folder written to…` | 2.0 removed the status bar. `QMainWindow`'s bar still exists but is hidden; do not draw it. |
| `Build EFI folder` as a *card* title | The setup and actions cards are untitled. `Build EFI folder` is the outline button in the 2 × 2 actions grid. |
| A menu bar hidden on Windows or Linux | The `File` / `View` / `Help` bar is visible on every platform: the system bar outside the window on macOS, a strip at the top of the window on Windows and Linux. The sidebar is still the primary navigation. |
| A `CURRENT TASK` caption or a transfer line under the task name | The task box is compact: task name, muted detail, 5 px bar, three metric tiles. The transfer line was removed when the box moved beside the checklist. |
| A `Cancel` button hidden until a job starts | All four action buttons are always visible in a 2 × 2 grid; `Cancel` is merely disabled until a job runs. |
| A sun / moon theme button in the page header | There is no theme button. `Settings > Appearance` owns the `System` / `Light` / `Dark` combo; `View > Toggle Theme` flips an explicit theme. |
| A `Settings` or `About` modal floating over the dashboard | Both are the Settings view, one of the eight pages. The only modals are `Engine verdict` and the two installer confirmations. |
| A help dialog with a close button, or `Open documentation` / `Report a bug` links | `Help` is a full view with in-window quick start, shortcuts, troubleshooting and diagnostics. No external URL ships. |
| A Donate view with a payment button, amount tiers, a donation link, or a licence-key field | There is no funding URL yet. Donate carries four non-money cards and one honest `Funding` note; it has zero buttons and zero inputs. |
| A desktop wallpaper outside the window, a floating inset panel, or app-painted window controls | The wallpaper lives **inside** the client area; the platform frame, title bar and menu bar stay. There are no traffic lights, no custom drag region and no resize ring. |
| A window with no menu bar, or a menu strip drawn inside a custom title area | The menu bar is visible on every platform: the system bar on macOS, a strip at the top of the window on Windows and Linux. |
| A flat grey canvas with no silk | The app paints the blue-silk wallpaper inside the window: a blue gradient, a light bloom, five low-alpha cubic ribbons and a vignette. The rail and content veil are glass over it. |
| A photo wallpaper, heavy blobs, or drop shadows | The silk is procedural strokes, never a texture asset; cards carry a 1 px border and a lighter top edge, never a blur. |
| Gradient nav items other than the checked pill, gradient text, or a gradient card header | The checked nav pill, primary button and progress fill are functional gradients; the wallpaper, veil, rail and card fills are material gradients. Headers, status words and unchecked nav items stay flat. |
| Wallpaper behind the native title bar, or outside the window | The wallpaper is clipped to the client area. The native title bar and the menu strip sit above it and are never painted by the app's backdrop. |
| A search pill on `Installer`, `Build EFI`, `Logs`, `Configure EFI`, `Settings`, `Help` or `Donate` | The search filters the device table, which exists only on `Compatibility`; the pill is hidden everywhere else. |
| Icons beside sidebar items forbidden (1.1 rule) | Icons are required: `download` / `build` / `sliders` in the three workflow sections, plus `gear` / `help` / `heart` for Settings, Help and Donate. They come from the inline SVG set, never a third-party library. |
| A sidebar pinned to exactly 200 px on every platform, or a nav label clipped to fit it | The rail is 200 px at the reference font and never narrower; a wider platform font grows it by the pixels its longest label needs. An action row that its width will not hold takes a second line rather than squeezing a button — in the running app that is the page's header action slot, the config card's actions and the Keys and Validation card headers. |
| A top-level `Compatibility`, `Build` or `Logs` sidebar item | 3.0 has exactly three workflow sections: `Installer`, `Build EFI`, `Configure EFI`. Compatibility, Build and Logs are segment tabs inside `Build EFI`. |
| An `Erase drive` / `Format` checkbox, a partition picker, or an installer that mounts a disk | The Installer copies files into an already-mounted FAT32 volume and replaces only `EFI` and `com.apple.recovery.boot`. It never formats, mounts or writes to a block device. |
| A USB combo that already has the first drive selected | No drive is selected until the user picks one. The placeholder says `Choose a USB drive`, and the write confirmation names the target. |
| A write button enabled before the recovery image is verified | Apple's signed chunklist and every image chunk are checked first. The write button also needs a complete EFI folder and an explicitly chosen drive. |
| An OCAT download, an OCAT process, an OCAT update check, or an external configurator | 3.3 edits the built `config.plist` in the window: schema-free tree, section rail, selected-entry inspector, inline `ocvalidate` and `macserial` serials. No external tool, release pin or OCAT attribution card. |
| A `Reset to preset`, `Update Center`, `Base Configs`, or `EFI Backups` product, or a standalone ASCII↔HEX mode switch in the editor chrome | The reference mockup's ancillary products are not in BlackDream. The page edits one document with one tree; the only ASCII/HEX choice is the `Show as text` checkbox inside the data dialog, and it round-trips every byte losslessly. |
| An installer page that shows the build stage checklist | The Installer owns two cards only: `macOS installer` and `USB drive`. Session cards stay in `Build EFI`. |
| `OpenCore EFI builder.` | The retired 2.0–2.3 tagline. The shipped tagline is `OpenCore, made simple.` under the `BlackDream` wordmark, never replaced. |
| A `Use example report` button | No sample data ships; the only inputs are drop and browse. |
| A password field, or an in-app admin prompt | The only authentication is polkit's own window for the Linux ACPI read, outside the app's frame; the Windows read needs none. |
| A second log pane on the `Logs` view | The same widget moves and grows; two logs would mean two buffers to keep in sync. |
| `⚠️` / `✅` emoji in verdicts | No emoji anywhere, at any size, in any theme. |

If a generated mockup survives §17 but still drifts, the failure is in the instruction, not the
model: send §16 alone with *"render S7, use only these strings"* rather than the whole document.
