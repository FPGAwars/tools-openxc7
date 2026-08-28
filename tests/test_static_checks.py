"""Tests for the static checks the `static` CI job runs.

Each checker is given a toy tree carrying exactly the defect it exists to
catch, because a checker that cannot fail is worse than no checker: it
reports green forever and nobody notices it stopped looking.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"

try:
    import yaml                                   # noqa: F401
    HAVE_YAML = True
except ImportError:                               # pragma: no cover
    HAVE_YAML = False


def run(script, *args):
    return subprocess.run(
        [str(SCRIPTS / script), *args],
        capture_output=True, text=True, check=False,
    )


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


HEALTHY_CALLER = """\
name: caller
on:
  workflow_dispatch:
jobs:
  chipdb:
    uses: ./.github/workflows/reusable.yml
    with:
      date: "2026-08-28"
  after:
    needs: [chipdb]
    runs-on: ubuntu-22.04
    steps:
      - run: echo "${{ needs.chipdb.outputs.identity }}"
"""

REUSABLE = """\
name: reusable
on:
  workflow_call:
    inputs:
      date:
        required: false
        type: string
    outputs:
      identity:
        value: ${{ jobs.gen.outputs.identity }}
jobs:
  gen:
    runs-on: ubuntu-22.04
    outputs:
      identity: ${{ steps.s.outputs.identity }}
    steps:
      - id: s
        run: echo "identity=x" >> "$GITHUB_OUTPUT"
"""


@unittest.skipUnless(HAVE_YAML, "PyYAML not installed (the CI job installs it)")
class WorkflowCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        write(self.root, ".github/workflows/caller.yml", HEALTHY_CALLER)
        write(self.root, ".github/workflows/reusable.yml", REUSABLE)

    def tearDown(self):
        self.temp.cleanup()

    def test_healthy_graph_passes(self):
        result = run("check-workflows.py", str(self.root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("cross-check: OK", result.stdout)

    def test_input_the_called_workflow_does_not_accept(self):
        """Actions ignores it silently; this must not."""
        write(self.root, ".github/workflows/caller.yml",
              HEALTHY_CALLER.replace("      date:", "      regenerate:"))
        result = run("check-workflows.py", str(self.root))
        self.assertEqual(result.returncode, 1)
        self.assertIn("rejects inputs ['regenerate']", result.stdout)

    def test_output_that_is_never_declared(self):
        """`needs.x.outputs.typo` evaluates to the empty string in Actions."""
        write(self.root, ".github/workflows/caller.yml",
              HEALTHY_CALLER.replace("outputs.identity }}", "outputs.identidad }}"))
        result = run("check-workflows.py", str(self.root))
        self.assertEqual(result.returncode, 1)
        self.assertIn("needs.chipdb.outputs.identidad is undeclared", result.stdout)

    def test_the_real_tree_is_consistent(self):
        result = run("check-workflows.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@unittest.skipUnless(HAVE_YAML, "PyYAML not installed (the CI job installs it)")
class ArtifactCheckerTests(unittest.TestCase):
    PRODUCER = """\
name: producer
on:
  workflow_dispatch:
jobs:
  build:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/upload-artifact@v7
        with:
          name: chipdb-bins
          path: dist/chipdb
"""
    CONSUMER = """\
name: consumer
on:
  workflow_dispatch:
jobs:
  pack:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/download-artifact@v6
        with:
          name: %s
          path: chipdb
"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        write(self.root, ".github/workflows/producer.yml", self.PRODUCER)

    def tearDown(self):
        self.temp.cleanup()

    def test_matching_names_pass(self):
        write(self.root, ".github/workflows/consumer.yml",
              self.CONSUMER % "chipdb-bins")
        result = run("check-artifacts.py", str(self.root))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("UNMATCHED DOWNLOADS: none", result.stdout)

    def test_a_download_nobody_uploads_is_caught(self):
        """The 2026-08 seed_from_artifact rename, in miniature."""
        write(self.root, ".github/workflows/consumer.yml",
              self.CONSUMER % "chipdb-seed")
        result = run("check-artifacts.py", str(self.root))
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNMATCHED DOWNLOADS: ['chipdb-seed']", result.stdout)

    def test_the_real_tree_is_consistent(self):
        result = run("check-artifacts.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TerminologyCheckerTests(unittest.TestCase):
    def make_repo(self, text: str) -> Path:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / "note.md").write_text(text, encoding="utf-8")
        environment = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": str(root / "gitconfig"),
            "GIT_CONFIG_SYSTEM": str(root / "gitconfig"),
        }
        subprocess.run(["git", "init", "-q", str(root)], check=True,
                       env=environment)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True,
                       env=environment)
        return root

    def test_a_pad_word_used_for_a_version_fails(self):
        root = self.make_repo("The sources are pinned in lock.json.\n")
        result = run("check-terminology.sh", str(root))
        self.assertEqual(result.returncode, 1)
        self.assertIn("note.md:1", result.stdout)
        self.assertIn("apio#924", result.stdout)

    def test_physical_pads_are_not_gated(self):
        root = self.make_repo(
            "set_property PACKAGE_PIN P15 [get_ports mainClk]\n"
            "The DI/WE pins of the SLICEM, and the board pin data.\n")
        result = run("check-terminology.sh", str(root))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("terminology: OK", result.stdout)

    def test_the_real_tree_is_clean(self):
        result = run("check-terminology.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
