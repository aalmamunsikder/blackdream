"""The mockup spec's allowlist must stay a mirror of the running UI, not a wish.

``docs/UI-MOCKUP-SPEC.md`` is what a design tool is told to copy verbatim. A spec that
drifts from the code is worse than none: it manufactures mockups that cannot be built,
and the first drift was found by eye. So every string in §16 is checked against the
literal source corpus here -- adjacent string literals are joined the way the compiler
joins them, because the UI's longest sentences are wrapped across lines.

Strings containing ``«`` are documented runtime placeholders and are not in the source.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

SPEC = os.path.join(ROOT, "docs", "UI-MOCKUP-SPEC.md")
TEMPLATE_MARK = "«"


def _source_literals() -> set[str]:
    literals: set[str] = set()
    for dirpath, _dirs, names in os.walk(os.path.join(ROOT, "src")):
        if "__pycache__" in dirpath:
            continue
        for name in names:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    literals.add(node.value)
                elif isinstance(node, ast.JoinedStr):
                    literals.update(value.value for value in node.values
                                    if isinstance(value, ast.Constant)
                                    and isinstance(value.value, str))
            # "abc "
            # "def"  ->  "abcdef"
            joined = re.sub(r'["\']\s*\n\s*["\']', "", text)
            literals.update(match.group(1) for match in
                            re.finditer(r'"((?:[^"\\\n]|\\.)*)"', joined))
    return literals


def _allowlist() -> dict:
    with open(SPEC, encoding="utf-8") as handle:
        blocks = re.findall(r"```json\n(.*?)\n```", handle.read(), re.S)
    assert blocks, "UI-MOCKUP-SPEC.md §16 lost its json block"
    return json.loads(blocks[0])


def _strings(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)
    elif isinstance(node, str):
        yield node


def test_spec_exists():
    assert os.path.isfile(SPEC)


def test_every_allowlisted_string_is_a_source_literal():
    literals = _source_literals()
    untraceable = [value for value in _strings(_allowlist())
                   if TEMPLATE_MARK not in value and len(value) > 6
                   and value not in literals]
    assert not untraceable, "invented strings in §16: {}".format(untraceable)


def test_verdicts_table_still_has_four_columns():
    """2.0 has a fourth, target-relative column -- and only four.

    The first iteration of this test guarded three columns because a mockup kept
    inventing a Status one. The dashboard made that column real and truthful: its
    label comes from ``verdicts.target_status``, not from a designer's adjective.
    The guard now pins the exact four headers so a fifth cannot slip in either.
    """
    with open(os.path.join(ROOT, "src", "blackdream", "ui", "main_window.py"),
              encoding="utf-8") as handle:
        call = re.search(r"setHeaderLabels\(\s*\[(.*?)\]\)", handle.read(), re.S)
    assert call, "the devices table is no longer declared with setHeaderLabels"
    headers = [part.strip().strip('"\'') for part in call.group(1).split(",")]
    allow = _allowlist()
    assert headers == allow["table_headers"] == [
        "Device", "Class", "macOS support", "Status"]
    assert allow["table_header_count"] == len(allow["table_headers"]) == 4


@pytest.mark.parametrize("code", [
    "cpu.no_sse4", "gpu.absent", "gpu.unsupported",
    "storage.absent", "storage.intel_vmd", "storage.no_compatible",
])
def test_all_six_fatals_are_speced_with_their_real_copy(code):
    from ocengine.fatal import FATAL_BY_CODE
    cards = {card["code"]: card for card in _allowlist()["cards"]
             if card["code"] == code}
    fatal = FATAL_BY_CODE[code]
    assert cards, "{} missing from §16".format(code)
    card = cards[code]
    assert card["title"] == fatal.title
    assert card["bullets"] == list(fatal.remediation)
    assert card["non_recoverable"] is (not fatal.recoverable)


def _engine_errors():
    from ocengine.fatal import EngineError
    # Subclasses are only discoverable once their module has been imported, and this
    # test's whole value is that it sees every one of them.
    import blackdream.core.job_runner  # noqa: F401
    import blackdream.core.pipeline  # noqa: F401
    import blackdream.core.installer  # noqa: F401
    import blackdream.core.config_editor  # noqa: F401
    import blackdream.hardware  # noqa: F401
    import ocengine.acpi_guru  # noqa: F401
    import ocengine.dsdt  # noqa: F401
    import ocengine.gathering_files  # noqa: F401
    import ocengine.resource_fetcher  # noqa: F401
    import ocengine.utils  # noqa: F401
    found, pending = {EngineError.code: EngineError}, [EngineError]
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        code = getattr(cls, "code", EngineError.code)
        if cls is not EngineError and code != EngineError.code:
            found.setdefault(code, cls)
    return found


def test_every_error_class_carries_copy_in_the_shape_the_card_renders():
    """``remediation`` is iterated per bullet, so a missing comma is a bullet per letter.

    Found by writing the card inventory check below: three classes declared
    ``remediation = ("one long sentence"
                     "continued.")`` -- parentheses, not a tuple -- and the error card
    would have rendered an 87-row list of single characters for them.
    """
    errors = _engine_errors()
    assert len(errors) > 20, "the walk found {} classes; it is not seeing the tree".format(
        len(errors))
    for code, cls in sorted(errors.items()):
        assert isinstance(cls.title, str) and cls.title, code
        assert isinstance(cls.remediation, tuple), \
            "{}.remediation is a {}, not a tuple of bullets".format(
                cls.__name__, type(cls.remediation).__name__)
        assert all(isinstance(item, str) and len(item) > 8 for item in cls.remediation), \
            "{}.remediation holds a fragment, not a sentence".format(cls.__name__)
        assert isinstance(cls.recoverable, bool), code


def test_every_spec_card_describes_an_error_the_app_can_actually_raise():
    """The card inventory is checked against the classes, not against prose.

    Titles always live on the class. Bullets are only comparable when the class
    carries them: several failures pass a per-occurrence ``remediation`` at the raise
    site, and a spec that restates one of those is a snapshot of a call site, which
    is exactly the kind of claim that goes stale without anything noticing.
    """
    by_code = _engine_errors()
    for card in _allowlist()["cards"]:
        error = by_code.get(card["code"])
        assert error is not None, "{} is not an error this app raises".format(card["code"])
        assert card["title"] == error.title, card["code"]
        if error.remediation:
            assert card["bullets"] == list(error.remediation), card["code"]


def test_build_stage_names_match_the_pipeline():
    from blackdream.core.pipeline import _STEPS
    assert _allowlist()["build_stages"] == list(_STEPS)


def test_scan_stage_names_match_the_vendored_scanner():
    """The 15-step checklist a mockup draws must be the one ``linux.py`` actually emits.

    Read from the AST rather than by running a scan: the names live in a list literal
    inside a method, they are only reachable on Linux, and a real scan touches sysfs.
    Order matters -- the GUI numbers the checklist as it arrives.
    """
    path = os.path.join(ROOT, "src", "blackdream", "hardware", "sniffer", "linux.py")
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    assignment = next((node for node in ast.walk(tree)
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "steps"
                               for target in node.targets)
                       and isinstance(node.value, ast.List)), None)
    assert assignment, "the scanner no longer declares its steps as a list literal"
    names = []
    for entry in assignment.value.elts:
        assert isinstance(entry, ast.Tuple) and len(entry.elts) == 3, \
            "a scan step is no longer (name, function, attribute)"
        message = entry.elts[0]
        assert isinstance(message, ast.Constant) and isinstance(message.value, str)
        names.append(message.value)
    assert _allowlist()["scan_stages"] == names


def test_stage_icons_match_the_window():
    """2.0 replaced the five glyph marks with SVG icons, because a text tick cannot
    carry the theme colour or the DPI scale."""
    from blackdream.ui.main_window import _STAGE_ICON, _STAGE_STATES
    allow = _allowlist()
    assert allow["stage_icons"] == dict(_STAGE_ICON)
    assert allow["stage_states"] == list(_STAGE_STATES)


def test_the_views_and_field_icons_match_the_window():
    from blackdream.ui.main_window import (
        _BUILD_VIEWS, _FIELD_STATE, _PAGE_COPY, _SECTIONS, _SECONDARY_VIEWS, _VIEWS)
    allow = _allowlist()
    assert allow["views"] == list(_VIEWS)
    assert allow["sections"] == list(_SECTIONS)
    assert allow["build_views"] == list(_BUILD_VIEWS)
    assert allow["sidebar"]["secondary"] == list(_SECONDARY_VIEWS)
    # The device search filters the table, which only exists on Compatibility; a
    # pill on any other page -- including the new section pages -- reorders
    # something invisible.
    assert allow["search"]["hidden_views"] == [
        name for name in _VIEWS if name != "Compatibility"]
    assert allow["page"]["titles"] == [_PAGE_COPY[name][0] for name in _VIEWS]
    assert allow["page"]["subtitles"] == [_PAGE_COPY[name][1] for name in _VIEWS]
    assert allow["field_icons"] == dict(_FIELD_STATE)
    assert (set(_SECTIONS) | set(_BUILD_VIEWS) | set(_SECONDARY_VIEWS)
            == set(_VIEWS))


def test_settings_help_and_donate_are_pages_not_dialogs():
    """2.1 promoted the two modals to views and added Donate.

    The old methods are the easiest regression to spot: a reintroduced ``_show_settings``
    would put a second, differently themed Settings surface back in the app. 3.0 added
    two native installer dialogs; they are confirmations, not settings surfaces.
    """
    from blackdream.ui.main_window import MainWindow

    assert not hasattr(MainWindow, "_show_settings")
    assert not hasattr(MainWindow, "_show_help")
    expects = {
        "engine_verdict", "write_installer", "installer_written",
        "add_key", "edit_value", "generate_serials",
        "replace_serials", "remove_key", "overwrite_config",
        "insert_preset"}
    assert set(_allowlist()["dialogs"]) == expects


def test_the_utility_views_render_exactly_the_cards_in_the_allowlist():
    """Every utility card in §16 is on screen, and no invented card is.

    This is the structural counterpart to the string check: a card title can be a
    legal literal and still never be mounted on the page the spec assigns it to.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

    from blackdream.ui.main_window import MainWindow, _PAGE_COPY

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    # The USB scan reads the host's mounts; the card inventory does not need it.
    window._usb_scanned = True
    allow = _allowlist()
    expected = {
        "Installer": allow["installer"]["cards"],
        "Settings": allow["settings"]["cards"],
        "Help": allow["help"]["cards"],
        "Configure EFI": allow["configure"]["cards"],
        "Donate": ([allow["donate"]["summary_title"]]
                   + [item["title"] for item in allow["donate"]["items"]]),
    }
    try:
        for view, titles in expected.items():
            window._show_view(view)
            app.processEvents()
            page = window.page_stack.currentWidget()
            if hasattr(page, "widget") and page.widget() is not None:
                page = page.widget()
            shown = {label.text() for label in page.findChildren(QLabel)
                     if label.objectName() == "cardTitle"}
            assert shown == set(titles), (view, sorted(shown))
            assert window.page_title.text() == _PAGE_COPY[view][0]
            assert window.page_subtitle.text() == _PAGE_COPY[view][1]
            assert window.search.isHidden(), "the device search on {}".format(view)
            assert window.page_actions.isHidden() is (view != "Configure EFI"), view
            if view in allow["sections"]:
                assert any(button.text() == view and button.isChecked()
                           for button in window.nav_buttons), view
            else:
                assert any(button.text() == view and button.isChecked()
                           for button in window.secondary_buttons), view
            if view in ("Installer", "Configure EFI"):
                allowed_buttons = set(allow["buttons"]) | {allow["fields"]["button"]}
                buttons = list(page.findChildren(QPushButton))
                if view == "Configure EFI":
                    buttons += list(window.page_actions.findChildren(QPushButton))
                assert {button.text() for button in buttons} <= allowed_buttons, view
        # The Donate page has no payment link and no field to type one into.
        window._show_view("Donate")
        app.processEvents()
        donate = window.page_stack.currentWidget().widget()
        assert donate.findChildren(QPushButton) == []
        assert donate.findChildren(QLineEdit) == []
        funding = allow["donate"]["items"][-1]
        assert funding["body"] in {label.text() for label in donate.findChildren(QLabel)}
    finally:
        for runner in (window.runner, window._installer_runner, window._usb_runner,
                       window._config_runner):
            runner.cancel()
        window._ticker.stop()


