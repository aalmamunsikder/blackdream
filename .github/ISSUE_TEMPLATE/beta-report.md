---
name: Beta report
about: Something BlackDream did, or a workflow you could not finish, on a beta build.
labels: bug
---

<!--
Fill in what you can and delete the rest. Nothing here is uploaded automatically:
BlackDream has no telemetry, no account and no update check, so this form is the
only feedback path. Read your answers before posting — a Report.json names your
machine, and an engine log can quote paths and device names you may not want
public. Never post an SMBIOS serial, MLB, UUID or ROM value.
-->

**BlackDream version**
<!-- The version line from Help ▸ About, e.g. 0.9.0-beta.4 -->

**Operating system and build**
<!-- e.g. Ubuntu 22.04 on X11, Fedora 40 on Wayland, Windows 11 23H2, macOS 14.7 on Intel -->

**Which workflow did you attempt?**
- [ ] Installer (download, verify, write to USB)
- [ ] Compatibility (open or collect a report, read the verdicts, compare)
- [ ] Build EFI (generate the folder, watch the stages, cancel)
- [ ] Configure EFI (edit, validate, serials, save, revert)
- [ ] Folder checks / manifest / diagnostic bundle
- [ ] Something else: 

**Expected versus actual**


**Steps to repeat, and does it repeat every time?**
1. 
2. 

**Error code shown on the red card, if any**


**Severity, as you judge it**
<!--
P0 blocker  wrong-target write, data loss, a verification bypass, config corruption,
            a leaked serial, or a crash that makes the app unsafe to use
P1 high     a core workflow fails on a supported platform, or recovery behaves wrongly
P2 normal   confusing copy, a UI inconsistency, a recoverable edge case
P3 polish   cosmetic only, no usability or accessibility impact
-->

- [ ] P0 — unsafe to use
- [ ] P1 — a workflow fails
- [ ] P2 — recoverable or confusing
- [ ] P3 — cosmetic

**Logs**
<!-- Attach the engine log saved from the Logs page. If the app closed, attach the
     newest crash-report file whose folder is listed by Help ▸ Copy environment info.
     Help ▸ Save diagnostic bundle… redacts identity values and the home folder;
     read its preview before you attach it. -->

- [ ] Engine log attached
- [ ] Crash report attached, if the app closed
- [ ] `Help ▸ Copy environment info` output pasted below

```text

```

**Does any attachment name your machine?**
<!-- Say which: device names, volume labels, home folder paths, usernames. -->

