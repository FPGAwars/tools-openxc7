"""Tests for CHIPDB-INFO.json: packaging it and validating it."""

import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from pack.assemble import write_env
from pack.chipdb import write_placeholder
from pack.chipdb_info import validate_package_info

PART = "xc7a35tcpg236"
OTHER = "xc7a50tcsg324"
DATA = b"packaged chipdb"


class ChipdbInfoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_info(self, **overrides):
        """A valid document plus the one bin it describes."""
        chipdb = self.root / "chipdb"
        chipdb.mkdir()
        (chipdb / f"{PART}.bin").write_bytes(DATA)
        info = {
            "schema": 3,
            "date": "20260827",
            "release-tag": "2026-08-27",
            "chipdb-id": "fixture-id",
            "generated-count": 1,
            "available-count": 2,
            "note": "fixture",
            "parts": {
                PART: {
                    "family": "artix7",
                    "generated": True,
                    "asset": f"apio-xilinx-chipdb-{PART}-20260827.bin.tgz",
                    "size": len(DATA),
                    "sha256": hashlib.sha256(DATA).hexdigest(),
                    "tgz_size": 123,
                    "tgz_sha256": "0" * 64,
                },
                OTHER: {"family": "artix7", "generated": False},
            },
        }
        info.update(overrides)
        path = self.root / "dated-info.json"
        path.write_text(json.dumps(info), encoding="utf-8")
        return path, chipdb, info

    def rewrite(self, path, info):
        path.write_text(json.dumps(info), encoding="utf-8")

    def test_write_env_copies_the_document_under_the_fixed_name(self):
        info_path, _, _ = self.make_info()
        (self.root / "config").mkdir()
        (self.root / "config" / "environment").write_text(
            "OPENXC7=1\n", encoding="utf-8")
        (self.root / "dist").mkdir()

        old_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            with mock.patch.dict(
                    os.environ, {"OPENXC7_CHIPDB_INFO": str(info_path)},
                    clear=False):
                with redirect_stdout(io.StringIO()):
                    write_env()
        finally:
            os.chdir(old_cwd)

        packaged = self.root / "dist" / "CHIPDB-INFO.json"
        self.assertEqual(packaged.read_bytes(), info_path.read_bytes())

    def test_accepts_the_bins_it_describes(self):
        info_path, chipdb, _ = self.make_info()
        self.assertEqual(validate_package_info(info_path, chipdb), (1, 2))

    def test_accepts_bins_that_live_outside_the_package(self):
        info_path, chipdb, _ = self.make_info()
        external = self.root / "chipdb-bins"
        external.mkdir()
        (external / f"{PART}.bin").write_bytes(DATA)
        for stale in chipdb.glob("*.bin"):        # the on-demand package
            stale.unlink()
        write_placeholder(chipdb)
        self.assertEqual(validate_package_info(info_path, external), (1, 2))

    def test_rejects_bin_drift(self):
        info_path, chipdb, _ = self.make_info()
        (chipdb / f"{PART}.bin").write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "size differs"):
            validate_package_info(info_path, chipdb)

    def test_rejects_a_bin_it_does_not_describe(self):
        info_path, chipdb, _ = self.make_info()
        (chipdb / f"{OTHER}.bin").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "do not match"):
            validate_package_info(info_path, chipdb)

    def test_rejects_an_older_schema(self):
        info_path, chipdb, info = self.make_info(schema=2)
        with self.assertRaisesRegex(ValueError, "schema"):
            validate_package_info(info_path, chipdb)

    def test_rejects_a_tag_that_is_not_the_date(self):
        info_path, chipdb, info = self.make_info()
        info["release-tag"] = "2026-08-26"
        self.rewrite(info_path, info)
        with self.assertRaisesRegex(ValueError, "release-tag"):
            validate_package_info(info_path, chipdb)

    def test_rejects_an_asset_name_of_another_date(self):
        info_path, chipdb, info = self.make_info()
        info["parts"][PART]["asset"] = \
            f"apio-xilinx-chipdb-{PART}-20260826.bin.tgz"
        self.rewrite(info_path, info)
        with self.assertRaisesRegex(ValueError, "apio resolves"):
            validate_package_info(info_path, chipdb)

    def test_rejects_a_non_generated_part_that_looks_downloadable(self):
        info_path, chipdb, info = self.make_info()
        info["parts"][OTHER]["asset"] = "apio-xilinx-chipdb-x-20260827.bin.tgz"
        self.rewrite(info_path, info)
        with self.assertRaisesRegex(ValueError, "not generated"):
            validate_package_info(info_path, chipdb)

    def test_rejects_counts_that_do_not_add_up(self):
        info_path, chipdb, info = self.make_info()
        info["available-count"] = 46
        self.rewrite(info_path, info)
        with self.assertRaisesRegex(ValueError, "available-count"):
            validate_package_info(info_path, chipdb)


if __name__ == "__main__":
    unittest.main()
