# BlackDream — UI mockup specification

**Version:** 2.1 · **Date:** 2026-10-22 · **Status:** every screen marked *built* is running code today

2.1 adds three utility views at the bottom of the sidebar — `Settings`, `Help` and `Donate`. They are
pages, not modals: the same header, the same glass cards, and the same theme. Settings carries the
theme picker, storage paths and about copy; Help carries the workflow, shortcuts, troubleshooting and
a diagnostics copy button; Donate lists non-money ways to help, and says plainly that funding is not
open yet.

2.0 is the **glass dashboard**: one frameless window, a painted pastel wallpaper, a translucent
sidebar, and cards instead of rows. The 1.1 shell survives — three primary views, cards, one log
widget — but its three-column table, glyph marks, separate `Build steps` card, bottom log dock and
status bar do not. Anything describing a toolbar or a left form column is 1.0 and is wrong.

This document describes every screen well enough to produce high-fidelity mockups. It is written for
a design tool or a chat model that will render the UI, so it states exact regions, exact copy, and
exact component states rather than adjectives.

### How to use this with an image model

1. Attach the real screenshots — they exist, they are not concepts, and they are rendered by the
   running app at 1536 × 1024:
   - `docs/screenshots/01-empty.png` · `02-compatibility-checked.png`
   - `docs/screenshots/03-device-details.png` · `04-build-view.png`
   - `docs/screenshots/05-logs-view.png` · `06-dark-compatibility.png`
   - `docs/screenshots/07-fatal-gpu.png` · `08-settings.png`
   - `docs/screenshots/09-help.png` · `10-donate.png`
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
| Form factor | Single frameless desktop window; the app paints its own shell |
| Window default size | 1440 × 940, resizable; minimum 1240 × 800 |
| Chrome | 22 px painted wallpaper inset, rounded translucent shell, three 12 px traffic-light buttons in the sidebar, drag by the header, 18 px resize grip bottom-right |
| Platforms | macOS 12+, Windows 10/11, Linux (X11 + Wayland) |
| Engine | Vendored OpCore Simplify (BSD-3), driven headless |
| Navigation | Fixed 232 px sidebar, three primary views: `Compatibility` · `Build EFI` · `Logs`, plus three utility views at the bottom: `Settings` · `Help` · `Donate` |
| Input model | Report file is dropped or picked; paths are never typed |
| Output | An EFI **folder**. Nothing is mounted, written to, or repaired |

### Non-goals (v1) — a mockup that shows these is wrong

- No command-line interface, no console window, no `$` prompt. The log pane is a read-only text
  surface inside the window.
- No writing to, mounting, or repairing an EFI partition. The only administrator prompt is polkit's
  own window for reading ACPI tables on Linux, and it is drawn outside the app's frame.
- No account, no sign-in, no telemetry banner, no update dialog.
- No multi-window wizard, no stepper, no "Next". The three primary sidebar items are views of one session.
- No native menu bar. `Settings`, `Help` and `Donate` are sidebar views, not dialogs.
- No modal Settings or About screen. 2.1 moved both into the Settings view.
- No status bar. 1.1 had one; 2.0 removed it, and completion is shown in the build card instead.
- No dark-mode-only design; both themes ship (§4).

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

There is one window with six views, and no wizard. A view groups the controls for one part of the
same session; it is not a step. Nothing is enabled or disabled because of which view is open, and
the error card sits above the page stack, so no view change can hide a failure.

---

## 3. Layout

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ ░ pastel wallpaper: vertical gradient + five radial blobs; 22 px inset on every edge ░        │
│ ┌────────────────────────────┬───────────────────────────────────────────────────────────────┐│
│ │ ● ● ●                      │ Hardware Compatibility                [⌕ Search…   Ctrl K] (☀)││
│ │                            │ Review what macOS can run on this machine, then build the EFI  ││
│ │ ◈  BlackDream              │ folder.                                                       ││
│ │    OpenCore EFI builder.   │                                                               ││
│ │                            │ ┌─ ① Select files ────┐ ┌─ ② macOS version ─┐ ┌─ ③ Actions ─┐││
│ │  ▸ Compatibility           │ │ Hardware report   ✓ │ │ [macOS Tahoe 26 ▾] │ │ Output …  ✓ │││
│ │  ▸ Build EFI               │ │ ACPI tables       · │ │ Detected support   │ │ [Build EFI] │││
│ │  ▸ Logs                    │ │ Collect · Read ACPI │ │ [summary panel]    │ │ [Check]     │││
│ │                            │ └─────────────────────┘ └────────────────────┘ │ [Open EFI]  │││
│ │                            │ ┌─ Detected devices ──────────────────────────┐ └────────────┘││
│ │                            │ │ Device · Class · macOS support · Status     │ ┌─ Device ───┐││
│ │                            │ │ ┌──┐ Intel Core i5-…  CPU  Up to…  ● pill  │ │ details    │││
│ │                            │ │ └──┘ … rows …                               │ │ grid       │││
│ │                            │ └─────────────────────────────────────────────┘ └────────────┘││
│ │                            │ ┌─ Build progress ─── Step 2 of 5 ───────────────────────────┐││
│ │                            │ │ [══════ 40%]   five stages        │ CURRENT TASK [product]  │││
│ │                            │ │                                   │ [task bar] [transfer]  │││
│ │                            │ │ [Elapsed] [Downloaded] [Speed] [Step]                      │││
│ │                            │ └────────────────────────────────────────────────────────────┘││
│ │ ⚙ Settings                 │ ┌─ Engine log ───────────────────────────────────────────────┐││
│ │ ? Help                     │ │ [Info and above ▾]  [Save log…] [copy]                    │││
│ │ ♡ Donate                   │ │ 12:04:19  INFO  == Checking compatibility ==              │││
│ │                            │ └────────────────────────────────────────────────────────────┘││
│ └────────────────────────────┴───────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The diagram is the **Compatibility** view, which is the densest screen: seven cards. The other two
views rearrange the *same widget instances* — nothing is duplicated:

| View | Cards, in order |
|---|---|
| `Compatibility` | Top row: `Select files` (stretch 4) · `macOS version` (3) · `Actions` (4). Middle row: `Detected devices` (3) · `Device details` (2). Bottom row: `Build progress` (3) · `Engine log` (2) |
| `Build EFI` | Top row: `Actions` (1) · `Build progress` (2). Bottom row: `Engine log` (1) |
| `Logs` | `Engine log` only, taking the full content height; no scroll area |
| `Settings` | Top row: `Appearance` (2) · `About` (3). Bottom row: `Storage` (3) · `Downloads and safety` (3) |
| `Help` | Top row: `Quick start` (3) · `Keyboard shortcuts` (2). Bottom row: `Troubleshooting` (3) · `Diagnostics` (2) |
| `Donate` | `Support the project` full width, then a 2 × 2 grid: `Test on real hardware` · `Send a compatibility report` · `Share the app` · `Funding` |

