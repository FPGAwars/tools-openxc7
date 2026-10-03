"""A Python script to build the openxc7 package for a given platform."""

# This script is called from the github build workflow and runs in the top
# dir of this repo. The openXC7 toolchain release it repackages is named in
# the build info (openxc7-toolchain-repo, openxc7-toolchain-release-tag).
# The workflow has already downloaded the release's SHA256SUMS and
# XILINX-PARTS-INDEX.json to ./_upstream; this script downloads the platform
# tarball there too and writes the apio package to ./_packages.

import os
import json
import hashlib
import subprocess
import shutil
import argparse
import urllib.request
from pathlib import Path
from typing import Dict, List

# -- Files that must exist in each package. On windows, fasm2frames is a
# -- .cmd launcher, which needs no executable bit.
REQUIRED_FILES = {
    "darwin-arm64": ["bin/nextpnr-xilinx", "bin/fasm2frames", "bin/xc7frames2bit"],
    "linux-x86-64": ["bin/nextpnr-xilinx", "bin/fasm2frames", "bin/xc7frames2bit"],
    "windows-amd64": [
        "bin/nextpnr-xilinx.exe",
        "bin/fasm2frames.cmd",
        "bin/xc7frames2bit.exe",
    ],
}

# -- The parts index schema apio reads.
EXPECTED_INDEX_SCHEMA = 8

# -- Where nextpnr-xilinx finds its chipdb files.
CHIPDB_DIR = "share/nextpnr/himbaechel/xilinx"


def run(cmd_args: List[str]) -> None:
    """Run a command and check that it succeeded."""
    print(f"\nRun: {cmd_args}", flush=True)
    subprocess.run(cmd_args, check=True)


def upstream_file_name(platform_id: str, release_tag: str) -> str:
    """The toolchain tarball, e.g. openxc7-toolchain-linux-x86-64-20260930.tgz"""
    return f"openxc7-toolchain-{platform_id}-{release_tag.replace('-', '')}.tgz"


def package_file_name(platform_id: str, release_tag: str) -> str:
    """The apio package, e.g. apio-openxc7-linux-x86-64-20261001.tgz"""
    return f"apio-openxc7-{platform_id}-{release_tag.replace('-', '')}.tgz"


def read_sha256sums(sums_file: Path) -> Dict[str, str]:
    """Parse a SHA256SUMS file into {file name: sha256}."""
    sums = {}
    for line in sums_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            sha, name = line.split()
            sums[name.lstrip("*")] = sha
    return sums


def check_sha256(file_path: Path, sums_file: Path) -> None:
    """Check a downloaded file against the release's SHA256SUMS."""
    expected = read_sha256sums(sums_file)[file_path.name]
    actual = hashlib.sha256(file_path.read_bytes()).hexdigest()
    print(f"sha256 {file_path.name}: {actual}")
    assert actual == expected, f"{file_path.name}: sha256 {actual} != {expected}"


def check_package_files(package_dir: Path, platform_id: str) -> None:
    """Check that the main tools exist and are executable."""
    for name in REQUIRED_FILES[platform_id]:
        file_path = package_dir / name
        print(f"Checking: {file_path}")
        assert file_path.is_file(), file_path
        if not name.endswith(".cmd"):
            assert os.access(file_path, os.X_OK), file_path


def check_parts_index(package_dir: Path, index_file: Path) -> None:
    """Check that the package's parts index is the release's one, that it
    is the schema apio reads, and that the chipdb files are in the
    directory where nextpnr-xilinx looks for them."""
    package_index = package_dir / "XILINX-PARTS-INDEX.json"
    assert package_index.read_bytes() == index_file.read_bytes(), package_index

    index = json.loads(index_file.read_text(encoding="utf-8"))
    assert index["schema"] == EXPECTED_INDEX_SCHEMA, index["schema"]

    # -- The chipdb files are in the engine's default directory, so apio
    # -- runs nextpnr-xilinx without --chipdb.
    assert not (package_dir / "chipdb").exists(), f"chipdb/ found, expected {CHIPDB_DIR}"
    chipdb_files = list((package_dir / CHIPDB_DIR).glob("chipdb-*.bin"))
    assert chipdb_files, f"no chipdb files in {CHIPDB_DIR}"
    print(f"Parts index: schema {index['schema']}, {len(chipdb_files)} chipdb files")


def build_package(
    platform_id: str,
    upstream_tgz: Path,
    index_file: Path,
    build_info: dict,
    packages_dir: Path,
) -> Path:
    """Repackage one toolchain tarball as the apio openxc7 package.
    Returns the path of the new package file."""

    package_filename = package_file_name(platform_id, build_info["release-tag"])
    package_dir = packages_dir / platform_id
    package_dir.mkdir(parents=True)

    # -- Extract the toolchain as is.
    run(["tar", "xzf", str(upstream_tgz), "-C", str(package_dir)])

    # -- Keep the toolchain's own build info: it says where the
    # -- binaries come from.
    (package_dir / "BUILD-INFO.json").rename(package_dir / "TOOLCHAIN-BUILD-INFO.json")

    # -- Write the apio build info.
    package_build_info = dict(build_info)
    package_build_info["target-platform"] = platform_id
    package_build_info["file-name"] = package_filename
    with (package_dir / "BUILD-INFO.json").open("w", encoding="utf-8") as f:
        json.dump(package_build_info, f, indent=2)
        f.write("\n")

    check_package_files(package_dir, platform_id)
    check_parts_index(package_dir, index_file)

    # -- Compress the package, with the same layout as the toolchain
    # -- tarball (apio extracts it into packages/openxc7).
    package_file = packages_dir / package_filename
    run(["tar", "czf", str(package_file), "-C", str(package_dir), "."])

    # -- Delete the package dir (large).
    shutil.rmtree(package_dir)
    return package_file


def main():
    """Builds the apio openxc7 package for one platform."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--platform_id", required=True, choices=REQUIRED_FILES)
    parser.add_argument("--build-info-json", required=True, type=Path)
    args = parser.parse_args()

    build_info = json.loads(args.build_info_json.read_text(encoding="utf-8"))
    print(json.dumps(build_info, indent=2))

    upstream_dir = Path("_upstream")
    upstream_repo = build_info["openxc7-toolchain-repo"]
    upstream_tag = build_info["openxc7-toolchain-release-tag"]

    # -- Download the toolchain tarball and check it.
    upstream_tgz = upstream_dir / upstream_file_name(args.platform_id, upstream_tag)
    url = (
        f"https://github.com/{upstream_repo}/releases/download/"
        f"{upstream_tag}/{upstream_tgz.name}"
    )
    print(f"\nDownloading {url}", flush=True)
    urllib.request.urlretrieve(url, upstream_tgz)
    check_sha256(upstream_tgz, upstream_dir / "SHA256SUMS")

    package_file = build_package(
        args.platform_id,
        upstream_tgz,
        upstream_dir / "XILINX-PARTS-INDEX.json",
        build_info,
        Path("_packages"),
    )

    # -- Delete the toolchain tarball (large).
    upstream_tgz.unlink()
    print(f"\nCreated {package_file}")


if __name__ == "__main__":
    main()
