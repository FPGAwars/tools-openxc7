"""Tests for XILINX-PARTS-INDEX.json: packaging it and validating it."""

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
from pack.parts_index import (ENTRY_KEYS, INDEX_ASSET, NOTE, PACKAGE_FILE,
                              SCHEMA, previous_index_asset_names,
                              validate_document, validate_package_info)

BASE = "xc7a35tcpg236"
OTHER = "xc7a50tcsg324"
PART = f"{BASE}-1"
SLOW = f"{BASE}-2L"          # same base part -> same chipdb file
DATA = b"packaged chipdb"
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
            "schema": 6,
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

    def test_accepts_a_schema_6_document(self):
        """Schema 6 is the current engine: schema 5's entry keys, no more."""
        _, _, info = self.make_index()
        self.assertEqual(info["schema"], SCHEMA)
        self.assertEqual(SCHEMA, 6)
        for entry in info["parts"].values():
            self.assertEqual(list(entry),
                             [key for key in ENTRY_KEYS if key in entry])
        self.assertEqual(sorted(validate_document(info, "2026-08-27")),
                         [PART, SLOW])

    def test_rejects_an_unknown_entry_key(self):
        """A key outside ENTRY_KEYS is refused. The index is a contract.

        The schema 6 draft carried an engine field on every entry. That
        document is not this schema: apio asserts the number, and a key
        the number does not define must not be silently ignored.
        """
        for part in (PART, f"{OTHER}-1"):
            with self.subTest(part=part):
                index_path, chipdb, info = self.make_index()
                info["parts"][part]["pnr"] = "nextpnr-xilinx"
                self.rewrite(index_path, info)
                with self.assertRaisesRegex(
                        ValueError, f"{part} has unknown key pnr"):
                    validate_package_info(index_path, chipdb)

    def test_the_note_names_both_schemas(self):
        """Schema 6 is the current engine; schema 7 is himbaechel."""
        self.assertIn("schema 6", NOTE)
        self.assertIn("schema 7", NOTE)
        self.assertIn("one chipdb file per base part", NOTE)
        self.assertIn("one chipdb file per die", NOTE)

    def test_the_published_schema_5_document_is_rejected(self):
        """The index of the 2026-09-15 release, as published: apio 1.6.0
        reads schema 5 and nothing else, this validator schema 6 only."""
        info = json.loads(PUBLISHED_SCHEMA_5.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "schema is 5, expected 6"):
            validate_document(info, "2026-09-15")

    def test_schema_6_is_the_published_document_at_a_new_number(self):
        """No other change of format: bump the schema, and the real
        document validates again. Its entry keys are ENTRY_KEYS."""
        info = json.loads(PUBLISHED_SCHEMA_5.read_text(encoding="utf-8"))
        info["schema"] = 6
        generated_entry = next(entry for entry in info["parts"].values()
                               if entry["generated"])
        plain_entry = next(entry for entry in info["parts"].values()
                           if not entry["generated"])
        self.assertEqual(tuple(generated_entry), ENTRY_KEYS)
        self.assertEqual(tuple(plain_entry),
                         tuple(key for key in ENTRY_KEYS
                               if key not in ("chipdb", "chipdb-size",
                                              "chipdb-sha256", "asset",
                                              "asset-size", "asset-sha256")))
        generated = validate_document(info, "2026-09-15")
        self.assertEqual((len(info["parts"]), len(generated)), (202, 128))

    def test_the_schema_6_draft_with_an_engine_field_is_rejected(self):
        """The document this branch used to emit (schema 6 plus an engine
        field on every entry) is refused as an unknown key."""
        info = json.loads(PUBLISHED_SCHEMA_5.read_text(encoding="utf-8"))
        info["schema"] = 6
        for entry in info["parts"].values():
            entry["pnr"] = "nextpnr-xilinx"
        with self.assertRaisesRegex(ValueError, "has unknown key pnr"):
            validate_document(info, "2026-09-15")

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

    def test_the_asset_and_the_file_in_the_package_are_one_name(self):
        """No date in the name: the document names its own release.

        Publishing it under the same fixed name it has inside every
        package (XILINX-PARTS-INDEX.json since the apio#1002 rename,
        PARTS-INDEX.json under apio#990) is what lets a reader ask for
        the index of a release without deriving a date first, and what
        makes "the asset and the file in the package are the same bytes"
        a comparison of two files with the same name.
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