- **Utility pages own their cards.** `Settings`, `Help` and `Donate` never mount the session cards;
  the devices table, progress card and log stay on their primary pages. This is why a build running
  in the background cannot make the Settings page sprout a progress bar.
- **Shell:** the window is transparent; the wallpaper is painted, not shipped as an image. A
  translucent rounded shell (radius 26) floats 22 px inside the window edge. Sidebar 232 px fixed;
  shell padding 10 px; 14 px between sidebar and content; content padding 12 px × 8 px.
- **Header:** page title 29 px / 800 and subtitle 13 px muted on the left; a 262 × 38 search pill and
  a 38 × 38 theme button on the right. The search filters the `Detected devices` table across all
  four columns and clears when a new report loads. It is hidden on `Settings`, `Help` and `Donate`,
  where there are no devices to filter. The header is also the window drag handle; double-click
  toggles maximize. On macOS the keycap reads `⌘ K`, elsewhere `Ctrl K`.
- **Sidebar:** traffic lights at the top (12 px, tooltips `Close` · `Minimize` · `Zoom`), then the
  36 px logo with `BlackDream` / `OpenCore EFI builder.`, then the three primary nav buttons, then a
  stretch, then `Settings`, `Help` and `Donate`. Primary items are 40 px high; utility items are
  36 px. Every item is icon + text, muted when idle, white on the blue gradient when active. All six
  are one exclusive group: opening a utility view unchecks the primary nav, and vice versa.
- **Cards** ride in one page column; stretches are listed above. Cards in a row share a height and
  pack their content to the top. A card with no growing child is padded with a trailing stretch so
  its content never floats mid-panel. Cards scroll with the page when the window is short.
- **Numbered cards:** only the three setup cards carry a number — `① Select files`,
  `② macOS version`, `③ Actions` — in a 20 px tinted circle. No other card is numbered, and the
  numbers are not a wizard sequence.
- **During a job the window follows the work:** the three build jobs show `Build EFI`, everything
  else shows `Compatibility`. The user is never asked to go look.
- **No status bar.** The bottom edge of the shell is card content; the resize grip floats in the
  corner.

---

## 4. Visual language

Both themes ship; every value below is read from `src/blackdream/ui/theme.py`. A mockup may use
either column, but must not mix them.

| Token | Light | Dark | Used for |
|---|---|---|---|
| `bgTop` / `bgMid` / `bgBottom` | `#a9bcf5` / `#e9defb` / `#f4cbd6` | `#141a2c` / `#1d1b33` / `#2a1c2a` | wallpaper gradient, top to bottom |
| `blobs` | blue, pink, orange, cyan, violet | dim blue, plum, rust, teal, indigo | five radial glows over the gradient |
| `shellBg` / `shellBorder` | `rgba(255,255,255,158)` / `rgba(255,255,255,226)` | `rgba(20,24,38,188)` / `rgba(255,255,255,26)` | the floating glass shell |
| `sidebarBg` / `sidebarBorder` | `rgba(255,255,255,120)` / `rgba(255,255,255,196)` | `rgba(15,19,30,150)` / `rgba(255,255,255,22)` | the sidebar sheet |
| `cardBg` / `cardBorder` | `rgba(255,255,255,190)` / `rgba(255,255,255,228)` | `rgba(31,37,55,196)` / `rgba(255,255,255,26)` | every card |
| `pathRowBg` | `rgba(255,255,255,152)` | `rgba(12,16,26,110)` | the three path rows |
| `fieldBg` / `fieldBorder` | `rgba(255,255,255,150)` / `rgba(148,163,196,92)` | `rgba(12,16,26,120)` / `rgba(255,255,255,34)` | combo, search pill, neutral buttons |
| `buttonBg` / `buttonHoverBg` | `rgba(255,255,255,168)` / `rgba(255,255,255,236)` | `rgba(255,255,255,18)` / `rgba(255,255,255,34)` | outline buttons and chips |
| `text` / `muted` / `faint` | `#1c2233` / `#66708a` / `#8b93a8` | `#e8ebf4` / `#9aa3b8` / `#7c8498` | body / hints and secondary / timestamps and disabled |
| `accent` / `accentSoft` / `accentDeep` | `#2563eb` / `#3b82f6` / `#4338ca` | `#8db4ff` / `#4f8ef7` / `#4338ca` | links, primary gradient, progress fill |
| `ok` / `okBg` / `okBorder` | `#15803d` / `rgba(22,163,74,30)` / `rgba(22,163,74,76)` | `#8fd6a4` / `rgba(45,138,82,48)` / `rgba(90,190,125,80)` | Supported status, good summary, done stages |
| `warn` / `warnBg` / `warnBorder` | `#b45309` / `rgba(245,158,11,34)` / `rgba(245,158,11,92)` | `#f0c274` / `rgba(196,138,38,44)` / `rgba(235,180,90,80)` | Limited support, checking state, WARN log text |
| `fail` / `failBg` / `failBorder` | `#b91c1c` / `rgba(239,68,68,30)` / `rgba(239,68,68,80)` | `#f2a0a8` / `rgba(190,58,72,52)` / `rgba(240,120,132,90)` | Not supported, rejected report, failing stage |
| `unknown` / `unknownBg` / `unknownBorder` | `#6b7280` / `rgba(107,114,128,26)` / `rgba(107,114,128,64)` | `#a3a9b8` / `rgba(255,255,255,20)` / `rgba(255,255,255,36)` | Not graded, empty path state |
| `tileIcon` / `tileBg` | `#3b6ef6` / `rgba(59,110,246,26)` | `#9dbcff` / `rgba(100,140,255,36)` | icon tiles and number badges |
| `taskBg` / `taskBorder` | `rgba(244,247,255,180)` / `rgba(255,255,255,228)` | `rgba(255,255,255,14)` / `rgba(255,255,255,26)` | current-task box |
| `metricBg` | `rgba(255,255,255,150)` | `rgba(255,255,255,12)` | the four metric tiles |
| `errorBg` / `errorFg` / `errorCode` | `rgba(254,226,226,218)` / `#8c1d24` / `#9a666c` | `rgba(74,28,34,222)` / `#f2b0b6` / `#c88a90` | the error card and rejected summary |
| `logBg` / `logFg` / `logMuted` | `#101319` / `#d8dbe4` / `#7d8496` | `#0d1016` / `#d8dbe4` / `#7d8496` | log pane — dark in **both** themes |
| `grid` / `groove` | `rgba(120,140,180,40)` / `rgba(120,140,180,60)` | `rgba(255,255,255,22)` / `rgba(255,255,255,30)` | table header rule / progress groove |

