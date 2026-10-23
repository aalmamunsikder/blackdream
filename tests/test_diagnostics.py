"""A bundle is a privacy decision, so the tests inspect its bytes.

They check three promises: identities never appear, the user's home path is
shortened, and nothing is written until ``write_*`` is called -- with only the
entries the user left selected.
"""

from __future__ import annotations

import ast
import zipfile
from pathlib import Path

from blackdream.core import diagnostics


def _bundle(tmp_path, **kwargs):
    return diagnostics.Bundle(home=tmp_path / "home", **kwargs)


def _secret_config():
    return {
        "PlatformInfo": {"Generic": {
            "SystemSerialNumber": "C02XK9ZZABCD",
            "MLB": "C02123456789ABCDE",
            "SystemUUID": "00112233-4455-6677-8899-AABBCCDDEEFF",
            "ROM": b"\x11\x22\x33\x44\x55\x66",
        }}
    }


def test_secrets_cover_every_identity_value_in_both_byte_spellings():
    secrets = diagnostics.secrets_from_config(_secret_config())

    assert "C02XK9ZZABCD" in secrets
    assert "C02123456789ABCDE" in secrets
    assert "00112233-4455-6677-8899-AABBCCDDEEFF" in secrets
    assert "112233445566" in secrets
    assert "112233445566".upper() in secrets


def test_an_empty_config_yields_no_secrets():
    assert diagnostics.secrets_from_config({}) == ()
    assert diagnostics.secrets_from_config([]) == ()


def test_scrub_removes_secrets_and_the_home_path(tmp_path):
    home = tmp_path / "home" / "alice"
    bundle = diagnostics.Bundle(home=home, secrets=("SERIAL123",))
    text = "Loaded {}/logs/run.txt for SERIAL123".format(home)

    cleaned = bundle.scrub(text)

    assert str(home) not in cleaned
    assert "SERIAL123" not in cleaned
    assert cleaned.startswith("Loaded ~/logs/run.txt")
    assert "<redacted>" in cleaned


def test_scrub_handles_windows_separators(tmp_path):
    home = tmp_path / "home"
    bundle = diagnostics.Bundle(home=home)
    text = str(home).replace("/", "\\") + "\\logs"

    assert str(home) not in bundle.scrub(text)


def test_every_entry_is_scrubbed_at_write_time_and_not_before(tmp_path):
    bundle = _bundle(tmp_path, secrets=("C02XK9ZZABCD",))
    bundle.add("engine.log", "serial is C02XK9ZZABCD\n")

    assert "C02XK9ZZABCD" in bundle.entries[0].body, "the preview shows raw text"
    assert "C02XK9ZZABCD" not in bundle.render()


def test_only_selected_entries_are_written(tmp_path):
    bundle = _bundle(tmp_path)
    bundle.add("environment.txt", "version 0.9.0\n", optional=False)
    bundle.add("engine.log", "log body\n")
    bundle.add("crash.txt", "traceback\n")
    bundle.set_included("crash.txt", False)

    rendered = bundle.render()

    assert "engine.log" in rendered
    assert "crash.txt" not in rendered
    assert "version 0.9.0" in rendered


def test_the_text_export_is_a_readable_file(tmp_path):
    bundle = _bundle(tmp_path)
    bundle.add("environment.txt", "BlackDream 0.9.0\n")
    target = tmp_path / "diag.txt"

    bundle.write_text(target)

    text = target.read_text()
    assert "diagnostic bundle" in text.lower()
    assert "Nothing was uploaded" in text
    assert "whether the EFI folder boots" in text


def test_the_zip_export_contains_one_named_entry_per_selected_part(tmp_path):
    bundle = _bundle(tmp_path, secrets=("C02XK9ZZABCD",))
    bundle.add("environment.txt", "BlackDream 0.9.0\n")
    bundle.add("engine log", "serial C02XK9ZZABCD\n")
    bundle.set_included("engine log", False)
    target = tmp_path / "diag.zip"

    bundle.write_zip(target)

    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        readme = archive.read("README.txt").decode()
        bodies = "".join(archive.read(name).decode() for name in names)
    assert names == ["README.txt", "environment.txt"]
    assert "upload" in readme.lower()
    assert "C02XK9ZZABCD" not in bodies


def test_entry_names_are_made_safe_for_an_archive(tmp_path):
    bundle = _bundle(tmp_path)
    bundle.add("../logs/run 1.log", "body\n")
    target = tmp_path / "diag.zip"

    bundle.write_zip(target)

    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
    assert all("/" not in name and ".." not in name for name in names)
    assert "logs-run-1.log" in names


def test_preview_says_nothing_was_written_and_lists_choices(tmp_path):
    bundle = _bundle(tmp_path)
    bundle.add("environment.txt", "x", optional=False)
    bundle.add("engine.log", "y", note="the last run")
    bundle.set_included("engine.log", False)

    preview = bundle.preview()

    assert "Nothing has been written or sent yet." in preview
    assert "[include] environment.txt" in preview
    assert "[off] engine.log" in preview
    assert "the last run" in preview
    assert "<redacted>" in preview


def test_an_empty_bundle_says_so_instead_of_writing_a_blank_file(tmp_path):
    preview = diagnostics.Bundle().preview()

    assert "No entries are selected." in preview


def test_environment_names_software_not_the_user():
    text = diagnostics.environment(
        "0.9.0-beta.1", "Linux-7.0", theme="Dark", frozen=True,
        architecture="x86_64")

    assert "BlackDream 0.9.0-beta.1" in text
    assert "Architecture: x86_64" in text
    assert "bundled app" in text


def test_tail_keeps_the_end_where_the_failure_is():
    text = "a" * 100 + "THE FAILURE"

    result = diagnostics.tail(text, limit=20)

    assert result.endswith("THE FAILURE")
    assert "earlier characters omitted" in result
    assert diagnostics.tail("short", limit=20) == "short"


def test_log_text_tolerates_undecodable_bytes(tmp_path):
    path = tmp_path / "log.txt"
    path.write_bytes(b"ok \xff\xfe broken")

    assert "ok" in diagnostics.log_text(path)
    assert "Could not read" in diagnostics.log_text(tmp_path / "absent")


def test_report_summary_describes_keys_without_reproducing_values(tmp_path):
    path = tmp_path / "Report.json"
    path.write_text('{"devices": ["secret-serial"], "chipset": "Z390"}')

    summary = diagnostics.report_summary(path)

    assert "Report.json with 2 top-level key(s)" in summary
    assert "secret-serial" not in summary


def test_a_missing_or_invalid_report_is_described(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")

    assert "could not be read" in diagnostics.report_summary(tmp_path / "none.json")
    assert "could not be read" in diagnostics.report_summary(bad)


def test_removing_an_entry_by_name():
    bundle = diagnostics.Bundle()
    bundle.add("a.txt", "a")
    bundle.add("b.txt", "b")

    bundle.remove("a.txt")

    assert [entry.name for entry in bundle.entries] == ["b.txt"]


def test_the_bundle_code_imports_nothing_that_can_reach_the_network():
    """The export is local: a module that cannot import a client cannot send one."""
    source = Path(diagnostics.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    network = {"urllib", "http", "socket", "requests", "httpx", "ftplib",
               "smtplib", "ssl", "telnetlib", "xmlrpc"}
    assert not imported & network
