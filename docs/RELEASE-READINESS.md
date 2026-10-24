# Release readiness record — 0.9.0-beta.3, Stage A

Recorded 2026-10-24 against `BlackDream_Beta_Release_Recommendation.md` (2026-10-23),
which was written for specification v3.3 and suggested the identifier `0.9.0-beta.1`.
This build is v3.6 / `0.9.0-beta.3`, so the recommendation's *screen numbers and version
label are stale*; its gates are not, and they are judged here one by one.

Stage A is the internal release-candidate stage: prove the critical workflows before
external testers are invited. This document is that proof, in the open, so a reviewer can
check every claim against the tree.

Stage A passed and `v0.9.0-beta.3` was published on 2026-10-24. Section 7 records what the
published bytes showed afterwards, and what was deliberately left as published.

Statuses used below:

* **Proved** — a named automated test in this repository's suite covers the behaviour.
* **Run** — executed by hand on a real machine, bundle or artifact this cycle.
* **Not proved** — nothing here demonstrates it, and what would.

The suite is 855 tests (853 pass, 2 skip: one needs `pefile` to read a Windows version
resource, one only runs where artifacts have been built). `docs/RELEASE-NOTES.md` states
that number and a test pins it to `pytest --collect-only`, so a claim about coverage
cannot drift from the coverage.

## 1. Stage A's own checklist (section 3 of the recommendation)

| Stage A bullet | Status | Evidence |
| --- | --- | --- |
| Reproducible artifacts for each supported platform | Run | the `Build beta artifacts` workflow built the Linux, Windows and Intel-macOS artifacts from the final commit of this cycle, and every leg's own audit step passed |
| Complete automated suite plus the UI microcopy allowlist test | Proved | 855 collected, 853 passed, 2 skipped; `tests/test_mockup_spec_allowlist.py` is 31 of them |
| The P0 checklist, including fault injection for installer writes and config saves | Mapped below | every gate in section 2; the injected faults are the second-swap failure, the cancelled write, the refused swap, the externally changed file and `test_a_value_plist_cannot_hold_fails_the_save_before_it_touches_the_disk` |
| The installer uses Apple's trust chain; pinned runtime binaries verified before they run | Proved | `test_the_real_apple_chunklist_verifies`, `test_asset_urls_must_stay_on_apple_cdn`, `test_a_tampered_tool_is_refused_before_it_runs`, `test_unpinned_download_still_refused` |
| Upgrade, install and uninstall behaviour; user cache and output folders not deleted | Run | the audited `.deb` was installed and then removed against a fake root inside a throwaway user namespace, the development host untouched: 472 paths appeared, 459 went away with the removal, and the thirteen that stayed are `dpkg`'s own database. Everything planted beside the package survived — another package's doc, an `index.theme` inside the shared `hicolor` tree, a plist, a settings file, an EFI output folder, an unrelated application under `/opt` — and `dpkg` named the reason: `directory '/usr/share/icons/hicolor' not empty so not removed`. The helper and its polkit action read back `root:root` `0755` and `0644`, and writable state lives in `$XDG_DATA_HOME/blackdream`, never inside the root-owned `/opt/blackdream`. **Still not proved:** a desktop session answering polkit's prompt for the installed helper. |
| Screenshots for the built states compared against the reject list | Run | all 14 window frames and the diagnostics dialog were re-rendered from this build at their own sizes, the other five dialogs came back byte-identical, and `docs/UI-MOCKUP-SPEC.md` §17 is what the allowlist test refuses |

## 2. Section 4 — P0 gates

### A. Installer integrity and USB safety

