"""Tests for XILINX-PARTS-INDEX.json: packaging it and validating it."""

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
from pack.parts_index import (ENTRY_KEYS, INDEX_ASSET, NOTE, PACKAGE_FILE,
                              SCHEMA, STAMP_FILE, asset_name, chipdb_name,
                              package_schema, previous_index_asset_names,
                              read_package_schema, validate_document,
                              validate_package_info)

BASE = "xc7a35tcpg236"
OTHER = "xc7a50tcsg324"
PART = f"{BASE}-1"
SLOW = f"{BASE}-2L"          # same base part -> same chipdb file
DIE_FILE = "chipdb-xc7a50t.bin"   # BASE and OTHER share the xc7a50t die
DATA = b"packaged chipdb"
STAMP = "fixture-id"
# The document of the 2026-09-15 release, byte for byte as published (its
# sha256 is in that release's SHA256SUMS): the last schema 5 index.
PUBLISHED_SCHEMA_5 = (Path(__file__).resolve().parent / "data" /
                      "XILINX-PARTS-INDEX-2026-09-15.json")


class PartsIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _stamp(self, chipdb):
        (chipdb / STAMP_FILE).write_text(STAMP + "\n", encoding="utf-8")

    def make_index(self, **overrides):
        """A valid schema 8 index plus the one chipdb file it describes.

        Two speed grades of one base part, one file: the die's. The other
        base part of that die is listed and not built.
        """
        chipdb = self.root / "chipdb"
        chipdb.mkdir(exist_ok=True)
        (chipdb / DIE_FILE).write_bytes(DATA)
        self._stamp(chipdb)
        built = {"chipdb": DIE_FILE}
        info = {
            "schema": SCHEMA,
            "date": "20260827",
            "release-tag": "2026-08-27",
            "chipdb-id": STAMP,
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

    def make_die_index(self):
        """Two base parts of the xc7a50t die (xc7a35t and xc7a50t), three
        built parts, ONE chipdb file; plus an xc7a100t part the release
        did not build."""
        chipdb = self.root / "chipdb"
        chipdb.mkdir(exist_ok=True)
        (chipdb / DIE_FILE).write_bytes(DATA)
        self._stamp(chipdb)
        built = {"chipdb": DIE_FILE}
        info = {
            "schema": SCHEMA, "date": "20260827", "release-tag": "2026-08-27",
            "chipdb-id": STAMP, "part-count": 4,
            "generated-count": 3, "chipdb-count": 1, "base-part-count": 3,
            "note": "fixture",
            "parts": {
                PART: {"family": "artix7", "base-part": BASE, "speed": "1",
                       "generated": True, **built},
                SLOW: {"family": "artix7", "base-part": BASE, "speed": "2L",
                       "generated": True, **built},
                f"{OTHER}-1": {"family": "artix7", "base-part": OTHER,
                               "speed": "1", "generated": True, **built},
                "xc7a100tcsg324-1": {"family": "artix7",
                                     "base-part": "xc7a100tcsg324",
                                     "speed": "1", "generated": False},
            },
        }
        path = self.root / "die-index.json"
        path.write_text(json.dumps(info), encoding="utf-8")
        return path, chipdb, info

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

        packaged = self.root / "dist" / PACKAGE_FILE
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
            {DIE_FILE})

    def test_accepts_chipdb_files_that_live_outside_the_package(self):
        index_path, chipdb, _ = self.make_index()
        external = self.root / "chipdb-bins"
        external.mkdir()
        (external / DIE_FILE).write_bytes(DATA)
        self._stamp(external)
        for stale in chipdb.glob("*.bin"):
            stale.unlink()
        write_placeholder(chipdb)
        self.assertEqual(validate_package_info(index_path, external)
                         ["generated-count"], 2)

    def test_rejects_a_stamp_that_is_not_the_index(self):
        index_path, chipdb, _ = self.make_index()
        (chipdb / STAMP_FILE).write_text("other-toolchain\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "chipdb-id"):
            validate_package_info(index_path, chipdb)

    def test_rejects_a_missing_stamp(self):
        index_path, chipdb, _ = self.make_index()
        (chipdb / STAMP_FILE).unlink()
        with self.assertRaisesRegex(ValueError, "absent"):
            validate_package_info(index_path, chipdb)

    def test_rejects_a_missing_bin_by_name(self):
        index_path, chipdb, _ = self.make_index()
        (chipdb / DIE_FILE).unlink()
        with self.assertRaisesRegex(ValueError, DIE_FILE):
            validate_package_info(index_path, chipdb)

    def test_rejects_a_chipdb_file_it_does_not_describe(self):
        index_path, chipdb, _ = self.make_index()
        (chipdb / f"{OTHER}.bin").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, f"unexpected \\['{OTHER}.bin'\\]"):
            validate_package_info(index_path, chipdb)

    def test_rejects_an_older_schema(self):
        """Schema 4 is the previous field naming (size/tgz_size, apio#947)."""
        index_path, chipdb, _ = self.make_index(schema=4)
        with self.assertRaisesRegex(ValueError, "schema"):
            validate_package_info(index_path, chipdb)

    def test_accepts_a_schema_8_document(self):
        """Schema 8: one file per die, the file name only, no engine field."""
        _, _, info = self.make_index()
        self.assertEqual(info["schema"], SCHEMA)
        self.assertEqual(SCHEMA, 8)
        for entry in info["parts"].values():
            self.assertEqual(list(entry),
                             [key for key in ENTRY_KEYS if key in entry])
            self.assertFalse(
                {"chipdb-size", "chipdb-sha256", "asset", "asset-size",
                 "asset-sha256"} & set(entry))
        self.assertEqual(sorted(validate_document(info, "2026-08-27")),
                         [PART, SLOW])

    def test_rejects_an_unknown_entry_key(self):
        """A key outside ENTRY_KEYS is refused. The index is a contract."""
        for part in (PART, f"{OTHER}-1"):
            with self.subTest(part=part):
                index_path, chipdb, info = self.make_index()
                info["parts"][part]["pnr"] = "nextpnr-himbaechel"
                self.rewrite(index_path, info)
                with self.assertRaisesRegex(
                        ValueError, f"{part} has unknown key pnr"):
                    validate_package_info(index_path, chipdb)

    def test_rejects_the_removed_download_fields(self):
        """Schema 7's sizes, hashes and asset name are not schema 8."""
        for key, value in (("chipdb-size", 1),
                           ("chipdb-sha256", "a" * 64),
                           ("asset", "apio-xilinx-chipdb-xc7a50t-20260827.bin.tgz"),
                           ("asset-size", 1),
                           ("asset-sha256", "b" * 64)):
            with self.subTest(key=key):
                index_path, chipdb, info = self.make_index()
                info["parts"][PART][key] = value
                self.rewrite(index_path, info)
                with self.assertRaisesRegex(
                        ValueError, f"{PART} has unknown key {key}"):
                    validate_package_info(index_path, chipdb)

    def test_the_note_describes_the_in_package_chipdb(self):
        self.assertIn("travel inside", NOTE)
        self.assertIn("in chipdb/", NOTE)
        self.assertIn("generated=false", NOTE)
        self.assertIn("supported, not built", NOTE)
        self.assertIn("schema 8", NOTE)
        self.assertNotIn("asset-sha256", NOTE)
        self.assertNotIn("download", NOTE)

    def test_the_published_schema_5_document_is_rejected(self):
        """The index of the 2026-09-15 release, as published. This
        validator accepts schema 8 only."""
        info = json.loads(PUBLISHED_SCHEMA_5.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "schema is 5, expected 8"):
            validate_document(info, "2026-09-15")

    def test_a_schema_6_document_is_rejected(self):
        info = json.loads(PUBLISHED_SCHEMA_5.read_text(encoding="utf-8"))
        info["schema"] = 6
        with self.assertRaisesRegex(ValueError, "schema is 6, expected 8"):
            validate_document(info, "2026-09-15")

    def test_a_schema_7_document_is_rejected(self):
        """Schema 7 is the previous contract (per-die files, downloaded).
        Bumping nothing else, a schema 8 reader refuses it."""
        _, _, info = self.make_index()
        info["schema"] = 7
        with self.assertRaisesRegex(ValueError, "schema is 7, expected 8"):
            validate_document(info, "2026-08-27")

    def test_bumping_a_schema_5_document_to_8_is_not_enough(self):
        """The published document's download fields are unknown keys, and
        its files are one per base part."""
        info = json.loads(PUBLISHED_SCHEMA_5.read_text(encoding="utf-8"))
        info["schema"] = 8
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            validate_document(info, "2026-09-15")

    def test_accepts_one_chipdb_file_per_die(self):
        """Two base parts of one die, three built parts, one chipdb file."""
        index_path, chipdb, info = self.make_die_index()
        self.assertEqual(sorted(validate_document(info, "2026-08-27")),
                         [PART, SLOW, f"{OTHER}-1"])
        self.assertEqual(validate_package_info(index_path, chipdb),
                         {"part-count": 4, "generated-count": 3,
                          "chipdb-count": 1, "base-part-count": 3})

    def test_the_schema_decides_the_file_name(self):
        """Schema 7 and 8 name the die; schema 6 names the base part."""
        self.assertEqual(chipdb_name(BASE), DIE_FILE)
        self.assertEqual(chipdb_name(BASE, 8), DIE_FILE)
        self.assertEqual(chipdb_name(BASE, 7), DIE_FILE)
        self.assertEqual(chipdb_name(BASE, 6), f"{BASE}.bin")
        self.assertEqual(chipdb_name(BASE, 5), f"{BASE}.bin")
        with self.assertRaisesRegex(ValueError, "no chipdb assets"):
            asset_name(BASE, "20260827")
        self.assertEqual(
            asset_name(BASE, "20260827", 7),
            "apio-xilinx-chipdb-xc7a50t-20260827.bin.tgz")
        self.assertEqual(
            asset_name(BASE, "20260827", 6),
            f"apio-xilinx-chipdb-{BASE}-20260827.bin.tgz")

        index_path, chipdb, info = self.make_die_index()
        info["parts"][f"{OTHER}-1"]["chipdb"] = f"{OTHER}.bin"
        self.rewrite(index_path, info)
        with self.assertRaisesRegex(ValueError, f"{OTHER}-1 chipdb .*"
                                    f"{DIE_FILE}"):
            validate_package_info(index_path, chipdb)

    def test_the_schema_number_is_what_a_package_carries(self):
        """What the harness and the E2E run: the schema of the package,
        and the file each built base part needs, as apio reads them."""
        _, _, info = self.make_die_index()
        self.assertEqual(package_schema(info),
                         (8, {BASE: DIE_FILE, OTHER: DIE_FILE}))
        # Older schemas are refused by the validator and still reported
        # by the reader, so a harness can open an older package.
        per_die = {
            "schema": 7,
            "parts": {PART: {"base-part": BASE, "generated": True,
                             "chipdb": DIE_FILE}},
        }
        self.assertEqual(package_schema(per_die), (7, {BASE: DIE_FILE}))
        per_base = {
            "schema": 6,
            "parts": {PART: {"base-part": BASE, "generated": True,
                             "chipdb": f"{BASE}.bin"}},
        }
        self.assertEqual(package_schema(per_base),
                         (6, {BASE: f"{BASE}.bin"}))
        published = json.loads(PUBLISHED_SCHEMA_5.read_text(encoding="utf-8"))
        schema, files = package_schema(published)
        self.assertEqual(schema, 5)
        self.assertEqual(files["xc7a35tcsg324"], "xc7a35tcsg324.bin")
        self.assertEqual(package_schema(None), (SCHEMA, {}))
        self.assertEqual(read_package_schema(self.root), (SCHEMA, {}))
        with self.assertRaisesRegex(ValueError, "schema 4"):
            package_schema({"schema": 4, "parts": {}})

    def test_rejects_a_key_that_is_not_base_part_plus_speed(self):
        """The key IS the part: apio looks the board's part up by name."""
        index_path, chipdb, info = self.make_index()
        info["parts"]["xc7a35tcpg236-9"] = info["parts"].pop(SLOW)
        self.rewrite(index_path, info)
        with self.assertRaisesRegex(ValueError, "the key IS the part"):
            validate_package_info(index_path, chipdb)

    def test_rejects_a_chipdb_name_that_is_not_the_die_file(self):
        index_path, chipdb, info = self.make_index()
        info["parts"][PART]["chipdb"] = f"{OTHER}.bin"
        self.rewrite(index_path, info)
        with self.assertRaisesRegex(ValueError, "in chipdb/"):
            validate_package_info(index_path, chipdb)

    def test_rejects_a_tag_that_is_not_the_date(self):
        index_path, chipdb, info = self.make_index()
        info["release-tag"] = "2026-08-26"
        self.rewrite(index_path, info)
        with self.assertRaisesRegex(ValueError, "release-tag"):
            validate_package_info(index_path, chipdb)

    def test_rejects_a_non_generated_part_that_names_a_file(self):
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

    def test_the_asset_and_the_file_in_the_package_are_one_name(self):
        """No date in the name: the document names its own release.

        Publishing it under the same fixed name it has inside every
        package (XILINX-PARTS-INDEX.json since the apio#1002 rename,
        PARTS-INDEX.json under apio#990) is what lets a reader ask for
        the index of a release without deriving a date first.
        """
        self.assertEqual(INDEX_ASSET, "XILINX-PARTS-INDEX.json")
        self.assertEqual(INDEX_ASSET, PACKAGE_FILE)

    def test_the_previous_asset_names_are_still_resolvable(self):
        """Releases published before the apio#1002 rename are still
        installed from: a reader must be able to name those files too.

        Newest first: PARTS-INDEX.json (apio#990, releases up to the
        rename), then the dated name every release up to 2026-08-31 used.
        """
        self.assertEqual(previous_index_asset_names("20260827"),
                         ["PARTS-INDEX.json",
                          "apio-xilinx-parts-index-20260827.json"])
        with self.assertRaises(ValueError):
            previous_index_asset_names("2026-08-27")


if __name__ == "__main__":
    unittest.main()
