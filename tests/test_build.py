"""Tests for .github/workflows/build.py, on a small fake toolchain tarball."""

import importlib.util
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / ".github" / "workflows" / "build.py"
spec = importlib.util.spec_from_file_location("build", SCRIPT)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

INDEX = {
    "schema": 8,
    "chipdb-count": 1,
    "parts": {
        "xc7a35tcsg324-1": {"generated": True, "chipdb": "chipdb-xc7a50t.bin"},
        "xc7a50tcsg324-1": {"generated": True, "chipdb": "chipdb-xc7a50t.bin"},
        "xc7a15tcsg324-1": {"generated": False},
    },
}

BUILD_INFO = {
    "package-name": "openxc7",
    "release-tag": "2026-10-01",
    "yosys-release-tag": "2026-03-24",
}


def make_toolchain(tmp_path: Path, index: dict = INDEX) -> Path:
    """A toolchain tarball with the files build.py checks."""
    tree = tmp_path / "toolchain"
    (tree / "bin").mkdir(parents=True)
    (tree / "chipdb").mkdir()
    for name in build.REQUIRED_FILES["linux-x86-64"]:
        (tree / name).write_text("#!/bin/sh\n")
        (tree / name).chmod(0o755)
    (tree / "chipdb" / "chipdb-xc7a50t.bin").write_bytes(b"chipdb")
    (tree / "XILINX-PARTS-INDEX.json").write_text(json.dumps(index))
    (tree / "BUILD-INFO.json").write_text('{"package-name": "openxc7-toolchain"}')
    tgz = tmp_path / "openxc7-toolchain-linux-x86-64-20260930.tgz"
    subprocess.run(["tar", "czf", str(tgz), "-C", str(tree), "."], check=True)
    return tgz


def test_file_names():
    assert (
        build.upstream_file_name("windows-amd64", "2026-09-30")
        == "openxc7-toolchain-windows-amd64-20260930.tgz"
    )
    assert (
        build.package_file_name("darwin-arm64", "2026-10-01")
        == "apio-openxc7-darwin-arm64-20261001.tgz"
    )


def test_check_sha256(tmp_path):
    file_path = tmp_path / "a.tgz"
    file_path.write_bytes(b"hello\n")
    sums = tmp_path / "SHA256SUMS"
    good = "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
    sums.write_text(f"{good}  a.tgz\n")
    build.check_sha256(file_path, sums)

    sums.write_text(f"{'0' * 64}  a.tgz\n")
    with pytest.raises(AssertionError):
        build.check_sha256(file_path, sums)


def test_build_package(tmp_path):
    tgz = make_toolchain(tmp_path)
    index_file = tmp_path / "XILINX-PARTS-INDEX.json"
    index_file.write_text(json.dumps(INDEX))

    package = build.build_package(
        "linux-x86-64", tgz, index_file, BUILD_INFO, tmp_path / "_packages"
    )

    assert package.name == "apio-openxc7-linux-x86-64-20261001.tgz"
    with tarfile.open(package) as tar:
        info = json.load(tar.extractfile("./BUILD-INFO.json"))
        toolchain_info = json.load(tar.extractfile("./TOOLCHAIN-BUILD-INFO.json"))
        names = tar.getnames()
    assert info == {
        **BUILD_INFO,
        "target-platform": "linux-x86-64",
        "file-name": "apio-openxc7-linux-x86-64-20261001.tgz",
    }
    assert toolchain_info == {"package-name": "openxc7-toolchain"}
    assert "./chipdb/chipdb-xc7a50t.bin" in names
    assert "./bin/nextpnr-xilinx" in names


def test_index_must_match_the_release(tmp_path):
    tgz = make_toolchain(tmp_path)
    index_file = tmp_path / "XILINX-PARTS-INDEX.json"
    index_file.write_text(json.dumps({**INDEX, "chipdb-count": 2}))
    with pytest.raises(AssertionError):
        build.build_package(
            "linux-x86-64", tgz, index_file, BUILD_INFO, tmp_path / "_packages"
        )


def test_index_schema(tmp_path):
    index = {**INDEX, "schema": 7}
    tgz = make_toolchain(tmp_path, index)
    index_file = tmp_path / "XILINX-PARTS-INDEX.json"
    index_file.write_text(json.dumps(index))
    with pytest.raises(AssertionError):
        build.build_package(
            "linux-x86-64", tgz, index_file, BUILD_INFO, tmp_path / "_packages"
        )


def test_chipdb_files_must_match_the_index(tmp_path):
    index = {**INDEX, "chipdb-count": 2}
    index["parts"] = {
        **INDEX["parts"],
        "xc7s25csga324-1": {"generated": True, "chipdb": "chipdb-xc7s25.bin"},
    }
    tgz = make_toolchain(tmp_path, index)
    index_file = tmp_path / "XILINX-PARTS-INDEX.json"
    index_file.write_text(json.dumps(index))
    with pytest.raises(AssertionError):
        build.build_package(
            "linux-x86-64", tgz, index_file, BUILD_INFO, tmp_path / "_packages"
        )
