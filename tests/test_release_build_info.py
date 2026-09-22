"""Tests for scripts/release-build-info.py, the release-level BUILD-INFO.

The three packages of a release carry three BUILD-INFO.json documents that
differ in exactly three fields: the platform, the tarball and the moment
that platform's job stamped it. Publishing one of them as the document of
the release would call a three-platform release a linux build, so the
release-level one is composed from all three.

Composing it is also the only cross-platform agreement check left in the
publisher: the three jobs of one run must have built from one revision,
one chipdb and one commit, and a disagreement has to stop the release
rather than be resolved silently in favour of whichever document was read
first.
"""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "release-build-info.py"

_spec = importlib.util.spec_from_file_location("release_build_info", SCRIPT)
release_build_info = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_build_info)

PLATFORMS = ("linux-x86-64", "darwin-arm64", "windows-amd64")
DATE = "20260907"


def package(platform, **overrides):
    """One package's BUILD-INFO.json, as scripts/build-info.sh writes it."""
    info = {
        "package-name": "openxc7",
        "description": "openXC7 toolchain for Xilinx 7-series FPGAs",
        "release-tag": "2026-09-07",
        "yosys-release-tag": "2026-03-24",
        "nextpnr-xilinx-revision": "68aeeb39f92e39bfb239c7e4a44dd93451fc1889",
        "prjxray-db-revision": "a90f27c1caefee5276f47440f4c730b50519a86f",
        "eigen-version": "3.4.0",
        "chipdb-source": "restored-from-cache",
        "use-cached-chipdb": True,
        "chipdb-id": "2e00b07a2226c0ad",
        "build-repo": "FPGAwars/tools-openxc7",
        "build-workflow": "build-pre-release",
        "workflow-run-id": "34127602283",
        "workflow-run-number": "65",
        "build-time": "2026-09-07 13:42:17 UTC",
        "commit": "3931811fdb26d2eaf484f2eb63d7db976e43316f",
        "target-platform": platform,
        "file-name": f"apio-openxc7-{platform}-{DATE}.tgz",
    }
    info.update(overrides)
    return info


def release(**per_platform):
    """The three documents of a healthy release, keyed by source name."""
    return {platform: package(platform, **per_platform.get(platform, {}))
            for platform in PLATFORMS}


def run_cli(documents):
    """Run the script over *documents*; return (exit code, stdout, stderr)."""
    with tempfile.TemporaryDirectory() as scratch:
        paths = []
        for name, info in documents.items():
            path = Path(scratch) / f"{name}.json"
            path.write_text(json.dumps(info), encoding="utf-8")
            paths.append(str(path))
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = release_build_info.main(paths)
        return code, out.getvalue(), err.getvalue()