| Gate | Status | Evidence |
| --- | --- | --- |
| Recovery metadata over HTTPS, signed chunklist verified against Apple's key | Proved | `test_the_real_apple_chunklist_verifies` (a chunklist downloaded from Apple, checked in as a fixture), `test_an_unsigned_chunklist_is_refused`, `test_a_chunklist_with_a_broken_signature_is_refused`, `test_a_truncated_chunklist_is_refused`, `test_asset_urls_must_stay_on_apple_cdn` |
| Every image chunk verified while copied | Proved | `test_verify_image_accepts_every_chunk_and_reports_the_file_digest`, `test_verify_image_refuses_a_flipped_byte`, `test_verify_image_refuses_a_short_or_long_file` |
| A partial download resumes; only a verified image is cached | Proved | `test_a_partial_image_resumes_where_it_stopped` (a `Range` request answered `206`), `test_a_server_that_ignores_the_range_restates_the_whole_image` (`200` restarts from zero), `test_cached_recovery_ignores_a_size_mismatch` |
| Releases keep separate images | Proved | `test_every_release_has_its_own_cache`, `test_cached_recovery_refuses_a_manifest_for_another_release`, `test_choosing_another_release_swaps_the_verified_image` |
| No drive is preselected | Proved | `test_the_view_scans_usb_once_and_never_preselects_a_drive` |
| Write enabled only with a verified image, a complete EFI and a chosen drive | Proved | `test_write_needs_the_image_the_efi_and_a_chosen_drive` |
| The confirmation names the volume and what is replaced | Proved | `test_the_write_confirmation_names_the_volume_and_defaults_to_cancel` |
| Never formats, mounts or opens a block device | Proved | `test_the_app_never_formats_mounts_or_opens_a_disk` reads every command literal and every `open()` literal in the app's source and refuses a formatting, partitioning, mounting or whole-disk verb; `diskutil list`/`info` are the only disk commands allowed |
| Target identity re-checked at the moment of writing | Proved | `test_a_drive_swapped_behind_the_confirmation_is_refused`, `test_the_system_volume_is_refused_even_when_a_scan_offers_it` |
| Unrelated files on the volume stay put | Proved | `test_write_installer_copies_and_preserves_unrelated_files` |
| Second-half failure restores the first; cancellation keeps the previous installer | Proved | `test_write_installer_rolls_back_when_the_second_swap_fails`, `test_write_installer_leaves_the_previous_efi_when_cancelled`; each also asserts no `.blackdream-stage-*` directory is left on the volume |
| Disconnect, no space, permission error, volume removal | Partly proved | Space and refusal paths are proved (`test_a_drive_without_room_is_refused_before_anything_is_copied`, `test_copy_tree_refuses_a_symlink`, `test_copy_tree_refuses_a_fifo`). A stick pulled mid-copy is **not proved**: every USB test above runs against a temporary directory, because a real volume cannot be detached on demand inside CI. This is the one row a Stage B tester has to fill. |

### B. EFI output and build lifecycle

| Gate | Status | Evidence |
| --- | --- | --- |
| Build output is a folder; no code path touches an EFI partition | Proved | `test_the_app_never_formats_mounts_or_opens_a_disk` again — the sweep covers the whole app, not only the installer — plus `test_a_foreign_non_empty_folder_is_refused_and_left_intact` |
| A foreign non-empty folder is refused, never cleaned | Proved | `test_a_foreign_non_empty_output_folder_is_refused_before_any_work`, `test_a_foreign_non_empty_folder_is_refused_and_left_intact` |
| Existing output replaced only on the app's own marker | Proved | `test_a_previous_blackdream_build_is_replaced`, `test_the_absent_marker_reads_as_nothing` |
| Five stages in order, metrics consistent with engine events | Proved | `test_build_stage_names_match_the_pipeline`, `test_stage_icons_match_the_window`, `test_a_stage_event_updates_the_existing_rows`, `test_rate_and_progress_copy_matches_the_dashboard` |
| Progress and task box recover from every end state | Proved | `test_cancel_and_failure_statuses_survive_the_state_refresh`, `test_a_thread_that_never_unwinds_is_abandoned_not_killed`, `test_a_failed_build_step_names_the_step_not_the_last_product`, `test_cancellation_stops_a_running_job_and_releases_the_buttons` |
| A second job cannot start on a running engine | Proved | `test_a_second_job_is_refused_while_the_first_is_running`, `test_a_report_cannot_replace_the_one_a_running_step_is_using` |
| Cancellation marks the active stage and hides the error card | Proved | `test_cancellation_is_cooperative_and_reports_cancelled` with the UI assertions in `test_cancellation_stops_a_running_job_and_releases_the_buttons` |
| A fatal error leaves the app open and shows no stale rows | Proved | `test_a_fatal_verdict_is_a_screen_not_an_exit`, `test_a_bare_engine_exception_no_longer_quits_the_app`, `test_a_fatal_report_clears_everything_the_previous_one_showed`, `test_a_stale_report_is_not_mistaken_for_this_scans_output` |