- **Typography:** the platform UI font (`Inter`, `SF Pro Text`, `Segoe UI`, `Noto Sans`, `DejaVu
  Sans` fallback) at 13 px body. Page title 29 px / 800; subtitle 13 px muted. Brand 18 px / 800,
  brand hint 11 px muted. Card title 15 px / 700, card hint 12 px muted. Path label 10 px / 600,
  path value 12 px / 600. Number badge 11 px / 800. Step label 12 px / 600, percentage 17 px / 800.
  Detail key 11 px / 600, detail value 12 px / 600. Task title 10 px / 700 uppercase, task name
  13 px / 800, task detail 11 px muted. Metric label 10 px muted, metric value 13 px / 700. Stage
  name 12 px, stage time 11 px faint. Log pane monospace (`DejaVu Sans Mono` / Menlo / Consolas) at
  11 px.
- **Shapes:** shell 26 px, sidebar 20 px, card 18 px, error card 14 px, path row 12 px, nav item
  12 px, button 10 px, search pill 19 px, task box 12 px, metric 10 px, progress bar 6 px (task bar
  4 px), log pane 11 px. Status pills are 21 px high with a 10.5 px radius.
- **Depth is a white border and a background step — never a shadow.** Qt has no `box-shadow`, and
  `QGraphicsDropShadowEffect` repaints the whole subtree on every log line. A mockup with drop
  shadows is not buildable here.
- **Gradient:** one blue gradient (`accentSoft` → `accentDeep`, left to right) is used on the
  primary button, the checked nav item and the progress fill. The app logo carries its own indigo
  gradient. No gradient headers, no gradient cards, no purple pills.
- **Logo:** the 36 px mark is a white `BD` lettermark on a 48-unit tile with a deep indigo gradient
  (`#6b78f4` → `#4338ca` → `#1c1749`) and a 20% white rim. The letter outlines are embedded paths,
  not a font lookup, so the mark is identical on every platform.
- **Icons:** every icon is a stroke SVG from `src/blackdream/ui/icons.py`, drawn on a 24 × 24
  viewBox with a 1.7 px round stroke, rendered at 2× device pixel ratio and recoloured from the
  palette. They appear in the nav, the `Settings` / `Help` / `Donate` items, card link buttons,
  path-row tiles (28 px), utility row tiles (28 px), device class tiles (26 px), stage rows (16 px),
  status pills (12 px), metric tiles (16 px), field state (16 px) and the log tools. The utility
  views add `heart` (Donate), `share` (Share the app) and `shield` (safety and ACPI advice). Icons
  are decorative beside text, never the only signal, and no icon is drawn at an unlisted size.
- **Density:** 12 px between cards, 16 px / 10 px card padding, 6 px inside a card, path rows 46 px,
  nav 40 px, table rows 34 px. No hero areas, no illustrations, no empty-state artwork.
- **The log pane is dark in both themes.** It is a console surface inside a GUI; keeping it dark
  makes engine output unmistakable no matter which theme the chrome is wearing.

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

Only S1–S11, S14, S16, S17, S18 and S19 may be presented as current product. S12, S13 and S15 must
be labelled *concept*. S14 and S16 follow host capability, not a platform guess: `Collect hardware`
is drawn on Linux and Windows, `Read ACPI tables` on Linux only, and each is absent rather than
disabled where its capability is missing. A macOS frame shows neither; a Windows frame shows Collect
only, because the Windows scan adopts the ACPI tables Hardware Sniffer exports.
`Settings`, `Help` and `Donate` are one screen each, not modal overlays.

`Logs` is not a screen and gets no ID: it is the same log card at full height with the other cards
removed, and the error card stays visible above it.

---

## 6. S1 · Empty

The window opens directly into this, on the `Compatibility` view. No splash, no dialog.

- **Header:** `Hardware Compatibility` / `Review what macOS can run on this machine, then build the
  EFI folder.` Search pill empty with placeholder `Search devices…` and the `Ctrl K` / `⌘ K` keycap.
  Theme button shows a sun in the light theme, a moon in the dark theme.
- **`① Select files`:** hint `Provide your hardware report and any optional ACPI tables.` Two 46 px
  path rows: `Hardware report` with a file tile, empty path, a hollow dot state icon and `Browse…`;
  `ACPI tables (optional)` with a layers tile, empty path, hollow dot, `Browse…`. Under them, two
  text links: `Collect hardware` — **drawn on Linux and Windows** — and `Read ACPI tables` —
  **drawn on Linux only**. Each is absent, never disabled, where its capability is missing.
- **`② macOS version`:** hint `Choose the macOS version you want to build for.` An empty 40 px
  combo, the caption `Detected support`, then the summary panel in its *empty* style (neutral field
  fill, muted text): `Load a Report.json, or collect hardware from this machine.` on Linux,
  `Load a Report.json, or scan this machine with Hardware Sniffer.` on Windows, and
  `Load a Report.json exported by Hardware Sniffer on the target PC.` where no scan can run. Below it the note
  `Support ranges come from the report's own compatibility data.`
- **`③ Actions`:** hint `The EFI is a folder; nothing is mounted or written to a disk.` Output row
  **pre-filled** with a real per-user path and an `ok` check-circle whose tooltip is
  `Will be created`, e.g. `~/.local/share/blackdream/builds/20261022-1147` (macOS
  `~/Library/Application Support/blackdream/builds/…`, Windows
  `%LOCALAPPDATA%\blackdream\builds\…`). Two buttons side by side: primary `Build EFI folder`
  (gradient, disabled) and outline `Check compatibility` (enabled). A second row holds outline
  `Open EFI folder` (disabled). `Cancel` is **not visible** until a job starts.
- **`Detected devices`:** hint `No report loaded yet.`; a right-aligned link `View details`; the
  empty note `Load a report to see this machine's devices and what macOS does with them.`; the table
  shows its four headers and no rows. Minimum table height 176 px.
- **`Device details`:** seven detail keys (`Device`, `Class`, `macOS support`, `Vendor`,
  `Device ID`, `Subsystem`, `Current status`), each with an em dash value, and a full-width
  `Recommendation` row below them showing `Select a device to see the engine's verdict for it.`;
  `Copy details` and `Show engine verdict` disabled.
- **`Build progress`:** right-aligned step label `Not started`; a 0 % bar and `0%`; the five build
  stages already listed as pending — hollow dot icon, muted name, `—` time; the task box reads
  `CURRENT TASK` / `Waiting to start` / `Nothing is downloading.` with an empty 5 px bar and
  `No transfer in progress.` The four metric tiles read `Elapsed time —`, `Downloaded 0 B`,
  `Speed —`, `Step 0/5`.