class ComposeTests(unittest.TestCase):

    def test_shared_fields_are_kept_and_a_row_per_package_added(self):
        document = release_build_info.compose(release())
        self.assertEqual(document["package-name"], "openxc7")
        self.assertEqual(document["release-tag"], "2026-09-07")
        self.assertEqual(document["chipdb-id"], "2e00b07a2226c0ad")
        self.assertEqual(sorted(document["packages"]), sorted(PLATFORMS))
        self.assertEqual(
            document["packages"]["windows-amd64"]["file-name"],
            f"apio-openxc7-windows-amd64-{DATE}.tgz")

    def test_the_per_package_fields_are_not_left_at_the_top_level(self):
        """A top-level target-platform would describe the whole release as
        one platform's build -- the reason this document is composed."""
        document = release_build_info.compose(release())
        for key in ("target-platform", "file-name", "build-time"):
            self.assertNotIn(key, document)

    def test_the_shared_keys_keep_the_order_of_the_package_document(self):
        """The two files are read side by side; they should read alike."""
        document = release_build_info.compose(release())
        source = [key for key in package("linux-x86-64")
                  if key not in ("target-platform", "file-name",
                                 "build-time")]
        self.assertEqual([key for key in document if key != "packages"],
                         source)
        self.assertEqual(list(document)[-1], "packages")

    def test_each_package_keeps_its_own_build_time(self):
        documents = release(**{"windows-amd64": {
            "build-time": "2026-09-07 13:55:40 UTC"}})
        document = release_build_info.compose(documents)
        self.assertEqual(document["packages"]["windows-amd64"]["build-time"],
                         "2026-09-07 13:55:40 UTC")
        self.assertEqual(document["packages"]["linux-x86-64"]["build-time"],
                         "2026-09-07 13:42:17 UTC")

    def test_a_disagreement_on_a_shared_field_is_an_error(self):
        """Three jobs, one run: a second commit means a mixed release."""
        documents = release(**{"darwin-arm64": {"commit": "deadbeef"}})
        with self.assertRaises(ValueError) as raised:
            release_build_info.compose(documents)
        self.assertIn("disagree on 'commit'", str(raised.exception))
        self.assertIn("deadbeef", str(raised.exception))

    def test_a_disagreement_on_the_chipdb_identity_is_an_error(self):
        documents = release(**{"windows-amd64": {"chipdb-id": "other"}})
        with self.assertRaises(ValueError) as raised:
            release_build_info.compose(documents)
        self.assertIn("chipdb-id", str(raised.exception))

    def test_a_disagreement_on_the_database_revision_is_an_error(self):
        """The prjxray-db every chipdb and every package is built from."""
        documents = release(**{"darwin-arm64": {
            "prjxray-db-revision": "1768fb35" + "0" * 32}})
        with self.assertRaises(ValueError) as raised:
            release_build_info.compose(documents)
        self.assertIn("prjxray-db-revision", str(raised.exception))

    def test_the_database_revision_reaches_the_release_document(self):
        document = release_build_info.compose(release())
        self.assertEqual(document["prjxray-db-revision"],
                         "a90f27c1caefee5276f47440f4c730b50519a86f")

    def test_a_document_with_a_different_field_set_is_an_error(self):
        documents = release()
        del documents["darwin-arm64"]["yosys-release-tag"]
        documents["darwin-arm64"]["something-else"] = "x"
        with self.assertRaises(ValueError) as raised:
            release_build_info.compose(documents)
        self.assertIn("yosys-release-tag", str(raised.exception))
        self.assertIn("something-else", str(raised.exception))

    def test_a_document_without_its_platform_is_an_error(self):
        documents = release()
        del documents["linux-x86-64"]["target-platform"]
        with self.assertRaises(ValueError) as raised:
            release_build_info.compose(documents)
        self.assertIn("target-platform", str(raised.exception))

    def test_two_documents_for_one_platform_is_an_error(self):
        documents = {"a": package("linux-x86-64"),
                     "b": package("linux-x86-64")}
        with self.assertRaises(ValueError) as raised:
            release_build_info.compose(documents)
        self.assertIn("two documents for platform", str(raised.exception))

    def test_no_documents_at_all_is_an_error(self):
        with self.assertRaises(ValueError):
            release_build_info.compose({})


class FixtureTests(unittest.TestCase):

    def test_the_fixture_carries_the_fields_build_info_writes(self):
        """The documents above stand for what scripts/build-info.sh writes:
        the same keys in the same order, or these tests describe another
        document."""
        with tempfile.TemporaryDirectory() as scratch:
            out = Path(scratch) / "BUILD-INFO.json"
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith("GITHUB_")}
            env.update(EIGEN_VERSION="3.4.0", YOSYS_RELEASE_TAG="2026-09-07")
            subprocess.run(
                ["bash", str(REPO / "scripts" / "build-info.sh"),
                 "linux-x86-64", "2026-09-07", "x.tgz", str(out)],
                env=env, check=True, capture_output=True)
            written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(list(written), list(package("linux-x86-64")))


class CommandLineTests(unittest.TestCase):

    def test_it_writes_the_document_to_stdout(self):
        code, out, _ = run_cli(release())
        self.assertEqual(code, 0)
        document = json.loads(out)
        self.assertEqual(sorted(document["packages"]), sorted(PLATFORMS))

    def test_a_disagreement_exits_non_zero_and_says_what_it_is(self):
        code, out, err = run_cli(release(**{"darwin-arm64": {
            "nextpnr-xilinx-revision": "0" * 40}}))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("nextpnr-xilinx-revision", err)

    def test_no_arguments_prints_the_usage(self):
        with redirect_stderr(StringIO()) as err:
            code = release_build_info.main([])
        self.assertEqual(code, 2)
        self.assertIn("release-build-info.py", err.getvalue())


if __name__ == "__main__":
    unittest.main()