def test_every_icon_named_in_the_allowlist_exists_in_the_inline_set():
    """A mockup must draw the app's own icons, not an approximation.

    The set is small and hand-drawn on a 24x24 stroke grid; a name that is not in
    ``icons._SVG`` renders a blank tile at runtime. This also keeps §16 honest when a
    new icon is introduced: the allowlist has to name it before a mockup can.
    """
    from blackdream.ui import icons
    allow = _allowlist()
    used = set()
    for key in ("field_icons", "stage_icons", "class_icons", "nav_icons", "chrome_icons"):
        used.update(allow[key].values())
    used.update(allow["progress"]["metric_icons"].values())
    assert used <= set(icons._SVG), sorted(used - set(icons._SVG))


def test_class_icons_cover_every_class_label_and_the_fallback():
    from blackdream.ui.main_window import _CLASS_ICON
    allow = _allowlist()
    assert allow["class_icons"] == {**dict(_CLASS_ICON), "other": "layers"}
    assert set(allow["class_labels"]) == set(_CLASS_ICON)


def test_status_labels_are_the_four_the_target_function_returns():
    """The pill labels are computed, not designed. Pin them to ``target_status``.

    A device native through one release and dropped in the next is the whole reason
    the column exists; a mockup that writes "Supported" for an OCLP-only device is
    the drift this test exists to stop.
    """
    from blackdream.core.verdicts import Verdict, target_status

    seen = {
        target_status(Verdict("CPU", "x", "Up to macOS Sonoma 14", True,
                              compatibility=("19.0.0", "23.0.0")), None).label,
        target_status(Verdict("CPU", "x", "Unsupported", False), None).label,
        target_status(Verdict("GPU", "x", "Unchecked", None), None).label,
        target_status(Verdict("CPU", "x", "Up to macOS Sonoma 14", True,
                              compatibility=("19.0.0", "23.0.0")), "25.0.0",
                      ("20.0.0", "25.0.0")).label,
        target_status(Verdict("CPU", "x", "Up to macOS Sonoma 14", True,
                              compatibility=("19.0.0", "23.0.0")), "25.0.0").label,
    }
    assert seen == set(_allowlist()["status_words"]["labels"])


