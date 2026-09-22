"""Family and die handling: the part-name rules and the parts manifest.

The manifest ``chipdb-parts.json`` is the single source of truth for the
chipdb parts (family -> footprints), shared with nix/windows/default.nix
and the CI assertions. Each part routes on the chipdb of its die
(``die_of``): several parts of the manifest share one chipdb file.
"""

import json
import re
from pathlib import Path

# -- Manifest with the list of parts to package
CHIPDB_PARTS_FILE = "chipdb-parts.json"

# -- The device at the start of a 7-series part name: xc7a100t, xc7vx485t,
# -- xc7s25, xc7z010. Artix, Kintex and Virtex devices end in 't';
# -- Spartan-7 and Zynq-7000 ones do not.
_DEVICE = re.compile(r"^(xc7(?:a|k|vx|v)\d+t|xc7[sz]\d+)")

# -- Devices that are another device's die, as prjxray-db's
# -- <family>/mapping/devices.yaml maps them to a fabric: an xc7a35t is an
# -- xc7a50t die, and it routes on the xc7a50t chipdb. flake.nix carries
# -- the only other copy of this table (dieOf); pack/chipdb.py checks it
# -- against the database the chipdb files are generated from.
DIE_ALIASES = {
    "xc7a35t": "xc7a50t",
    "xc7s75": "xc7s100",
    "xc7z035": "xc7z045",
}


def family_of(part: str) -> str:
    """Family of a 7-series part, derived from its name prefix.

    Same rule (and same order) as the shell copy in e2e/run-parts.sh and
    as the uarch's own CMakeLists, which maps a die to its prjxray-db
    directory the same way. An unknown prefix is an error: a part reached
    the packer that no family can claim.
    """
    for prefix, family in (
        ("xc7a", "artix7"),
        ("xc7k", "kintex7"),
        ("xc7s", "spartan7"),
        ("xc7z", "zynq7"),
        ("xc7v", "virtex7"),
    ):
        if part.startswith(prefix):
            return family
    raise ValueError(f"unknown 7-series family for part '{part}'")


def device_of(part: str) -> str:
    """Device of a 7-series part: xc7a35tcsg324 -> xc7a35t."""
    match = _DEVICE.match(part)
    if not match:
        raise ValueError(f"no 7-series device in part name '{part}'")
    return match.group(1)


def die_of(part: str) -> str:
    """Die of a 7-series part: the fabric its chipdb describes.

    The device, unless the database says that device is another one's die
    (DIE_ALIASES): xc7a100tcsg324 -> xc7a100t, xc7a35tcpg236 -> xc7a50t.
    Every part of a die routes on that die's chipdb, whatever its package
    or speed grade.
    """
    device = device_of(part)
    return DIE_ALIASES.get(device, device)


def chipdb_parts() -> list:
    """List [(family, part), ...] read from the manifest."""
    manifest = Path.cwd() / CHIPDB_PARTS_FILE
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return [(family, part)
            for family, parts in data.items()
            for part in parts]


def families() -> list:
    """Families present in the manifest, deduplicated, in manifest order.

    Derived from the part names with family_of() so the copies that used
    to hardcode 'artix7' (prjxray-db, nextpnr-xilinx-meta) iterate exactly
    the families the manifest asks for. With the current artix7-only
    manifest this returns ['artix7'] and the behavior is unchanged.
    """
    seen = []
    for _, part in chipdb_parts():
        family = family_of(part)
        if family not in seen:
            seen.append(family)
    return seen


def chipdb_dies() -> list:
    """List [(family, die), ...] of the manifest, each die once.

    One chipdb file per die: this is the list of files to generate. In
    manifest order, each die where its first part appears.
    """
    seen = []
    for family, part in chipdb_parts():
        entry = (family, die_of(part))
        if entry not in seen:
            seen.append(entry)
    return seen