- **`Engine log`:** filter `Info and above`, `Save log…`, copy icon; the pane is empty and dark.
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

A 46 px rounded row: a 28 px tinted icon tile, a stacked 10 px label and 12 px value, a 16 px state
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

The second line appears only when the machine needs OCLP for some release. While a report is
checking, or after it was rejected, the panel uses the neutral style; after rejection it uses the
**error** style (red fill, red text) with `Compatibility check failed.`

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

Four headers, always: `Device` · `Class` · `macOS support` · `Status`. The first column stretches;
the others are fixed at 94 px (`Class`), 268 px (`macOS support`) and 124 px (`Status`). Rows are
34 px, alternate with a faint tint, single-selection, never sortable. The table has its own
scrollbar and a 176 px minimum height.

**Row anatomy.** A 26 px rounded tinted tile with a class icon, then the device name. Long names are
shown in full wherever the column allows and always in the tooltip. The class is one plain word:

`CPU` · `GPU` · `Audio` · `Ethernet` · `Wi-Fi` · `Storage` · `USB` · `Bluetooth` · `SD card` ·
`Display` · `Biometric` (fallback: the section name, with a layers icon).

**`macOS support`** is the engine's own sentence, verbatim, and is printed in normal text colour:

| Verdict shape | Meaning |
|---|---|
| `Up to macOS Tahoe 26` | supported through the newest release |
| `macOS Catalina 10.15 to macOS Tahoe 26` | supported in a range |
| `Maximum support up to macOS High Sierra 10.13` | capped low |
| `Unsupported` | graded and rejected |
| `Unchecked` | the engine did not grade it |

`Unsupported` is not a blocked build — HDMI audio lands there on almost every healthy laptop. Only
the six fatal conditions in §8 block anything, and they arrive as a card, never as a row.

**Status pill.** The fourth column is a 21 px pill: a 12 px status icon plus a text label, with a
tinted fill, a 1 px border and coloured text. It answers one question — *will this device work on
the release selected in ②?*

| Label | Tone | Meaning |
|---|---|---|
| `Supported` | ok (green) | native on the selected release |
| `Limited support` | warn (amber) | works on the selected release only through OpenCore Legacy Patcher |
| `Not supported` | fail (red) | either no release supports it, it is too old for the selection, or it is too new and has no OCLP path |
| `Not graded` | unknown (grey) | the engine carried no compatibility tuple to judge |

The pill's tooltip is the status detail followed by the recommendation, e.g.
`Not supported on macOS Tahoe 26. Last native support is macOS Sequoia 15. Choose macOS Sequoia 15 or
earlier for native support.` Selecting another macOS version changes pills and tooltips; the
`macOS support` column does not change. Icons inside pills repeat the text; they never replace it.

The card hint becomes `Detected «n» devices from your hardware report.` The table's first row is
selected automatically and the details card describes it. `View details` selects the first
`Not supported` row, or the first row when none is unsupported.

### 7.6 Device details

A two-column grid with 102 px keys: `Device`, `Class`, `macOS support`, `Vendor`, `Device ID`,
`Subsystem`, `Current status`, then a full-width `Recommendation` line. Values default to an em
dash. The recommendation is coloured by the status tone. The card header carries the status label
as a pill-shaped badge, right-aligned.

Two outline buttons at the bottom: `Copy details` puts every `Key: value` pair plus the
recommendation on the clipboard; `Show engine verdict` opens a modal titled `Engine verdict` with
the device name, the engine's support sentence, the status label, the detail and the recommendation.
Both are disabled until a row is selected.

### 7.7 Actions

Output row at the top. Then a two-button row: the gradient `Build EFI folder` (build icon, white)
and the outline `Check compatibility` (pulse icon). Then a row with outline `Open EFI folder`
(folder icon) and, only while a job runs, outline `Cancel`. Enablement follows §11 exactly. `Build
EFI folder` stays disabled until a report has been graded; `Open EFI folder` enables only after a
build wrote a folder that still exists.

### 7.8 Build progress

Header: title `Build progress` on the left, the step label right-aligned: `Not started`, or
`Step 2 of 5` while a stage runs, or `Step 5 of 5` when all five are done. Under it a 9 px progress
bar and a 17 px `40%` at the right end. Qt's centred bar text is never drawn; the percentage sits
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

Beside the checklist (3 : 2) is the current-task box: the 10 px uppercase label `CURRENT TASK`, the
task name in bold, a detail line, a 5 px progress bar, and a transfer line. Between stages it
reads `Waiting to start` / `Nothing is downloading.` / `No transfer in progress.` During a transfer
the task name is the product, the detail is `<done> of <total>` (or `<size> downloaded` when the
length is unknown), the small bar follows the transfer, and the transfer line reads
`«product» · «size» · «rate»`. After analysis it reads `Ready to build` / `Choose a macOS version,
then build the EFI folder.` After a build it reads `EFI folder ready` / the result path, the small
bar is full, and the transfer line reads `Build complete.`

Four metric tiles below: `Elapsed time`, `Downloaded`, `Speed`, `Step`, each with a 16 px tinted
icon. Formatters, which a mockup must copy:

- Elapsed: `1.4 s` under a minute, `1:42` under an hour, `1:02:03` above.
- Size: `0 B`, `512 KB`, `1.4 MB`, `2.31 GB` (binary units, one decimal for MB, two for GB).
- Rate: `—` when idle, `904 KB/s` below 1 MiB/s, `1.9 MB/s` at or above it. The Speed tile and the
  transfer line share this formatter; stage times never use it.
- Step: `<done>/<total>`.

The card hint is `Step, transfer and timing from the engine.` at rest; `Building your OpenCore EFI
folder.` while one of the three build jobs runs; `The EFI folder is ready.` after the build.

### 7.9 Engine log