def test_rate_and_progress_copy_matches_the_dashboard():
    """1.1 forbade MB/s; 2.0's Speed tile prints it above 1 MiB/s.

    The allowlist carries both units, and the formatter is the source of truth.
    """
    from blackdream.ui.main_window import _format_rate

    allow = _allowlist()
    assert allow["progress"]["rate_units"] == ["KB/s", "MB/s", "—"]
    assert _format_rate(0) == "—"
    assert _format_rate(904 * 1024) == "904 KB/s"
    assert _format_rate(2 * 1024 * 1024) == "2.0 MB/s"
    assert allow["progress"]["step_position"] == "Step «n» of «total»"
    assert allow["progress"]["percent"] == "«pct»%"


def test_the_installer_and_configure_sections_name_their_cards():
    """The two new sections are not allowed to grow a card the spec never saw."""
    allow = _allowlist()
    assert allow["installer"]["cards"] == ["macOS installer", "USB drive"]
    assert allow["configure"]["cards"] == [
        "config.plist", "Sections", "Keys", "Selected entry", "Validation"]
    assert set(allow["installer"]["cards"]) | set(allow["configure"]["cards"]) \
        <= set(allow["card_titles"])


def test_help_shortcuts_are_generated_by_the_window():
    """The Help card renders ``_shortcut_rows``; the allowlist must be that list.

    The three workflow sections moved onto Ctrl 1/2/3 and the build tabs onto
    Ctrl Shift 1/2/3 when 3.0 added the Installer. A mockup still printing the
    2.6 bindings is the drift this pins.
    """
    from blackdream.ui.main_window import MainWindow

    rows = MainWindow._shortcut_rows()
    allow = _allowlist()["help"]["shortcuts"]
    assert [row["action"] for row in allow] == [action for action, _keys in rows]
    for row, (_action, keys) in zip(allow, rows):
        assert row["mac"] == row["keys"].replace("Ctrl", "⌘")
        assert keys == (row["mac"] if sys.platform == "darwin" else row["keys"])


