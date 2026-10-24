"""The native config editor: plist fidelity, schema defaults, and pin checks."""

from __future__ import annotations

import hashlib
import os
import plistlib
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ocengine.paths import EnginePaths  # noqa: E402

from blackdream.core import config_editor as editor  # noqa: E402


def _document(tmp_path: Path):
    data = {
        "ACPI": {"Add": [], "Quirks": {"FadtEnableReset": False}},
        "Booter": {"Quirks": {"AvoidRuntimeDefrag": True}},
        "PlatformInfo": {"Automatic": True, "Generic": {
            "SystemProductName": "MacPro7,1",
            "ROM": b"\x11\x22\x33\x44\x55\x66",
        }},
    }
    path = tmp_path / "config.plist"
    path.write_bytes(plistlib.dumps(data, sort_keys=False))
    return editor.ConfigDocument.load(path), data


def _use_isolated_tools(monkeypatch, tmp_path: Path) -> Path:
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setattr(editor.engine_paths, "tools_dirs",
                        lambda create=False: [str(tools)])
    monkeypatch.setattr(editor.engine_paths, "install_tools_dir",
                        lambda: str(tools))
    monkeypatch.setattr(editor.engine_paths, "is_on_import_path",
                        lambda _path: False)
    monkeypatch.setattr(editor.engine_paths, "_current", EnginePaths(
        cache_dir=tmp_path / "cache", tools_dir=tools))
    return tools


PLATFORM_KEY = editor._platform_key()
INSTALL_NAME, ARCHIVE_MEMBER, _PINNED_DIGEST = editor.OCVALIDATE_ASSETS[PLATFORM_KEY]


def _pin(monkeypatch, digest: str):
    monkeypatch.setattr(editor, "OCVALIDATE_ASSETS", {
        PLATFORM_KEY: (INSTALL_NAME, ARCHIVE_MEMBER, digest),
    })


def test_a_round_trip_preserves_order_and_binary_values(tmp_path):
    document, _data = _document(tmp_path)
    assert list(document.data) == ["ACPI", "Booter", "PlatformInfo"]
    assert document.data["PlatformInfo"]["Generic"]["ROM"] == (
        b"\x11\x22\x33\x44\x55\x66")
    assert not document.is_dirty()

    document.data["ACPI"]["Quirks"]["FadtEnableReset"] = True
    assert document.is_dirty()
    document.save()

    reloaded = editor.ConfigDocument.load(document.path)
    assert list(reloaded.data) == ["ACPI", "Booter", "PlatformInfo"]
    assert reloaded.data["ACPI"]["Quirks"]["FadtEnableReset"] is True
    assert not reloaded.is_dirty()


def test_save_keeps_the_previous_file_as_a_backup(tmp_path):
    document, _data = _document(tmp_path)
    original = document.path.read_bytes()
    document.data["Booter"]["Quirks"]["AvoidRuntimeDefrag"] = False
    document.save()

    backup = document.path.with_name(document.path.name + ".bak")
    assert backup.read_bytes() == original
    assert plistlib.loads(document.path.read_bytes())["Booter"]["Quirks"][
        "AvoidRuntimeDefrag"] is False


def test_a_value_plist_cannot_hold_fails_the_save_before_it_touches_the_disk(
        tmp_path):
    """A document that cannot be serialised must refuse, not truncate.

    A half-written config.plist is an unbootable machine, so the bytes are built
    first and the file is only replaced once they exist.
    """
    document, _data = _document(tmp_path)
    before = document.path.read_bytes()
    document.data["Booter"]["Quirks"]["AvoidRuntimeDefrag"] = {1, 2}

    with pytest.raises(editor.ConfigWriteFailed) as caught:
        document.save()

    assert "plist cannot serialise" in caught.value.detail
    assert document.path.read_bytes() == before
    assert sorted(item.name for item in tmp_path.iterdir()) == ["config.plist"]


def test_an_external_change_is_detected(tmp_path):
    document, _data = _document(tmp_path)
    assert not document.changed_on_disk()
    document.path.write_bytes(document.path.read_bytes() + b"\n")
    assert document.changed_on_disk()


def test_a_missing_file_is_read_as_a_typed_failure(tmp_path):
    with pytest.raises(editor.ConfigReadFailed):
        editor.ConfigDocument.load(tmp_path / "missing.plist")


def test_a_non_dictionary_root_is_refused(tmp_path):
    path = tmp_path / "config.plist"
    path.write_bytes(plistlib.dumps(["not", "a", "dict"]))
    with pytest.raises(editor.ConfigReadFailed):
        editor.ConfigDocument.load(path)


def test_schema_children_come_from_the_pinned_sample():
    children = dict(editor.known_children(("Kernel", "Quirks")))
    assert children["AppleXcpmCfgLock"] is False
    assert children["SetApfsTrimTimeout"] == -1
    template = editor.array_template(("ACPI", "Add"))
    assert isinstance(template, dict) and "Path" in template
    assert editor.array_template(("ACPI", "Quirks")) is None
    assert editor.known_children(("Not", "There")) == []


