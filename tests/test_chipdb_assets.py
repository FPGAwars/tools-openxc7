"""Tests for the parts-index writer and the database inventory.

pack.chipdb_assets used to also build the per-die release assets. Schema 8
publishes none: the writer produces XILINX-PARTS-INDEX.json and nothing else.
"""

import json
import tempfile
import unittest
from pathlib import Path

from pack.chipdb_assets import build_index, database_parts
from pack.parts_index import (ENTRY_KEYS, INDEX_ASSET, PACKAGE_FILE,
                              SCHEMA, release_tag, validate_document)

DIE_FILE = "chipdb-xc7a50t.bin"     # the die of xc7a35t and xc7a50t parts


class ChipdbAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.chipdb = self.root / "package" / "chipdb"
        self.database = (
            self.root / "package" / "share" / "nextpnr" / "external" /
            "prjxray-db"
        )
        self.output = self.root / "index"
        self.repo.mkdir()
        self.chipdb.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def add_database_part(self, family, speed_part):
        path = self.database / family / speed_part / "part.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("device: fixture\n", encoding="utf-8")

    def fixture(self, part="xc7a35tcpg236", other="xc7a50tcsg324"):
        """A one-part manifest plus one footprint the database has only.

        Both are xc7a50t dies: the chipdb file is that die's, and the other
        footprint -- on the same die but not in the manifest -- is not
        built all the same (the manifest is what L1 routes).
        """
        self.add_database_part("artix7", f"{part}-1")
        self.add_database_part("artix7", f"{part}-2")
        self.add_database_part("artix7", f"{other}-1")
        (self.repo / "chipdb-parts.json").write_text(
            json.dumps({"artix7": [part]}), encoding="utf-8"
        )
        (self.chipdb / "chipdb-id.txt").write_text(
            "fixture-id\n", encoding="utf-8"
        )
        (self.chipdb / DIE_FILE).write_bytes(b"chipdb fixture")
        return part, other

    def test_database_parts_keep_every_speed_grade(self):
        self.add_database_part("artix7", "xc7a35tcpg236-1")
        self.add_database_part("artix7", "xc7a35tcpg236-2L")
        self.add_database_part("spartan7", "xc7s50csga324-1IL")

        self.assertEqual(
            database_parts(self.database),
            {
                "xc7a35tcpg236-1": {"family": "artix7",
                                    "base-part": "xc7a35tcpg236",
                                    "speed": "1"},
                "xc7a35tcpg236-2L": {"family": "artix7",
                                     "base-part": "xc7a35tcpg236",
                                     "speed": "2L"},
                "xc7s50csga324-1IL": {"family": "spartan7",
                                      "base-part": "xc7s50csga324",
                                      "speed": "1IL"},
            },
        )

    def test_a_die_directory_is_not_a_part(self):
        """xc7a50t is the die: no speed grade, so nothing apio can build for.

        Today those directories carry no part.yaml of their own, so this is
        a guard against the database growing one rather than a live case.
        """
        self.add_database_part("artix7", "xc7a35tcpg236-1")
        self.add_database_part("artix7", "xc7a50t")

        self.assertEqual(sorted(database_parts(self.database)),
                         ["xc7a35tcpg236-1"])

    def test_release_tag_is_the_tag_apio_derives_the_date_from(self):
        self.assertEqual(release_tag("20260827"), "2026-08-27")
        with self.assertRaises(ValueError):
            release_tag("2026-08-27")

    def test_published_document_has_the_name_readers_resolve(self):
        """The writer and the reader of the index name must agree.

        pack.chipdb_assets writes the file; INDEX_ASSET is what
        scripts/asset-check.sh fetches a release by, and PACKAGE_FILE what
        pack.assemble puts at the root of every package -- one name for
        both (XILINX-PARTS-INDEX.json since the apio#1002 rename).
        """
        self.fixture()
        info_path = build_index(
            self.repo, self.chipdb, self.output, "20260827", self.database
        )
        self.assertEqual(info_path.name, INDEX_ASSET)
        self.assertEqual(info_path.name, PACKAGE_FILE)
        self.assertEqual(sorted(p.name for p in self.output.iterdir()),
                         [INDEX_ASSET])

    def test_index_describes_every_part_of_the_database(self):
        part, other = self.fixture()

        info_path = build_index(
            self.repo, self.chipdb, self.output, "20260827", self.database
        )
        info = json.loads(info_path.read_text(encoding="utf-8"))

        self.assertEqual(info["schema"], SCHEMA)
        self.assertEqual(info["date"], "20260827")
        self.assertEqual(info["release-tag"], "2026-08-27")
        self.assertEqual(info["chipdb-id"], "fixture-id")
        self.assertEqual(info["part-count"], 3)
        self.assertEqual(info["generated-count"], 2)
        self.assertEqual(info["chipdb-count"], 1)
        self.assertEqual(info["base-part-count"], 2)
        self.assertEqual(sorted(info["parts"]),
                         sorted([f"{part}-1", f"{part}-2", f"{other}-1"]))

        entry = info["parts"][f"{part}-1"]
        self.assertEqual(list(entry), ["family", "base-part", "speed",
                                       "generated", "chipdb"])
        self.assertTrue(entry["generated"])
        self.assertEqual(entry["family"], "artix7")
        self.assertEqual(entry["base-part"], part)
        self.assertEqual(entry["speed"], "1")
        self.assertEqual(entry["chipdb"], DIE_FILE)
        self.assertEqual(info["parts"][f"{part}-2"] | {"speed": "1"}, entry)
        self.assertEqual(info["parts"][f"{other}-1"],
                         {"family": "artix7", "base-part": other,
                          "speed": "1", "generated": False})

    def test_every_entry_follows_entry_keys_and_validates(self):
        """Keys in ENTRY_KEYS order, generated or not, and the document
        the writer produces is one the validator accepts."""
        self.fixture()
        info_path = build_index(
            self.repo, self.chipdb, self.output, "20260827", self.database
        )
        info = json.loads(info_path.read_text(encoding="utf-8"))

        entries = info["parts"].values()
        self.assertEqual({entry["generated"] for entry in entries},
                         {True, False})
        for part, entry in info["parts"].items():
            with self.subTest(part=part):
                self.assertEqual(list(entry),
                                 [key for key in ENTRY_KEYS if key in entry])
        self.assertEqual(sorted(validate_document(info, "2026-08-27")),
                         ["xc7a35tcpg236-1", "xc7a35tcpg236-2"])

    def test_one_file_per_die_shared_by_its_parts(self):
        """Two manifest base parts on the xc7a50t die and one on xc7a100t:
        two chipdb files, and the parts of a die repeat the same file."""
        for base in ("xc7a35tcpg236", "xc7a50tcsg324", "xc7a100tcsg324"):
            self.add_database_part("artix7", f"{base}-1")
            self.add_database_part("artix7", f"{base}-2")
        (self.repo / "chipdb-parts.json").write_text(json.dumps(
            {"artix7": ["xc7a100tcsg324", "xc7a35tcpg236", "xc7a50tcsg324"]}),
            encoding="utf-8")
        (self.chipdb / "chipdb-id.txt").write_text("fixture-id\n",
                                                   encoding="utf-8")
        (self.chipdb / DIE_FILE).write_bytes(b"xc7a50t die")
        (self.chipdb / "chipdb-xc7a100t.bin").write_bytes(b"xc7a100t die")

        info = json.loads(build_index(
            self.repo, self.chipdb, self.output, "20260827", self.database
        ).read_text())

        self.assertEqual(sorted(p.name for p in self.output.iterdir()),
                         [INDEX_ASSET])
        self.assertEqual((info["part-count"], info["generated-count"],
                          info["chipdb-count"], info["base-part-count"]),
                         (6, 6, 2, 3))
        self.assertEqual(info["parts"]["xc7a35tcpg236-1"]["chipdb"],
                         info["parts"]["xc7a50tcsg324-2"]["chipdb"])
        self.assertEqual(info["parts"]["xc7a100tcsg324-1"]["chipdb"],
                         "chipdb-xc7a100t.bin")
        self.assertNotEqual(info["parts"]["xc7a35tcpg236-1"]["chipdb"],
                            info["parts"]["xc7a100tcsg324-1"]["chipdb"])
        self.assertEqual(len(validate_document(info, "2026-08-27")), 6)

    def test_generated_part_must_exist_in_database(self):
        part = "xc7a35tcpg236"
        (self.repo / "chipdb-parts.json").write_text(
            json.dumps({"artix7": [part]}), encoding="utf-8"
        )
        (self.chipdb / "chipdb-id.txt").write_text(
            "fixture-id\n", encoding="utf-8"
        )
        (self.chipdb / DIE_FILE).write_bytes(b"chipdb fixture")
        self.database.mkdir(parents=True)

        with self.assertRaisesRegex(ValueError, "not present"):
            build_index(
                self.repo, self.chipdb, self.output, "20260827", self.database
            )

    def test_unstamped_chipdb_is_refused(self):
        self.fixture()
        (self.chipdb / "chipdb-id.txt").unlink()
        with self.assertRaisesRegex(ValueError, "unstamped"):
            build_index(
                self.repo, self.chipdb, self.output, "20260827", self.database
            )

    def test_a_manifest_part_without_its_bin_is_refused(self):
        self.fixture()
        (self.chipdb / DIE_FILE).unlink()
        with self.assertRaisesRegex(ValueError, "without bin"):
            build_index(
                self.repo, self.chipdb, self.output, "20260827", self.database
            )


if __name__ == "__main__":
    unittest.main()
