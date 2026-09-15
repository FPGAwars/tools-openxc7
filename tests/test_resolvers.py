"""Tests for the closure resolvers in pack.relocate.

Everything runs against synthetic fixtures (fake python packages on
sys.path, canned ldd/otool output, a fake python prefix): the tests never
touch the real /nix/store, which is exactly the property the resolvers
were built to have.
"""

import importlib
import io
import os
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from pack import relocate

LDD_SAMPLE = """\
\tlinux-vdso.so.1 (0x00007ffd21bfe000)
\tlibantlr4-runtime.so.4.9 => /nix/store/aaaa-antlr4-runtime-cpp-4.9.3/lib/libantlr4-runtime.so.4.9 (0x00007f9d3c000000)
\tlibuuid.so.1 => /nix/store/bbbb-util-linux-minimal-2.41-lib/lib/libuuid.so.1 (0x00007f9d3c100000)
\tlibmissing.so.2 => not found
\tlibc.so.6 => /nix/store/cccc-glibc-2.40/lib/libc.so.6 (0x00007f9d3c200000)
"""

OTOOL_SAMPLE = [
    "/nix/store/dddd-libffi-3.4.6/lib/libffi.8.dylib",
    "/nix/store/eeee-libcxx-16.0.6/lib/libc++.1.0.dylib",
]


def fake_completed(stdout):
    return subprocess.CompletedProcess(args=[], returncode=0,
                                       stdout=stdout, stderr="")


class ResolvePythonPackageTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.site = Path(self.temp.name)
        pkg = self.site / "fakepkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("X = 1\n", encoding="utf-8")
        (self.site / "fake_mod.py").write_text("Y = 2\n", encoding="utf-8")
        self.old_path = sys.path[:]
        sys.path.insert(0, str(self.site))
        importlib.invalidate_caches()

    def tearDown(self):
        sys.path[:] = self.old_path
        importlib.invalidate_caches()
        self.temp.cleanup()

    def test_package_dir_resolved(self):
        self.assertEqual(relocate.resolve_python_package("fakepkg"),
                         self.site / "fakepkg")

    def test_single_file_module_resolved(self):
        self.assertEqual(relocate.resolve_python_package("fake_mod"),
                         self.site / "fake_mod.py")

    def test_unknown_module_exits(self):
        with self.assertRaises(SystemExit):
            relocate.resolve_python_package("no_such_module_0072")


class NeededDepsTests(unittest.TestCase):

    def test_linux_ldd_parsed_and_not_found_skipped(self):
        with mock.patch.object(relocate, "IS_DARWIN", False), \
             mock.patch.object(relocate.subprocess, "run",
                               return_value=fake_completed(LDD_SAMPLE)):
            deps = relocate.needed_deps(Path("/fake/libparse_fasm.so"))
        self.assertEqual(deps, {
            "libantlr4-runtime.so.4.9": Path(
                "/nix/store/aaaa-antlr4-runtime-cpp-4.9.3/lib/"
                "libantlr4-runtime.so.4.9"),
            "libuuid.so.1": Path(
                "/nix/store/bbbb-util-linux-minimal-2.41-lib/lib/libuuid.so.1"),
            "libc.so.6": Path("/nix/store/cccc-glibc-2.40/lib/libc.so.6"),
        })

    def test_darwin_otool_keyed_by_basename(self):
        fake_macpack = types.ModuleType("macpack")
        fake_macpack._otool_deps = lambda path: OTOOL_SAMPLE
        with mock.patch.object(relocate, "IS_DARWIN", True), \
             mock.patch.dict(sys.modules, {"macpack": fake_macpack}):
            deps = relocate.needed_deps(Path("/fake/_ctypes.so"))
        self.assertEqual(deps, {
            "libffi.8.dylib": Path(
                "/nix/store/dddd-libffi-3.4.6/lib/libffi.8.dylib"),
            "libc++.1.0.dylib": Path(
                "/nix/store/eeee-libcxx-16.0.6/lib/libc++.1.0.dylib"),
        })