The card header carries, right-aligned: a 162 px level combo (`Info and above` · `Warnings and
above` · `Everything`), a `Save log…` chip with a save icon, and a 30 px copy icon whose tooltip is
`Copy the log`. The pane below is dark in both themes, 11 px monospace, no line wrap, minimum
150 px, capped at 4000 lines.

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
• On Linux, press Read ACPI tables (asks for administrator) on the Compatibility view.
```

The card appears on the `Build EFI` view, where the button was pressed. The row that fixes it is one
click away on `Compatibility`, and its state icon already says the same thing: a hollow dot with
`No folder chosen`, or an amber alert with `No .aml files here`. There is no focus ring and no
animated pointer — the app does not move the user's window for them.

**S7 Build in progress** — two of five stages `check-circle`, stage three `spinner` and bold, the
step label `Step 3 of 5`, the bar at 40 %, the task box naming the product and its bytes, the Speed
tile live, `Cancel` visible and enabled, the log scrolling.

**S8 Build finished** — all five stages `check-circle`, `Step 5 of 5`, bar 100 %, task name
`EFI folder ready`, task detail the result path, transfer line `Build complete.`, hint `The EFI
folder is ready.`, `Open EFI folder` enabled, log's last line `Done: <path>`. No confetti, no modal,
no "Success!" screen. The filled card and the enabled button are the whole celebration.

**S9 Cancelled** — the stage in flight becomes `minus`, later stages stay `dot`, the task detail
reads `<step> cancelled.`, the log gets `<step> cancelled` in warn colour, `Cancel` hides again and
the other controls return to their pre-build state. The error card stays hidden: cancelling is not a
failure.

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
| Sidebar | `BlackDream` · `OpenCore EFI builder.` · `Compatibility` · `Build EFI` · `Logs` · `Settings` · `Help` · `Donate` |
| Window controls | tooltips `Close` · `Minimize` · `Zoom` |
| Page headings | `Hardware Compatibility` · `Build EFI Folder` · `Engine Log` · `Settings` · `Help` · `Support BlackDream`, with the subtitles in §16 |
| Search | placeholder `Search devices…`; keycap `Ctrl K` / `⌘ K` |
| Theme toggle | tooltip `Switch to the dark theme` / `Switch to the light theme`; a sun icon in light, a moon in dark |
| Card titles | `Select files` · `macOS version` · `Actions` · `Detected devices` · `Device details` · `Build progress` · `Engine log` · `Appearance` · `About` · `Storage` · `Downloads and safety` · `Quick start` · `Keyboard shortcuts` · `Troubleshooting` · `Diagnostics` · `Support the project` · `Test on real hardware` · `Send a compatibility report` · `Share the app` · `Funding` |
| Card hints | §16 `card_hints` — the devices hint changes with state; `Appearance`, `Storage` and `Quick start` carry fixed hints |
| Empty notes | `Load a report to see this machine's devices and what macOS does with them.` · `The engine rejected this report before grading any device.` |
| Field labels | `Hardware report` · `ACPI tables (optional)` · `Output folder` |
| Field button | `Browse…` |
| Link buttons | `Collect hardware` · `Read ACPI tables` · `View details` · `Copy details` · `Show engine verdict` |
| Link tooltips | `Scan this machine and write a Report.json` · `Scan this machine with Hardware Sniffer; downloads and runs the verified tool` · `Read the firmware tables from this machine; asks for administrator rights` |
| Buttons | `Check compatibility` · `Build EFI folder` · `Cancel` · `Open EFI folder` · `Save log…` |
| Table headers | `Device` · `Class` · `macOS support` · `Status` — exactly four columns |
| Class labels | `CPU` `GPU` `Audio` `Ethernet` `Wi-Fi` `Storage` `USB` `Bluetooth` `SD card` `Display` `Biometric` |
| Status pills | `Supported` · `Limited support` · `Not supported` · `Not graded` |
| Summary | `Load a Report.json, or collect hardware from this machine.` · `Load a Report.json, or scan this machine with Hardware Sniffer.` · `Load a Report.json exported by Hardware Sniffer on the target PC.` · `Checking <file>…` · `Native support: <ranges>` · `With OpenCore Legacy Patcher: <ranges>` · `Compatibility check failed.` |
| Summary note | `Support ranges come from the report's own compatibility data.` · `Status is computed for <release>.` · `The engine suggests <release>.` · `Needs OpenCore Legacy Patcher.` |
| Version items | `<name>` or `<name>  ·  suggested, needs OCLP` (badges joined by `, `) |
| Progress card | `Not started` · `Step <n> of <total>` · `<pct>%` · metric labels `Elapsed time` `Downloaded` `Speed` `Step` · `0 B` · `<done>/<total>` |
| Task box | `CURRENT TASK` · `Waiting to start` · `Nothing is downloading.` · `No transfer in progress.` · `Ready to build` · `Choose a macOS version, then build the EFI folder.` · `Running…` · `<done> of <total>` · `<size> downloaded` · `EFI folder ready` · `Build complete.` · `<step> cancelled.` · `<step> failed.` |
| Metrics formatters | `<n>.<d> s` · `M:SS` · `H:MM:SS` · `0 B` · `<n> KB` · `<n>.<d> MB` · `<n>.<dd> GB` · `—` · `<n> KB/s` · `<n>.<d> MB/s` |
| Log filter | `Info and above` · `Warnings and above` · `Everything` |
| Log line | `== <step> ==` · `Graded <n> devices` · `SMBIOS model: <model>` · `<step> finished in <s> s` · `<step> cancelled` · `<step> failed` · `<n> earlier log lines were dropped` · `Done: <path>` · `<n> hardware sections written to <path>` · `<n> ACPI tables read from firmware` |
| Log tools | `Copy the log` · `Save log…` |
| Error card | `code: <code>` · `This machine cannot run macOS as configured.` (italic suffix, only the two unrecoverable fatals) |
| Settings view | `Theme` · `Light` · `Dark` · `Artifact cache` · `Runtime tools` · `BlackDream <version>` · `MIT` / `BSD-3-Clause` about copy · `Pinned SHA-256` · `Folder only` · `No account` |
| Help view | quick-start titles and bodies · shortcut actions · `Troubleshooting` copy · `Copy environment info` · `Nothing has been copied.` · `Copied to the clipboard.` |
| Donate view | `Support the project` summary · `Test on real hardware` · `Send a compatibility report` · `Share the app` · `Funding` · `Donation links are not open yet.` |
| Dialogs | `Engine verdict` only. Settings and About are views in 2.1 |

`<step>` is either a §16.2 engine stage name or a §16 job name — never a string invented to fit the
width of a bar.

---

## 11. Component state matrix

| App state | Report row | ACPI row | Output row | Check | Combo | Build | Cancel | Open folder | Collect/Read ACPI |
|---|---|---|---|---|---|---|---|---|---|
| S1 empty | on | on | on | on | off (empty) | **off** | hidden | **off** | on |
| S2 checking | off | off | off | off | off | off | **on, visible** | off | off |
| S3 verdicts | on | on | on | on | on | **on** | hidden | off | on |
| S4/S5 fatal, rejected | on | on | on | on | off | **off** | hidden | off | on |
| S6 build blocked | on | on | on | on | on | **on** | hidden | off | on |
| S7 building | off | off | off | off | off | off | **on, visible** | off | off |
| S8 done | on | on | on | on | on | on | hidden | **on** | on |
| S9 cancelled | on | on | on | on | on | on | hidden | off | on |
| S10 unexpected | on | on | on | on | on | on | hidden | off | on |

