"""Tests for per-FPGA chipdb assets and database inventory."""

import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from pack.chipdb_assets import available_parts, build_assets


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

    def test_schema_two_preserves_flat_parts_contract(self):
        part = "xc7a35tcpg236"
        other = "xc7a50tcsg324"
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

        index_path = build_assets(
            self.repo, self.chipdb, self.output, "20260826", self.database
        )
        index = json.loads(index_path.read_text(encoding="utf-8"))

        self.assertEqual(index["schema"], 2)
        self.assertEqual(index["date"], "20260826")
        self.assertEqual(index["chipdb_id"], "fixture-id")
        self.assertEqual([entry["part"] for entry in index["parts"]], [part])
        self.assertEqual(index["parts"][0]["name"], part)
        family = index["families"]["artix7"]
        self.assertEqual(
            [entry["name"] for entry in family["generated-parts"]], [part]
        )
        self.assertEqual(family["available-parts"], [part, other])
        for key in ("asset", "size", "sha256", "tgz_size", "tgz_sha256"):
            self.assertIn(key, index["parts"][0])

        asset = self.output / index["parts"][0]["asset"]
        with tarfile.open(asset, "r:gz") as archive:
            self.assertEqual(archive.getnames(), [f"{part}.bin"])
            self.assertEqual(archive.extractfile(f"{part}.bin").read(),
                             b"chipdb fixture")

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
                self.repo, self.chipdb, self.output, "20260826", self.database
            )


if __name__ == "__main__":
    unittest.main()
