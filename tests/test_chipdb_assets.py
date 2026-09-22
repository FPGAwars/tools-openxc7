"""Tests for per-FPGA chipdb assets, the cache and the database inventory."""

import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from pack.chipdb_assets import build_assets, database_parts
from pack.parts_index import (ENTRY_KEYS, INDEX_ASSET, PACKAGE_FILE,
                              release_tag, validate_document)

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
        self.output = self.root / "assets"
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
        both (XILINX-PARTS-INDEX.json since the apio#1002 rename). The
        name is a release contract, so a divergence must fail here rather
        than at a release gate.
        """
        self.fixture()
        info_path = build_assets(
            self.repo, self.chipdb, self.output, "20260827", self.database
        )
        self.assertEqual(info_path.name, INDEX_ASSET)
        self.assertEqual(info_path.name, PACKAGE_FILE)

    def test_index_describes_every_part_of_the_database(self):
        part, other = self.fixture()

        info_path = build_assets(
            self.repo, self.chipdb, self.output, "20260827", self.database
        )
        info = json.loads(info_path.read_text(encoding="utf-8"))

        self.assertEqual(info["schema"], 7)
        self.assertEqual(info["date"], "20260827")
        self.assertEqual(info["release-tag"], "2026-08-27")
        self.assertEqual(info["chipdb-id"], "fixture-id")
        # Two speed grades of the built base part, one of the other.
        self.assertEqual(info["part-count"], 3)
        self.assertEqual(info["generated-count"], 2)
        self.assertEqual(info["chipdb-count"], 1)
        self.assertEqual(info["base-part-count"], 2)
        self.assertEqual(sorted(info["parts"]),
                         sorted([f"{part}-1", f"{part}-2", f"{other}-1"]))

        entry = info["parts"][f"{part}-1"]
        self.assertEqual(list(entry), ["family", "base-part", "speed",
                                       "generated", "chipdb",
                                       "chipdb-size", "chipdb-sha256",
                                       "asset", "asset-size",
                                       "asset-sha256"])
        self.assertTrue(entry["generated"])
        self.assertEqual(entry["family"], "artix7")
        self.assertEqual(entry["base-part"], part)
        self.assertEqual(entry["speed"], "1")
        self.assertEqual(entry["chipdb"], DIE_FILE)
        self.assertEqual(entry["asset"],
                         "apio-xilinx-chipdb-xc7a50t-20260827.bin.tgz")
        self.assertEqual(entry["chipdb-size"], len(b"chipdb fixture"))
        # The other speed grade points at the very same file and asset.
        self.assertEqual(info["parts"][f"{part}-2"] | {"speed": "1"}, entry)
        # A part the database supports but this release did not build
        # carries nothing that would make it look downloadable.
        self.assertEqual(info["parts"][f"{other}-1"],
                         {"family": "artix7", "base-part": other,
                          "speed": "1", "generated": False})

        asset = self.output / entry["asset"]
        self.assertEqual(asset.stat().st_size, entry["asset-size"])
        with tarfile.open(asset, "r:gz") as archive:
            self.assertEqual(archive.getnames(), [DIE_FILE])
            self.assertEqual(archive.extractfile(DIE_FILE).read(),
                             b"chipdb fixture")

    def test_every_entry_follows_entry_keys_and_validates(self):
        """Keys in ENTRY_KEYS order, generated or not, and the document
        the writer produces is one the validator accepts."""
        self.fixture()
        info_path = build_assets(
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

    def test_cache_is_reused_when_the_identity_matches(self):
        part, _ = self.fixture()
        cache = self.root / "cache"

        first = build_assets(self.repo, self.chipdb, self.output, "20260827",
                             self.database, cache=cache, jobs=2)
        self.assertTrue((cache / f"{DIE_FILE}.tgz").is_file())
        self.assertEqual((cache / "chipdb-id.txt").read_text().strip(),
                         "fixture-id")

        # A second run for another date reuses the compressed bytes and
        # renames them; the document is rebuilt with the new date.
        second_output = self.root / "assets2"
        second = build_assets(self.repo, self.chipdb, second_output,
                              "20260828", self.database, cache=cache, jobs=2)
        old = json.loads(first.read_text())["parts"][f"{part}-1"]
        new = json.loads(second.read_text())["parts"][f"{part}-1"]
        self.assertEqual(new["asset-sha256"], old["asset-sha256"])
        self.assertEqual(new["asset"],
                         "apio-xilinx-chipdb-xc7a50t-20260828.bin.tgz")
        self.assertTrue((second_output / new["asset"]).is_file())

    def test_cache_of_another_toolchain_is_not_reused(self):
        part, _ = self.fixture()
        cache = self.root / "cache"
        cache.mkdir()
        (cache / "chipdb-id.txt").write_text("other-id\n", encoding="utf-8")
        (cache / f"{DIE_FILE}.tgz").write_bytes(b"not a tar.gz at all")

        info_path = build_assets(self.repo, self.chipdb, self.output,
                                 "20260827", self.database, cache=cache)
        entry = json.loads(info_path.read_text())["parts"][f"{part}-1"]
        asset = self.output / entry["asset"]
        with tarfile.open(asset, "r:gz") as archive:   # rebuilt, not copied
            self.assertEqual(archive.getnames(), [DIE_FILE])
        self.assertEqual((cache / "chipdb-id.txt").read_text().strip(),
                         "fixture-id")

    def test_one_asset_per_die_shared_by_its_parts(self):
        """Two manifest base parts on the xc7a50t die and one on xc7a100t:
        two chipdb files, two assets, and the parts of a die repeat the
        same file, asset and hashes -- which the validator requires."""
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

        info = json.loads(build_assets(
            self.repo, self.chipdb, self.output, "20260827", self.database,
            jobs=2).read_text())

        self.assertEqual(sorted(p.name for p in self.output.glob("*.tgz")),
                         ["apio-xilinx-chipdb-xc7a100t-20260827.bin.tgz",
                          "apio-xilinx-chipdb-xc7a50t-20260827.bin.tgz"])
        self.assertEqual((info["part-count"], info["generated-count"],
                          info["chipdb-count"], info["base-part-count"]),
                         (6, 6, 2, 3))
        promise = {part: {key: entry[key] for key in
                          ("chipdb", "chipdb-sha256", "asset",
                           "asset-sha256")}
                   for part, entry in info["parts"].items()}
        self.assertEqual(promise["xc7a35tcpg236-1"], promise["xc7a50tcsg324-2"])
        self.assertNotEqual(promise["xc7a35tcpg236-1"],
                            promise["xc7a100tcsg324-1"])
        self.assertEqual(promise["xc7a100tcsg324-2"]["chipdb"],
                         "chipdb-xc7a100t.bin")
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
            build_assets(
                self.repo, self.chipdb, self.output, "20260827", self.database
            )

    def test_unstamped_chipdb_is_refused(self):
        self.fixture()
        (self.chipdb / "chipdb-id.txt").unlink()
        with self.assertRaisesRegex(ValueError, "unstamped"):
            build_assets(
                self.repo, self.chipdb, self.output, "20260827", self.database
            )


if __name__ == "__main__":
    unittest.main()
