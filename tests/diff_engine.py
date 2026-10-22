"""Differential harness: pristine upstream engine vs our vendored engine.

Imports both module trees in one process (`Scripts` from the untouched clone at
``/data/BlackDream/OpCore-Simplify``, `ocengine` from ``src/``), feeds each the same
synthetic report, and compares the verdict text line by line. Upstream writes to
stdout with ANSI colour and calls ``sys.exit``; ours writes to a sink and raises a
typed error. Those two surfaces are normalised here -- anything else that differs is a
real grading change introduced by the conversion.

Run: python3 tests/diff_engine.py [limit]
"""

import contextlib, io, itertools, json, re, sys, time
from unittest import mock

ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
PRISTINE_ROOT = "/data/BlackDream/OpCore-Simplify"
CONVERTED_ROOT = "/data/BlackDream/blackdream/src"
sys.path.insert(0, PRISTINE_ROOT)
sys.path.insert(0, CONVERTED_ROOT)

import fixtures  # noqa: E402

INTEL_IDS = ["0042", "0046", "0102", "0106", "010A", "0152", "0156", "0162", "0412",
             "0A16", "0C16", "0D16", "0B16", "1618", "0910", "191B", "591E", "3E98",
             "3E9B", "3EA1", "87C0", "8A52", "9B41", "A780", "46A3", "4C8A", "1234"]
AMD_IDS = ["15D8", "15DD", "1636", "6995", "699F", "73FF", "73BF", "6879", "67DF", "7000"]
NV_IDS = ["1B80", "1C03", "128B", "0DC1", "17C2", "1F12", "2206", "2504"]
AMD_CODENAMES = ["Hainan", "Oland", "Cape Verde", "Pitcairn", "Tahiti", "Bonaire",
                 "Vega 10", "Vega 20", "Navi 10", "Navi 21", "Navi 23", "Polaris 20",
                 "Ellesmere", "Baffin", "Radeon R5 M330"]
NV_CODENAMES = ["Kepler", "Pascal", "Maxwell", "Fermi", "Tesla", "Turing", "Ampere"]
CPU_NAMES = ["Intel Core i7-8550U", "Intel Celeron 2955U", "Intel Pentium 4405Y",
             "AMD Ryzen 5 3500U"]
SIMDS = ["SSE3,SSE4.1,SSE4.2,AVX,AVX2", "SSE3,SSE4.1,SSE4.2,AVX",
         "SSE2,SSSE3", "SSE3,SSE4.1,SSE4.2"]
NET_IDS = ["8086-15B8", "8086-24F3", "8086-A370", "14E4-43A0", "168C-003C",
           "10EC-8125", "1D6B-0001"]


def reports():
    """Cross the branch-relevant fields; each report is a full healthy shape."""
    base = fixtures.coffee_lake_laptop()
    combos = []
    for device_id in INTEL_IDS:
        combos.append(("intel-{}".format(device_id),
                       {"Manufacturer": "Intel", "Codename": "Amber Lake",
                        "Device ID": "8086-" + device_id, "Device Type": "Integrated GPU"},
                       "Intel UHD Graphics"))
    for codename, device_id in zip(AMD_CODENAMES, AMD_IDS * 2):
        combos.append(("amd-{}".format(device_id),
                       {"Manufacturer": "AMD", "Codename": codename,
                        "Device ID": "1002-" + device_id, "Device Type": "Discrete GPU"},
                       "AMD Radeon Graphics"))
    for codename, device_id in zip(NV_CODENAMES, NV_IDS):
        combos.append(("nv-{}".format(device_id),
                       {"Manufacturer": "NVIDIA", "Codename": codename,
                        "Device ID": "10DE-" + device_id, "Device Type": "Discrete GPU"},
                       "NVIDIA GeForce"))
    for label, gpu, gpu_name in combos:
        for cpu, simd in itertools.product(CPU_NAMES, SIMDS):
            report = json.loads(json.dumps(base))
            report["CPU"]["Processor Name"] = cpu
            report["CPU"]["SIMD Features"] = simd
            report["GPU"] = {gpu_name: dict(gpu)}
            report["Monitor"] = {
                "Internal Panel": {"Connector Type": "eDP", "Resolution": "1920x1080",
                                   "Connected GPU": gpu_name}}
            yield "{}|{}|{}".format(label, cpu, simd), report
    for label, gpu, gpu_name in combos[:24]:
        for platform in ("Desktop", "Laptop"):
            for connector in ("VGA", "HDMI"):
                report = json.loads(json.dumps(base))
                report["Motherboard"]["Platform"] = platform
                report["GPU"] = {gpu_name: dict(gpu)}
                report["Monitor"] = {
                    "External": {"Connector Type": connector, "Resolution": "1920x1080",
                                 "Connected GPU": gpu_name}}
                yield "{}|{}|{}".format(label, platform, connector), report
    for net_id in NET_IDS:
        for connector in ("Internal", "VGA"):
            report = json.loads(json.dumps(base))
            report["Monitor"] = {"Panel": {"Connector Type": connector,
                                           "Resolution": "1920x1080",
                                           "Connected GPU": "Intel UHD Graphics 630"}}
            report["Network"] = {"NIC": {"Bus Type": "PCI", "Device ID": net_id,
                                         "PCI Path": "PciRoot(0x0)/Pci(0x1f,0x6)"}}
            yield "net|{}|{}".format(net_id, connector), report


