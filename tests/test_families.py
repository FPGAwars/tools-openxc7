"""Tests for pack.families: the prefix rule and the manifest loader."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from pack.families import (
    CHIPDB_PARTS_FILE,
    chipdb_parts,
    families,
    family_of,
)


class TestFamilyOf(unittest.TestCase):
    """family_of must replicate the nix/nextpnr-xilinx-chipdb.nix rule."""

    def test_artix7(self):
        self.assertEqual(family_of("xc7a35tcsg324"), "artix7")

    def test_kintex7(self):
        self.assertEqual(family_of("xc7k70tfbg676"), "kintex7")

    def test_spartan7(self):
        self.assertEqual(family_of("xc7s50csga324"), "spartan7")

    def test_zynq7(self):
        self.assertEqual(family_of("xc7z010clg400"), "zynq7")

    def test_virtex7(self):
        self.assertEqual(family_of("xc7v585tffg1157"), "virtex7")

    def test_unknown_prefix_raises(self):
        # -- Unlike the nix script (which skips with a warning), the packer
        # -- treats an unknown footprint as an error.
        for part in ("xc6slx9", "xczu3eg", "ice40hx8k", "lfe5u-45f", ""):
            with self.assertRaises(ValueError):
                family_of(part)


class TestManifest(unittest.TestCase):
    """Manifest loading (chipdb_parts / families) against a fixture."""

    def setUp(self):
        self._old_cwd = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        manifest = {
            "artix7": ["xc7a35tcsg324", "xc7a100tfgg676"],
            "zynq7": ["xc7z010clg400"],
        }
        Path(CHIPDB_PARTS_FILE).write_text(
            json.dumps(manifest), encoding="utf-8")

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_chipdb_parts_flattens_in_manifest_order(self):
        self.assertEqual(
            chipdb_parts(),
            [
                ("artix7", "xc7a35tcsg324"),
                ("artix7", "xc7a100tfgg676"),
                ("zynq7", "xc7z010clg400"),
            ],
        )

    def test_families_deduplicated_in_manifest_order(self):
        self.assertEqual(families(), ["artix7", "zynq7"])


if __name__ == "__main__":
    unittest.main()
