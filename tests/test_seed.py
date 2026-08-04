"""Tests for pack.chipdb.seed_chipdb (stamp acceptance/rejection)."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from pack.chipdb import seed_chipdb, write_stamp
from pack.families import CHIPDB_PARTS_FILE

IDENTITY = "0123456789abcdef"
PART = "xc7a35tcsg324"


class TestSeedChipdb(unittest.TestCase):

    def setUp(self):
        self._old_cwd = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        os.chdir(self.root)

        # -- Manifest fixture (seed_chipdb iterates chipdb_parts())
        Path(CHIPDB_PARTS_FILE).write_text(
            json.dumps({"artix7": [PART]}), encoding="utf-8")

        # -- Target tree and seed directory with one prebuilt .bin
        self.dst_dir = self.root / "dist" / "chipdb"
        self.dst_dir.mkdir(parents=True)
        self.seed_dir = self.root / "seed"
        self.seed_dir.mkdir()
        (self.seed_dir / f"{PART}.bin").write_bytes(b"SEED-BIN")

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _with_seed_env(self):
        return mock.patch.dict(
            os.environ, {"OPENXC7_CHIPDB_SEED": str(self.seed_dir)})

    def test_no_env_var_is_a_noop(self):
        env = {k: v for k, v in os.environ.items()
               if k != "OPENXC7_CHIPDB_SEED"}
        with mock.patch.dict(os.environ, env, clear=True):
            seed_chipdb(IDENTITY)
        self.assertFalse((self.dst_dir / f"{PART}.bin").exists())

    def test_matching_stamp_copies_bins(self):
        write_stamp(self.seed_dir, IDENTITY)
        with self._with_seed_env(), redirect_stdout(io.StringIO()):
            seed_chipdb(IDENTITY)
        self.assertEqual(
            (self.dst_dir / f"{PART}.bin").read_bytes(), b"SEED-BIN")

    def test_existing_bin_is_not_overwritten(self):
        write_stamp(self.seed_dir, IDENTITY)
        (self.dst_dir / f"{PART}.bin").write_bytes(b"ALREADY-THERE")
        with self._with_seed_env(), redirect_stdout(io.StringIO()):
            seed_chipdb(IDENTITY)
        self.assertEqual(
            (self.dst_dir / f"{PART}.bin").read_bytes(), b"ALREADY-THERE")

    def test_mismatched_stamp_is_rejected(self):
        write_stamp(self.seed_dir, "feedfacecafebeef")
        with self._with_seed_env():
            with self.assertRaises(SystemExit):
                seed_chipdb(IDENTITY)
        # -- Nothing must have been copied from the foreign seed
        self.assertFalse((self.dst_dir / f"{PART}.bin").exists())

    def test_missing_stamp_is_rejected(self):
        # -- Seed directory without chipdb-id.txt: refuse it too
        with self._with_seed_env():
            with self.assertRaises(SystemExit):
                seed_chipdb(IDENTITY)
        self.assertFalse((self.dst_dir / f"{PART}.bin").exists())


if __name__ == "__main__":
    unittest.main()
