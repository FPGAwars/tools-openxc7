"""Tests for packaging and validating the embedded chipdb index."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pack.assemble import write_env
from pack.chipdb_index import validate_package_index


class ChipdbIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_index(self):
        part = "xc7a35tcpg236"
        chipdb = self.root / "chipdb"
        chipdb.mkdir()
        data = b"packaged chipdb"
        (chipdb / f"{part}.bin").write_bytes(data)
        entry = {
            "part": part,
            "name": part,
            "family": "artix7",
            "asset": f"apio-xilinx-chipdb-{part}-20260826.bin.tgz",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "tgz_size": 123,
            "tgz_sha256": "0" * 64,
        }
        index = {
            "schema": 2,
            "parts": [entry],
            "families": {
                "artix7": {
                    "generated-parts": [entry],
                    "available-parts": [part, "xc7a50tcsg324"],
                }
            },
        }
        index_path = self.root / "dated-index.json"
        index_path.write_text(json.dumps(index), encoding="utf-8")
        return index_path, chipdb, index

    def test_write_env_copies_index_under_stable_name(self):
        index_path, _, _ = self.make_index()
        (self.root / "config").mkdir()
        (self.root / "config" / "environment").write_text(
            "OPENXC7=1\n", encoding="utf-8"
        )
        (self.root / "dist").mkdir()

        old_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            with mock.patch.dict(
                    os.environ, {"OPENXC7_CHIPDB_INDEX": str(index_path)},
                    clear=False):
                write_env()
        finally:
            os.chdir(old_cwd)

        packaged = self.root / "dist" / "apio-xilinx-chipdb-index.json"
        self.assertEqual(packaged.read_bytes(), index_path.read_bytes())

    def test_validation_accepts_matching_bins(self):
        index_path, chipdb, _ = self.make_index()
        self.assertEqual(validate_package_index(index_path, chipdb), 1)

    def test_validation_rejects_bin_drift(self):
        index_path, chipdb, _ = self.make_index()
        (chipdb / "xc7a35tcpg236.bin").write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "size differs"):
            validate_package_index(index_path, chipdb)

    def test_validation_rejects_generated_set_drift(self):
        index_path, chipdb, _ = self.make_index()
        (chipdb / "xc7a50tcsg324.bin").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "do not match"):
            validate_package_index(index_path, chipdb)


if __name__ == "__main__":
    unittest.main()
