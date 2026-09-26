"""The chipdb cache key of the CI and the identity stamp hash the same files.

chipdb.yml restores the bins from a cache keyed by hashFiles(...); the
packer seeds from that cache only when the bins carry the identity
chipdb_identity() computes. If a file moved the identity but not the key,
every run after that change would restore bins the packer then refuses,
and regenerate them on each run without anything saying why. If a file
moved neither, a stale cache would be the only one there is.

The identity side is measured, not read: each candidate file is changed in
a fixture tree and the test records whether chipdb_identity() moves. The
key side is read from the workflow itself, so a change to either list is a
change to what is tested.
"""

import fnmatch
import os
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from pack.chipdb import chipdb_identity

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github/workflows/chipdb.yml"

# In the key and not in the identity, on purpose: prjxray (the tools) does
# not take part in generating a chipdb, so its revision cannot change the
# bins; keying the cache on it only makes the cache more conservative.
KEY_ONLY = {"nix/prjxray.nix"}

HASH_FILES = re.compile(r"hashFiles\(([^)]*)\)")


def cache_keys() -> dict:
    """{cache path: [hashFiles patterns]} of the chipdb job's caches."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    keys = {}
    for step in workflow["jobs"]["chipdb"]["steps"]:
        if not str(step.get("uses", "")).startswith("actions/cache"):
            continue
        match = HASH_FILES.search(step["with"]["key"])
        patterns = re.findall(r"'([^']*)'", match.group(1))
        keys[step["with"]["path"]] = patterns
    return keys


def probe_files(key_patterns) -> list:
    """Every file the identity could plausibly read, relative to the repo.

    The key's own patterns (a glob stands for one file that matches it),
    every file under nix/ and the root build inputs, and one patch that
    does not exist in the tree: a glob the identity reads but the key does
    not would otherwise never show up, since nix/patches is empty today.
    """
    files = {pattern.replace("*", "probe") for pattern in key_patterns}
    files |= {str(path.relative_to(REPO)) for path in (REPO / "nix").rglob("*")
              if path.is_file()}
    files |= {"flake.nix", "flake.lock", "chipdb-parts.json",
              "nix/patches/probe.patch"}
    return sorted(files)


def identity_files(candidates) -> set:
    """The candidates whose content moves chipdb_identity().

    Every candidate exists in the fixture, so a file the identity requires
    but the fixture lacked would exit instead of being silently left out.
    """
    old_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        for relative in candidates:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{relative}\n", encoding="utf-8")
        os.chdir(root)
        try:
            before = chipdb_identity()
            moved = set()
            for relative in candidates:
                path = root / relative
                original = path.read_text(encoding="utf-8")
                path.write_text(original + "changed\n", encoding="utf-8")
                if chipdb_identity() != before:
                    moved.add(relative)
                path.write_text(original, encoding="utf-8")
        finally:
            os.chdir(old_cwd)
    return moved


def covered(relative, patterns) -> bool:
    return any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns)


class ChipdbCacheKeyTests(unittest.TestCase):

    def test_the_only_cache_is_the_bins(self):
        """Schema 8 publishes no compressed chipdb assets, so there is no
        second cache of them."""
        keys = cache_keys()
        self.assertEqual(sorted(keys), ["chipdb-cache"])

    def test_the_key_hashes_what_the_identity_hashes(self):
        patterns = cache_keys()["chipdb-cache"]
        moved = identity_files(probe_files(patterns))
        # every file that moves the identity is in the key...
        self.assertEqual(sorted(f for f in moved if not covered(f, patterns)), [])
        # ...and every file of the key moves it, bar the documented extra
        for pattern in patterns:
            matches = [f for f in moved if fnmatch.fnmatchcase(f, pattern)]
            if pattern in KEY_ONLY:
                self.assertEqual(matches, [], pattern)
            else:
                self.assertNotEqual(matches, [], pattern)

    def test_the_key_only_files_exist(self):
        for relative in KEY_ONLY:
            self.assertTrue((REPO / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
