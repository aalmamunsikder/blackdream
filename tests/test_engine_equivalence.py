"""Differential equivalence between the pristine upstream engine and ours.

Needs the untouched clone at ``/data/BlackDream/OpCore-Simplify`` (pinned ``f0e1e44``);
skips when it is not checked out, so CI on its own still passes.
"""

import os
import sys
from pathlib import Path

import pytest

PRISTINE = "/data/BlackDream/OpCore-Simplify"
sys.path.insert(0, str(Path(__file__).resolve().parent))

if not os.path.isdir(os.path.join(PRISTINE, "Scripts")):
    pytest.skip("pristine upstream clone not available", allow_module_level=True)

import diff_engine


def test_compatibility_checker_matches_upstream_over_the_branch_space():
    """814 reports that cross every branch-relevant field: Intel/AMD/NVIDIA device
    ids and codenames, CPU name x SIMD set, platform, connector type, network ids.
    Verdict ranges, fatal-vs-exit correspondence, and message text must all agree."""
    mismatches = []
    seen = set()
    for label, report in diff_engine.reports():
        if label in seen:
            continue
        seen.add(label)
        pristine_lines, pristine_outcome = diff_engine.run_pristine(report)
        converted_lines, converted_outcome = diff_engine.run_converted(report)
        reason = diff_engine.compare(pristine_lines, pristine_outcome,
                                     converted_lines, converted_outcome)
        if reason:
            mismatches.append("{}: {}".format(label, reason))

    assert not mismatches, "{} of {} reports diverge:\n{}".format(
        len(mismatches), len(seen), "\n".join(mismatches[:20]))