### C. Configuration editor data safety

| Gate | Status | Evidence |
| --- | --- | --- |
| Opening never alters; edits stay in memory | Proved | `test_a_round_trip_preserves_order_and_binary_values`, `test_an_inline_edit_is_only_saved_when_save_is_pressed` |
| Nothing is written until Save | Proved | the same test, plus `test_undo_and_redo_walk_snapshots_without_touching_the_file` |
| Save is atomic and keeps `config.plist.bak` | Proved | `test_save_keeps_the_previous_file_as_a_backup`, `test_atomic_write_replaces_an_existing_file` |
| External change detected, Cancel is the default | Proved | `test_an_external_change_is_detected`, `test_saving_over_an_external_change_asks_first` |
| Revert reloads the file and discards unsaved edits | Proved | `test_an_external_change_is_reported_and_revert_reloads`, `test_a_validation_result_clears_after_every_kind_of_edit` |
| Key order and unknown keys survive | Proved | `test_key_order_is_part_of_what_is_preserved_by_history`, `test_a_round_trip_preserves_order_and_binary_values`, `test_missing_standard_keys_can_be_added_without_losing_unknown_ones` |
| Value types and every byte of `data` preserved | Proved | `test_text_view_of_data_is_lossless_for_every_byte`, `test_text_view_rejects_text_that_would_change_the_bytes`, `test_type_names_distinguish_booleans_from_integers` |
| Preset uses the pinned schema, appends, does not duplicate | Proved | `test_inserting_a_preset_creates_its_target_and_never_duplicates`, `test_inserting_the_same_preset_again_selects_the_existing_entry`, `test_a_preset_that_does_not_fit_the_document_is_refused` |
| Validation runs on a temporary copy | Proved | `test_validation_checks_a_temporary_copy_and_leaves_the_file_alone` — the copy holds the in-memory state, sits outside the config's own folder, is deleted afterwards, and the file on disk keeps its original bytes |
| A verdict goes stale after any edit, add, remove, move, serial write or revert | Proved | `test_a_validation_result_clears_after_every_kind_of_edit` walks all seven mutation kinds |
| Serials need confirmation and never reach the log | Proved | `test_generate_serials_confirms_before_touching_the_document`, `test_generated_smbios_values_never_reach_the_engine_log` |
| An invalid or unreadable config never crashes or overwrites | Proved | `test_a_missing_or_unreadable_report_is_refused_before_grading`, `test_a_non_dictionary_root_is_refused`, `test_a_missing_file_is_read_as_a_typed_failure`, `test_a_value_plist_cannot_hold_fails_the_save_before_it_touches_the_disk` |

### D. Privacy, diagnostics and safe UI state

| Gate | Status | Evidence |
| --- | --- | --- |
| No sign-in, telemetry, ads or update check | Proved | `test_the_bundle_code_imports_nothing_that_can_reach_the_network`, `test_the_vendored_scanner_never_elevates_or_reaches_the_network`, and `packaging/verify-artifacts.py`, which reads the finished artifacts back and refuses the build if a runtime binary leaked into the wheel or sdist or a notice is missing |
| Environment info excludes report contents | Proved | `test_environment_names_software_not_the_user`, `test_scrub_removes_secrets_and_the_home_path` |
| Engine text is escaped, never rich text | Proved | `test_report_text_cannot_format_the_window`, `test_a_device_name_is_rendered_as_text_not_markup` |
| State is named in words, not only colour | Proved | `test_mockup_spec_allowlist` pins the visible labels; the status column carries the label text (`test_the_status_column_grows_to_fit_its_widest_label`) |
| No password field; polkit prompts outside the app | Proved | `test_the_helper_refuses_to_run_unprivileged`, `test_a_refusal_from_polkit_keeps_its_own_reason`, `test_a_helper_the_calling_user_can_edit_is_never_offered` |
| A rejected report clears the whole view | Proved | `test_a_fatal_report_clears_everything_the_previous_one_showed`, `test_a_missing_or_unreadable_report_is_refused_before_grading` |

