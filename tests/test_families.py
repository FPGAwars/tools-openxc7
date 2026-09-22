"""Tests for pack.families: the prefix rules and the manifest loader."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from pack.families import (
    CHIPDB_PARTS_FILE,
    DIE_ALIASES,
    chipdb_dies,
    chipdb_parts,
    device_of,
    die_of,
    families,
    family_of,
)


class TestFamilyOf(unittest.TestCase):
    """family_of: the prjxray-db directory of a part, by its prefix."""

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


class TestDieOf(unittest.TestCase):
    """die_of: the chipdb file a part routes on (one per die)."""

    def test_every_die_of_the_manifest(self):
        """The ten dies of today's manifest, from one part of each; the
        expected values are the fabrics prjxray-db's mapping/devices.yaml
        gives (a90f27c1)."""
        for part, die in (
            ("xc7a100tcsg324", "xc7a100t"),
            ("xc7a200tffg1156", "xc7a200t"),
            ("xc7a50tcpg236", "xc7a50t"),
            ("xc7s25csga324", "xc7s25"),
            ("xc7s50ftgb196", "xc7s50"),
            ("xc7z010clg225", "xc7z010"),
            ("xc7z020clg484", "xc7z020"),
            ("xc7z030fbg676", "xc7z030"),
            ("xc7z045ffv900", "xc7z045"),
            ("xc7z100ffg1156", "xc7z100"),
        ):
            with self.subTest(part=part):
                self.assertEqual(die_of(part), die)

    def test_a_device_on_another_die_takes_that_die(self):
        """An xc7a35t is an xc7a50t die: every xc7a35t part routes on the
        xc7a50t chipdb, whatever its package."""
        for part in ("xc7a35tcpg236", "xc7a35tcsg324", "xc7a35tcsg325",
                     "xc7a35tfgg484", "xc7a35tftg256"):
            with self.subTest(part=part):
                self.assertEqual(device_of(part), "xc7a35t")
                self.assertEqual(die_of(part), "xc7a50t")
        self.assertEqual(die_of("xc7s75fgga484"), "xc7s100")
        self.assertEqual(die_of("xc7z035ffg676"), "xc7z045")
        self.assertEqual(DIE_ALIASES, {"xc7a35t": "xc7a50t",
                                       "xc7s75": "xc7s100",
                                       "xc7z035": "xc7z045"})

    def test_devices_with_and_without_the_t(self):
        """Artix, Kintex and Virtex devices end in t; Spartan-7 and Zynq do
        not, so the package must not be swallowed into the device."""
        self.assertEqual(device_of("xc7k325tffg900"), "xc7k325t")
        self.assertEqual(device_of("xc7vx485tffg1761"), "xc7vx485t")
        self.assertEqual(device_of("xc7s100fgga676"), "xc7s100")
        self.assertEqual(device_of("xc7z020clg400"), "xc7z020")

    def test_a_name_without_a_device_raises(self):
        for part in ("xc6slx9", "xczu3eg", "ice40hx8k", "xc7a", ""):
            with self.subTest(part=part):
                with self.assertRaises(ValueError):
                    die_of(part)


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

    def test_one_die_per_chipdb_file_in_manifest_order(self):
        """Parts of one die are one file: xc7a35t and xc7a50t parts share
        the xc7a50t die, which appears where its first part does."""
        Path(CHIPDB_PARTS_FILE).write_text(json.dumps({
            "artix7": ["xc7a100tcsg324", "xc7a35tcpg236", "xc7a50tcsg324",
                       "xc7a35tcsg324", "xc7a100tfgg676"],
            "zynq7": ["xc7z010clg400", "xc7z010clg225"],
        }), encoding="utf-8")
        self.assertEqual(
            chipdb_dies(),
            [("artix7", "xc7a100t"), ("artix7", "xc7a50t"),
             ("zynq7", "xc7z010")])


if __name__ == "__main__":
    unittest.main()
