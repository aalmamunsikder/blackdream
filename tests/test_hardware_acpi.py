"""The root-gated half of end-to-end input: reading the firmware ACPI tables.

Everything here runs unprivileged.  The helper is tested as a library (:func:`dump_into`
over a fixture folder) and as a process (its refusal to run without root), and the app
side is driven against a fake ``pkexec`` and a fake helper that produce exactly the
layout the real one promises.  That leaves one claim unproven by this file: that polkit
shows the dialog and that root can read ``/sys/firmware/acpi/tables``.  Proving that
needs somebody to type a password.
"""

from __future__ import annotations

import ast
import os
import stat
import struct
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from blackdream.hardware import acpi

# Everything in this file is the Linux half of the ACPI step: polkit's action file,
# ``pkexec``, and ``/sys/firmware/acpi/tables``. Windows has no ``os.geteuid`` and no
# ``/sys``, so collecting the file there fails before a single test runs.
LINUX = sys.platform.startswith("linux")
pytestmark = pytest.mark.skipif(not LINUX, reason="the ACPI helper is Linux-only")
from blackdream.hardware import dump_acpi_tables as helper
from blackdream.core.pipeline import Cancelled
from ocengine.fatal import EngineError

SRC = Path(__file__).resolve().parent.parent / "src" / "blackdream" / "hardware"

SIGNATURES = ["DSDT", "APIC", "DMAR", "SSDT1", "SSDT2", "FACP", "TPM2"]


def table_bytes(signature: str) -> bytes:
    """A header the engine's own signature reader would accept: 4 bytes, then length."""
    body = b"\x00" * 32
    return signature.encode() + struct.pack("<I", 36 + len(body)) + body


@pytest.fixture
def source(tmp_path):
    """A stand-in for ``/sys/firmware/acpi/tables``."""
    directory = tmp_path / "tables"
    directory.mkdir()
    for signature in SIGNATURES:
        (directory / signature).write_bytes(table_bytes(signature))
    return directory