`on`/`off` here means enabled/disabled, never shown/hidden — no state in this table hides a card,
and the open view never disables a control. `Cancel` is the one control whose *visibility* changes:
it exists only while a job is running, because a Cancel button that does nothing is a lie. The two
optional link buttons follow host capability: `Collect hardware` is drawn on Linux and Windows,
`Read ACPI tables` on Linux only, and neither is drawn where the capability is missing — a disabled
button would promise a feature the build does not have.

`Settings`, `Help` and `Donate` do not change the session state matrix. Their controls stay enabled
while a job runs: the theme picker is local, the diagnostics button only reads paths and the last
error code, and neither touches the engine. Opening one of these views during a build does not move
the window off the build; when the job starts, the window still follows it to `Build EFI`.

---

## 12. Explicitly not allowed in a mockup

§16 is the machine-readable string allowlist and §17 records drift that generated mockups have
already been caught doing. Both are checked by `tests/test_mockup_spec_allowlist.py`, which parses
§16 and refuses any string that is not a literal in `src/` — so this document cannot quietly fall
behind the code, and a mockup built from it cannot contain a sentence the app would never print.

- A three-column Devices table. 2.0 has four headers, always; the fourth is the target-relative
  `Status` pill (§7.5). But the pill may only say one of the four labels in §16 — never
  `Compatible`, `Works`, `Best effort`, a bare check mark, or a fifth column such as `In build`.
- A verdict column painted red for `Unsupported`. The support column is plain text; the pill carries
  the judgement, and `Unsupported` is not necessarily a blocked build.
- A status bar along the bottom edge, or a `Ready` line anywhere. 2.0 removed it.
- A toolbar across the top, a native menu bar, a hamburger, or a collapsible rail. `Settings`,
  `Help` and `Donate` live at the bottom of the fixed 232 px rail, and each opens a page.
- A Settings or About modal over the dashboard. 2.1 replaced both with the Settings view; the only
  modal left is `Engine verdict`.
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
- Flat white boxes on a flat grey background, or drop shadows. The shell is translucent over a
  painted pastel wallpaper, and depth is a white border and a background step.
- Purple pill buttons, a second gradient family, or gradient card headers. One blue gradient covers
  the primary button, the active nav item and the progress fill; only the app logo has its own.
- Icons from a third-party icon font or library, or hand-drawn approximations of the app's icons.
  The set is the inline SVGs in `src/blackdream/ui/icons.py`.
- `OpenCore, made simple.` or any upstream tagline. The product line is `OpenCore EFI builder.`
- A "Download OpenCore" button, a mirrors/proxies settings screen, or a picker for the OpenCore
  version — the engine pins these.
- Any mention of writing to the EFI partition, mounting disks, or a terminal prompt. v1 emits a
  folder.
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
| Window chrome | identical frameless shell on all three platforms; the app draws the traffic lights, drag handle and resize grip itself | same | same |
| Drag window | header drag uses the system move gesture where available; double-click maximizes | same | same |
| Default output | `~/Library/Application Support/blackdream/builds/<stamp>/EFI` | `%LOCALAPPDATA%\blackdream\builds\<stamp>\EFI` | `~/.local/share/blackdream/builds/<stamp>/EFI` |
| Artifact cache | `~/Library/Application Support/blackdream/cache` | `%LOCALAPPDATA%\blackdream\cache` | `$XDG_DATA_HOME/blackdream/cache` |
| Search keycap | `⌘ K` | `Ctrl K` | `Ctrl K` |
| Settings / Help shortcuts | `⌘ ,` · `F1` | `Ctrl ,` · `F1` | `Ctrl ,` · `F1` |
| Utility views | same three pages; search pill hidden | same | same |
| Drop target | whole window for `.json` | whole window | whole window (Wayland: the file-chooser fallback must be shown) |
| Reveal folder | Finder | Explorer | the session's file manager |
| Collect hardware | absent — load a report exported on the target PC | Hardware Sniffer, downloaded, SHA-256 pinned, run with `-e -o` | local sysfs/DMI scan, no elevation, no network |
| Read ACPI tables | absent | absent — the scan adopts the tables Hardware Sniffer exports | privileged helper via polkit's own window |
| Toolchain | `iasl-stable`/`iasl-legacy` and `macserial`, universal Mach-O, digest-pinned | PE binaries, digest-pinned, installed outside the package | ELF binaries, digest-pinned, installed outside the package |

---

## 14. Accessibility and text rules

- All three failure surfaces (card, summary panel, log) are selectable text; error copy must be
  copy-pasteable, because it is what gets pasted into a bug report.
- Contrast: the error foreground on the error fill and the log foreground on the log fill both
  exceed 7:1 in each theme. Do not lighten them for aesthetics.
- Never colour alone: pills pair an icon with a label, stage rows pair an icon with a state name,
  field states pair an icon with a tooltip.
- The Devices table must survive a 200 % UI scale by wrapping the `macOS support` column, never by
  truncating a device name mid-token. The full name is always in the row tooltip.
- Engine text is untrusted content: device names come from a report written by another program, and
  remote filenames come from GitHub. Mockups should show long, awkward names
  (`Intel Cannon Lake-HDMI`, `Realtek RTL8821CE-CU4AA_921E PCIe Network Card`) rather than tidy ones.
- No string is ever split across two labels to fake a line break; ranges use ` - ` (hyphen), not an
  en-dash, because the value is also printed to logs.
- The theme picker, the diagnostics button and all six sidebar items are keyboard-reachable. The
  theme picker changes the theme immediately; it does not need a Save button, and no utility view
  has one.

---

## 15. Host actions, utility screens and planned screens

**S14 Collect hardware from this machine.** A link button with a small waveform icon in
`① Select files`, below the two path rows, drawn wherever the host can produce a report — Linux and
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

**S16 Read ACPI tables.** The Linux-only link button, under the ACPI row, labelled
`Read ACPI tables` with the tooltip `Read the firmware tables from this machine; asks for
administrator rights` — the tooltip names the cost because the cost is a system authentication
window the user was not expecting. Clicking it starts the job `Reading ACPI tables`: controls
disable, `Cancel` appears, the log gets `== Reading ACPI tables ==` and then one line per table, and
the task box names the job. There is no progress bar and no percentage: the wait is a human deciding,
not work being measured.

On success the ACPI row fills with `<report folder>/ACPI` and an ok check-circle with
`<n> .aml file(s) found`. On refusal (`acpi.refused`) or on a machine where the privileged helper is
not installed (`acpi.helper_missing`) the error card says so and the row stays a hollow dot with
`No folder chosen` — a denied authorisation is not a hardware fault and must not be drawn as one.
In a source checkout the helper is *never* installed, because root must not execute a file the user
can edit, so this is the state a developer sees first; the card gives the one-time install command
rather than pretending.

