"""Tests for scripts/regress-baseline-from-report.py, and above all --only.

The tool rewrites a whole baseline file, so what it must be trusted about is
what it leaves ALONE. --only exists because a test added to the suite has no
baseline on windows until a CI run records it, and recording that one entry
must not also commit the runner's run-to-run pnr_seconds spread over the
entries that already have one.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "regress-baseline-from-report.py"

_spec = importlib.util.spec_from_file_location("baseline_from_report", SCRIPT)
baseline_from_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(baseline_from_report)

TOOLS = {"nextpnr": "Version 68aeeb3", "yosys": "Yosys 0.63+173"}


def result(test, part, status="OK", metrics=None, findings=()):
    return {"test": test, "part": part, "status": status,
            "metrics": metrics, "findings": list(findings)}


def metrics(fmax, pnr, luts=1, ffs=1):
    return {"fmax_mhz": fmax, "luts": luts, "ffs": ffs, "brams": 0, "dsps": 0,
            "pnr_seconds": pnr, "bit_bytes": 2192174}


REPORT = {
    "tools": TOOLS,
    "summary": "NEW",
    "results": [
        # already in the baseline, and slower on this runner than when recorded
        result("constant", "xc7a35tcpg236", metrics=metrics(2865.33, 12.09)),
        result("pll", "xc7a35tcpg236", metrics=metrics(451.06, 7.16)),
        # the one this run is here to record
        result("sonata-blinky", "xc7a50tcsg324", status="NEW",
               metrics=metrics(313.97, 7.36, luts=66, ffs=31)),
    ],
}

BASELINE = {
    "constant": {"xc7a35tcpg236": dict(metrics(2865.33, 10.61), env=TOOLS)},
    "pll": {"xc7a35tcpg236": dict(metrics(451.06, 6.81), env=TOOLS)},
}


class BaselineFromReport(unittest.TestCase):

    def run_tool(self, *argv, baseline=BASELINE, report=REPORT):
        """Run main() against a throwaway repo, return (rc, stdout, file)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baselines = root / "regress" / "baselines"
            baselines.mkdir(parents=True)
            path = baselines / "windows-amd64.json"
            if baseline is not None:
                path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
            report_path = root / "regress-report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            out = StringIO()
            argv = ["regress-baseline-from-report.py", *argv,
                    "windows-amd64", str(report_path)]
            with mock.patch.object(baseline_from_report, "REPO", root), \
                    mock.patch.object(sys, "argv", argv), redirect_stdout(out):
                try:
                    rc = baseline_from_report.main()
                except SystemExit as exit_:            # argparse errors
                    rc = exit_.code
            written = path.read_text(encoding="utf-8") if path.exists() else None
            return rc, out.getvalue(), written

    def test_only_records_the_named_test_and_nothing_else(self):
        rc, out, written = self.run_tool("--only", "sonata-blinky")
        self.assertEqual(rc, 0)
        after = json.loads(written)
        self.assertEqual(after["sonata-blinky"]["xc7a50tcsg324"]["fmax_mhz"], 313.97)
        self.assertEqual(after["sonata-blinky"]["xc7a50tcsg324"]["env"], TOOLS)
        # the two entries that already had a baseline keep the numbers they
        # were recorded with, not the ones this run measured
        self.assertEqual(after["constant"], BASELINE["constant"])
        self.assertEqual(after["pll"], BASELINE["pll"])
        self.assertIn("1 entries recorded (--only sonata-blinky)", out)

    def test_only_touches_nothing_but_the_added_block(self):
        # the property the release gate is reviewed on: the diff is the block
        before = json.dumps(BASELINE, indent=2, sort_keys=True) + "\n"
        _, _, written = self.run_tool("--only", "sonata-blinky")
        removed = [line for line in before.splitlines()
                   if line not in written.splitlines()]
        self.assertEqual(removed, [])

    def test_without_only_every_entry_is_refreshed(self):
        # the contrast that gives --only its reason to exist
        rc, out, written = self.run_tool()
        self.assertEqual(rc, 0)
        after = json.loads(written)
        self.assertEqual(after["constant"]["xc7a35tcpg236"]["pnr_seconds"], 12.09)
        self.assertEqual(after["pll"]["xc7a35tcpg236"]["pnr_seconds"], 7.16)
        self.assertIn("3 entries recorded ->", out)
        self.assertIn("constant/xc7a35tcpg236: pnr_seconds 10.61 -> 12.09", out)

    def test_a_test_the_report_does_not_have_is_an_error_not_a_rewrite(self):
        before = json.dumps(BASELINE, indent=2, sort_keys=True) + "\n"
        rc, _, written = self.run_tool("--only", "sonata-blinkey")
        self.assertEqual(rc, 2)
        self.assertEqual(written, before)

    def test_a_test_with_findings_is_not_recorded_even_when_named(self):
        report = dict(REPORT, results=[
            result("sonata-blinky", "xc7a50tcsg324", status="FAIL",
                   metrics=metrics(313.97, 7.36),
                   findings=["expected artifact missing: bitstream"]),
        ])
        rc, out, written = self.run_tool("--only", "sonata-blinky", report=report)
        self.assertEqual(rc, 0)
        self.assertNotIn("sonata-blinky", json.loads(written))
        self.assertIn("not recorded (1): sonata-blinky/xc7a50tcsg324 (FAIL)", out)

    def test_a_skip_is_not_recorded_either(self):
        report = dict(REPORT, results=[
            result("sonata-blinky", "xc7a50tcsg324", status="SKIP",
                   metrics=metrics(313.97, 7.36)),
        ])
        rc, _, written = self.run_tool("--only", "sonata-blinky", report=report)
        self.assertEqual(rc, 0)
        self.assertNotIn("sonata-blinky", json.loads(written))


if __name__ == "__main__":
    unittest.main()
