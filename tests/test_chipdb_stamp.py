"""Tests for pack.chipdb.chipdb_identity (glob + hash over fixtures)."""

import os
import tempfile
import unittest
from pathlib import Path

from pack.chipdb import chipdb_identity
from pack.families import CHIPDB_PARTS_FILE


def make_fixture(root: Path):
    """Create the exact set of files chipdb_identity hashes."""
    (root / "nix" / "patches").mkdir(parents=True)
    (root / "nix" / "nextpnr-xilinx.nix").write_text(
        "nextpnr revision\n", encoding="utf-8")
    (root / "nix" / "nextpnr-xilinx-chipdb.nix").write_text(
        "chipdb derivation\n", encoding="utf-8")
    (root / CHIPDB_PARTS_FILE).write_text(
        '{"artix7": ["xc7a35tcsg324"]}\n', encoding="utf-8")
    (root / "nix" / "patches" / "a.patch").write_text(
        "patch a\n", encoding="utf-8")


class TestChipdbIdentity(unittest.TestCase):

    def setUp(self):
        self._old_cwd = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        make_fixture(self.root)
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_identity_is_stable(self):
        first = chipdb_identity()
        second = chipdb_identity()
        self.assertEqual(first, second)
        # -- 16 lowercase hex chars (truncated sha256 hexdigest)
        self.assertRegex(first, r"^[0-9a-f]{16}$")

    def test_identity_changes_when_patch_added(self):
        before = chipdb_identity()
        (self.root / "nix" / "patches" / "b.patch").write_text(
            "patch b\n", encoding="utf-8")
        self.assertNotEqual(chipdb_identity(), before)

    def test_identity_changes_when_source_changes(self):
        before = chipdb_identity()
        (self.root / CHIPDB_PARTS_FILE).write_text(
            '{"artix7": ["xc7a35tcsg324", "xc7a200tfbg484"]}\n',
            encoding="utf-8")
        self.assertNotEqual(chipdb_identity(), before)

    def test_only_patch_files_are_hashed(self):
        # -- The real glob is nix/patches/*.patch: a stray non-.patch file
        # -- must not alter the identity.
        before = chipdb_identity()
        (self.root / "nix" / "patches" / "notes.txt").write_text(
            "not a patch\n", encoding="utf-8")
        self.assertEqual(chipdb_identity(), before)

    def test_patches_hash_in_sorted_order_not_creation_order(self):
        # -- The glob result is sorted(): the identity must not depend on
        # -- file creation order.
        (self.root / "nix" / "patches" / "b.patch").write_text(
            "patch b\n", encoding="utf-8")
        first = chipdb_identity()

        with tempfile.TemporaryDirectory() as other:
            other_root = Path(other)
            make_fixture(other_root)
            # -- Recreate the same files, adding the patches in reverse
            # -- creation order (b existed first in the other tree)
            (other_root / "nix" / "patches" / "a.patch").unlink()
            (other_root / "nix" / "patches" / "b.patch").write_text(
                "patch b\n", encoding="utf-8")
            (other_root / "nix" / "patches" / "a.patch").write_text(
                "patch a\n", encoding="utf-8")
            os.chdir(other_root)
            try:
                second = chipdb_identity()
            finally:
                os.chdir(self.root)
        self.assertEqual(first, second)

    def test_missing_source_exits(self):
        (self.root / "nix" / "nextpnr-xilinx.nix").unlink()
        with self.assertRaises(SystemExit):
            chipdb_identity()


if __name__ == "__main__":
    unittest.main()
