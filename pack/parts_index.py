"""PARTS-INDEX.json: the map from a part number to its chipdb file.

Every package carries this document at its root, and the release
publishes the same bytes under the same name. It is what apio's on-demand
loader reads: given the part a board is built for, it says which chipdb
file that part needs, which release asset carries it and what must end
up on disk.

The naming is Vivado's. ``xc7a200t`` is the device, ``fbg484`` the
package and ``3`` the speed grade; ``xc7a200tfbg484-3`` is the **part**
and ``xc7a200tfbg484`` its **base part**. The index is keyed by the part,
because which parts share a chipdb file is an implementation detail of
this repository (apio#947): today one file serves every speed grade of a
base part, and if that ever changes only this document does.

This module owns the format (schema, note, asset names) and validates it:
``pack.chipdb_assets`` writes the document, L1 checks a package against
the bins it describes, and scripts/asset-check.sh checks a published
release against it -- one validator, three callers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .families import family_of

SCHEMA = 5

# Keys an entry has only when this release built the part's chipdb. Each
# name says WHAT it describes -- the chipdb file that must end up on disk,
# or the asset downloaded to get it (apio#947, which is why schema is 5).
GENERATED_KEYS = ("chipdb", "chipdb-size", "chipdb-sha256",
                  "asset", "asset-size", "asset-sha256")

# Order of the keys inside one entry, as a reader of the JSON sees them.
ENTRY_KEYS = ("family", "base-part", "speed", "generated") + GENERATED_KEYS

NOTE = (
    "Keyed by the full part number, <base-part>-<speed>, in Vivado's "
    "naming: device xc7a200t + package fbg484 = base part xc7a200tfbg484, "
    "speed grade 3, part xc7a200tfbg484-3. An entry with generated=true "
    "is built for THIS release: download <asset> from the release named "
    "by release-tag and leave <chipdb> in the package's chipdb/ "
    "directory. chipdb-size/chipdb-sha256 describe that uncompressed "
    "chipdb file (what must end up on disk); asset-size/asset-sha256 "
    "describe the downloaded asset, a tar.gz carrying the file at its "
    "root. The speed grades of one base part deliberately repeat chipdb, "
    "asset and hashes: one file serves them all today, so 'already on "
    "disk with that sha256' is the only deduplication a loader needs, "
    "and a future release may split them without any change outside this "
    "document. family is the "
    "prjxray database directory the part lives in "
    "($PRJXRAY_DB_DIR/<family>/<part>/part.yaml). An entry with "
    "generated=false is a part the packaged database supports that this "
    "release did not build: supported, not available for download. A "
    "chipdb file is only valid with the openxc7 package of the SAME "
    "release tag; chipdb-id is the identity stamp of the set."
)

# The one name the document travels under, at the root of every package
# AND as the release asset: it says which release it belongs to inside
# itself (release-tag), which is what a reader has to check anyway, so a
# dated file name only repeated it less reliably. Published this way since
# apio#990, like SHA256SUMS; pack.chipdb_assets writes the file, and
# scripts/asset-check.sh fetches a release by this same name.
PACKAGE_FILE = "PARTS-INDEX.json"
INDEX_ASSET = PACKAGE_FILE

# The name the asset carried until the 2026-08-31 release. Releases
# published before the rename are still checked and installed from, and
# apio's loader looks for both names, so the reader side keeps this one.
PREVIOUS_INDEX_ASSET = "apio-xilinx-parts-index-{date}.json"


def release_tag(date: str) -> str:
    """The release tag a YYYYMMDD asset date comes from (apio's rule)."""
    if len(date) != 8 or not date.isdigit():
        raise ValueError(f"asset date must be YYYYMMDD: {date!r}")
    return f"{date[:4]}-{date[4:6]}-{date[6:]}"


def asset_name(base_part: str, date: str) -> str:
    """Release asset carrying one base part's chipdb, for a given date."""
    return f"apio-xilinx-chipdb-{base_part}-{date}.bin.tgz"


def chipdb_name(base_part: str) -> str:
    """Chipdb file name of a base part: what apio leaves in chipdb/."""
    return f"{base_part}.bin"


def previous_index_asset_name(date: str) -> str:
    """Name the document was published under before apio#990."""
    release_tag(date)          # rejects a date that is not YYYYMMDD
    return PREVIOUS_INDEX_ASSET.format(date=date)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_entry(part: str, entry: dict, date: str) -> None:
    """Check one part entry on its own."""
    if not isinstance(entry, dict):
        raise ValueError(f"PARTS-INDEX entry for {part} must be an object")
    base = entry.get("base-part")
    speed = entry.get("speed")
    if not isinstance(base, str) or not isinstance(speed, str):
        raise ValueError(
            f"PARTS-INDEX entry for {part} has no base-part/speed")
    if part != f"{base}-{speed}":
        raise ValueError(
            f"PARTS-INDEX: {part} is not {base}-{speed} (the key IS the part)")
    if entry.get("family") != family_of(base):
        raise ValueError(f"PARTS-INDEX entry for {part} has the wrong family")
    if not isinstance(entry.get("generated"), bool):
        raise ValueError(f"PARTS-INDEX entry for {part} has no generated flag")
    if not entry["generated"]:
        # A part nobody can download must not look downloadable.
        extra = [key for key in GENERATED_KEYS if key in entry]
        if extra:
            raise ValueError(
                f"PARTS-INDEX: {part} is not generated but carries {extra}")
        return
    for key in GENERATED_KEYS:
        if key not in entry:
            raise ValueError(f"PARTS-INDEX: generated {part} has no {key}")
    if entry["chipdb"] != chipdb_name(base):
        raise ValueError(
            f"PARTS-INDEX: {part} chipdb {entry['chipdb']!r} is not the file "
            f"apio leaves in chipdb/ for {base} ({chipdb_name(base)})")
    if entry["asset"] != asset_name(base, date):
        raise ValueError(
            f"PARTS-INDEX: {part} asset {entry['asset']!r} is not the "
            f"name apio resolves for {date} ({asset_name(base, date)})")
    for key in ("chipdb-size", "asset-size"):
        if not isinstance(entry[key], int) or entry[key] <= 0:
            raise ValueError(f"PARTS-INDEX: {part} has an invalid {key}")
    for key in ("chipdb-sha256", "asset-sha256"):
        value = entry[key]
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"PARTS-INDEX: {part} has an invalid {key}")


