"""scripts/ci-install-oss-cad-suite.sh states no version of its own: the
release comes from OSS_CAD_SUITE_DATE and the suite on disk must be it."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ci-install-oss-cad-suite.sh"


def run(suite, date=None):
    env = {key: value for key, value in os.environ.items()
           if key != "OSS_CAD_SUITE_DATE"}
    env["OSS_CAD_SUITE_PATH"] = str(suite)
    if date is not None:
        env["OSS_CAD_SUITE_DATE"] = date
    return subprocess.run(["bash", str(SCRIPT)], env=env,
                          capture_output=True, text=True)


def fake_suite(root, release, yosys="2026-03-24"):
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "yosys").write_text("#!/bin/sh\n")
    (root / "bin" / "yosys").chmod(0o755)
    info = {"release-tag": release}
    if yosys:
        info["yosys-release-tag"] = yosys
    (root / "BUILD-INFO.json").write_text(json.dumps(info), encoding="utf-8")


class CiInstallTests(unittest.TestCase):

    def test_no_release_is_an_error_not_a_default(self):
        with tempfile.TemporaryDirectory() as scratch:
            done = run(Path(scratch) / "s")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("OSS_CAD_SUITE_DATE", done.stderr)

    def test_a_malformed_release_is_refused(self):
        with tempfile.TemporaryDirectory() as scratch:
            done = run(Path(scratch) / "s", "20260807")
        self.assertEqual(done.returncode, 2)

    def test_the_suite_on_disk_is_the_requested_release(self):
        with tempfile.TemporaryDirectory() as scratch:
            suite = Path(scratch) / "s"
            fake_suite(suite, "2026-08-07")
            done = run(suite, "2026-08-07")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("yosys-release-tag 2026-03-24", done.stdout)

    def test_a_different_release_on_disk_fails(self):
        with tempfile.TemporaryDirectory() as scratch:
            suite = Path(scratch) / "s"
            fake_suite(suite, "2026-08-07")
            done = run(suite, "2026-09-29")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("2026-08-07", done.stderr)

    def test_a_suite_without_a_yosys_tag_fails(self):
        with tempfile.TemporaryDirectory() as scratch:
            suite = Path(scratch) / "s"
            fake_suite(suite, "2026-08-07", yosys=None)
            done = run(suite, "2026-08-07")
        self.assertNotEqual(done.returncode, 0)
