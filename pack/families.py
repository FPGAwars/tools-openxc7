"""Family handling: the part-name -> family rule and the parts manifest.

The manifest ``chipdb-parts.json`` is the single source of truth for the
chipdb parts (family -> footprints), shared with nix/windows/default.nix
and the CI assertions.
"""

import json
from pathlib import Path

# -- Manifest with the list of parts to package
CHIPDB_PARTS_FILE = "chipdb-parts.json"


def family_of(part: str) -> str:
    """Family of a 7-series part, derived from its name prefix.

    Same rule (and same order) as nix/nextpnr-xilinx-chipdb.nix, the other
    place that maps footprints to families. Unlike the nix script (which
    skips unknown footprints with a warning, because the prjxray-db may
    grow families we do not package), an unknown prefix here is an error:
    a part reached the packer that no family can claim.
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