def test_installer_release_catalogue_matches_the_spec():
    """The picker's contents are data, so §16 pins the data, not one label."""
    from blackdream.core.installer import RECOVERY_RELEASES

    allow = _allowlist()["installer"]["releases"]
    assert [(release.name, release.version)
            for release in RECOVERY_RELEASES] == list(
                zip(allow["names"], allow["versions"]))


def test_help_quick_start_is_generated_by_the_window():
    """The Quick start card must describe the three sections, in workflow order.

    A legal literal can still be on the wrong page or in the wrong order; this
    pins the rendered rows, not just the string corpus.
    """
    from blackdream.ui.main_window import _QUICK_START

    allow = _allowlist()["help"]
    assert allow["quick_start"] == [
        {"title": title, "body": body, "icon": icon}
        for title, body, icon in _QUICK_START]
    assert [title for title, _body, _icon in _QUICK_START][0] == "Make the installer"
    assert [title for title, _body, _icon in _QUICK_START][-1] == "Configure the EFI"


def test_help_quick_start_renders_one_row_per_step():
    """A duplicated add() left every step on the card twice; count the rows.

    The allowlist test above compares the table to the spec, not the table to
    what the card built, so it cannot see a render-side duplicate.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from blackdream.ui.main_window import MainWindow, _InfoRow, _QUICK_START

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._usb_scanned = True
    try:
        window._show_view("Help")
        app.processEvents()
        rows = window.quick_start_card.findChildren(_InfoRow)
        assert [row.body.text() for row in rows] == [
            body for _title, body, _icon in _QUICK_START]
        assert len(rows) == 6
    finally:
        for runner in (window.runner, window._installer_runner, window._usb_runner,
                       window._config_runner):
            runner.cancel()
        window._ticker.stop()


def test_the_allowlist_describes_the_native_window():
    """2.6 keeps the platform frame and moves the mockup's silk inside the window.

    The literal check cannot catch a removed control's strings, because they simply
    stop appearing; the shape of §16 is what says the window uses the platform
    frame, shows its menu bar everywhere, and groups the setup cards instead of
    numbering them. The wallpaper is visual, not copy, so it is documented in §4
    and pinned by the shell tests rather than added here.
    """
    allow = _allowlist()
    assert allow["window"]["frameless"] is False
    assert "inset" not in allow["window"]
    assert "corner_radius" not in allow["window"]
    assert allow["window"]["minimum_size"] == [1160, 700]
    assert allow["menus"] == ["File", "View", "Help"]
    assert allow["sidebar"]["workflow_label"] == "WORKFLOW"
    assert "window_controls" not in allow["sidebar"]
    assert "status_bar" not in allow
    assert "Select files" not in allow["card_titles"]
    assert "Actions" not in allow["card_titles"]
    assert "macOS version" in allow["card_titles"]
    assert "Build progress" in allow["card_titles"]
    assert "Build EFI folder" not in allow["card_titles"]
    assert allow["sidebar"]["hint"] == "OpenCore, made simple."
    appearance = allow["settings"]["appearance"]
    assert appearance["choices"] == ["System", "Light", "Dark"]
    assert appearance["hint"] == "Follows the system by default. Changes apply immediately."


def test_the_first_boot_card_is_the_spec_and_the_module():
    """Advice rows are copy, so §16 carries them and the card must render them.

    ``first_boot.STEPS`` is the only source of the checklist, and a mockup that
    reorders the six steps or invents a seventh would pass the string check alone.
    """
    from blackdream.core import first_boot

    block = _allowlist()["help"]["first_boot"]
    assert block["steps"] == [{"title": step.title, "body": step.body,
                               "icon": step.icon} for step in first_boot.STEPS]
    assert block["boundary"] == first_boot.to_text().splitlines()[-1]
    assert block["title"] == "Before the first boot"


def test_the_first_boot_card_renders_one_row_per_step():
    """Count the rows on the page, not the table in the spec."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from blackdream.core import first_boot
    from blackdream.ui.main_window import MainWindow, _InfoRow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._usb_scanned = True
    try:
        window._show_view("Help")
        app.processEvents()
        rows = window.first_boot_card.findChildren(_InfoRow)
        titles = [label.text() for label
                  in window.first_boot_card.findChildren(QLabel)
                  if label.objectName() == "rowTitle"]
        assert titles == [step.title for step in first_boot.STEPS]
        assert [row.body.text() for row in rows] == [
            step.body for step in first_boot.STEPS]
        assert len(rows) == 6
        assert window.first_boot_note.text() == "Nothing has been copied."
    finally:
        for runner in (window.runner, window._installer_runner, window._usb_runner,
                       window._config_runner):
            runner.cancel()
        window._ticker.stop()