## 3. Section 5 — P1 release quality

| Check | Status | Evidence |
| --- | --- | --- |
| Launch, open a report, browse, reveal a folder, save a log on each shipped platform | Run | each CI leg runs the relocated bundle's `--version` and `--smoke` path; the Linux bundle was launched from the downloaded artifact by hand |
| Native title bar, menus and window controls per platform | Proved | `test_the_window_uses_the_native_frame`, `test_the_menu_bar_is_visible_and_drives_the_views` |
| Linux X11 and Wayland smoke-tested, file-chooser fallback | Run, with one gap | the downloaded CI bundle was started on this machine's real Wayland session with `QT_QPA_PLATFORM=wayland` and again with `=xcb`; both printed `smoke ok: platform=…` and exited 0, and the bundle ships both `libqwayland.so` and `libqxcb.so`. The documented Wayland file-chooser fallback for drag-and-drop is **not proved** — it needs a human to drop a file. |
| Windows Hardware Sniffer download, digest check, run, report adoption | Proved in code | `tests/test_windows_collect.py` (8 tests) parses and adopts a recorded Sniffer run, including `test_a_stale_report_is_not_mistaken_for_this_scans_output`; the digest is pinned and checked by `tests/test_artifact_digests.py`. Not run on real Windows hardware. |
| Linux non-elevated scan and separate polkit ACPI read, refusal not shown as a fault | Run + Proved | the ACPI dump was read from real firmware through polkit on this machine; `test_a_refusal_from_polkit_keeps_its_own_reason` proves a refusal keeps its own wording |
| macOS shows neither collection nor ACPI link | Proved | `capabilities_follow_the_host[darwin-...]`, `test_the_window_draws_only_the_actions_this_host_has` |
| Runtime binaries are platform-shaped and pinned; nothing runs before verification | Proved | `an_iasl_asset_and_a_name_allowlist_exist_for_each_host`, `every_host_has_a_pinned_macserial`, `test_a_tampered_tool_is_refused_before_it_runs`, `test_an_archive_member_with_the_wrong_digest_is_never_installed`, `test_the_pinned_archive_installs_only_the_verified_member` |
| System, Light and Dark themes; the log stays dark | Proved | `test_system_mode_follows_the_desktop`, `test_the_theme_button_remembers_an_explicit_choice`, `test_the_old_boolean_appearance_key_still_migrates` |
| Minimum size, page scrolling, dashboard stacking, table resizing | Proved | `test_a_split_stacks_before_it_clips`, `test_the_status_column_grows_to_fit_its_widest_label` |
| 200 % UI scale without mid-token truncation | Not proved | needs a desktop session at that scale; the offscreen suite cannot measure font metrics. `test_a_long_key_path_is_not_elided_in_the_preview` covers one instance that was found by eye: the Windows leg measured a key path at 468 px where Linux measured 237, so the assertion now asks only that the column honour its content up to the cap, because a pixel count is a fact about one machine's font. |
| Keyboard reach and visible focus rings | Partly | shortcuts and menu navigation are generated and pinned (`test_help_shortcuts_are_generated_by_the_window`, `test_the_menu_bar_is_visible_and_drives_the_views`); focus rectangles are **not measured** by any test. |
| Log filtering, copy, save, long lines, dropped-buffer warning | Proved | the log-page tests in `test_ui_native_shell.py`/`test_gui_slice.py`, including the dropped-lines warning |
| Screens and labels match the current spec allowlist; nothing obsolete remains | Proved | `tests/test_mockup_spec_allowlist.py` (31 tests) pins shipped UI copy to `docs/UI-MOCKUP-SPEC.md` §16 and rejects the §17 list |

