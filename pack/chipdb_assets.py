"""Write XILINX-PARTS-INDEX.json from a stamped chipdb directory.

The document describes every part the packaged prjxray database knows
about. It travels twice under one name, ``XILINX-PARTS-INDEX.json``: as a
release asset and at the root of every platform package. Schema 8 ships
the chipdb files inside the package, so this module writes the index
only. The per-die ``.bin.tgz`` assets belonged to schema 7 and earlier.

The format itself (schema, key order, validation) lives in
``pack.parts_index``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .families import die_of, family_of
from .parts_index import (ENTRY_KEYS, INDEX_ASSET, NOTE, SCHEMA,
                          chipdb_name, release_tag)

# Name of the identity stamp inside a chipdb directory (pack.chipdb owns it;
# repeated here to keep this module importable on its own).
STAMP = "chipdb-id.txt"


def database_parts(database: Path) -> dict[str, dict]:
    """Every part the packaged prjxray database has a part.yaml for.

    The directory name IS the part in Vivado's naming
    (``xc7a200tfbg484-3``): base part plus speed grade. Directories
    without a speed suffix are the die (``xc7a200t``), not a part, and
    carry no part.yaml of their own -- they are skipped rather than
    guessed at. Returns {part: {family, base-part, speed}}, part-sorted.
    """
    if not database.is_dir():
        raise ValueError(f"prjxray-db directory not found: {database}")

    result: dict[str, dict] = {}
    for family_dir in sorted(path for path in database.iterdir()
                             if path.is_dir()):
        for part_yaml in family_dir.glob("*/part.yaml"):
            part = part_yaml.parent.name
            if "-" not in part:
                continue
            base_part, speed = part.rsplit("-", 1)
            mapped_family = family_of(base_part)
            if mapped_family != family_dir.name:
                raise ValueError(
                    f"database family mismatch for {part}: "
                    f"directory {family_dir.name}, mapping {mapped_family}"
                )
            result[part] = {
                "family": family_dir.name,
                "base-part": base_part,
                "speed": speed,
            }
    return dict(sorted(result.items()))


def build_index(repo: Path, chipdb: Path, output: Path, date: str,
                database: Path) -> Path:
    """Write the parts index that names each built part's chipdb file.

    ``chipdb`` must hold the manifest bins and ``chipdb-id.txt``. The
    document is the only file written into ``output``.
    """
    stamp_file = chipdb / STAMP
    if not stamp_file.is_file():
        raise ValueError(f"{chipdb} has no {STAMP} (unstamped set)")

    manifest = json.loads((repo / "chipdb-parts.json").read_text(
        encoding="utf-8"))
    inventory = database_parts(database)
    known_base_parts = {entry["base-part"] for entry in inventory.values()}
    output.mkdir(parents=True, exist_ok=True)
    stamp = stamp_file.read_text(encoding="utf-8").strip()

    # The manifest parts of a die share its chipdb file. Every one of
    # those files has to be in the directory the packages will ship.
    manifest_base_parts = set()
    dies = set()
    for declared_family, base_parts in manifest.items():
        for base_part in base_parts:
            family = family_of(base_part)
            if family != declared_family:
                raise ValueError(
                    f"manifest family mismatch for {base_part}: "
                    f"declared {declared_family}, mapping {family}"
                )
            if base_part not in known_base_parts:
                raise ValueError(
                    "manifest part not present in packaged prjxray-db: "
                    f"{base_part}"
                )
            source = chipdb / chipdb_name(base_part)
            if not source.is_file():
                raise ValueError(f"manifest part without bin: {source}")
            manifest_base_parts.add(base_part)
            dies.add(die_of(base_part))

    # One entry per part of the database, part-sorted, with the keys of an
    # entry always in the same order. A part is built when its base part
    # is in the manifest -- the parts L1 routes -- and the parts of a die
    # repeat its chipdb file name on purpose: which parts share a file is
    # ours to change, and the index is what hides it.
    parts_doc = {}
    for part, meta in inventory.items():
        entry = dict(meta)
        entry["generated"] = meta["base-part"] in manifest_base_parts
        if entry["generated"]:
            entry["chipdb"] = chipdb_name(meta["base-part"])
        parts_doc[part] = {key: entry[key] for key in ENTRY_KEYS
                           if key in entry}

    info = {
        "schema": SCHEMA,
        "date": date,
        "release-tag": release_tag(date),
        "chipdb-id": stamp,
        "part-count": len(parts_doc),
        "generated-count": sum(1 for entry in parts_doc.values()
                               if entry["generated"]),
        "chipdb-count": len(dies),
        "base-part-count": len(known_base_parts),
        "note": NOTE,
        "parts": parts_doc,
    }
    info_path = output / INDEX_ASSET
    info_path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(
        f"parts index: {info_path.name} "
        f"({info['generated-count']} of {info['part-count']} parts built, "
        f"from {info['chipdb-count']} chipdb files, "
        f"chipdb-id {stamp})"
    )
    return info_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write XILINX-PARTS-INDEX.json from a stamped chipdb directory.")
    parser.add_argument("repo", type=Path)
    parser.add_argument("chipdb", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("date")
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    try:
        build_index(args.repo, args.chipdb, args.output, args.date,
                    args.database)
    except ValueError as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