def test_the_read_only_dialogs_spec_the_boundaries_the_code_prints():
    """The comparison dialogs quote a module boundary; §16 must quote the same sentence.

    These sentences are the whole safety claim of the comparison surfaces, and a
    spec that paraphrases one is a mockup that promises something else. The
    histories' status words and cap are data, so they are pinned to the module too.
    """
    from blackdream.core import build_history, release_matrix, report_compare
    from blackdream.core import schema_preview

    allow = _allowlist()
    dialogs = allow["read_only_dialogs"]
    assert dialogs["release_matrix"]["boundary"] == release_matrix.BOUNDARY
    assert dialogs["report_compare"]["boundary"] == report_compare.BOUNDARY
    assert dialogs["report_compare"]["hardware_fields"] == [
        field for field in report_compare.HARDWARE_FIELDS]
    assert dialogs["profiles"]["title"] == "Profiles"
    assert dialogs["history"]["statuses"] == list(build_history.STATUSES)
    assert dialogs["history"]["max_entries"] == build_history.MAX_ENTRIES
    assert allow["configure"]["schema_preview"]["export"]["boundary"] in (
        schema_preview.to_text(schema_preview.Preview("1.0.8", (), {})))
    assert allow["help"]["cards"][-1] == "Before the first boot"


def test_the_new_links_and_headers_are_speced_as_buttons_or_links():
    """A link label in the wrong §16 list is a mockup that draws the wrong widget.

    ``Compare reports…`` and its neighbours are sidebar-free links; ``History…`` and
    ``Schema preview…`` live in a card header. §16 keeps those three families apart,
    so a design tool cannot promote one into the other's chrome.
    """
    allow = _allowlist()
    for label in ("Compare reports…", "Profiles…", "Compare releases…"):
        assert label in allow["links"]["buttons"], label
        assert label not in allow["buttons"], label
    for label in ("History…", "Schema preview…", "Dependencies…",
                  "Copy the checklist", "Save current", "Use", "Rename…",
                  "Open folder", "Copy history", "Save as text…"):
        assert label in allow["buttons"], label


