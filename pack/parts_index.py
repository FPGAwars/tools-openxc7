"""XILINX-PARTS-INDEX.json: the map from a part number to its chipdb file.

Every package carries this document at its root, and the release
publishes the same bytes under the same name. Schema 8, which this
module emits, ships the chipdb files inside the package: given the part
a board is built for, an entry names the file in ``chipdb/``.

The naming is Vivado's. ``xc7a200t`` is the device, ``fbg484`` the
package and ``3`` the speed grade; ``xc7a200tfbg484-3`` is the **part**
and ``xc7a200tfbg484`` its **base part**. The index is keyed by the part,
because which parts share a chipdb file is an implementation detail of
this repository (apio#947): one file serves every part of a die --
every package and speed grade of the device, and of the devices that are
the same die (an xc7a35t is an xc7a50t).

This module owns the format (schema, note, validation):
``pack.chipdb_assets`` writes the document, L1 checks a package against
the bins it describes, and scripts/asset-check.sh checks a published
release against it -- one validator, three callers.

The schema number is the contract (apio#1071, apio#1070). A package
carries one engine, so a reader asserts the number and already knows the
binary and the command line. Schema 8 is the himbaechel engine with the
chipdb files inside the package. An entry has no engine field and no
download fields.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .families import die_of, family_of

SCHEMA = 8

# Schema 6 (and 5 before it): one chipdb file per base part, command line
# ``nextpnr-xilinx --chipdb <file> --xdc``. Schema 7 was the himbaechel
# engine with the same per-die files, published as separate release assets
# for apio to download. Schema 8, which this module emits, keeps that
# engine and those file names and ships the files in the package. The
# validator accepts only the schema this branch emits.
PER_BASE_PART_SCHEMA = 6
PER_DIE_SCHEMAS = (7, SCHEMA)

# The one key a built part carries beyond the four every part has: the
# file name in the package's chipdb/ directory. Schemas 5, 6 and 7 also
# recorded sizes, hashes and a release asset; schema 8 does not.
GENERATED_KEYS = ("chipdb",)

# Order of the keys inside one entry, as a reader of the JSON sees them.
ENTRY_KEYS = ("family", "base-part", "speed", "generated") + GENERATED_KEYS

# On-disk name of the identity stamp, next to the bins. pack.chipdb writes
# it; repeated here so this module does not import the generator.
STAMP_FILE = "chipdb-id.txt"

NOTE = (
    "Keyed by the full part number, <base-part>-<speed>, in Vivado's "
    "naming: device xc7a200t + package fbg484 = base part xc7a200tfbg484, "
    "speed grade 3, part xc7a200tfbg484-3. The chipdb files travel inside "
    "this package, in chipdb/. An entry with generated=true was built for "
    "THIS release: chipdb is the file name in that directory "
    "(chipdb-<die>.bin). The parts of one die -- the speed grades of a "
    "base part, and the packages of the device or of another device on "
    "the same die -- deliberately repeat that file name: one file serves "
    "them all. family is the prjxray database directory the part lives in "
    "($PRJXRAY_DB_DIR/<family>/<part>/part.yaml). An entry with "
    "generated=false is a part the packaged database supports that this "
    "release did not build: supported, not built. schema 8 is the "
    "contract: one chipdb file per die, command line nextpnr-xilinx "
    "--device <part> --chipdb <file> -o xdc= -o fasm= --report. A "
    "package carries one engine, so the schema number is what a reader "
    "asserts. chipdb-id is the identity stamp of the set "
    "(chipdb/chipdb-id.txt); a chipdb file is only valid with the "
    "openxc7 package of the SAME release tag."
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
    """The release tag a YYYYMMDD package date comes from (apio's rule)."""
    if len(date) != 8 or not date.isdigit():
        raise ValueError(f"package date must be YYYYMMDD: {date!r}")
    return f"{date[:4]}-{date[4:6]}-{date[6:]}"


def _as_schema(schema: int) -> int:
    if isinstance(schema, int) and not isinstance(schema, bool):
        return schema
    raise ValueError(f"parts-index schema must be an integer, not {schema!r}")


def _chipdb_unit(base_part: str, schema: int) -> str:
    """What one chipdb file covers under *schema*: the die, or the base part."""
    number = _as_schema(schema)
    if number <= PER_BASE_PART_SCHEMA:
        return base_part
    if number in PER_DIE_SCHEMAS:
        return die_of(base_part)
    raise ValueError(
        f"schema {number} has no chipdb file names "
        f"(this index emits schema {SCHEMA})")


def asset_name(base_part: str, date: str, schema: int = SCHEMA) -> str:
    """Release asset a schema 5, 6 or 7 index named for a base part.

    Schema 8 publishes no chipdb assets: the files travel in the package.
    Kept so a reader of an older document can still name what it pointed at.
    """
    number = _as_schema(schema)
    if number >= SCHEMA:
        raise ValueError(
            f"schema {number} publishes no chipdb assets; "
            "the chipdb files travel in the package")
    return (f"apio-xilinx-chipdb-{_chipdb_unit(base_part, number)}-"
            f"{date}.bin.tgz")


def chipdb_name(base_part: str, schema: int = SCHEMA) -> str:
    """Chipdb file a base part needs: the name in chipdb/.

    Schema 7 and 8: the file of its die, chipdb-xc7a50t.bin for an
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


def _check_entry(part: str, entry: dict, _date: str) -> None:
    """Check one part entry on its own.

    The date is a document-level check: an entry no longer names an asset.
    """
    if not isinstance(entry, dict):
        raise ValueError(f"XILINX-PARTS-INDEX entry for {part} must be an object")
    # The index is a contract: a key this schema does not define (an asset
    # field from schema 7, the engine field the schema 6 draft carried) is
    # refused, not ignored. apio asserts the schema number and reads these
    # keys only.
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
        # A part this release did not build must not name a chipdb file.
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
            f"in chipdb/ for {base} ({chipdb_name(base)})")


def validate_document(info: dict, expect_tag: str | None = None) -> dict:
    """Check the document on its own; return the generated entries by part.

    *expect_tag* is the release the document was actually found in. A
    document naming another tag describes a different package than the one
    it was published next to -- the class of failure a release gate must
    catch, and the one a run crossing midnight UTC would produce.
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

    *chipdb* is the directory that holds exactly the generated chipdb
    files and ``chipdb-id.txt``: the package's own chipdb/. Returns the
    document counts. A missing bin and an extra bin are both named.
    """
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read XILINX-PARTS-INDEX: {error}") from error

    generated = validate_document(info)

    stamp_path = chipdb / STAMP_FILE
    stamp = stamp_path.read_text(encoding="utf-8").strip() \
        if stamp_path.is_file() else ""
    if stamp != info["chipdb-id"]:
        raise ValueError(
            f"XILINX-PARTS-INDEX chipdb-id {info['chipdb-id']!r} does not match "
            f"{stamp_path} ({stamp or 'absent'})")

    described = {entry["chipdb"] for entry in generated.values()}
    present = {path.name for path in chipdb.glob("*.bin")}
    missing = sorted(described - present)
    extra = sorted(present - described)
    if missing or extra:
        raise ValueError(
            "XILINX-PARTS-INDEX chipdb files do not match the bins in "
            f"{chipdb}: missing {missing or 'none'}, "
            f"unexpected {extra or 'none'}")
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

    No document: the schema this repository emits. Schemas 5 and 6 name
    one chipdb file per base part; schemas 7 and 8 name one per die. The
    validator accepts only the schema this module emits. The reader still
    reports 5, 6 and 7 so a harness can open an older package. Any other
    number is refused rather than guessed at. The files are the ones the
    document names for its built parts, read the way apio reads them.
    """
    if info is None:
        return SCHEMA, {}
    schema = info.get("schema")
    if schema not in (5, 6, *PER_DIE_SCHEMAS):
        raise ValueError(
            f"XILINX-PARTS-INDEX schema {schema!r} is not one of "
            f"5, 6, 7, {SCHEMA}")
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
