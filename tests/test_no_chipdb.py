"""Tests for the on-demand placeholder that stands where the bins used to be."""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from pack.chipdb import PLACEHOLDER, skip_chipdb

PART = "xc7a35tcpg236"
DATA = b"packaged chipdb"


class PlaceholderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_cwd = Path.cwd()
        os.chdir(self.root)
        self.chipdb = self.root / "dist" / "chipdb"
        self.chipdb.mkdir(parents=True)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    def test_placeholder_replaces_the_stamp_and_stale_intermediates(self):
        (self.chipdb / "chipdb-id.txt").write_text("fixture-id\n")
        (self.chipdb / f"{PART}.bba").write_text("truncated")
        with redirect_stdout(io.StringIO()):
            skip_chipdb()
        self.assertIn("on-demand", (self.chipdb / PLACEHOLDER).read_text())
        self.assertFalse((self.chipdb / "chipdb-id.txt").exists())
        self.assertFalse((self.chipdb / f"{PART}.bba").exists())

    def test_leftover_bins_stop_the_pack_instead_of_being_deleted(self):
        (self.chipdb / f"{PART}.bin").write_bytes(DATA)
        with self.assertRaises(SystemExit):
            skip_chipdb()
        # the expensive part of a build is still there, untouched
        self.assertEqual((self.chipdb / f"{PART}.bin").read_bytes(), DATA)
        self.assertFalse((self.chipdb / PLACEHOLDER).exists())


if __name__ == "__main__":
    unittest.main()