Draw the authentication window as the desktop's own, outside the app's frame, or not at all. It is
polkit's window, not ours, and no BlackDream mockup may contain a password field: the app never asks
for a secret, which is the whole difference from the terminal route it replaces.

**S17 Settings.** A full view, not a modal. Four cards in two rows.

- `Appearance` (left, stretch 2) carries one control: a `Theme` label and a `Light` / `Dark` combo.
  The change applies immediately, is stored in `QSettings` under `appearance/dark`, and the hint
  says `The theme applies immediately and is remembered for the next launch.` There is no Save
  button and no Apply button.
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

**S18 Help.** A full view with four cards. `Quick start` is a four-row list with 28 px tiles:
`Load a report`, `Choose a release`, `Check compatibility`, `Build the folder`; each row is a 13 px
title over a 12 px muted sentence. `Keyboard shortcuts` is a two-column list of action and keycap:
`Search devices`, `Open a report`, `Compatibility`, `Build EFI`, `Logs`, `Settings`, `Help`, `Quit`.
The keycap uses `Ctrl` (`⌘` on macOS) and `F1` for Help. `Troubleshooting` is four icon rows about
the red card, a refused ACPI read, a rejected report and saving the log. `Diagnostics` explains that
the copied summary contains the app version, platform, theme, cache paths and last error code, and
no report contents; its `Copy environment info` button writes that text to the clipboard and its
muted note changes from `Nothing has been copied.` to `Copied to the clipboard.`. No external links.

**S19 Donate.** A full view. `Support the project` runs full width: `BlackDream is free and MIT
licensed. It has no account, no telemetry and no ads.` Below it is a 2 × 2 grid of cards, each with
a 28 px icon tile in its header: `Test on real hardware` (`monitor`), `Send a compatibility report`
(`file`), `Share the app` (`share`), `Funding` (`heart`). The first three give ways to help without
money. `Funding` says `Donation links are not open yet. No payment button is shown until there is a
page behind it.` — and there is no payment button, field, tier or licence key anywhere on the view.
No funding URL exists yet; a mockup that invents one is wrong.

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
`src/blackdream/core/job_runner.py`, `src/blackdream/hardware/acpi.py` and `src/ocengine/fatal.py`
on 2026-10-22. Paste this block into the mockup tool and require every visible string to appear in
it. `«…»` marks a value the code fills in at runtime — invent a plausible one, never a new label.

```json
{
  "window": {
    "title": "BlackDream",
    "default_size": [
      1440,
      940
    ],
    "minimum_size": [
      1240,
      800
    ]
  },
  "views": [
    "Compatibility",
    "Build EFI",
    "Logs",
    "Settings",
    "Help",
    "Donate"
  ],
  "sidebar": {
    "brand": "BlackDream",
    "hint": "OpenCore EFI builder.",
    "secondary": [
      "Settings",
      "Help",
      "Donate"
    ],
    "window_controls": [
      "Close",
      "Minimize",
      "Zoom"
    ]
  },
  "nav_icons": {
    "Compatibility": "pulse",
    "Build EFI": "build",
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
    "sun": "sun",
    "moon": "moon",
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
      "Hardware Compatibility",
      "Build EFI Folder",
      "Engine Log",
      "Settings",
      "Help",
      "Support BlackDream"
    ],
    "subtitles": [
      "Review what macOS can run on this machine, then build the EFI folder.",
      "Watch the engine work and open the folder when it is done.",
      "Every message the engine reported, in order.",
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
      "Settings",
      "Help",
      "Donate"
    ]
  },
  "theme_toggle": [
    "Switch to the dark theme",
    "Switch to the light theme"
  ],
  "card_titles": [
    "Select files",
    "macOS version",
    "Actions",
    "Detected devices",
    "Device details",
    "Build progress",
    "Engine log",
    "Appearance",
    "About",
    "Storage",
    "Downloads and safety",
    "Quick start",
    "Keyboard shortcuts",
    "Troubleshooting",
    "Diagnostics",
    "Support the project",
    "Test on real hardware",
    "Send a compatibility report",
    "Share the app",
    "Funding"
  ],
  "card_hints": [
    "Provide your hardware report and any optional ACPI tables.",
    "Choose the macOS version you want to build for.",
    "The EFI is a folder; nothing is mounted or written to a disk.",
    "No report loaded yet.",
    "Detected «n» devices from your hardware report.",
    "No devices were graded from this report.",
    "Step, transfer and timing from the engine.",
    "Building your OpenCore EFI folder.",
    "The EFI folder is ready.",
    "The theme applies immediately and is remembered for the next launch.",
    "Where downloads and the tools that read firmware live.",
    "Four steps from a report to an EFI folder."
  ],
  "empty_notes": [
    "Load a report to see this machine's devices and what macOS does with them.",
    "The engine rejected this report before grading any device."
  ],
  "fields": {
    "labels": [
      "Hardware report",
      "ACPI tables (optional)",
      "Output folder"
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
    "Rejected"
  ],
  "links": {
    "buttons": [
      "Collect hardware",
      "Read ACPI tables",
      "View details",
      "Copy details",
      "Show engine verdict"
    ],
    "tooltips": [
      "Scan this machine and write a Report.json",
      "Scan this machine with Hardware Sniffer; downloads and runs the verified tool",
      "Read the firmware tables from this machine; asks for administrator rights"
    ]
  },
  "buttons": [
    "Check compatibility",
    "Build EFI folder",
    "Cancel",
    "Open EFI folder",
    "Save log…"
  ],
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
    "class_width": 94,
    "support_width": 268,
    "status_width": 124,
    "row_height": 34,
    "minimum_height": 176
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
  "status_pills": {
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
    "height": 21,
    "radius": 10.5,
    "icon_size": 12,
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
        "Limited support on «macOS name»: runs through OpenCore Legacy Patcher."
      ],
      "recommendations": [
        "This release needs OpenCore Legacy Patcher for this device."
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
      "Speed",
      "Step"
    ],
    "metric_icons": {
      "elapsed": "clock",
      "downloaded": "download",
      "speed": "gauge",
      "step": "steps"
    },
    "metric_idle": {
      "downloaded": "0 B",
      "step": "0/«total»"
    },
    "task_title": "CURRENT TASK",
    "task_idle": [
      "Waiting to start",
      "Nothing is downloading.",
      "No transfer in progress."
    ],
    "task_ready": [
      "Ready to build",
      "Choose a macOS version, then build the EFI folder."
    ],
    "task_running": "Running…",
    "task_done": [
      "EFI folder ready",
      "Build complete."
    ],
    "task_cancelled": "«step» cancelled.",
    "task_failed": "«step» failed.",
    "transfer": [
      "«done» of «total»",
      "«size» downloaded",
      "«product» · «size» · «rate»"
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
    "Writing the EFI folder"
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
      "«count» ACPI tables read from firmware"
    ],
    "copy_tooltip": "Copy the log",
    "save_caption": "Save log",
    "save_filter": "Log files (*.log);;All files (*)"
  },
  "dialogs": {
    "engine_verdict": {
      "title": "Engine verdict",
      "body": "«device»\n\nEngine verdict: «support»\nStatus: «status»\n\n«detail»\n«recommendation»"
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
        "On Linux, press Read ACPI tables (asks for administrator) on the Compatibility view."
      ],
      "non_recoverable": false
    },
    {
      "code": "acpi.unsupported",
      "title": "These firmware tables cannot be read from inside the app",
      "detail": "Dumping tables from sysfs is a Linux feature; this is «platform».",
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
        "Try again. If it repeats, this machine does not expose a readable DSDT even to root.",
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
        "Light",
        "Dark"
      ],
      "hint": "The theme applies immediately and is remembered for the next launch."
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
      "Diagnostics"
    ],
    "quick_start_hint": "Four steps from a report to an EFI folder.",
    "quick_start": [
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
        "action": "Compatibility",
        "keys": "Ctrl 1",
        "mac": "⌘ 1"
      },
      {
        "action": "Build EFI",
        "keys": "Ctrl 2",
        "mac": "⌘ 2"
      },
      {
        "action": "Logs",
        "keys": "Ctrl 3",
        "mac": "⌘ 3"
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
      "body": "Copy a short summary for a bug report: app version, platform, theme, cache paths and the last error code. No report contents are included.",
      "button": "Copy environment info",
      "idle": "Nothing has been copied.",
      "copied": "Copied to the clipboard."
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
  }
}
```