def validate_document(info: dict, expect_tag: str | None = None) -> dict:
    """Check the document on its own; return the generated entries by part.

    *expect_tag* is the release the document was actually found in. A
    document naming another tag sends apio's loader to assets that live
    somewhere else -- the class of failure a release gate must catch, and
    the one a run crossing midnight UTC would produce.
    """
    if info.get("schema") != SCHEMA:
        raise ValueError(
            f"PARTS-INDEX schema is {info.get('schema')!r}, expected {SCHEMA}")
    date = info.get("date")
    if not isinstance(date, str):
        raise ValueError("PARTS-INDEX has no date")
    try:
        expected_tag = release_tag(date)
    except ValueError as error:
        raise ValueError(f"PARTS-INDEX {error}") from error
    if info.get("release-tag") != expected_tag:
        raise ValueError(
            f"PARTS-INDEX release-tag {info.get('release-tag')!r} does not "
            f"match date {date} (apio derives the date from the tag)")
    if expect_tag is not None and info["release-tag"] != expect_tag:
        raise ValueError(
            f"PARTS-INDEX release-tag {info['release-tag']!r} is not the "
            f"release it was published in ({expect_tag})")
    if not info.get("chipdb-id"):
        raise ValueError("PARTS-INDEX has no chipdb-id")

    parts = info.get("parts")
    if not isinstance(parts, dict) or not parts:
        raise ValueError("PARTS-INDEX parts must be a non-empty object")

    generated = {}
    for part, entry in parts.items():
        _check_entry(part, entry, date)
        if entry["generated"]:
            generated[part] = entry

    # The speed grades of one base part share a chipdb file, so they must
    # promise the same bytes. Divergence here would have a loader fetch
    # one file and check it against another's hash.
    by_base: dict = {}
    for part, entry in generated.items():
        promise = tuple(entry[key] for key in GENERATED_KEYS)
        first = by_base.setdefault(entry["base-part"], (part, promise))
        if first[1] != promise:
            raise ValueError(
                f"PARTS-INDEX: {part} and {first[0]} share base part "
                f"{entry['base-part']} but describe different files")

    chipdb_files = {entry["chipdb"] for entry in generated.values()}
    base_parts = {entry["base-part"] for entry in parts.values()}
    for key, expected in (("part-count", len(parts)),
                          ("generated-count", len(generated)),
                          ("chipdb-count", len(chipdb_files)),
                          ("base-part-count", len(base_parts))):
        if info.get(key) != expected:
            raise ValueError(
                f"PARTS-INDEX {key} {info.get(key)!r} != {expected}")
    return generated


def validate_package_info(info_path: Path, chipdb: Path) -> dict:
    """Validate the document and the chipdb files it describes.

    *chipdb* is the directory that must hold exactly the generated chipdb
    files: the package's own chipdb/ in a package that ships them, or the
    directory apio's loader downloads into. Returns the document counts.
    """
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read PARTS-INDEX: {error}") from error

    generated = validate_document(info)

    # Several parts point at the same file: compare the SET of files.
    described = {entry["chipdb"]: entry for entry in generated.values()}
    present = sorted(path.name for path in chipdb.glob("*.bin"))
    if sorted(described) != present:
        raise ValueError(
            "PARTS-INDEX generated chipdb files do not match the bins in "
            f"{chipdb}: index={sorted(described)}, bins={present}")
    for name in present:
        path = chipdb / name
        entry = described[name]
        if entry["chipdb-size"] != path.stat().st_size:
            raise ValueError(f"PARTS-INDEX chipdb-size differs for {name}")
        if entry["chipdb-sha256"] != _sha256(path):
            raise ValueError(f"PARTS-INDEX chipdb-sha256 differs for {name}")
    return {key: info[key] for key in ("part-count", "generated-count",
                                       "chipdb-count", "base-part-count")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("index", type=Path)
    parser.add_argument("chipdb", type=Path)
    args = parser.parse_args()
    try:
        counts = validate_package_info(args.index, args.chipdb)
    except ValueError as error:
        parser.exit(1, f"error: {error}\n")
    print(f"PARTS-INDEX: {counts['part-count']} parts "
          f"({counts['base-part-count']} base parts) of the packaged "
          f"database, {counts['generated-count']} of them built by this "
          f"release from {counts['chipdb-count']} chipdb files, which "
          f"match the ones in {args.chipdb}")


if __name__ == "__main__":
    main()
