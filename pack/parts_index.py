"""XILINX-PARTS-INDEX.json: the map from a part number to its chipdb file.

Every package carries this document at its root, and the release
publishes the same bytes under the same name. It is what apio's on-demand
loader reads: given the part a board is built for, it says which chipdb
file that part needs, which release asset carries it and what must end
up on disk.

The naming is Vivado's. ``xc7a200t`` is the device, ``fbg484`` the
package and ``3`` the speed grade; ``xc7a200tfbg484-3`` is the **part**
and ``xc7a200tfbg484`` its **base part**. The index is keyed by the part,
because which parts share a chipdb file is an implementation detail of
this repository (apio#947): today one file serves every part of a die --
every package and speed grade of the device, and of the devices that are
the same die (an xc7a35t is an xc7a50t) -- and when that changed, from
one file per base part, only this document did.

This module owns the format (schema, note, asset names) and validates it:
``pack.chipdb_assets`` writes the document, L1 checks a package against
the bins it describes, and scripts/asset-check.sh checks a published
release against it -- one validator, three callers.

The schema number is the contract (apio#1071). A package carries one
engine, so a reader asserts the number and already knows the binary and
the command line. Schema 7, which this module emits, is the himbaechel
engine. Schema 6 is the current engine. An entry has no engine field.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .families import die_of, family_of

SCHEMA = 7

# Schema 6 (and 5 before it) is the current engine: one chipdb file per
# base part, command line ``nextpnr-xilinx --chipdb <file> --xdc``.
# Schema 7, which this module emits, is the himbaechel engine installed
# as the same binary: one chipdb file per die, command line
# ``nextpnr-xilinx --device <part> --chipdb <file> -o xdc= -o fasm=
# --report``. The validator accepts only the schema this branch emits.
PER_BASE_PART_SCHEMA = 6

# Keys an entry has only when this release built the part's chipdb. Each
# name says WHAT it describes -- the chipdb file that must end up on disk,
# or the asset downloaded to get it (the apio#947 names, schema 5).
GENERATED_KEYS = ("chipdb", "chipdb-size", "chipdb-sha256",
                  "asset", "asset-size", "asset-sha256")

# Order of the keys inside one entry, as a reader of the JSON sees them.
# The same keys schema 5 published: the schema number, not a field,
# says which engine the file was built for.
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
    "root. The parts of one die -- the speed grades of a base part, and "
    "the packages of the device or of another device on the same die -- "
    "deliberately repeat chipdb, asset and hashes: one file, "
    "chipdb-<die>.bin, serves them all, so 'already on disk with that "
    "sha256' is the only deduplication a loader needs, and a future "
    "release may split or merge them without any change outside this "
    "document. family is the "
    "prjxray database directory the part lives in "
    "($PRJXRAY_DB_DIR/<family>/<part>/part.yaml). An entry with "
    "generated=false is a part the packaged database supports that this "
    "release did not build: supported, not available for download. "
    "schema 6 is the index of the current engine: one chipdb file per "
    "base part, command line nextpnr-xilinx --chipdb <file> --xdc. "
    "schema 7 is the index of the himbaechel engine, installed as the "
    "same nextpnr-xilinx binary: one chipdb file per die "
    "(chipdb-<die>.bin; the entry names the file its part uses), "
    "command line nextpnr-xilinx --device <part> --chipdb <file> "
    "-o xdc= -o fasm= --report. A package carries one engine, so the "
    "schema number is the contract. A "
    "chipdb file is only valid with the openxc7 package of the SAME "
    "release tag; chipdb-id is the identity stamp of the set."
)

# The one name the document travels under, at the root of every package
# AND as the release asset: it says which release it belongs to inside
# itself (release-tag), which is what a reader has to check anyway, so a
# dated file name only repeated it less reliably. Renamed to
# XILINX-PARTS-INDEX.json with apio#1002 (the sibling indices
# ICE40/ECP5/GOWIN-PARTS-INDEX.json get the same shape); published as
# PARTS-INDEX.json from apio#990 until then, like SHA256SUMS.
# pack.chipdb_assets writes the file, and scripts/asset-check.sh fetches
# a release by this same name.
PACKAGE_FILE = "XILINX-PARTS-INDEX.json"
INDEX_ASSET = PACKAGE_FILE

# The names published releases carried before the apio#1002 rename.
# Releases published with either are still checked and installed from,
# and apio's loader accepts every one, so the reader side keeps both:
# the apio#990 name (releases up to the rename) and the dated name the
# asset carried until the 2026-08-31 release.
PREVIOUS_PACKAGE_FILE = "PARTS-INDEX.json"
LEGACY_INDEX_ASSET = "apio-xilinx-parts-index-{date}.json"


def release_tag(date: str) -> str:
    """The release tag a YYYYMMDD asset date comes from (apio's rule)."""
    if len(date) != 8 or not date.isdigit():
        raise ValueError(f"asset date must be YYYYMMDD: {date!r}")
    return f"{date[:4]}-{date[4:6]}-{date[6:]}"


def _as_schema(schema: int) -> int:
    if isinstance(schema, int) and not isinstance(schema, bool):
        return schema
    raise ValueError(f"parts-index schema must be an integer, not {schema!r}")


def _chipdb_unit(base_part: str, schema: int) -> str:
    """What one chipdb file covers under *schema*: the die, or the base part."""
    if schema <= PER_BASE_PART_SCHEMA:
        return base_part
    if schema != SCHEMA:
        raise ValueError(
            f"schema {schema} has no chipdb file names "
            f"(this index emits schema {SCHEMA})")
    return die_of(base_part)


def asset_name(base_part: str, date: str, schema: int = SCHEMA) -> str:
    """Release asset carrying a base part's chipdb, for a given date.

    One per die under schema 7 (every base part of a die names the same
    asset), or one per base part under schema 6.
    """
    number = _as_schema(schema)
    return (f"apio-xilinx-chipdb-{_chipdb_unit(base_part, number)}-"
            f"{date}.bin.tgz")


def chipdb_name(base_part: str, schema: int = SCHEMA) -> str:
    """Chipdb file a base part needs: what apio leaves in chipdb/.

    Schema 7: the file of its die, chipdb-xc7a50t.bin for an
    xc7a35tcsg324. Schema 6: the base part's own, xc7a35tcsg324.bin.
    """
    number = _as_schema(schema)
    unit = _chipdb_unit(base_part, number)
    if number <= PER_BASE_PART_SCHEMA:
        return f"{unit}.bin"
    return f"chipdb-{unit}.bin"


def previous_index_asset_names(date: str) -> list[str]:
    """Names the document was published under before the apio#1002 rename.

    Newest first: the apio#990 name (PARTS-INDEX.json), then the dated
    asset name of the releases up to 2026-08-31.
    """
    release_tag(date)          # rejects a date that is not YYYYMMDD
    return [PREVIOUS_PACKAGE_FILE, LEGACY_INDEX_ASSET.format(date=date)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_entry(part: str, entry: dict, date: str) -> None:
    """Check one part entry on its own."""
    if not isinstance(entry, dict):
        raise ValueError(f"XILINX-PARTS-INDEX entry for {part} must be an object")
    # The index is a contract: a key this schema does not define (the
    # engine field the schema 6 draft carried, for one) is refused, not
    # ignored. apio asserts the schema number and reads these keys only.
    unknown = sorted(key for key in entry if key not in ENTRY_KEYS)
    if unknown:
        kind = "key" if len(unknown) == 1 else "keys"
        raise ValueError(
            f"XILINX-PARTS-INDEX: {part} has unknown {kind} "
            f"{', '.join(unknown)}")
    base = entry.get("base-part")
    speed = entry.get("speed")
    if not isinstance(base, str) or not isinstance(speed, str):
        raise ValueError(
            f"XILINX-PARTS-INDEX entry for {part} has no base-part/speed")
    if part != f"{base}-{speed}":
        raise ValueError(
            f"XILINX-PARTS-INDEX: {part} is not {base}-{speed} (the key IS the part)")
    if entry.get("family") != family_of(base):
        raise ValueError(f"XILINX-PARTS-INDEX entry for {part} has the wrong family")
    if not isinstance(entry.get("generated"), bool):
        raise ValueError(f"XILINX-PARTS-INDEX entry for {part} has no generated flag")
    if not entry["generated"]:
        # A part nobody can download must not look downloadable.
        extra = [key for key in GENERATED_KEYS if key in entry]
        if extra:
            raise ValueError(
                f"XILINX-PARTS-INDEX: {part} is not generated but carries {extra}")
        return
    for key in GENERATED_KEYS:
        if key not in entry:
            raise ValueError(f"XILINX-PARTS-INDEX: generated {part} has no {key}")
    if entry["chipdb"] != chipdb_name(base):
        raise ValueError(
            f"XILINX-PARTS-INDEX: {part} chipdb {entry['chipdb']!r} is not the file "
            f"apio leaves in chipdb/ for {base} ({chipdb_name(base)})")
    if entry["asset"] != asset_name(base, date):
        raise ValueError(
            f"XILINX-PARTS-INDEX: {part} asset {entry['asset']!r} is not the "
            f"name apio resolves for {date} ({asset_name(base, date)})")
    for key in ("chipdb-size", "asset-size"):
        if not isinstance(entry[key], int) or entry[key] <= 0:
            raise ValueError(f"XILINX-PARTS-INDEX: {part} has an invalid {key}")
    for key in ("chipdb-sha256", "asset-sha256"):
        value = entry[key]
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"XILINX-PARTS-INDEX: {part} has an invalid {key}")


def validate_document(info: dict, expect_tag: str | None = None) -> dict:
    """Check the document on its own; return the generated entries by part.

    *expect_tag* is the release the document was actually found in. A
    document naming another tag sends apio's loader to assets that live
    somewhere else -- the class of failure a release gate must catch, and
    the one a run crossing midnight UTC would produce.
    """
    if info.get("schema") != SCHEMA:
        raise ValueError(
            f"XILINX-PARTS-INDEX schema is {info.get('schema')!r}, expected {SCHEMA}")
    date = info.get("date")
    if not isinstance(date, str):
        raise ValueError("XILINX-PARTS-INDEX has no date")
    try:
        expected_tag = release_tag(date)
    except ValueError as error:
        raise ValueError(f"XILINX-PARTS-INDEX {error}") from error
    if info.get("release-tag") != expected_tag:
        raise ValueError(
            f"XILINX-PARTS-INDEX release-tag {info.get('release-tag')!r} does not "
            f"match date {date} (apio derives the date from the tag)")
    if expect_tag is not None and info["release-tag"] != expect_tag:
        raise ValueError(
            f"XILINX-PARTS-INDEX release-tag {info['release-tag']!r} is not the "
            f"release it was published in ({expect_tag})")
    if not info.get("chipdb-id"):
        raise ValueError("XILINX-PARTS-INDEX has no chipdb-id")

    parts = info.get("parts")
    if not isinstance(parts, dict) or not parts:
        raise ValueError("XILINX-PARTS-INDEX parts must be a non-empty object")

    generated = {}
    for part, entry in parts.items():
        _check_entry(part, entry, date)
        if entry["generated"]:
            generated[part] = entry

    # The parts that name one chipdb file -- every part of a die -- must
    # promise the same bytes. Divergence here would have a loader fetch
    # one file and check it against another's hash.
    by_file: dict = {}
    for part, entry in generated.items():
        promise = tuple(entry[key] for key in GENERATED_KEYS)
        first = by_file.setdefault(entry["chipdb"], (part, promise))
        if first[1] != promise:
            raise ValueError(
                f"XILINX-PARTS-INDEX: {part} and {first[0]} share chipdb "
                f"file {entry['chipdb']} but describe different files")

    chipdb_files = {entry["chipdb"] for entry in generated.values()}
    base_parts = {entry["base-part"] for entry in parts.values()}
    for key, expected in (("part-count", len(parts)),
                          ("generated-count", len(generated)),
                          ("chipdb-count", len(chipdb_files)),
                          ("base-part-count", len(base_parts))):
        if info.get(key) != expected:
            raise ValueError(
                f"XILINX-PARTS-INDEX {key} {info.get(key)!r} != {expected}")
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
        raise ValueError(f"cannot read XILINX-PARTS-INDEX: {error}") from error

    generated = validate_document(info)

    # Several parts point at the same file: compare the SET of files.
    described = {entry["chipdb"]: entry for entry in generated.values()}
    present = sorted(path.name for path in chipdb.glob("*.bin"))
    if sorted(described) != present:
        raise ValueError(
            "XILINX-PARTS-INDEX generated chipdb files do not match the bins in "
            f"{chipdb}: index={sorted(described)}, bins={present}")
    for name in present:
        path = chipdb / name
        entry = described[name]
        if entry["chipdb-size"] != path.stat().st_size:
            raise ValueError(f"XILINX-PARTS-INDEX chipdb-size differs for {name}")
        if entry["chipdb-sha256"] != _sha256(path):
            raise ValueError(f"XILINX-PARTS-INDEX chipdb-sha256 differs for {name}")
    return {key: info[key] for key in ("part-count", "generated-count",
                                       "chipdb-count", "base-part-count")}


def _described_files(info: dict) -> dict:
    """{base part: chipdb file} for the parts the document says are built."""
    parts = info.get("parts") or {}
    files = {}
    if isinstance(parts, dict):
        for entry in parts.values():
            if (isinstance(entry, dict) and entry.get("generated")
                    and "base-part" in entry and "chipdb" in entry):
                files[entry["base-part"]] = entry["chipdb"]
    return files


def package_schema(info: dict | None) -> tuple:
    """(schema, {base part: chipdb file}) of a package, from its index.

    No document: the schema this repository emits. Schema 5 and 6 are the
    current engine; schema 7 is the himbaechel engine. Any other number
    is refused rather than guessed at. The files are the ones the
    document names for its built parts, read the way apio reads them.
    """
    if info is None:
        return SCHEMA, {}
    schema = info.get("schema")
    if schema not in (5, 6, SCHEMA):
        raise ValueError(
            f"XILINX-PARTS-INDEX schema {schema!r} is not one of 5, 6, {SCHEMA}")
    return schema, _described_files(info)


def read_package_schema(package: Path) -> tuple:
    """package_schema() of the package tree at *package*."""
    index = Path(package) / PACKAGE_FILE
    if not index.is_file():
        return package_schema(None)
    return package_schema(json.loads(index.read_text(encoding="utf-8")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("index", type=Path)
    parser.add_argument("chipdb", type=Path)
    args = parser.parse_args()
    try:
        counts = validate_package_info(args.index, args.chipdb)
    except ValueError as error:
        parser.exit(1, f"error: {error}\n")
    print(f"XILINX-PARTS-INDEX: {counts['part-count']} parts "
          f"({counts['base-part-count']} base parts) of the packaged "
          f"database, {counts['generated-count']} of them built by this "
          f"release from {counts['chipdb-count']} chipdb files, which "
          f"match the ones in {args.chipdb}")


if __name__ == "__main__":
    main()
