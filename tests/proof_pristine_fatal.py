import io, os, sys, contextlib, importlib, json
from unittest import mock

from pristine import insert_paths

TARGET = sys.argv[1]           # "pristine" | "converted"
insert_paths()
pkg = "Scripts" if TARGET == "pristine" else "ocengine"
import fixtures

cc_mod = importlib.import_module(pkg + ".compatibility_checker")
CompatibilityChecker = cc_mod.CompatibilityChecker

def run(builder):
    report = json.loads(json.dumps(builder()))   # deep copy: engine mutates
    buf = io.StringIO()
    outcome = {}
    with mock.patch("builtins.input", lambda *a, **k: ""):
        try:
            with contextlib.redirect_stdout(buf):
                hr, native, ocl = CompatibilityChecker().check_compatibility(report)
            outcome = {"kind": "ok", "native": native, "ocl": ocl}
        except SystemExit as e:
            outcome = {"kind": "SystemExit", "code": e.code}
        except BaseException as e:
            outcome = {"kind": type(e).__name__, "str": str(e)}
    text = buf.getvalue()
    outcome["ansi"] = "\x1b[" in text
    outcome["lines"] = len([l for l in text.splitlines() if l.strip()])
    return outcome

names = [("healthy/" + n, f) for n, f in sorted(fixtures.ALL_HEALTHY.items())] + \
        [("fatal/" + n, f) for n, f in sorted(fixtures.ALL_FATAL.items())]
print("=== {} ===".format(TARGET))
for name, builder in names:
    print("{:38s} {}".format(name, json.dumps(run(builder), default=str)))