def test_missing_standard_keys_can_be_added_without_losing_unknown_ones():
    data = {"UEFI": {"Quirks": {"MadeUpKey": True}}}
    for key, value in editor.known_children(("UEFI", "Quirks")):
        data["UEFI"]["Quirks"].setdefault(key, value)
    assert data["UEFI"]["Quirks"]["MadeUpKey"] is True
    assert data["UEFI"]["Quirks"]["EnableVectorAcceleration"] is True


@pytest.mark.parametrize("kind,text,expected", [
    ("boolean", "true", True),
    ("boolean", "no", False),
    ("integer", "-1", -1),
    ("integer", "0x10", 16),
    ("real", "1.5", 1.5),
    ("string", " PciRoot(0x0) ", " PciRoot(0x0) "),
    ("data", "11 22 33", b"\x11\x22\x33"),
])
def test_scalar_parsing(kind, text, expected):
    assert editor.parse_value(kind, text) == expected


@pytest.mark.parametrize("kind,text", [
    ("integer", "twelve"),
    ("real", "x"),
    ("data", "abc"),
])
def test_invalid_scalar_text_is_rejected(kind, text):
    with pytest.raises(ValueError):
        editor.parse_value(kind, text)


def test_data_formatting_is_hex_and_truncates_long_blobs():
    assert editor.format_value(b"\x00\xff") == "00 FF"
    long = editor.format_value(bytes(range(64)))
    assert long.endswith("\u2026")


def test_text_view_of_data_is_lossless_for_every_byte():
    payload = bytes(range(256))
    text = editor.data_to_text(payload)
    assert editor.text_to_data(text) == payload


def test_text_view_shows_ascii_and_escapes_the_rest():
    assert editor.data_to_text(b"Hello, world") == "Hello, world"
    assert editor.data_to_text(b"line\nnext\tend") == "line\\nnext\\tend"
    assert editor.data_to_text(b"a\\b\x00\x1f\xff") == "a\\\\b\\x00\\x1F\\xFF"
    assert editor.text_to_data("a\\\\b\\x00\\x1f\\xff") == b"a\\b\x00\x1f\xff"


@pytest.mark.parametrize("text, message", [
    ("trailing\\", "lone backslash"),
    ("\\x1", "exactly two hexadecimal"),
    ("\\xZZ", "exactly two hexadecimal"),
    ("\\q", "Unknown escape"),
    ("caf\u00e9", "printable ASCII"),
    ("\t", "printable ASCII"),
])
def test_text_view_rejects_text_that_would_change_the_bytes(text, message):
    with pytest.raises(ValueError, match=message):
        editor.text_to_data(text)


def test_type_names_distinguish_booleans_from_integers():
    assert editor.type_name(True) == "boolean"
    assert editor.type_name(1) == "integer"
    assert editor.type_name(b"") == "data"
    assert editor.type_name({}) == "dictionary"
    assert editor.type_name([]) == "array"


def test_path_helpers_keep_array_indexes_straight():
    data = {"Kernel": {"Add": [{"BundlePath": "A.kext"},
                               {"BundlePath": "B.kext"}]}}
    editor.set_at(data, ("Kernel", "Add", 0, "BundlePath"), "C.kext")
    assert data["Kernel"]["Add"][0]["BundlePath"] == "C.kext"
    new_path = editor.move_item(data, ("Kernel", "Add", 0), 1)
    assert new_path == ("Kernel", "Add", 1)
    assert [item["BundlePath"] for item in data["Kernel"]["Add"]] == [
        "B.kext", "C.kext"]
    editor.remove_at(data, ("Kernel", "Add", 0))
    assert data["Kernel"]["Add"] == [{"BundlePath": "C.kext"}]


def test_a_validator_run_parses_a_clean_result():
    output = (
        "NOTE: This version of ocvalidate is only compatible with OpenCore "
        "version 1.0.8!\n\nCompleted validating config.plist in 1 ms. "
        "No issues found.\n")
    result = editor.parse_validator_output(output, 0)
    assert result.ok
    assert result.issues == ()
    assert result.version.startswith("NOTE: This version")
    assert result.summary == "No issues found."


def test_a_validator_run_keeps_every_ocs_line_as_an_issue():
    output = (
        "OCS: No schema for ClearTaskSwitchBit at 2 index, context <Quirks>!\n"
        "OCS: No schema for HideVerbose at 3 index, context <Drivers>!\n"
        "Serialisation returns 2 errors!\n")
    result = editor.parse_validator_output(output, 2)
    assert not result.ok
    assert len(result.issues) == 3
    assert result.issues[0].startswith("OCS: No schema")
    assert result.summary == "3 issues found."


def test_a_silent_nonzero_exit_is_still_a_reported_issue():
    result = editor.parse_validator_output("", 3)
    assert not result.ok
    assert result.issues == ("ocvalidate exited with status 3.",)