def _script(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(0o755)
    return path


# ---- the helper's own rules ----


def test_table_names_keeps_only_plain_table_files(source, tmp_path):
    (source / "data").mkdir()
    (source / "outside").symlink_to(tmp_path / "elsewhere")
    (source / "DSDT.aml").write_bytes(table_bytes("DSDT"))
    (source / "two words").write_bytes(b"junk")
    assert helper.table_names(str(source)) == sorted(SIGNATURES)


def test_dump_copies_every_table_and_names_it_for_the_picker(source, tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    assert helper.dump_into(str(dest), str(source)) == sorted(SIGNATURES)
    assert sorted(p.name for p in dest.iterdir()) == sorted(
        "{}.aml".format(signature) for signature in SIGNATURES)


def test_a_firmware_with_no_dsdt_is_refused_rather_than_emptied(tmp_path):
    source = tmp_path / "tables"
    source.mkdir()
    (source / "APIC").write_bytes(table_bytes("APIC"))
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(helper.DumpFailed, match="no DSDT"):
        helper.dump_into(str(dest), str(source))


def test_one_unreadable_table_is_skipped_but_the_dsdt_is_not(source, tmp_path):
    os.chmod(source / "FACP", 0o000)
    try:
        dest = tmp_path / "dest"
        dest.mkdir()
        written = helper.dump_into(str(dest), str(source))
        assert "FACP" not in written
        assert "DSDT" in written
    finally:
        os.chmod(source / "FACP", 0o644)


@pytest.mark.skipif(getattr(os, "geteuid", lambda: 1)() == 0,
                    reason="the point is that this is not root")
def test_the_helper_refuses_to_run_unprivileged():
    result = subprocess.run([sys.executable, str(SRC / acpi.HELPER_NAME)],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "must run as root" in result.stderr


HELPER_TREE = ast.parse((SRC / acpi.HELPER_NAME).read_text(encoding="utf-8"))


def _attribute_reads(tree, owner, attr):
    return [node for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            and node.attr == attr and isinstance(node.value, ast.Name)
            and node.value.id == owner]


def test_the_helper_reads_no_arguments_at_all():
    """The property pkexec's documentation demands of an action that keeps rights.

    ``auth_admin_keep`` means a second dump can run with no prompt, so a helper that
    honoured an argument would let the caller choose where root writes.
    """
    assert not _attribute_reads(HELPER_TREE, "sys", "argv")
    assert not [node for node in ast.walk(HELPER_TREE) if isinstance(node, ast.Name)
                and node.id == "argv"]
    assert not _attribute_reads(HELPER_TREE, "os", "execv")
    assert not _attribute_reads(HELPER_TREE, "subprocess", "run")


def test_the_helper_reads_only_three_environment_names():
    """The ones that say who to hand the folder back to -- nothing that steers it.

    pkexec scrubs the environment before the helper runs, so an override here would be
    unusable anyway; pinning the set is what stops a future edit from making the
    behaviour caller-controlled through a route that looks harmless.
    """
    keys = set()
    for node in ast.walk(HELPER_TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" \
                and isinstance(node.func.value, ast.Attribute) \
                and node.func.value.attr == "environ":
            keys.update(arg.value for arg in node.args if isinstance(arg, ast.Constant))
    assert keys == {"PKEXEC_UID", "SUDO_UID", "SUDO_GID"}


def test_the_helper_touches_no_network_and_no_shell():
    imported = {alias.name.split(".")[0] for node in ast.walk(HELPER_TREE)
                if isinstance(node, ast.Import) for alias in node.names}
    assert imported <= {"os", "re", "shutil", "stat", "sys", "tempfile"}
    assert not imported & {"subprocess", "urllib", "socket", "http", "requests"}


def test_the_only_absolute_paths_are_the_firmware_folder_and_a_temp_prefix():
    paths = [node.value for node in ast.walk(HELPER_TREE)
             if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and node.value.startswith("/")]
    assert all(path.startswith("/sys/firmware/acpi") for path in paths), paths
    assert helper.TABLE_DIR == "/sys/firmware/acpi/tables"


# ---- who may be asked to run it ----


class _Stat:
    def __init__(self, uid, mode):
        self.st_uid = uid
        self.st_mode = mode


def _pretend_stat(monkeypatch, uid, mode, target):
    monkeypatch.setattr(acpi.os, "stat", lambda path: _Stat(uid, mode))
    monkeypatch.setattr(acpi, "INSTALLED_HELPER", target)
    monkeypatch.delenv(acpi.HELPER_ENV, raising=False)


def test_a_helper_the_calling_user_can_edit_is_never_offered(tmp_path, monkeypatch):
    candidate = _script(tmp_path / acpi.HELPER_NAME, "#!/usr/bin/python3\n")
    for uid, mode in ((os.getuid(), 0o100755), (0, 0o100755 | stat.S_IWGRP),
                      (0, 0o100755 | stat.S_IWOTH)):
        _pretend_stat(monkeypatch, uid, mode, candidate)
        assert acpi.trusted_helper() is None, (uid, oct(mode))


def test_a_helper_root_owns_and_nobody_else_writes_is_offered(tmp_path, monkeypatch):
    candidate = _script(tmp_path / acpi.HELPER_NAME, "#!/usr/bin/python3\n")
    _pretend_stat(monkeypatch, 0, 0o100755, candidate)
    assert acpi.trusted_helper() == candidate.resolve()


def test_a_helper_nobody_can_execute_is_not_offered(tmp_path, monkeypatch):
    candidate = tmp_path / acpi.HELPER_NAME
    candidate.write_text("#!/usr/bin/python3\n")
    candidate.chmod(0o644)
    _pretend_stat(monkeypatch, 0, 0o100644, candidate)
    assert acpi.trusted_helper() is None


def test_this_checkout_cannot_be_the_helper():
    """Measured on the real files, not on a fixture.

    A checkout is writable by whoever cloned it, so the packaged install has to move
    the helper somewhere root owns -- and this is why the app says that plainly
    instead of letting pkexec prompt over a file the user could have edited.
    """
    info = os.stat(acpi.helper_source())
    assert info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    assert acpi.trusted_helper() is None or acpi.trusted_helper() != acpi.helper_source()


# ---- the app side, driven by a fake pkexec ----

FAKE_HELPER = textwrap.dedent("""\
    #!/usr/bin/python3
    import os, shutil, sys, tempfile
    dest = tempfile.mkdtemp(prefix=os.environ.get("FAKE_PREFIX", "blackdream-acpi-"))
    if os.environ.get("FAKE_RECORD"):
        open(os.environ["FAKE_RECORD"], "w").write(dest)

    def leave(code):
        # A real helper that fails removes its own folder; the fake has to, or the
        # failure tests would litter whatever tmp root the runner happens to use.
        shutil.rmtree(dest, ignore_errors=True)
        sys.exit(code)

    if os.environ.get("FAKE_SILENT") == "1":
        leave(0)
    for signature in os.environ.get("FAKE_TABLES", "").split(","):
        if signature:
            open(os.path.join(dest, signature + ".aml"), "wb").write(
                signature.encode() + b"\\x00" * 36)
    code = int(os.environ.get("FAKE_EXIT", "0"))
    if code:
        sys.stderr.write(os.environ.get("FAKE_WHY", "") + "\\n")
        leave(code)
    print(dest)
    """)

FAKE_PKEXEC = textwrap.dedent("""\
    #!/usr/bin/python3
    import os, sys
    program = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if os.environ.get("FAKE_ECHO"):
        open(os.environ["FAKE_ECHO"], "w").write("\\n".join(sys.argv[1:]))
    sys.exit(os.execv(program[-1], [program[-1]]))
    """)


@pytest.fixture
def rig(tmp_path):
    return acpi.AcpiDumper(helper=_script(tmp_path / "fake_helper.py", FAKE_HELPER),
                           pkexec=str(_script(tmp_path / "pkexec", FAKE_PKEXEC)))


def _ask(monkeypatch, *tables, **fake):
    monkeypatch.setenv("FAKE_TABLES", ",".join(tables))
    for key, value in fake.items():
        monkeypatch.setenv("FAKE_" + key.upper(), str(value))


def _failure(dumper, out_dir):
    try:
        dumper.dump(out_dir)
    except EngineError as error:
        return error
    raise AssertionError("the dump should not have succeeded")


def test_the_dump_lands_beside_the_report_and_its_temp_folder_goes(rig, tmp_path, monkeypatch):
    record = tmp_path / "announced"
    _ask(monkeypatch, "DSDT", "APIC", "SSDT1", record=str(record))
    report_dir = tmp_path / "reports" / "run"
    report_dir.mkdir(parents=True)

    dumped = rig.dump(report_dir)

    assert dumped.acpi_dir == report_dir / acpi.ACPI_SUBDIR
    assert dumped.tables == ("APIC", "DSDT", "SSDT1")
    assert sorted(p.name for p in dumped.acpi_dir.iterdir()) == [
        "APIC.aml", "DSDT.aml", "SSDT1.aml"]
    assert not record.read_text().strip() or not Path(record.read_text()).exists()


def test_the_internal_agent_is_switched_off(rig, tmp_path, monkeypatch):
    """Without it, a session with no agent blocks on /dev/tty instead of failing.

    Measured: pkexec waited for an answer that could not arrive, and the job would sit
    inside the runner until its budget expired rather than reporting anything.
    """
    echo = tmp_path / "argv"
    _ask(monkeypatch, "DSDT", silent=1)
    monkeypatch.setenv("FAKE_ECHO", str(echo))
    with pytest.raises(acpi.TablesDumpFailed):
        rig.dump(tmp_path / "out")
    argv = echo.read_text().split("\n")
    assert argv[0] == "--disable-internal-agent"
    assert argv[-1] == str(rig.helper)


def test_the_authentication_window_being_closed_is_not_blamed_on_the_hardware(
        rig, tmp_path, monkeypatch):
    _ask(monkeypatch, "DSDT", exit=acpi.DISMISSED)
    error = _failure(rig, tmp_path / "out")
    assert isinstance(error, acpi.TablesRefused)
    assert "closed" in error.detail


def test_a_refusal_from_polkit_keeps_its_own_reason(rig, tmp_path, monkeypatch):
    _ask(monkeypatch, "DSDT", exit=acpi.REFUSED, why="Not authorized")
    error = _failure(rig, tmp_path / "out")
    assert isinstance(error, acpi.TablesRefused)
    assert error.detail == "Not authorized"


def test_the_helpers_own_failure_carries_its_stderr(rig, tmp_path, monkeypatch):
    _ask(monkeypatch, "DSDT", exit=2, why="the firmware exposed no DSDT")
    error = _failure(rig, tmp_path / "out")
    assert isinstance(error, acpi.TablesDumpFailed)
    assert "no DSDT" in error.detail


def test_a_folder_that_is_not_a_dump_is_rejected(rig, tmp_path, monkeypatch):
    _ask(monkeypatch, "DSDT", prefix="someone-elses-tmp-")
    error = _failure(rig, tmp_path / "out")
    assert isinstance(error, acpi.TablesDumpFailed)
    assert "unexpected folder" in error.detail


def test_a_dump_that_announced_nothing_is_rejected(rig, tmp_path, monkeypatch):
    _ask(monkeypatch, "DSDT", silent=1)
    error = _failure(rig, tmp_path / "out")
    assert isinstance(error, acpi.TablesDumpFailed)
    assert "no folder" in error.detail


def test_no_answer_in_time_withdraws_the_request(tmp_path):
    slow = _script(tmp_path / "pkexec", "#!/bin/sh\nexec sleep 30\n")
    dumper = acpi.AcpiDumper(helper=_script(tmp_path / "anything.py",
                                            "#!/usr/bin/python3\n"),
                             pkexec=str(slow), timeout=0.4)
    error = _failure(dumper, tmp_path / "out")
    assert isinstance(error, acpi.TablesTimedOut)
    assert "0.4" in error.detail


def test_cancelling_during_the_wait_stops_waiting(tmp_path):
    slow = _script(tmp_path / "pkexec", "#!/bin/sh\nexec sleep 30\n")
    dumper = acpi.AcpiDumper(helper=_script(tmp_path / "anything.py",
                                            "#!/usr/bin/python3\n"),
                             pkexec=str(slow), timeout=30)
    with pytest.raises(Cancelled):
        dumper.dump(tmp_path / "out", is_cancelled=lambda: True)


def test_a_missing_pkexec_is_explained_as_one(tmp_path):
    dumper = acpi.AcpiDumper(helper=_script(tmp_path / "anything.py",
                                            "#!/usr/bin/python3\n"),
                             pkexec="definitely-not-pkexec")
    error = _failure(dumper, tmp_path / "out")
    assert isinstance(error, acpi.TablesHelperMissing)
    assert "polkit" in error.detail


# ---- the polkit action, and what ships with the package ----


@pytest.fixture(scope="module")
def policy_action():
    root = ET.parse(SRC / acpi.POLICY_NAME).getroot()
    return root.find("action")


def test_the_policy_binds_one_action_to_the_installed_helper(policy_action):
    assert policy_action.get("id") == "com.blackdream.dumpacpi"
    assert (SRC / acpi.POLICY_NAME).name == policy_action.get("id") + ".policy"
    annotations = {node.get("key"): node.text for node in policy_action.findall("annotate")}
    assert annotations == {"org.freedesktop.policykit.exec.path": str(acpi.INSTALLED_HELPER)}


def test_the_policy_asks_for_administrator_and_keeps_the_answer(policy_action):
    defaults = {node.tag: node.text for node in policy_action.find("defaults")}
    assert defaults == {"allow_any": "no", "allow_inactive": "no",
                        "allow_active": "auth_admin_keep"}


def test_the_policy_text_says_what_is_being_authorised(policy_action):
    message = policy_action.find("message").text.lower()
    assert "acpi" in message and "administrator" in message


def test_the_helper_is_shipped_and_needs_nothing_but_the_standard_library():
    text = (SRC / acpi.HELPER_NAME).read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/python3")
    assert acpi.helper_source().is_file() and acpi.policy_source().is_file()
    imported = {alias.name.split(".")[0] for node in ast.walk(HELPER_TREE)
                if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    assert imported <= {"os", "re", "shutil", "stat", "sys", "tempfile"}


def test_the_dump_folder_is_the_one_the_engine_recurses_into():
    """``read_acpi_tables`` finds a SysReport-shaped export by its ``ACPI`` leaf."""
    assert acpi.ACPI_SUBDIR == "ACPI"
