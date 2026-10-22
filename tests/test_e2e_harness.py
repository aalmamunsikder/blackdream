"""The headless harness must resolve versions the way the window does and fail
cleanly without touching the network or the user's real cache.

The build itself is exercised by ``tools/e2e_build.py`` in the release checklist;
these tests cover the argument handling that would otherwise only fail in CI.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from blackdream.core.versions import VersionOption


def _harness():
    spec = importlib.util.spec_from_file_location("e2e_build", ROOT / "tools" / "e2e_build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OPTIONS = [
    VersionOption(darwin_major=22, name="macOS Ventura 13", requires_oclp=True, is_suggested=False),
    VersionOption(darwin_major=24, name="macOS Sequoia 15", requires_oclp=False, is_suggested=True),
]


def test_no_request_uses_the_suggested_option():
    harness = _harness()
    assert harness.choose_version(OPTIONS, None).value == "24.99.99"


@pytest.mark.parametrize("wanted", ["22", "22.99.99", "macOS Ventura 13"])
def test_every_spelling_of_a_version_resolves(wanted):
    harness = _harness()
    assert harness.choose_version(OPTIONS, wanted).darwin_major == 22


def test_an_unoffered_version_lists_the_real_choices():
    harness = _harness()
    with pytest.raises(SystemExit) as caught:
        harness.choose_version(OPTIONS, "26")
    message = str(caught.value)
    assert "not offered" in message
    assert "macOS Ventura 13 (22.99.99)" in message
    assert "macOS Sequoia 15 (24.99.99)" in message


def test_report_and_output_are_required():
    harness = _harness()
    with pytest.raises(SystemExit):
        harness._parser().parse_args([])
    args = harness._parser().parse_args(["--report", "R.json", "--output", "out"])
    assert args.report == "R.json" and args.output == "out"


def test_a_missing_report_fails_with_a_typed_error(tmp_path, monkeypatch, capsys):
    harness = _harness()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("BLACKDREAM_TOOLS_DIR", raising=False)

    code = harness.main([
        "--report", str(tmp_path / "Report.json"),
        "--output", str(tmp_path / "EFI"),
    ])

    assert code == 1
    captured = capsys.readouterr()
    assert "error: report.rejected" in captured.err
    assert "File does not exist" in captured.err
    assert not (tmp_path / "EFI").exists()


def test_warnings_precede_the_failure_in_the_log(monkeypatch, capsys):
    from ocengine import runtime
    from ocengine.fatal import EngineError

    harness = _harness()

    def failing_run(args):
        sink = runtime.RecordingSink()
        runtime.set_sink(sink)
        sink.log("warning", "the first mirror refused the request")
        raise EngineError(detail="the build stopped")

    monkeypatch.setattr(harness, "run", failing_run)
    try:
        code = harness.main(["--report", "R.json", "--output", "EFI"])
    finally:
        runtime.set_sink(runtime.NullSink())

    assert code == 1
    err = capsys.readouterr().err
    assert "the first mirror refused the request" in err
    assert err.index("the first mirror") < err.index("error: engine.error")
