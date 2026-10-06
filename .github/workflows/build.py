"""A Python script update in-place a directory with the upstream package
to become the downstream Apio package. It is called from the
build-pre-release.yaml workflow which does the unpacking of the upstream
package and the packing of the downstream package.
"""

# TODO: Fix "size" field in fpga entries.

import os
from typing import Any
import json
import argparse
from pathlib import Path

# -- Files that must exist in each package. On windows, fasm2frames is a
# -- .cmd launcher, which needs no executable bit.
REQUIRED_FILES = {
    "darwin-arm64": [
        "bin/nextpnr-xilinx",
        "bin/fasm2frames",
        "bin/xc7frames2bit",
    ],
    "linux-x86-64": [
        "bin/nextpnr-xilinx",
        "bin/fasm2frames",
        "bin/xc7frames2bit",
    ],
    "windows-amd64": [
        "bin/nextpnr-xilinx.exe",
        "bin/fasm2frames.cmd",
        "bin/xc7frames2bit.exe",
    ],
}

# -- The parts index schema apio reads.
EXPECTED_UPSTREAM_SCHEMA = 8


def check_package_files(platform_id: str, package_dir: Path) -> None:
    """Check that the main tools exist and are executable."""
    print("*** In check_package_files()")

    for name in REQUIRED_FILES[platform_id]:
        file_path = package_dir / name
        print(f"Checking: {file_path}")
        assert file_path.is_file(), file_path
        if not name.endswith(".cmd"):
            assert os.access(file_path, os.X_OK), file_path


def write_build_info_file(
    platform_id: str, build_info_json: Path, package_dir: Path
) -> None:
    """Write BUILD-INFO.json in the package."""
    print("*** In write_build_info_file()")

    # -- Construct our own build info
    print(f"Reading file {str(build_info_json)}")
    build_info = json.loads(build_info_json.read_text(encoding="utf-8"))
    build_info["platform"] = platform_id

    # -- Delete the upstream build info from the package
    build_info_path = package_dir / "BUILD-INFO.json"
    print(f"Deleting file {str(build_info_path)}")
    build_info_path.unlink()

    # -- Write the build info
    print(f"Writing file {str(build_info_path)}")
    with build_info_path.open("w") as f:
        json.dump(build_info, f, indent=2)
        f.write("\n")


def write_parts_index(
    build_info_json: Path, package_dir: Path, upstream_inventory_json: Path
) -> None:
    """Write a XILINX-PARTS-INDEX.json in the package, based on the upstream
    XILINX-PARTS-INVENTORY.json."""

    # pylint: disable=too-many-locals

    print("*** In write_parts_index()")

    # -- Read the upstream parts inventory file.
    print(f"Reading file {str(upstream_inventory_json)}")
    upstream_inventory: dict[str, Any] = json.loads(
        upstream_inventory_json.read_text(encoding="utf-8")
    )

    # -- Extract information from the build info
    print(f"Reading file {str(build_info_json)}")
    build_info = json.loads(build_info_json.read_text(encoding="utf-8"))
    release_tag = (build_info["release-tag"],)
    yosys_release_tag = (build_info["yosys-release-tag"],)

    # -- Check that we understand the schema
    assert upstream_inventory["schema"] == EXPECTED_UPSTREAM_SCHEMA, upstream_inventory[
        "schema"
    ]

    # -- Construct the parts entries based on the upstream repository.
    generated_count = 0
    non_generated_count = 0
    parts_dict: dict[str, dict] = {}
    for part_id, part_info in upstream_inventory["parts"].items():
        assert isinstance(part_id, str)

        # -- Determine if this part is generated.
        is_generated: bool = part_info["generated"]
        assert isinstance(is_generated, bool)
        if is_generated:
            generated_count += 1
        else:
            non_generated_count += 1

        # -- Add entry
        part_entry = {
            "generated": is_generated,
            # --
            "definition": {
                "part-num": part_info["part-num"],
                "arch": "xilinx",
                "size": "???",  # MISSING VALUE
                "xilinx-params": {
                    "yosys-family": part_info["family"],
                    "yosys-arch": "xc7",
                    "yosys-part": part_id,
                    "speed": part_info["speed"],
                },
            },
        }
        parts_dict[part_id.lower()] = part_entry

    # -- Sanity check that we generate a sufficient number of parts.
    print(f"Generated: {generated_count} of {len(parts_dict)} parts.")
    assert generated_count > 100, generated_count

    # -- Construct the parts index dict.
    parts_index = {
        "schema": 10,
        "arch": "xilinx",
        "release-tag": release_tag,
        "yosys-release-tag": yosys_release_tag,
        "total": len(parts_dict),
        "generated": generated_count,
        "non-generated": non_generated_count,
        "parts": parts_dict,
    }

    # -- Write the parts index to the package.
    index_path = package_dir / "XILINX-PARTS-INDEX.json"
    print(f"Writing file {str(index_path)}")
    with index_path.open("w") as f:
        json.dump(parts_index, f, indent=2)
        f.write("\n")


def main():
    """Builds the apio openxc7 package for one platform."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-id", choices=REQUIRED_FILES.keys(), required=True)
    parser.add_argument("--build-info-json", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--upstream-inventory-json", type=Path, required=True)
    args = parser.parse_args()

    # -- Sanity check the upstream package.
    check_package_files(
        args.platform_id,
        args.package_dir,
    )

    # -- Write BUILD-INFO.json in the package.
    write_build_info_file(
        args.platform_id,
        args.build_info_json,
        args.package_dir,
    )

    # -- Write XILINX-PARTS-INDEX.json to the package.
    write_parts_index(
        args.build_info_json,
        args.package_dir,
        args.upstream_inventory_json,
    )

    # -- All done.
    print("All done OK")


if __name__ == "__main__":
    main()
