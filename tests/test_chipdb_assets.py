"""Tests for per-FPGA chipdb assets, the cache and the database inventory."""

import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from pack.chipdb_assets import available_parts, build_assets, release_tag


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
        """A one-part manifest plus one footprint the database has only."""
        self.add_database_part("artix7", f"{part}-1")
        self.add_database_part("artix7", f"{part}-2")
        self.add_database_part("artix7", f"{other}-1")
        (self.repo / "chipdb-parts.json").write_text(
            json.dumps({"artix7": [part]}), encoding="utf-8"
        )
        (self.chipdb / "chipdb-id.txt").write_text(
            "fixture-id\n", encoding="utf-8"
        )
        (self.chipdb / f"{part}.bin").write_bytes(b"chipdb fixture")
        return part, other

    def test_available_parts_collapse_speed_variants(self):
        self.add_database_part("artix7", "xc7a35tcpg236-1")
        self.add_database_part("artix7", "xc7a35tcpg236-2L")
        self.add_database_part("artix7", "xc7a50tcsg324-1")
        self.add_database_part("spartan7", "xc7s50csga324-1IL")

        self.assertEqual(
            available_parts(self.database),
            {
                "artix7": ["xc7a35tcpg236", "xc7a50tcsg324"],
                "spartan7": ["xc7s50csga324"],
            },
        )

    def test_release_tag_is_the_tag_apio_derives_the_date_from(self):
        self.assertEqual(release_tag("20260827"), "2026-08-27")
        with self.assertRaises(ValueError):
            release_tag("2026-08-27")

    def test_document_describes_generated_and_available_parts(self):
        part, other = self.fixture()

        info_path = build_assets(
            self.repo, self.chipdb, self.output, "20260827", self.database
        )
        info = json.loads(info_path.read_text(encoding="utf-8"))

        self.assertEqual(info["schema"], 3)
        self.assertEqual(info["date"], "20260827")
        self.assertEqual(info["release-tag"], "2026-08-27")
        self.assertEqual(info["chipdb-id"], "fixture-id")
        self.assertEqual(info["generated-count"], 1)
        self.assertEqual(info["available-count"], 2)
        self.assertEqual(sorted(info["parts"]), sorted([part, other]))

        entry = info["parts"][part]
        self.assertTrue(entry["generated"])
        self.assertEqual(entry["family"], "artix7")
        self.assertEqual(entry["asset"],
                         f"apio-xilinx-chipdb-{part}-20260827.bin.tgz")
        self.assertEqual(entry["size"], len(b"chipdb fixture"))
        # A footprint the database supports but this release did not build
        # carries nothing that would make it look downloadable.
        self.assertEqual(info["parts"][other],
                         {"family": "artix7", "generated": False})

        asset = self.output / entry["asset"]
        self.assertEqual(asset.stat().st_size, entry["tgz_size"])
        with tarfile.open(asset, "r:gz") as archive:
            self.assertEqual(archive.getnames(), [f"{part}.bin"])
            self.assertEqual(archive.extractfile(f"{part}.bin").read(),
                             b"chipdb fixture")

    def test_cache_is_reused_when_the_identity_matches(self):
        part, _ = self.fixture()
        cache = self.root / "cache"

        first = build_assets(self.repo, self.chipdb, self.output, "20260827",
                             self.database, cache=cache, jobs=2)
        self.assertTrue((cache / f"{part}.bin.tgz").is_file())
        self.assertEqual((cache / "chipdb-id.txt").read_text().strip(),
                         "fixture-id")

        # A second run for another date reuses the compressed bytes and
        # renames them; the document is rebuilt with the new date.
        second_output = self.root / "assets2"
        second = build_assets(self.repo, self.chipdb, second_output,
                              "20260828", self.database, cache=cache, jobs=2)
        old = json.loads(first.read_text())["parts"][part]
        new = json.loads(second.read_text())["parts"][part]
        self.assertEqual(new["tgz_sha256"], old["tgz_sha256"])
        self.assertEqual(new["asset"],
                         f"apio-xilinx-chipdb-{part}-20260828.bin.tgz")
        self.assertTrue((second_output / new["asset"]).is_file())

    def test_cache_of_another_toolchain_is_not_reused(self):
        part, _ = self.fixture()
        cache = self.root / "cache"
        cache.mkdir()
        (cache / "chipdb-id.txt").write_text("other-id\n", encoding="utf-8")
        (cache / f"{part}.bin.tgz").write_bytes(b"not a tar.gz at all")

        info_path = build_assets(self.repo, self.chipdb, self.output,
                                 "20260827", self.database, cache=cache)
        entry = json.loads(info_path.read_text())["parts"][part]
        asset = self.output / entry["asset"]
        with tarfile.open(asset, "r:gz") as archive:   # rebuilt, not copied
            self.assertEqual(archive.getnames(), [f"{part}.bin"])
        self.assertEqual((cache / "chipdb-id.txt").read_text().strip(),
                         "fixture-id")

    def test_generated_part_must_exist_in_database(self):
        part = "xc7a35tcpg236"
        (self.repo / "chipdb-parts.json").write_text(
            json.dumps({"artix7": [part]}), encoding="utf-8"
        )
        (self.chipdb / "chipdb-id.txt").write_text(
            "fixture-id\n", encoding="utf-8"
        )
        (self.chipdb / f"{part}.bin").write_bytes(b"chipdb fixture")
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