def test_the_dependency_dialog_is_speced_widget_by_widget():
    """S34's §16 block is read off the built dialog, not off the prose.

    The five fields the roadmap asks for -- trigger, evidence, key path,
    confidence, source -- are seven caption labels in a grid nobody can grep for by
    name, and the boundary sentence is shared with the export. Pinning the block to
    the widgets is what keeps a mockup from inventing an eighth row, a fourth
    severity word, or the ``Fix`` button this surface refuses to have.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from blackdream.core import dependency_advisor
    from blackdream.ui import icons
    from blackdream.ui.main_window import _AdvisorDialog
    from blackdream.ui.theme import LIGHT

    app = QApplication.instance() or QApplication([])
    allow = _allowlist()["configure"]["dependencies"]
    document = {"Kernel": {"Add": [
        {"BundlePath": "Lilu.kext", "Enabled": True},
        {"BundlePath": "WhateverGreen.kext", "Enabled": True},
        {"BundlePath": "NootRX.kext", "Enabled": True},
    ]}, "UEFI": {"Drivers": []}}
    report = dependency_advisor.advise(document, "23.99.99")
    dialog = _AdvisorDialog(None, report, "/tmp/config.plist",
                            "macOS Sonoma 14", (), LIGHT)
    try:
        assert [dialog.tree.headerItem().text(column)
                for column in range(3)] == allow["headers"]
        assert list(dialog._values) == allow["fields"]
        assert list(dialog._SEVERITY.values()) == allow["severities"]
        assert dialog.hint.text() == allow["boundary"]
        assert allow["boundary"] == dependency_advisor.BOUNDARY
        assert allow["boundary"] in dependency_advisor.to_text(report)
        assert [dialog.minimumSize().width(), dialog.minimumSize().height()] \
            == allow["minimum_size"]
        assert dialog.windowTitle() == allow["title"]
        assert dialog.target_note.text() == allow["target"].replace(
            "«release»", "macOS Sonoma 14")
        assert dialog.summary.text() == report.summary
        assert dialog.go_button.text() == allow["go"]
        assert dialog.go_button.toolTip() == allow["go_tooltip"]
        assert dialog.dismiss_button.text() == allow["dismiss"]
        assert dialog.dismiss_button.toolTip() == allow["dismiss_tooltip"]
        assert dialog.restore_button.text() == allow["restore"]
        assert dialog.show_dismissed.text() == allow["show_dismissed"]
        assert allow["ruleset"] == dependency_advisor.RULESET
        assert allow["store"] == dependency_advisor.default_dismissal_path().name
        assert allow["icon"] in icons._SVG
        # A severity word in the spec that no row ever prints is a mockup drawing
        # a badge the code cannot produce; the three that do exist must cover the
        # rows this two-kext argument yields.
        printed = {dialog.tree.topLevelItem(row).text(0)
                   for row in range(len(dialog._rows))}
        assert printed <= set(allow["severities"])
        assert printed == {dialog._SEVERITY[item.severity]
                           for item in report.advisories}
    finally:
        dialog.deleteLater()
        app.processEvents()