## 17. Known drift in AI-generated mockups — check the output against this before accepting it

Each row was produced by a model reading an earlier version of this document or the reference render,
and is contradicted by running code. None is a stylistic choice you can keep.

| Invented by the mockup | Reality |
|---|---|
| Three columns, with the status idea rejected as "a second judgement" | 2.0 deliberately has four. `Status` is not a second opinion: `verdicts.target_status` answers "does this device work on the *selected* release?" from the engine's own tuples. Changing the combo changes the pills. |
| `Supported ✓` / `Best effort` / `Compatible` pills, or an icon-only pill | Exactly four labels: `Supported`, `Limited support`, `Not supported`, `Not graded`, each with an icon **and** text. The labels are literals in `verdicts.py`. |
| A red `Unsupported` row, or "Unsupported blocks the build" | The support column is plain text and an unsupported device does not block a build. Only the six fatal cards do. |
| `Incompatible GPU detected… You can still build an EFI folder` | `gpu.unsupported` is `recoverable = False` and blocks the build. There is no "still buildable" GPU path. Copy is fixed in §16. |
| `Building OpenCorePkg`, `Finalizing EFI folder` | The five names in §7.8. The engine emits exactly those and nothing else. |
| A horizontal numbered stepper, or card numbers ① ② ③ read as "step 1/2/3" | The three numbers label setup cards; they are not a wizard. `Step 2 of 5` is a status label on the engine's stage list. |
| Glyph marks `· ▶ ✓ ✗ –` in the stage list | SVG icons `dot`, `spinner`, `check-circle`, `x-circle`, `minus`. A text tick cannot follow the theme colour or the DPI scale. |
| A `Build steps` card next to the progress bar | One card, `Build progress`: stages, current task, metrics and bar together. |
| `macOS Tahoe 26 [suggested]` with two spaces and brackets | `macOS Tahoe 26  ·  suggested, needs OCLP` — two spaces, a middle dot, two spaces, comma-joined badges. |
| Per-stage timers forbidden | Allowed and built: each stage row has an elapsed time on the right (`—` until it runs). The old rule was 1.1. |
| `OpenCorePkg: 62% at 1904 kB/s` only, never MB/s | The rate formatter prints `KB/s` below 1 MiB/s and `1.9 MB/s` at or above it. Copy §7.8 exactly. |
| `OpenCorePkg: 62% at 1.9 MB/s` for a slow transfer | Below 1 MiB/s it must be whole `KB/s`, e.g. `904 KB/s`. |
| A green `Built completed successfully` card | S8 is a full progress card, an enabled `Open EFI folder`, and `Done: <path>` in the log. No success card, no modal. |
| A bottom status bar reading `Ready` / `EFI folder written to…` | 2.0 removed the status bar. `QMainWindow`'s bar still exists but is hidden; do not draw it. |
| `Build EFI folder` as a *card* title | The card is `Actions`. `Build EFI folder` is the primary button inside it. |
| A native menu bar with `File` and `Help` | None. `Settings`, `Help` and `Donate` are sidebar items at the bottom of the rail. |
| A `Settings` or `About` modal floating over the dashboard | Both are the Settings view, one of the six pages. The only modal in the app is `Engine verdict` from the compatibility table. |
| A help dialog with a close button, or `Open documentation` / `Report a bug` links | `Help` is a full view with in-window quick start, shortcuts, troubleshooting and diagnostics. No external URL ships. |
| A Donate view with a payment button, amount tiers, a donation link, or a licence-key field | There is no funding URL yet. Donate carries four non-money cards and one honest `Funding` note; it has zero buttons and zero inputs. |
| A fake Windows title bar, or traffic lights only on a macOS frame | The app is frameless on every platform and draws its own traffic lights, drag handle and resize grip. |
| Flat white cards, grey background, drop shadows | Glass: translucent shell and sidebar over a pastel gradient with blobs. No shadow anywhere. |
| Purple pill buttons, gradient headers | One blue gradient: primary button, active nav item, progress fill. The logo has its own indigo gradient. |
| Icons beside sidebar items forbidden (1.1 rule) | Icons are required: `pulse` / `build` / `logs` in the nav, plus `gear` / `help` / `heart` for Settings, Help and Donate. They come from the inline SVG set, never a third-party library. |
| `OpenCore, made simple.` | Upstream's tagline. Ours is `OpenCore EFI builder.` — in the sidebar, never replaced. |
| A `Use example report` button | No sample data ships; the only inputs are drop and browse. |
| A password field, or an in-app admin prompt | The only authentication is polkit's own window for the Linux ACPI read, outside the app's frame. |
| A second log pane on the `Logs` view | The same widget moves and grows; two logs would mean two buffers to keep in sync. |
| `⚠️` / `✅` emoji in verdicts | No emoji anywhere, at any size, in any theme. |

If a generated mockup survives §17 but still drifts, the failure is in the instruction, not the
model: send §16 alone with *"render S7, use only these strings"* rather than the whole document.
