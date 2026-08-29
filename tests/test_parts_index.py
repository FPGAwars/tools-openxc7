"""Tests for PARTS-INDEX.json: packaging it and validating it."""

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
from pack.parts_index import (index_asset_name, validate_document,
                              validate_package_info)

BASE = "xc7a35tcpg236"
OTHER = "xc7a50tcsg324"
PART = f"{BASE}-1"
SLOW = f"{BASE}-2L"          # same base part -> same chipdb file
DATA = b"packaged chipdb"


class PartsIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_index(self, **overrides):
        """A valid index plus the one chipdb file it describes."""
        chipdb = self.root / "chipdb"
        chipdb.mkdir(exist_ok=True)
        (chipdb / f"{BASE}.bin").write_bytes(DATA)
        built = {
            "chipdb": f"{BASE}.bin",
            "chipdb-size": len(DATA),
            "chipdb-sha256": hashlib.sha256(DATA).hexdigest(),
            "asset": f"apio-xilinx-chipdb-{BASE}-20260827.bin.tgz",
            "asset-size": 123,
            "asset-sha256": "0" * 64,
        }
        info = {
            "schema": 5,
            "date": "20260827",
            "release-tag": "2026-08-27",
            "chipdb-id": "fixture-id",
            "part-count": 3,
            "generated-count": 2,
            "chipdb-count": 1,
            "base-part-count": 2,
            "note": "fixture",
            "parts": {
                PART: {"family": "artix7", "base-part": BASE, "speed": "1",
                       "generated": True, **built},
                SLOW: {"family": "artix7", "base-part": BASE, "speed": "2L",
                       "generated": True, **built},
                f"{OTHER}-1": {"family": "artix7", "base-part": OTHER,
                               "speed": "1", "generated": False},
            },
        }
        info.update(overrides)
        path = self.root / "dated-index.json"
        path.write_text(json.dumps(info), encoding="utf-8")
        return path, chipdb, info

    def rewrite(self, path, info):
        path.write_text(json.dumps(info), encoding="utf-8")

    def test_write_env_copies_the_document_under_the_fixed_name(self):
        index_path, _, _ = self.make_index()
        (self.root / "config").mkdir()
        (self.root / "config" / "environment").write_text(
            "OPENXC7=1\n", encoding="utf-8")
        (self.root / "dist").mkdir()

        old_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            with mock.patch.dict(
                    os.environ, {"OPENXC7_PARTS_INDEX": str(index_path)},
                    clear=False):
                with redirect_stdout(io.StringIO()):
                    write_env()
        finally:
            os.chdir(old_cwd)

        packaged = self.root / "dist" / "PARTS-INDEX.json"
        self.assertEqual(packaged.read_bytes(), index_path.read_bytes())

    def test_accepts_the_chipdb_files_it_describes(self):
        index_path, chipdb, _ = self.make_index()
        self.assertEqual(
            validate_package_info(index_path, chipdb),
            {"part-count": 3, "generated-count": 2, "chipdb-count": 1,
             "base-part-count": 2})

    def test_speed_grades_of_one_base_part_share_one_file(self):
        """The point of keying by part: 2 generated parts, 1 chipdb file."""
        _, _, info = self.make_index()
        generated = validate_document(info)
        self.assertEqual(sorted(generated), [PART, SLOW])
        self.assertEqual(
            {entry["chipdb"] for entry in generated.values()},
            {f"{BASE}.bin"})

    def test_accepts_chipdb_files_that_live_outside_the_package(self):
        index_path, chipdb, _ = self.make_index()
        external = self.root / "chipdb-bins"
        external.mkdir()
        (external / f"{BASE}.bin").write_bytes(DATA)
        for stale in chipdb.glob("*.bin"):        # the on-demand package
            stale.unlink()
        write_placeholder(chipdb)
        self.assertEqual(validate_package_info(index_path, external)
                         ["generated-count"], 2)

    def test_rejects_chipdb_drift(self):
        index_path, chipdb, _ = self.make_index()
        (chipdb / f"{BASE}.bin").write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "size differs"):
            validate_package_info(index_path, chipdb)

    def test_rejects_a_chipdb_file_it_does_not_describe(self):
        index_path, chipdb, _ = self.make_index()
        (chipdb / f"{OTHER}.bin").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "do not match"):
            validate_package_info(index_path, chipdb)

    def test_rejects_an_older_schema(self):
        """Schema 4 is the previous field naming (size/tgz_size, apio#947)."""
        index_path, chipdb, _ = self.make_index(schema=4)
        with self.assertRaisesRegex(ValueError, "schema"):
            validate_package_info(index_path, chipdb)

    def test_rejects_a_key_that_is_not_base_part_plus_speed(self):
        """The key IS the part: apio looks the board's part up by name."""
        index_path, chipdb, info = self.make_index()
        info["parts"]["xc7a35tcpg236-9"] = info["parts"].pop(SLOW)
        self.rewrite(index_path, info)
        with self.assertRaisesRegex(ValueError, "the key IS the part"):
            validate_package_info(index_path, chipdb)

    def test_rejects_a_chipdb_name_that_is_not_the_base_part(self):
        index_path, chipdb, info = self.make_index()
        info["parts"][PART]["chipdb"] = f"{OTHER}.bin"
        self.rewrite(index_path, info)
        with self.assertRaisesRegex(ValueError, "leaves in chipdb/"):
            validate_package_info(index_path, chipdb)

    def test_rejects_speed_grades_that_promise_different_files(self):
        """One file, one promise: a loader dedups by sha256."""
        index_path, chipdb, info = self.make_index()
        info["parts"][SLOW]["asset-size"] = 999
        self.rewrite(index_path, info)
        with self.assertRaisesRegex(ValueError, "describe different files"):
            validate_package_info(index_path, chipdb)

    def test_rejects_a_tag_that_is_not_the_date(self):
        index_path, chipdb, info = self.make_index()
        info["release-tag"] = "2026-08-26"
        self.rewrite(index_path, info)
        with self.assertRaisesRegex(ValueError, "release-tag"):
            validate_package_info(index_path, chipdb)

    def test_rejects_an_asset_name_of_another_date(self):
        index_path, chipdb, info = self.make_index()
        for part in (PART, SLOW):
            info["parts"][part]["asset"] = \
                f"apio-xilinx-chipdb-{BASE}-20260826.bin.tgz"
        self.rewrite(index_path, info)
        with self.assertRaisesRegex(ValueError, "apio resolves"):
            validate_package_info(index_path, chipdb)

    def test_rejects_a_non_generated_part_that_looks_downloadable(self):
        index_path, chipdb, info = self.make_index()
        info["parts"][f"{OTHER}-1"]["chipdb"] = f"{OTHER}.bin"
        self.rewrite(index_path, info)
        with self.assertRaisesRegex(ValueError, "not generated"):
            validate_package_info(index_path, chipdb)

    def test_rejects_counts_that_do_not_add_up(self):
        for key, wrong in (("part-count", 46), ("generated-count", 1),
                           ("chipdb-count", 2), ("base-part-count", 3)):
            with self.subTest(key=key):
                index_path, chipdb, info = self.make_index()
                info[key] = wrong
                self.rewrite(index_path, info)
                with self.assertRaisesRegex(ValueError, key):
                    validate_package_info(index_path, chipdb)

    def test_document_must_name_the_release_it_was_published_in(self):
        """What a release gate asks: is this map the map of THIS release?

        The document is valid on its own (date and release-tag agree); what
        it is not is the one that belongs to the release it was found in --
        the shape a run crossing midnight UTC produces.
        """
        _, _, info = self.make_index()
        self.assertEqual(sorted(validate_document(info, "2026-08-27")),
                         [PART, SLOW])
        with self.assertRaisesRegex(ValueError, "not the release"):
            validate_document(info, "2026-08-28")

    def test_index_asset_name_follows_the_release_date(self):
        self.assertEqual(index_asset_name("20260827"),
                         "apio-xilinx-parts-index-20260827.json")
        with self.assertRaises(ValueError):
            index_asset_name("2026-08-27")


if __name__ == "__main__":
    unittest.main()
