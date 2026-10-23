"""The built-in scanner must produce a report the engine itself accepts.

Everything here is checked against the vendored engine's real schema and, where the
hardware allows, the real machine -- a hand-written report that grades well proves the
fixtures work, not that the scanner does.
"""

import ast
import json
import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import fixtures
from blackdream.core.pipeline import Pipeline
from blackdream.hardware import collect as collect_module
from blackdream.hardware import CollectionRejected, ReportCollector
from ocengine.fatal import FatalIncompatibility
from ocengine.report_validator import ReportValidator
from ocengine.runtime import RecordingSink, set_sink

SNIFFER = SRC / "blackdream" / "hardware" / "sniffer"
LINUX = sys.platform.startswith("linux") and Path("/sys/bus/pci/devices").is_dir()


def _python_files():
    return sorted(p for p in SNIFFER.rglob("*.py"))


@pytest.fixture
def sink():
    recording = RecordingSink()
    set_sink(recording)
    return recording


def _calls(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                yield func.id, node
            elif isinstance(func, ast.Attribute):
                yield func.attr, node


def test_the_vendored_scanner_touches_no_terminal():
    """A GUI has no terminal: a surviving print, prompt or exit is a conversion defect.

    Matched on the syntax tree, not the text -- the scanner has a method genuinely
    named ``input``, paths genuinely named ``/sys/class/input``, and docstrings that
    name the very calls that were removed.
    """
    forbidden_builtin = {"print", "input", "raw_input"}
    forbidden_attribute = {"system", "exit", "_exit", "popen", "execv", "execve", "spawnl"}
    offenders = []

    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name, call in _calls(tree):
            func = call.func
            if isinstance(func, ast.Name) and name in forbidden_builtin:
                offenders.append("{}:{}: {}".format(path.name, call.lineno, name))
            elif isinstance(func, ast.Attribute) and name in forbidden_attribute:
                offenders.append("{}:{}: {}.{}".format(path.name, call.lineno, getattr(func.value, "id", "?"), name))

    assert offenders == []


def test_the_vendored_scanner_never_elevates_or_reaches_the_network():
    """Upstream's runner had a sudo mode and its release fetcher shared the tree.

    A scan must be pure local reads: no download at collection time, no privilege
    escalation, and no shell string that a device name could influence.
    """
    banned_imports = {"urllib", "requests", "socket", "http", "ftplib", "run", "github", "resource_fetcher", "cpuid"}
    offenders = []

    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in banned_imports:
                        offenders.append("{}:{}: imports {}".format(path.name, node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in banned_imports:
                offenders.append("{}:{}: imports {}".format(path.name, node.lineno, node.module))

        for name, call in _calls(tree):
            if name in {"run", "Popen", "call", "check_output"}:
                if any(keyword.arg == "shell" and getattr(keyword.value, "value", False) for keyword in call.keywords):
                    offenders.append("{}:{}: shell=True".format(path.name, call.lineno))
                for literal in ast.walk(call):
                    if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                        if literal.value in {"sudo", "pkexec", "su"} or literal.value.startswith(("http://", "https://")):
                            offenders.append("{}:{}: {!r}".format(path.name, literal.lineno, literal.value))

    assert offenders == []


def test_the_bsd_license_and_provenance_ship_with_the_code():
    assert "BSD" in (SNIFFER / "LICENSE.upstream.BSD-3-Clause").read_text()
    notice = (SNIFFER / "VENDOR_NOTICE.txt").read_text()
    assert "Hardware-Sniffer" in notice
    assert re.search(r"Upstream commit\s+: \w{40}", notice)


def test_the_checklist_redraws_from_zero_at_a_constant_total(sink):
    """EngineBridge rebuilds its list on index 0, so any other shape renders one row."""
    checklist = collect_module._Checklist(sink)
    for index in range(1, 4):
        checklist.started("step {}".format(index), index, 3)
    checklist.finished()

    totals = {total for _name, _index, total, _state in sink.stages}
    assert totals == {3}
    assert [name for name, index, _t, _s in sink.stages if index == 0] == ["step 1", "step 1", "step 1", "step 1"]
    assert sink.stages[-3:] == [("step 1", 0, 3, "done"), ("step 2", 1, 3, "done"), ("step 3", 2, 3, "done")]


def test_a_rejected_acpi_path_is_dropped_not_fatal(sink, tmp_path):
    """The bug that made the first real scan unusable: sysfs reports _TZ_ paths.

    A thermal zone sits outside the \\_SB namespace the engine's acpi_path pattern
    allows, and ACPI Path is optional -- so the right answer is to lose that one value,
    not the report.
    """
    raw = fixtures.coffee_lake_laptop()
    raw["System Devices"]["LNXTHERM"] = {"Bus Type": "ACPI", "Device": "LNXTHERM", "ACPI Path": "\\_TZ_.THRM"}
    raw["BIOS"]["Above 4G Decoding"] = "Disabled"
    path = tmp_path / "Report.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    collector = ReportCollector()
    cleaned, findings = collector._reconcile(ReportValidator(), path, raw)

    assert "ACPI Path" not in cleaned["System Devices"]["LNXTHERM"]
    assert "Above 4G Decoding" not in cleaned["BIOS"]
    assert len(findings) == 2
    assert Pipeline().load_report(path)["System Devices"]["LNXTHERM"]["Device"] == "LNXTHERM"


def test_a_required_section_the_machine_lacks_is_stated_not_omitted(sink, tmp_path):
    """A virtual machine has no GPU, USB controller or storage controller to report.

    The scan omits empty sections and the engine then rejects the whole report for the
    missing keys, which is how a clean machine produced "the scanned hardware report was
    not accepted". Recording "none found" is what the scan actually measured.
    """
    raw = fixtures.coffee_lake_laptop()
    for section in ("GPU", "USB Controllers", "Storage Controllers"):
        del raw[section]
    path = tmp_path / "Report.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    cleaned, findings = ReportCollector()._reconcile(ReportValidator(), path, raw)

    assert cleaned["GPU"] == {}
    assert cleaned["USB Controllers"] == {}
    assert cleaned["Storage Controllers"] == {}
    assert any("no gpu found" in finding for finding in findings)
    assert Pipeline().load_report(path)["GPU"] == {}


def test_a_missing_cpu_is_never_invented(sink, tmp_path):
    """The counterpart: every CPU field is required, so an absent CPU means the scan saw
    nothing it could name. Inventing a placeholder would grade a machine nobody measured."""
    raw = fixtures.coffee_lake_laptop()
    del raw["CPU"]
    path = tmp_path / "Report.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(CollectionRejected):
        ReportCollector()._reconcile(ReportValidator(), path, raw)


def test_reconciliation_reports_when_it_cannot_fix_the_report(sink, tmp_path):
    path = tmp_path / "Report.json"
    path.write_text(json.dumps({"Motherboard": {"Name": "", "Chipset": "", "Platform": "Desktop"}}), encoding="utf-8")

    with pytest.raises(CollectionRejected):
        ReportCollector()._reconcile(ReportValidator(), path, json.loads(path.read_text()))


def test_absent_sections_are_read_from_the_schema_not_a_hardcoded_list():
    report = fixtures.coffee_lake_laptop()
    del report["Bluetooth"]
    report["SD Controller"] = {}

    absent = collect_module._absent_sections(ReportValidator(), report)

    assert {"Bluetooth", "SD Controller"} <= set(absent)
    assert "GPU" not in absent


@pytest.mark.skipif(not LINUX, reason="needs a Linux sysfs to scan")
def test_a_real_scan_is_accepted_and_graded_by_the_engine(sink, tmp_path):
    """The end-to-end claim, measured on this machine rather than asserted."""
    try:
        collected = ReportCollector().collect(tmp_path)
    except CollectionRejected as refusal:
        pytest.fail("this machine's scan was rejected: {}".format(refusal.detail))
    assert collected.report_path.name == "Report.json"

    pipeline = Pipeline()
    try:
        analysis = pipeline.analyze(pipeline.load_report(collected.report_path))
    except FatalIncompatibility as refusal:
        # A virtual machine reports no GPU, and the engine refuses to grade a machine
        # nothing can drive a display on. That is the scan being accepted and the
        # hardware being rejected, which is the distinction this test exists to draw.
        assert refusal.code == "gpu.absent", refusal.code
    else:
        assert analysis.report.get("CPU", {}).get("Compatibility")
    assert set(collected.report) >= {"Motherboard", "BIOS", "CPU", "GPU", "Network", "USB Controllers", "Input", "Storage Controllers"}


@pytest.mark.skipif(not LINUX, reason="needs a Linux sysfs to scan")
def test_a_real_scan_names_the_identifiers_the_engine_can_use(sink, tmp_path):
    from ocengine.datasets import chipset_data, cpu_data

    try:
        report = ReportCollector().collect(tmp_path).report
    except CollectionRejected as refusal:
        pytest.fail("this machine's scan was rejected: {}".format(refusal.detail))
    cpu_codename = report["CPU"]["Codename"]
    chipset = report["Motherboard"]["Chipset"]

    if cpu_codename == "Unknown":
        pytest.skip("this CPU is not in the engine's tables; the collector says so")
    assert cpu_codename in cpu_data.IntelCPUGenerations + getattr(cpu_data, "AMDCPUGenerations", [])
    if chipset == "Unknown":
        # A virtual machine has no chipset to read from DMI. The test's claim is that
        # the names the collector does produce are names the engine knows, so a host
        # that produces none has nothing to check here.
        pytest.skip("this chipset is not in the engine's tables; the collector says so")
    assert chipset in chipset_data.IntelChipsets + getattr(chipset_data, "AMDChipsets", [])
    assert report["CPU"]["SIMD Features"]
