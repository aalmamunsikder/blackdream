# Release readiness record — 0.9.0-beta.3, Stage A

Recorded 2026-10-24 against `BlackDream_Beta_Release_Recommendation.md` (2026-10-23),
which was written for specification v3.3 and suggested the identifier `0.9.0-beta.1`.
This build is v3.6 / `0.9.0-beta.3`, so the recommendation's *screen numbers and version
label are stale*; its gates are not, and they are judged here one by one.

Stage A is the internal release-candidate stage: prove the critical workflows before
external testers are invited. This document is that proof, in the open, so a reviewer can
check every claim against the tree.

Statuses used below:

* **Proved** — a named automated test in this repository's suite covers the behaviour.
* **Run** — executed by hand on a real machine, bundle or artifact this cycle.
* **Not proved** — nothing here demonstrates it, and what would.

The suite is 850 tests (848 pass, 2 skip: one needs `pefile` to read a Windows version
resource, one only runs where artifacts have been built). `docs/RELEASE-NOTES.md` states
that number and a test pins it to `pytest --collect-only`, so a claim about coverage
cannot drift from the coverage.

## 1. Stage A's own checklist (section 3 of the recommendation)

| Stage A bullet | Status | Evidence |
| --- | --- | --- |
| Reproducible artifacts for each supported platform | Run | the `Build beta artifacts` workflow built the Linux, Windows and Intel-macOS artifacts from the final commit of this cycle, and every leg's own audit step passed |
| Complete automated suite plus the UI microcopy allowlist test | Proved | 850 collected, 848 passed, 2 skipped; `tests/test_mockup_spec_allowlist.py` is 31 of them |
| The P0 checklist, including fault injection for installer writes and config saves | Mapped below | every gate in section 2; the injected faults are the second-swap failure, the cancelled write, the refused swap, the externally changed file and `test_a_value_plist_cannot_hold_fails_the_save_before_it_touches_the_disk` |
| The installer uses Apple's trust chain; pinned runtime binaries verified before they run | Proved | `test_the_real_apple_chunklist_verifies`, `test_asset_urls_must_stay_on_apple_cdn`, `test_a_tampered_tool_is_refused_before_it_runs`, `test_unpinned_download_still_refused` |
| Upgrade, install and uninstall behaviour; user cache and output folders not deleted | **Not run** | the ownership rule in section 2 is what a package may own, and the `.deb`'s helper mode and owner are read off the finished artifact, but no machine has actually installed or removed this package: that needs root, and this host grants root only through polkit for the ACPI helper |
| Screenshots for the built states compared against the reject list | Run | all 14 window frames were re-rendered from this build, the six dialogs at their own sizes, and `docs/UI-MOCKUP-SPEC.md` §17 is what the allowlist test refuses |

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

The audited artifact and the published one must be the same bytes. The audit below was
run on the CI build of the beta 3 sources, and these files ship inside the bundle
(`README.md`, `docs/RELEASE-NOTES.md`), so after this record is committed the workflow has
to run again on the final commit and the fresh download re-audited before any tag:
`SHA256SUMS.txt` matched the CI build, the bundle's glibc floor measured 2.35, the `.deb`'s
ACPI helper came out root-owned and mode-restricted, no runtime binary leaked into the
wheel or sdist, and a package may only own the trees BlackDream's own files live in — so an
uninstall cannot take away a profile, a build history or a folder the user chose.

**NO-GO for Stage C (wider public beta) until:**

1. the installer has been written to a real FAT32 stick on at least one OS, with the
   volume pulled mid-copy once and the rollback inspected (`docs/RELEASE-NOTES.md` asks
   testers to do exactly this, which is the honest way to close A12);
2. one Windows and one macOS tester have run Compatibility → Build → Configure end to
   end, since the notes promise those platforms build and smoke-test but do not claim a
   hardware run;
3. 200 % scaling and keyboard focus have been looked at on a desktop session — both are
   visible checks no test can make.

**Still gated on the maintainer:** pushing the tag runs the publish job, and a published
release is public and effectively permanent. Nothing above authorises it.

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