## 4. Section 6 — test matrix as actually covered

Do not read a green suite as hardware coverage. This is what each cell really means.

| Workflow | Linux x86_64 (this host) | Windows | macOS Intel | CI legs |
| --- | --- | --- | --- | --- |
| Launch, menus, native frame, theme | Run | Not run on hardware | Not run on hardware | bundle starts and smoke-tests |
| Open/drop a report, view compatibility | Run (real machine + recorded corpus) | Not run on hardware | Not run on hardware | suite |
| Collect hardware from this machine | Run | Not run on hardware | Not applicable by design | recorded-fixture tests |
| Read ACPI tables through the app | Run (polkit, real firmware) | Not applicable by design | Not applicable by design | suite |
| Build an EFI folder, and cancel it | Run | Not run on hardware | Not run on hardware | suite |
| Configure: edit, validate, save, backup, revert | Run | Not run on hardware | Not run on hardware | suite |
| Download and verify a recovery image | Run (Apple's servers, real chunklist) | Not run on hardware | Not run on hardware | digest-pinned fixtures |
| Write the installer to a FAT32 stick | **Not run on physical media** | Not run | Not run | directory stand-in |
| Drag-and-drop and the Wayland chooser fallback | X11 only | Not run | Not run | — |

Hardware and report cases, as the recommendation lists them: fully supported, `Limited
support`, ordinary `Not supported`, each fatal condition (no SSE4.x, no GPU, unsupported
GPU, no storage controller, Intel VMD, no compatible controller), missing/empty/unreadable
ACPI, invalid and stale reports, and long device names are all covered by
`test_verdicts.py`, `test_compat_fatal_paths.py`, `test_hardware_acpi.py`,
`test_offline_device_matrix.py` and the recorded report corpus. Slow or interrupted
downloads, unknown content length and cancellation at each stage are covered by
`test_download_robustness.py` and `test_job_runner.py`.

What is **not** covered anywhere: a second physical drive, a drive removed mid-copy, a
machine nobody has reported, and a Mac that boots the result. The last one is out of
scope by design — BlackDream has no boot button and a boot test remains the only proof of
a boot.

## 5. Section 7 — feedback loop

`.github/ISSUE_TEMPLATE/beta-report.md` is the template: version and environment line,
which workflow, expected versus actual, whether it repeats, the error code on the red
card, the saved engine log and crash report, and whether any attachment names the
machine. It carries the four severities with the recommendation's own definitions and
their release actions. There is no form inside the app and nothing is uploaded;
`docs/RELEASE-NOTES.md` and `README.md` say where to send it.

## 6. Section 8 — success criteria

| Criterion | Result |
| --- | --- |
| 100 % of the P0 checks pass on the candidate | Not met as written: 37 of the 38 gates are proved or run, and A12's pull-the-stick-mid-copy case has no evidence. The suite is green (848 passed, 2 skipped, 850 collected). |
| Zero known P0 defects | Met — none open. |
| Every supported OS has one successful end-to-end Compatibility → Build → Configure run | Met on Linux; **not met** on Windows or macOS on real hardware |
| Installer writing passes the safety checklist on every OS where it ships | **Not met** — proved against a directory stand-in only |
| No known data loss, unintended disk mutation, unknown-key loss or unverified write | Met, and now machine-checked (the package-ownership rule and the disk-command sweep) |
| Every reported issue has severity, reproduction, owner, next action | Met for this cycle: the gaps are recorded above with what would close them |
| Help text and the published notes state platform differences and limits | Met — the notes' *Tested on* and *Known issues* sections say so |

## 7. Section 10 — go / no-go

**GO for Stage B (a small closed beta) on `0.9.0-beta.3`.** Stage A's exit gate is met in
every clause but one: no known data-loss or wrong-target-write defect remains, and the
startup smoke test passes on the real session in both QPA platforms; the clause it does
not meet is "every P0 check passes", because A12's physical-media half has no evidence.
That is the half Stage B exists to test — journey 4 in `docs/RELEASE-NOTES.md` asks a
tester to write to a stick they can afford to lose and safely eject it.

The workflow was run again on the last commit that changes anything inside a bundle
(`README.md`, `docs/RELEASE-NOTES.md`, `docs/THIRD-PARTY.md` and `LICENSE` are copied beside
the launcher) and the downloaded bytes were audited on this host: all five digests in
`SHA256SUMS.txt` verified, the bundle's glibc floor measured 2.35 across 417 files, the
`.deb`'s ACPI helper came out root-owned and mode-restricted, no runtime binary leaked into
the wheel or sdist, and each package owns only the trees BlackDream's own files live in. The
bundle then started on this machine's Wayland session and again on X11 (`smoke ok:
platform=wayland`, `smoke ok: platform=xcb`).

**What "the audited artifact is the published one" actually rests on.** It cannot rest on a
digest, and comparing two builds proved that: `7f3dfaf` and its child `a762715` differ in
this file alone, and the builds of them produced different `.tar.gz`, `.deb` and `.rpm`
digests while the wheel's came out identical. Extracting both bundles explains the split —
every file in them is byte-for-byte the same except `_internal/base_library.zip`, whose 155
entries are the same module names with the same CRC-32s and the same sizes, written in a
different order. A digest identifies a build, not a commit. The identity is structural
instead: `publish` runs only on a tag push, `needs: build`, and feeds `gh release create`
from `actions/download-artifact` on that same run's uploads — it never rebuilds — while that
run's own `build-release.sh` step is what measures the artifacts. So the bytes a tag
publishes are the bytes that tag's run audited, and what a pre-tag audit can honestly promise
is that these sources build into the content checked above. After a tag, the published files
should be downloaded and re-measured with the same script; a mismatch there is a reason to
delete the release, not to argue about it.

This record is the one file that can still change afterwards, and it ships in neither the
bundle nor the wheel: only the source distribution carries it, so a wording fix here does
not move a shipped binary. Anything else that changes must go through the same
build-and-audit cycle before a tag.

**NO-GO for Stage C (wider public beta) until:**

1. the installer has been written to a real FAT32 stick on at least one OS, with the
   volume pulled mid-copy once and the rollback inspected (`docs/RELEASE-NOTES.md` asks
   testers to do exactly this, which is the honest way to close A12);
2. one Windows and one macOS tester have run Compatibility → Build → Configure end to
   end, since the notes promise those platforms build and smoke-test but do not claim a
   hardware run;
3. 200 % scaling and keyboard focus have been looked at on a desktop session — both are
   visible checks no test can make.

**The gate was opened, by the maintainer.** `v0.9.0-beta.3` was tagged on `56b56d1` and
the run it triggered published the prerelease. The published files were then downloaded
and re-measured here with the same script: the five digests in the release's own
`SHA256SUMS.txt` verify against the downloaded bytes, the bundle's glibc floor still reads
2.35, no runtime tool leaked into the wheel or the sdist, and the `.deb` still owns only
the trees it documents. The `.rpm` is the one artifact this host cannot read — it has no
`rpm` or `rpm2cpio` — so its bytes are proved by `sha256sum -c` against that same
checksums file, and its listing was audited by the CI leg, which does have `rpm`.

**Comparing the published bundle against the tree found a weak rule, not a bad file.**
`packaging/blackdream.spec` collected every notice into one `licenses` directory under
`Path(document).name`, and two of them — the vendored engine's and Hardware Sniffer's — are
both called `VENDOR_NOTICE.txt`. In the published beta 3, `licenses/VENDOR_NOTICE.txt` is
Sniffer's text and the engine's copy of that name is gone. The audit passed it because its
rule asked only whether a *name* appeared anywhere in the bundle, and nothing was in fact
missing: each vendored tree carries its own copy beside the modules it belongs to
(`_internal/ocengine/VENDOR_NOTICE.txt` and
`_internal/blackdream/hardware/sniffer/VENDOR_NOTICE.txt`, both read back with their
source digests), and the two `LICENSE.upstream.BSD-3-Clause` texts are byte-identical to
each other, so everything a tester reads is present and correct. So the fix is not the
checker's new byte rule, which would have passed beta 3 as it passed the name rule — the
real guard is the spec itself: each document now names its landing directory
(`licenses/ocengine`, `licenses/sniffer`), and
`test_two_vendored_documents_never_land_on_one_path_in_the_bundle` refuses any `NOTICE_FILES`
list in which two documents would write the same path. Matching a notice by bytes rather
than by file name is a separate, smaller hardening: it now fails a bundle that carries a
stale or truncated copy, which a name check cannot see.

**Beta 3 stays published as it is, and the fix ships in the next build.** The alternative —
delete the release and the tag, then re-tag the corrected commit under the same name —
rewrites a public record, invalidates the checksums anyone may already have filed, and buys
nothing: the directory it repairs is the copy that was never load-bearing. Each asset shows
one download, and that download is this record's own verification pass. The corrected
`licenses` layout and the collision test reach testers with the next tag — and that tag has
to carry a new label, because `v0.9.0-beta.3` is taken and the publish job keys on the tag
name. The fix was built and measured before it reaches a tag: run `40088446818` built all
three platforms from `c749492` and every leg's own audit step passed — including the Linux
leg's read of the `.rpm`, which this host cannot do — and the downloaded Linux bytes were
re-measured here: five digests verified, the bundle's floor still glibc 2.35, and
`_internal/licenses/ocengine/VENDOR_NOTICE.txt` and
`_internal/licenses/sniffer/VENDOR_NOTICE.txt` both present with their source digests
(`739a9e7e…` and `3fa21902…`, where the published beta 3 held only the second under
`licenses/`). That bundle then started on this machine's Wayland session and again on X11.

**Stage C's third gate — "200 % scaling and keyboard focus have been looked at on a desktop
session" — was looked at, and it turned up four visible defects.** The method had to be
measurement, not a glance: every view was rendered offscreen at 1280x820 and again with
`QT_SCALE_FACTOR=2` (the grab comes back 2560x1640), every visible button was compared against
its own `sizeHint()` at `minimumSize()`, and the keyboard was driven with real `Tab` and arrow
events through `QTest`.

Three of the four were clipping, and none of them could be seen in the published frames because
every frame is 1536 px wide. The Configure EFI `Keys` card held eight buttons in one row and at
the window's own minimum width squeezed `Changes…` into `hanges`; it is now two rows, `Undo`, `Redo`,
`Changes…` over `Add key`, `Add item`, `Remove`, `Up`, `Down`. The brand tagline lost its last
letter — the 200 px rail is a spec promise, so the row's own margins and spacing gave way instead,
and `OpenCore, made simple.` now reads whole in all fourteen window frames. The Help card's
"Nothing has been copied or saved." was squeezed beside two buttons into a narrow column and got
its own line. The fourth was the progress card's stage names, which lost their last glyph
mid-letter; the row now elides to the card's width and the tooltip carries the whole line.
`test_no_button_is_narrower_than_its_own_label` walks all eight views at `minimumSize()` and
refuses any button narrower than its own label — it fails on the pre-fix layout with seven
offenders, which is what makes it worth having.

**200 % scaling found nothing new, and that is the finding.** Qt doubles the device pixels and
leaves the logical geometry alone, so a card that fits at 1280 logical pixels fits at 2560
device pixels, and one that clips does both. The one place where the spec promised a mechanism
the code does not have was §14's Devices-table rule — "wrapping the `macOS support` column, never
by truncating a device name mid-token". Measured: the card is 640 px wide at every window width,
the table gives way from the right (the support column shrinks from 266 px to its 110 px floor
before the name column loses anything, which keeps at least 165 px), and a name longer than that
elides with the whole string in the row tooltip. Wrapping was not implemented: a report can name
a device anything at all — `test_a_device_name_is_rendered_as_text_not_markup` feeds it
`<b>Bold</b> CPU` — so no fixed-width column can promise against truncation, and the row height
is pinned at 29 px by design. §14 now states the mechanism the code actually has, and
`test_the_release_range_gives_way_before_the_device_name` pins the column floors at 1160, 1280
and 1900 px.

**Keyboard focus reaches what the spec names, and two things that looked like bugs are not.**
`test_the_keyboard_reaches_what_the_spec_promises` drives the rail the way a person does: `Tab`
lands on the group's first button, five `Down` presses visit all six and change the page each
time, ending on `Donate`; the theme picker and all three Help diagnostics buttons are in the
`Tab` chain. Measured chain lengths at 1280x820: Compatibility 22 stops, Build 12, Installer 7,
Logs 6, Help 5, Settings 2 controls, Configure EFI 2 with no document open and 14 with one,
Donate 1 control — and Donate is meant to have none, since its own card says "Donation links are
not open yet. No payment button is shown until there is a page behind it." The two near-misses: only
the rail's first button carries `Qt.TabFocus` (`0xB` against `0xA` for the other five), which is
Qt's own auto-exclusive focus fix-up and not a defect; and the obvious-looking repair — putting
the six buttons in an explicit `QButtonGroup` — was tried and measurably *breaks* the arrow walk
rather than enabling it. Sending `Down` at the window instead of the focused button also appears
to do nothing, which is how the first pass at this gate nearly produced a wrong bug report.

**The frames were re-rendered from the fixed build, and two were stale in a second way.** All
fourteen window frames now come from this tree. Five of the six dialogs came back byte-identical
to the frames they replace, which is the check that they still say what they say; the sixth,
`15-diagnostics-bundle.png`, printed `BlackDream 0.9.0-beta.2` in a bundle the current app
reports as `0.9.0-beta.3`, so it was re-rendered too. `08-settings.png` turned out to have been
rendered on 2026-10-23, before the version bump: it read `BlackDream 0.1.0` with the theme pinned
to `Light` and the storage card pointing at a scratch cache directory. It now shows the current
version, the `System` default and the paths a first run really uses.

## 8. What this cycle changed in the code

Five P0 claims were promises rather than evidence, and each now has a test:

* `test_the_app_never_formats_mounts_or_opens_a_disk` — the "never formats, never mounts,
  never opens a block device" sentence became a source sweep.
* `test_validation_checks_a_temporary_copy_and_leaves_the_file_alone` — "validation uses
  `ocvalidate` on a temporary copy" was implemented but untested.
* `test_a_validation_result_clears_after_every_kind_of_edit` and
  `test_generated_smbios_values_never_reach_the_engine_log` — the staleness rule and the
  serial-privacy promise now cover every mutation kind and the log itself.
* A drive swapped behind the confirmation, the system volume, and an out-of-space volume
  are refused in tests, as is the HTTP `Range`/`206` resume path that a partial download
  depends on.
* `packaging/verify-artifacts.py` refuses a package that owns anything outside
  `/opt/blackdream` and its documented system trees.
* One sentence in this record was itself the finding: the two builds compared above proved
  that a digest cannot promise the published bytes are the audited ones, so the claim now
  rests on what `release.yml` actually does rather than on a checksum.
* The published bundle was the second finding of the same kind: `licenses/` held one
  `VENDOR_NOTICE.txt` where two upstreams had each sent one. `packaging/blackdream.spec`
  now pairs every notice with the directory it lands in, `packaging/verify-artifacts.py`
  recognises a notice by its bytes, and
  `test_two_vendored_documents_never_land_on_one_path_in_the_bundle` reads the spec and
  refuses a list in which two documents would write the same path.
* The third Stage-C gate found four clipped labels and one spec sentence describing a
  mechanism the code never had. The Configure toolbar's eight buttons became two rows, the
  brand tagline and the Help diagnostics note got the room they need, and a long stage name
  elides with the whole line in its tooltip;
  `test_no_button_is_narrower_than_its_own_label` and
  `test_the_keyboard_reaches_what_the_spec_promises` pin the two rules a screenshot cannot.
  §14's Devices-table sentence now states the column floors the table actually keeps, with
  `test_the_release_range_gives_way_before_the_device_name` holding them at three widths.
