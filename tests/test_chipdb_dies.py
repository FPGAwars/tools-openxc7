"""Tests for the per-die chipdb generation of pack.chipdb.

One chipdb file per die of the manifest, generated within a memory budget,
and a die rule the packaged database must agree with.
"""

import io
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from pack import chipdb
from pack.families import CHIPDB_PARTS_FILE


class GenerateDiesTests(unittest.TestCase):
    """generate_dies: at most N at once, never over the memory budget."""

    def run_fake(self, dies, jobs, budget_mib, fail=None):
        """Run generate_dies with a stand-in build that records overlap."""
        lock = threading.Lock()
        running = {}
        seen = []

        def build(family, die):
            with lock:
                running[die] = chipdb.peak_of(die)
                seen.append(dict(running))
            time.sleep(0.02)
            with lock:
                del running[die]
            if die == fail:
                raise SystemExit(f"generator failed on {die}")
            return f"built {die}"

        with redirect_stdout(io.StringIO()):
            chipdb.generate_dies(dies, jobs, budget_mib, build=build)
        return seen

    def test_the_default_budget_never_runs_the_two_big_dies_together(self):
        """xc7z045 (9.4 GB) and xc7z100 (12.4 GB) exceed a 16 GB runner
        together; under the default budget they run one after the other,
        while small dies fill the rest."""
        dies = [("zynq7", die) for die in chipdb.DIE_PEAK_MIB]
        seen = self.run_fake(dies, 10, chipdb.DEFAULT_MEM_GB * 1024)
        self.assertFalse([s for s in seen if {"xc7z045", "xc7z100"} <= set(s)])
        self.assertTrue(all(sum(s.values()) <= chipdb.DEFAULT_MEM_GB * 1024
                            for s in seen))
        self.assertTrue(any(len(s) > 1 for s in seen), "never parallel")
        self.assertEqual(len(seen), len(dies))

    def test_jobs_bound_the_parallelism(self):
        dies = [("artix7", die) for die in ("xc7s25", "xc7z010", "xc7s50",
                                            "xc7a50t", "xc7z020")]
        seen = self.run_fake(dies, 2, 1e9)
        self.assertEqual(max(len(s) for s in seen), 2)

    def test_a_die_bigger_than_the_budget_runs_alone(self):
        dies = [("zynq7", "xc7z100"), ("zynq7", "xc7z010"),
                ("spartan7", "xc7s25")]
        seen = self.run_fake(dies, 4, 4 * 1024)
        self.assertIn({"xc7z100": chipdb.DIE_PEAK_MIB["xc7z100"]}, seen)
        self.assertFalse([s for s in seen if "xc7z100" in s and len(s) > 1])

    def test_an_unknown_die_counts_as_the_biggest(self):
        self.assertEqual(chipdb.peak_of("xc7k480t"),
                         max(chipdb.DIE_PEAK_MIB.values()))

    def test_a_failure_stops_the_generation_and_is_raised(self):
        dies = [("artix7", die) for die in ("xc7a50t", "xc7s25", "xc7z010")]
        with self.assertRaises(SystemExit):
            self.run_fake(dies, 1, 1e9, fail="xc7a50t")


class DieCheckTests(unittest.TestCase):
    """check_dies: die_of() against the database's own mapping."""

    def setUp(self):
        self._old_cwd = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        os.chdir(self.root)
        Path(CHIPDB_PARTS_FILE).write_text(
            json.dumps({"artix7": ["xc7a35tcpg236", "xc7a50tcsg324"]}),
            encoding="utf-8")
        self.db = self.root / "prjxray-db"
        self.write_mapping("xc7a50t")

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def write_mapping(self, fabric_of_35t):
        """prjxray-db's two mapping files, in their real shape."""
        mapping = self.db / "artix7" / "mapping"
        mapping.mkdir(parents=True, exist_ok=True)
        (mapping / "parts.yaml").write_text(
            "xc7a35tcpg236-1:\n  device: xc7a35t\n  package: cpg236\n"
            "  speedgrade: '1'\n"
            "xc7a50tcsg324-1:\n  device: xc7a50t\n  package: csg324\n"
            "  speedgrade: '1'\n", encoding="utf-8")
        (mapping / "devices.yaml").write_text(
            "# device to fabric mapping\n"
            f'"xc7a50t":\n  fabric: "xc7a50t"\n'
            f'"xc7a35t":\n  fabric: "{fabric_of_35t}"\n', encoding="utf-8")

    def test_the_database_maps_every_base_part_to_its_die(self):
        self.assertEqual(chipdb.database_dies(self.db),
                         {"xc7a35tcpg236": "xc7a50t",
                          "xc7a50tcsg324": "xc7a50t"})
        chipdb.check_dies(self.db)          # agrees: no exception

    def test_a_disagreement_stops_the_generation(self):
        """A wrong die would build a chipdb without the part's package, and
        the index would promise it to apio anyway."""
        self.write_mapping("xc7a35t")
        with self.assertRaisesRegex(SystemExit, "xc7a35tcpg236: die_of says "
                                    "xc7a50t, the database xc7a35t"):
            chipdb.check_dies(self.db)

    def test_a_part_the_database_lacks_stops_the_generation(self):
        Path(CHIPDB_PARTS_FILE).write_text(
            json.dumps({"artix7": ["xc7a100tcsg324"]}), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "the database nothing"):
            chipdb.check_dies(self.db)


class ChipdbFileTests(unittest.TestCase):

    def test_one_file_per_die(self):
        self.assertEqual(chipdb.chipdb_file("xc7a50t"), "chipdb-xc7a50t.bin")

    def test_the_placeholder_names_the_per_die_assets(self):
        self.assertIn("chipdb-<die>.bin", chipdb.PLACEHOLDER_TEXT)
        self.assertIn("apio-xilinx-chipdb-<die>-<YYYYMMDD>.bin.tgz",
                      chipdb.PLACEHOLDER_TEXT)

    def test_every_die_of_the_manifest_has_a_measured_peak(self):
        """The budget is only as good as the table: a die of the real
        manifest missing from it would count as the biggest one."""
        manifest = Path(__file__).resolve().parent.parent / CHIPDB_PARTS_FILE
        old = Path.cwd()
        try:
            os.chdir(manifest.parent)
            from pack.families import chipdb_dies
            missing = [die for _, die in chipdb_dies()
                       if die not in chipdb.DIE_PEAK_MIB]
        finally:
            os.chdir(old)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
