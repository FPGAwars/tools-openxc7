"""scripts/ci-install-oss-cad-suite.sh states no version of its own: the
release comes from YOSYS_RELEASE_TAG and the suite on disk must be it."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ci-install-oss-cad-suite.sh"


def run(suite, tag=None):
    env = {key: value for key, value in os.environ.items()
           if key != "YOSYS_RELEASE_TAG"}
    env["OSS_CAD_SUITE_PATH"] = str(suite)
    if tag is not None:
        env["YOSYS_RELEASE_TAG"] = tag
    return subprocess.run(["bash", str(SCRIPT)], env=env,
                          capture_output=True, text=True)


def fake_suite(root, version=None):
    """A YosysHQ suite as far as the script looks: bin/yosys and VERSION."""
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "yosys").write_text("#!/bin/sh\n")
    (root / "bin" / "yosys").chmod(0o755)
    if version:
        (root / "VERSION").write_text(version + "\n", encoding="utf-8")


class CiInstallTests(unittest.TestCase):

    def test_no_release_is_an_error_not_a_default(self):
        with tempfile.TemporaryDirectory() as scratch:
            done = run(Path(scratch) / "s")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("YOSYS_RELEASE_TAG", done.stderr)

    def test_a_malformed_release_is_refused(self):
        with tempfile.TemporaryDirectory() as scratch:
            done = run(Path(scratch) / "s", "20260324")
        self.assertEqual(done.returncode, 2)

    def test_the_suite_on_disk_is_the_requested_release(self):
        with tempfile.TemporaryDirectory() as scratch:
            suite = Path(scratch) / "s"
            fake_suite(suite, "20260324")
            done = run(suite, "2026-03-24")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("yosys release 2026-03-24", done.stdout)

    def test_a_different_release_on_disk_fails(self):
        with tempfile.TemporaryDirectory() as scratch:
            suite = Path(scratch) / "s"
            fake_suite(suite, "20260324")
            done = run(suite, "2026-09-27")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("20260324", done.stderr)

    def test_a_suite_without_a_version_file_fails(self):
        with tempfile.TemporaryDirectory() as scratch:
            suite = Path(scratch) / "s"
            fake_suite(suite)
            done = run(suite, "2026-03-24")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("unknown", done.stderr)
