"""A Python script update in-place a directory with the upstream package
to become the downstream Apio package. It is called from the
build-pre-release.yaml workflow which does the unpacking of the upstream
package and the packing of the downstream package.
"""

import os
import re
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

# -- The prjxray database and the chipdb files, within the package.
DATABASE_DIR = "share/nextpnr/external/prjxray-db"
CHIPDB_DIR = "share/nextpnr/himbaechel/xilinx"

# -- The --device pattern of nextpnr-xilinx, verbatim from
# -- XilinxImpl::init_database() in himbaechel/uarch/xilinx/xilinx.cc
# -- (openXC7/nextpnr 62eff1cd). Groups: device, package, speed grade.
NEXTPNR_DEVICE = re.compile(
    r"(xc7z007s|xc7z012s|xc7z014s|xc7[azks]\d+t?|xc7vx\d+t?)"
    r"([a-z0-9]*)(?:-(1IL|1Q|2L|[123]))?"
)

# -- Size label of the Zynq devices: their Programmable Logic Cells in
# -- DS190 (v1.11.1) "Zynq-7000 SoC Data Sheet: Overview", Table 1. The
# -- other devices name their size (xc7a35t -> 35k).
ZYNQ_SIZE = {
    "xc7z007s": "23k",
    "xc7z012s": "55k",
    "xc7z014s": "65k",
    "xc7z010": "28k",
    "xc7z015": "74k",
    "xc7z020": "85k",
    "xc7z030": "125k",
    "xc7z035": "275k",
    "xc7z045": "350k",
    "xc7z100": "444k",
}


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


def read_devices_yaml(devices_yaml: Path) -> dict[str, str]:
    """Read a prjxray-db mapping/devices.yaml, a flat list of '"<device>":'
    lines, each followed by a '  fabric: "<die>"' line. Returns {device: die}.
    """
    fabrics = {}
    device = ""
    for line in devices_yaml.read_text(encoding="utf-8").splitlines():
        if line.startswith('"'):
            device = line.strip('":')
        elif line.strip().startswith("fabric:"):
            assert device, line
            fabrics[device] = line.split(":")[1].strip(' "')
    return fabrics


def fpga_size(device: str) -> str:
    """The size label of a device, e.g. 35k for xc7a35t."""
    if device.startswith("xc7z"):
        return ZYNQ_SIZE[device]
    match = re.fullmatch(r"xc7[a-z]+(\d+)t?", device)
    assert match, device
    return f"{match[1]}k"


def xilinx_parts(package_dir: Path) -> tuple[dict[str, dict], list[str]]:
    """Generate the xilinx fpga definitions from the prjxray database and
    the chipdb files in the package. A part is listed if the database has
    its directory, the package has the chipdb file of its die, and nextpnr
    accepts its name.
    """

    # pylint: disable=too-many-locals

    chipdbs = (package_dir / CHIPDB_DIR).glob("chipdb-*.bin")
    dies = {p.stem.removeprefix("chipdb-") for p in chipdbs}

    skipped = []
    parts = {}
    database_dir = package_dir / DATABASE_DIR
    for devices_yaml in sorted(database_dir.glob("*/mapping/devices.yaml")):
        family_dir = devices_yaml.parent.parent
        fabrics = read_devices_yaml(devices_yaml)

        # -- Each part has a <base-part>-<speed> directory with a part.yaml.
        for part_yaml in sorted(family_dir.glob("*-*/part.yaml")):
            part_id = part_yaml.parent.name
            fpga_id = part_id.lower()

            # -- Skip the parts we can't build.
            match = NEXTPNR_DEVICE.fullmatch(part_id)
            if not match or fabrics.get(match[1]) not in dies:
                print(f"skipping non buildable fpga: {fpga_id}")
                skipped.append(fpga_id)
                continue

            # -- Add fpga definition
            device, package, speed = match.groups()
            parts[fpga_id] = {
                "arch": "xilinx",
                "vendor-part": f"{device}-{speed}{package}".upper(),
                "size": fpga_size(device),
                "xilinx-params": {
                    "yosys-arch": "xc7",
                    "yosys-family": family_dir.name,
                    "nextpnr-device": part_id,
                },
            }
    return (parts, skipped)


def write_fpgas_definitions_file(package_dir: Path) -> None:
    """Write a FPGAS.jsonc in the package, based on the prjxray database
    and the chipdb files the package carries.
    """

    print("*** In write_parts_index()")

    # -- Construct the parts entries based on the package files.
    fpgas_dict, skipped = xilinx_parts(package_dir)

    # -- Sanity check that we generate a sufficient number of parts.
    print(f"Generated: {len(fpgas_dict)}, skipped {len(skipped)} parts.")
    assert len(fpgas_dict) > 100, len(fpgas_dict)

    prefix_lines = [
        "// Automatically generated, do not edit!",
        "// Base FPGAs definitions for the Apio's 'xilinx' architecture.",
        "//",
        "// xilinx:",
        f"//   Generated :  {len(fpgas_dict)}",
        f"//   Skipped   :  {len(skipped)}",
    ]

    for fpga_id in skipped:
        prefix_lines.append(f"//     - {fpga_id}")

    file_text = (
        "\n".join(prefix_lines) + "\n//\n" + json.dumps(fpgas_dict, indent=2) + "\n"
    )

    # -- Write the fpga index to the package.
    file_path = package_dir / "FPGAS.jsonc"
    print(f"Writing file {str(file_path)}")
    with file_path.open("w") as f:
        f.write(file_text)


def main():
    """Builds the apio openxc7 package for one platform."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-id", choices=REQUIRED_FILES.keys(), required=True)
    parser.add_argument("--build-info-json", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path, required=True)
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

    # -- Write FPGAS.jsonc to the package.
    write_fpgas_definitions_file(args.package_dir)

    # -- All done.
    print("All done OK")


if __name__ == "__main__":
    main()