def test_validation_checks_a_temporary_copy_and_leaves_the_file_alone(
        tmp_path, monkeypatch):
    """The saved config.plist is never the file ocvalidate is pointed at.

    A validator that rewrote or truncated the real file would corrupt an EFI
    folder the moment somebody pressed Validate, so the copy is temporary, it
    holds the in-memory state rather than the old bytes, and it disappears.
    """
    document, _data = _document(tmp_path)
    before = document.path.read_bytes()
    document.data["Booter"]["Quirks"]["ResizeAppleGpuBars"] = -1
    seen = []

    def fake_run_ocvalidate(path, allow_download=True):
        copy = Path(path)
        seen.append(copy)
        assert copy.parent != tmp_path
        assert plistlib.loads(copy.read_bytes())["Booter"]["Quirks"][
            "ResizeAppleGpuBars"] == -1
        return editor.ValidationResult(
            ok=True, version="", issues=(), output="No issues found.")

    monkeypatch.setattr(editor, "run_ocvalidate", fake_run_ocvalidate)
    result = editor.validate_document(document.data, allow_download=False)

    assert result.ok
    assert len(seen) == 1
    assert not seen[0].exists() and not seen[0].parent.exists()
    assert document.path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [document.path]


def test_a_verified_tool_is_found_in_the_tools_directory(monkeypatch, tmp_path):
    tools = _use_isolated_tools(monkeypatch, tmp_path)
    binary = tools / INSTALL_NAME
    binary.write_bytes(b"validator")
    binary.chmod(0o755)
    _pin(monkeypatch, hashlib.sha256(b"validator").hexdigest())

    assert editor.find_ocvalidate() == binary


def test_a_tampered_tool_is_refused_before_it_runs(monkeypatch, tmp_path):
    tools = _use_isolated_tools(monkeypatch, tmp_path)
    binary = tools / INSTALL_NAME
    binary.write_bytes(b"not the validated bytes")
    binary.chmod(0o755)
    _pin(monkeypatch, hashlib.sha256(b"validator").hexdigest())

    with pytest.raises(editor.OcvalidateVerificationFailed):
        editor.find_ocvalidate()


def test_a_missing_tool_without_downloads_is_a_typed_failure(monkeypatch, tmp_path):
    _use_isolated_tools(monkeypatch, tmp_path)
    _pin(monkeypatch, "0" * 64)
    with pytest.raises(editor.OcvalidateUnavailable):
        editor.ensure_ocvalidate(allow_download=False)


def test_the_pinned_archive_installs_only_the_verified_member(monkeypatch, tmp_path):
    tools = _use_isolated_tools(monkeypatch, tmp_path)
    member = ARCHIVE_MEMBER
    payload = b"inside the archive"
    archive_bytes = _archive_with(member, payload)
    _pin(monkeypatch, hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(editor, "OCVALIDATE_ARCHIVE_SHA256",
                        hashlib.sha256(archive_bytes).hexdigest())

    class FakeFetcher:
        def download_and_save_file(self, url, destination, sha256_hash, product=None):
            assert sha256_hash == editor.OCVALIDATE_ARCHIVE_SHA256
            Path(destination).write_bytes(archive_bytes)
            return True

    import ocengine.resource_fetcher as fetcher_module

    monkeypatch.setattr(fetcher_module, "ResourceFetcher", FakeFetcher)
    installed = editor.ensure_ocvalidate()

    assert installed == tools / INSTALL_NAME
    assert installed.read_bytes() == payload
    assert os.access(installed, os.X_OK)


def test_an_archive_member_with_the_wrong_digest_is_never_installed(
        monkeypatch, tmp_path):
    tools = _use_isolated_tools(monkeypatch, tmp_path)
    member = ARCHIVE_MEMBER
    archive_bytes = _archive_with(member, b"tampered member")
    _pin(monkeypatch, hashlib.sha256(b"expected member").hexdigest())
    monkeypatch.setattr(editor, "OCVALIDATE_ARCHIVE_SHA256",
                        hashlib.sha256(archive_bytes).hexdigest())

    class FakeFetcher:
        def download_and_save_file(self, url, destination, sha256_hash, product=None):
            Path(destination).write_bytes(archive_bytes)
            return True

    import ocengine.resource_fetcher as fetcher_module

    monkeypatch.setattr(fetcher_module, "ResourceFetcher", FakeFetcher)
    with pytest.raises(editor.OcvalidateVerificationFailed):
        editor.ensure_ocvalidate()
    assert not (tools / INSTALL_NAME).exists()


def test_serial_values_land_in_platform_info_and_keep_binary_rom():
    data = {"PlatformInfo": {"Generic": {}}}
    editor.apply_serials(data, {
        "SystemSerialNumber": "C02TEST",
        "MLB": "C02TESTMLB",
        "SystemUUID": "00000000-0000-0000-0000-000000000001",
        "ROM": b"\xAA\xBB\xCC\xDD\xEE\xFF",
    }, "MacPro7,1")
    generic = data["PlatformInfo"]["Generic"]
    assert generic["SystemProductName"] == "MacPro7,1"
    assert generic["SystemSerialNumber"] == "C02TEST"
    assert generic["ROM"] == b"\xAA\xBB\xCC\xDD\xEE\xFF"


def _archive_with(member: str, payload: bytes) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(member, payload)
    return buffer.getvalue()
