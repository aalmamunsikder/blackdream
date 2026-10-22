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
        _FIELD_STATE, _PAGE_COPY, _PRIMARY_VIEWS, _SECONDARY_VIEWS, _VIEWS)
    allow = _allowlist()
    assert allow["views"] == list(_VIEWS)
    assert allow["sidebar"]["secondary"] == list(_SECONDARY_VIEWS)
    assert allow["search"]["hidden_views"] == list(_SECONDARY_VIEWS)
    assert allow["page"]["titles"] == [_PAGE_COPY[name][0] for name in _VIEWS]
    assert allow["page"]["subtitles"] == [_PAGE_COPY[name][1] for name in _VIEWS]
    assert allow["field_icons"] == dict(_FIELD_STATE)
    assert set(_PRIMARY_VIEWS) | set(_SECONDARY_VIEWS) == set(_VIEWS)


def test_settings_help_and_donate_are_pages_not_dialogs():
    """2.1 promoted the two modals to views and added Donate.

    The old methods are the easiest regression to spot: a reintroduced ``_show_settings``
    would put a second, differently themed Settings surface back in the app.
    """
    from blackdream.ui.main_window import MainWindow

    assert not hasattr(MainWindow, "_show_settings")
    assert not hasattr(MainWindow, "_show_help")
    assert set(_allowlist()["dialogs"]) == {"engine_verdict"}


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
    allow = _allowlist()
    expected = {
        "Settings": allow["settings"]["cards"],
        "Help": allow["help"]["cards"],
        "Donate": ([allow["donate"]["summary_title"]]
                   + [item["title"] for item in allow["donate"]["items"]]),
    }
    try:
        for view, titles in expected.items():
            window._show_view(view)
            app.processEvents()
            page = window.page_stack.currentWidget().widget()
            shown = {label.text() for label in page.findChildren(QLabel)
                     if label.objectName() == "cardTitle"}
            assert shown == set(titles), (view, sorted(shown))
            assert window.page_title.text() == _PAGE_COPY[view][0]
            assert window.page_subtitle.text() == _PAGE_COPY[view][1]
            assert window.search.isHidden(), "the device search on {}".format(view)
            assert any(button.text() == view and button.isChecked()
                       for button in window.secondary_buttons)
        # The Donate page has no payment link and no field to type one into.
        window._show_view("Donate")
        app.processEvents()
        donate = window.page_stack.currentWidget().widget()
        assert donate.findChildren(QPushButton) == []
        assert donate.findChildren(QLineEdit) == []
        funding = allow["donate"]["items"][-1]
        assert funding["body"] in {label.text() for label in donate.findChildren(QLabel)}
    finally:
        window.runner.cancel()
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
    assert seen == set(_allowlist()["status_pills"]["labels"])


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


def test_the_allowlist_describes_the_glass_dashboard_not_the_old_shell():
    """2.0 removed the status bar, the menu bar and the separate steps card.

    None of those can be caught by the literal check, because a removed control's
    strings simply stop appearing; the shape of §16 is what says they are gone.
    """
    allow = _allowlist()
    assert "status_bar" not in allow
    assert "menus" not in allow
    assert "Build steps" not in allow["card_titles"]
    assert "Build progress" in allow["card_titles"]
    assert "Actions" in allow["card_titles"]
    assert "Build EFI folder" not in allow["card_titles"]
    assert allow["window"]["minimum_size"] == [1240, 800]
    assert allow["sidebar"]["hint"] == "OpenCore EFI builder."