BOX = "╔╗╚╝╟╠─║│┌└"


def normalise(lines):
    """Drop blank lines, ANSI, and box-drawing/banner chrome. head() becomes a sink
    section event rather than a log line, and exit_program()'s contact card is
    presentation that the GUI owns."""
    out = []
    for line in lines:
        text = ANSI.sub("", line).strip()
        if not text or set(text) <= set(BOX + " "):
            continue
        if text[0] in BOX:
            continue
        out.append(text)
    return out


# Upstream stdout intentionally removed by the conversion rather than folded into a
# typed error -- author-directed content, not user information.
DOCUMENTED_DROPS = (
    "Please do NOT spam my inbox",
    "For more information, to report errors",
    "Thank you for using our program",
)

WORD = re.compile(r"[A-Za-z][A-Za-z0-9.()/-]{2,}")


def folds_into_error(line, error):
    """True when an upstream stdout line survived as the raised error's detail or
    remediation. Compared by significant-word coverage, since the conversion
    rewords the sentences into complete paragraphs."""
    haystack = " ".join([error.title, error.detail] + list(error.remediation)).lower()
    tokens = {token.lower() for token in WORD.findall(line)}
    if not tokens:
        return True
    kept = sum(1 for token in tokens if token in haystack)
    return kept / len(tokens) >= 0.6


def run_pristine(report):
    import Scripts.compatibility_checker as p_cc
    captured = io.StringIO()
    with mock.patch("builtins.input", lambda *a, **k: ""), \
         mock.patch.object(time, "sleep", lambda *a, **k: None):
        try:
            with contextlib.redirect_stdout(captured):
                _hr, native, ocl = p_cc.CompatibilityChecker().check_compatibility(
                    json.loads(json.dumps(report)))
            return normalise(captured.getvalue().splitlines()), ("ok", native, ocl)
        except SystemExit as exit_error:
            return normalise(captured.getvalue().splitlines()), ("exit", exit_error.code)


def run_converted(report):
    from ocengine import runtime
    import ocengine.compatibility_checker as c_cc
    recorder = runtime.RecordingSink()
    previous = runtime.set_sink(recorder)
    with mock.patch("builtins.input", lambda *a, **k: ""):
        try:
            _hr, native, ocl = c_cc.CompatibilityChecker().check_compatibility(
                json.loads(json.dumps(report)))
            outcome = ("ok", native, ocl)
        except BaseException as error:
            outcome = (type(error).__name__, str(error), error)
    runtime.set_sink(previous)
    messages = [message for _level, message in recorder.logs]
    return normalise(messages), outcome


def compare(pristine_lines, pristine_outcome, converted_lines, converted_outcome):
    """Return None when equivalent, else a short reason string."""
    if pristine_outcome[0] == "ok":
        if converted_outcome[0] != "ok":
            return "upstream ok, ours raised {}".format(converted_outcome[0])
        if pristine_outcome[1:] != converted_outcome[1:]:
            return "verdict range drift {} != {}".format(pristine_outcome[1:], converted_outcome[1:])
        if pristine_lines != converted_lines:
            return "message text drift"
        return None
    # upstream exited the process: ours must raise a typed fatal instead
    if converted_outcome[0] == "ok":
        return "upstream exited but ours returned a verdict"
    shared = min(len(pristine_lines), len(converted_lines))
    if pristine_lines[:shared] != converted_lines[:shared] or len(converted_lines) > len(pristine_lines):
        return "message text drift before the fatal"
    for leftover in pristine_lines[shared:]:
        if any(drop in leftover for drop in DOCUMENTED_DROPS):
            continue
        if not folds_into_error(leftover, converted_outcome[2]):
            return "fatal text lost: {!r}".format(leftover)
    return None


def main(limit=None):
    from ocengine import runtime
    mismatches, checked = [], 0
    seen = set()
    for label, report in reports():
        if label in seen:
            continue
        seen.add(label)
        if limit and checked >= limit:
            break
        pristine_lines, pristine_outcome = run_pristine(report)
        converted_lines, converted_outcome = run_converted(report)
        checked += 1
        reason = compare(pristine_lines, pristine_outcome, converted_lines, converted_outcome)
        if reason:
            mismatches.append((label, pristine_lines, pristine_outcome,
                               converted_lines, converted_outcome, reason))
    print("reports compared: {}".format(checked))
    print("mismatches: {}".format(len(mismatches)))
    for label, pl, po, cl, co, reason in mismatches[:12]:
        print("\n### {}  [{}]".format(label, reason))
        print("pristine : {}".format(po))
        print("converted: {}".format(co))
        import difflib
        for line in list(difflib.unified_diff(pl, cl, "upstream", "ours", lineterm=""))[:24]:
            print("  " + line)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else None))