class ResolveNeededTests(unittest.TestCase):

    def patched_deps(self, mapping):
        # -- mapping: object name -> {dependency name: path}
        return mock.patch.object(
            relocate, "needed_deps",
            side_effect=lambda obj: mapping[obj.name])

    def test_resolves_by_fullmatch(self):
        mapping = {"libparse_fasm.so": {
            "libantlr4-runtime.so.4.9": Path("/store/antlr/lib/libantlr4-runtime.so.4.9"),
        }}
        with self.patched_deps(mapping):
            self.assertEqual(
                relocate.resolve_needed(Path("libparse_fasm.so"),
                                        r"libantlr4-runtime\..*"),
                Path("/store/antlr/lib/libantlr4-runtime.so.4.9"))

    def test_pattern_is_a_full_match(self):
        # -- "libuuid.so.1" must NOT match "libuuid.so.1.2.3"
        mapping = {"x.so": {"libuuid.so.1.2.3": Path("/store/libuuid.so.1.2.3")}}
        with self.patched_deps(mapping):
            with self.assertRaises(SystemExit):
                relocate.resolve_needed(Path("x.so"), r"libuuid\.so\.1")

    def test_missing_dependency_exits(self):
        with self.patched_deps({"x.so": {}}):
            with self.assertRaises(SystemExit):
                relocate.resolve_needed(Path("x.so"), r"libffi\..*")

    def test_resolve_needed_in_scans_every_object(self):
        # -- which object carries the dependency differs by platform
        mapping = {
            "antlr_to_tuple.so": {"libc.so.6": Path("/store/libc.so.6")},
            "libparse_fasm.so": {
                "libantlr4-runtime.so.4.9": Path("/store/antlr/libantlr4-runtime.so.4.9"),
            },
        }
        with self.patched_deps(mapping):
            self.assertEqual(
                relocate.resolve_needed_in(
                    [Path("antlr_to_tuple.so"), Path("libparse_fasm.so")],
                    r"libantlr4-runtime\..*"),
                Path("/store/antlr/libantlr4-runtime.so.4.9"))

    def test_resolve_needed_in_exits_naming_the_objects(self):
        with self.patched_deps({"a.so": {}, "b.so": {}}):
            with self.assertRaises(SystemExit) as ctx:
                relocate.resolve_needed_in([Path("a.so"), Path("b.so")], r"z.*")
        self.assertIn("a.so", str(ctx.exception))
        self.assertIn("b.so", str(ctx.exception))


class PythonCtypesTests(unittest.TestCase):

    def fake_prefix(self, root: Path):
        dynload = root / "lib" / "python3.12" / "lib-dynload"
        dynload.mkdir(parents=True)
        (root / "bin").mkdir()
        interpreter = root / "bin" / "python3.12"
        interpreter.write_text("", encoding="utf-8")
        return interpreter, dynload

    def test_locates_the_extension_of_the_shipped_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            interpreter, dynload = self.fake_prefix(Path(tmp))
            ext = dynload / "_ctypes.cpython-312-x86_64-linux-gnu.so"
            ext.write_bytes(b"fake")
            # -- _ctypes_test sorts first in a naive glob; it is NOT ctypes
            (dynload / "_ctypes_test.cpython-312-x86_64-linux-gnu.so"
             ).write_bytes(b"decoy")
            with mock.patch.object(relocate.shutil, "which",
                                   return_value=str(interpreter)):
                self.assertEqual(relocate.python_ctypes(), ext)

    def test_missing_extension_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            interpreter, _ = self.fake_prefix(Path(tmp))
            with mock.patch.object(relocate.shutil, "which",
                                   return_value=str(interpreter)):
                with self.assertRaises(SystemExit):
                    relocate.python_ctypes()


class CopyPythonDepTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.site = self.root / "site"
        self.site.mkdir()
        pkg = self.site / "fakepkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("X = 1\n", encoding="utf-8")
        (pkg / "mod.py").write_text("Y = 2\n", encoding="utf-8")
        (self.site / "fake_mod.py").write_text("Z = 3\n", encoding="utf-8")
        self.old_path = sys.path[:]
        self.old_cwd = Path.cwd()
        sys.path.insert(0, str(self.site))
        importlib.invalidate_caches()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.old_cwd)
        sys.path[:] = self.old_path
        importlib.invalidate_caches()
        self.temp.cleanup()

    def site_packages(self):
        return self.root / "dist" / "lib" / "python3.12" / "site-packages"

    def test_package_tree_copied(self):
        with redirect_stdout(io.StringIO()):
            relocate.copy_python_dep("fakepkg")
        dst = self.site_packages() / "fakepkg"
        self.assertEqual((dst / "__init__.py").read_text(encoding="utf-8"),
                         "X = 1\n")
        self.assertEqual((dst / "mod.py").read_text(encoding="utf-8"),
                         "Y = 2\n")

    def test_single_file_module_copied(self):
        with redirect_stdout(io.StringIO()):
            relocate.copy_python_dep("fake_mod")
        dst = self.site_packages() / "fake_mod.py"
        self.assertEqual(dst.read_text(encoding="utf-8"), "Z = 3\n")

    def test_second_copy_is_kept_not_recopied(self):
        with redirect_stdout(io.StringIO()):
            relocate.copy_python_dep("fakepkg")
            marker = self.site_packages() / "fakepkg" / "__init__.py"
            marker.write_text("TOUCHED\n", encoding="utf-8")
            relocate.copy_python_dep("fakepkg")
        self.assertEqual(marker.read_text(encoding="utf-8"), "TOUCHED\n")

    def test_unknown_module_exits_before_touching_dist(self):
        with self.assertRaises(SystemExit):
            relocate.copy_python_dep("no_such_module_0072")
        self.assertFalse((self.root / "dist").exists())


if __name__ == "__main__":
    unittest.main()
