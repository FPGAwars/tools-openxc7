"""Validation for CHIPDB-INFO.json, the chipdb map a package carries.

The same document is published as the dated release asset. L1 validates
it against the bins it describes: the packaged ones in a package that
still ships its chipdb, and the external directory apio's on-demand
loader fetches into otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .chipdb_assets import SCHEMA, asset_name, release_tag
from .families import family_of

GENERATED_KEYS = ("asset", "size", "sha256", "tgz_size", "tgz_sha256")

# Name of the release asset the document itself is published under, fixed
# since apio#900. pack.chipdb_assets writes the file; this is the reader
# side (scripts/asset-check.sh fetches a release by this name), and
# tests/test_chipdb_assets.py asserts the two agree.
INFO_ASSET = "apio-xilinx-chipdb-index-{date}.json"


def info_asset_name(date: str) -> str:
    """Release asset carrying this document for a given YYYYMMDD date."""
    release_tag(date)          # rejects a date that is not YYYYMMDD
    return INFO_ASSET.format(date=date)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_document(info: dict, expect_tag: str | None = None) -> dict:
    """Check the document on its own; return the generated entries by part.

    *expect_tag* is the release the document was actually found in. A
    document naming another tag sends apio's loader to assets that live
    somewhere else -- the class of failure a release gate must catch, and
    the one a run crossing midnight UTC would produce.
    """
    if info.get("schema") != SCHEMA:
        raise ValueError(
            f"CHIPDB-INFO schema is {info.get('schema')!r}, expected {SCHEMA}")
    date = info.get("date")
    if not isinstance(date, str):
        raise ValueError("CHIPDB-INFO has no date")
    try:
        expected_tag = release_tag(date)
    except ValueError as error:
        raise ValueError(f"CHIPDB-INFO {error}") from error
    if info.get("release-tag") != expected_tag:
        raise ValueError(
            f"CHIPDB-INFO release-tag {info.get('release-tag')!r} does not "
            f"match date {date} (apio derives the date from the tag)")
    if expect_tag is not None and info["release-tag"] != expect_tag:
        raise ValueError(
            f"CHIPDB-INFO release-tag {info['release-tag']!r} is not the "
            f"release it was published in ({expect_tag})")
    if not info.get("chipdb-id"):
        raise ValueError("CHIPDB-INFO has no chipdb-id")

    parts = info.get("parts")
    if not isinstance(parts, dict) or not parts:
        raise ValueError("CHIPDB-INFO parts must be a non-empty object")

    generated = {}
    for part, entry in parts.items():
        if not isinstance(entry, dict):
            raise ValueError(f"CHIPDB-INFO entry for {part} must be an object")
        if entry.get("family") != family_of(part):
            raise ValueError(f"CHIPDB-INFO entry for {part} has the wrong family")
        if not isinstance(entry.get("generated"), bool):
            raise ValueError(f"CHIPDB-INFO entry for {part} has no generated flag")
        if not entry["generated"]:
            # A part nobody can download must not look downloadable.
            extra = [key for key in GENERATED_KEYS if key in entry]
            if extra:
                raise ValueError(
                    f"CHIPDB-INFO: {part} is not generated but carries {extra}")
            continue
        for key in GENERATED_KEYS:
            if key not in entry:
                raise ValueError(f"CHIPDB-INFO: generated {part} has no {key}")
        if entry["asset"] != asset_name(part, date):
            raise ValueError(
                f"CHIPDB-INFO: {part} asset {entry['asset']!r} is not the "
                f"name apio resolves for {date} ({asset_name(part, date)})")
        for key in ("size", "tgz_size"):
            if not isinstance(entry[key], int) or entry[key] <= 0:
                raise ValueError(f"CHIPDB-INFO: {part} has an invalid {key}")
        for key in ("sha256", "tgz_sha256"):
            value = entry[key]
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"CHIPDB-INFO: {part} has an invalid {key}")
        generated[part] = entry

    if info.get("generated-count") != len(generated):
        raise ValueError(
            f"CHIPDB-INFO generated-count {info.get('generated-count')!r} != "
            f"{len(generated)} generated entries")
    if info.get("available-count") != len(parts):
        raise ValueError(
            f"CHIPDB-INFO available-count {info.get('available-count')!r} != "
            f"{len(parts)} entries")
    return generated


def validate_package_info(info_path: Path, chipdb: Path) -> tuple:
    """Validate the document and the bins it describes.

    *chipdb* is the directory that must hold exactly the generated bins:
    the package's own chipdb/ in a package that ships them, or the
    directory apio's loader downloads into. Returns (generated, available).
    """
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read CHIPDB-INFO: {error}") from error

    generated = validate_document(info)

    present = sorted(path.stem for path in chipdb.glob("*.bin"))
    if sorted(generated) != present:
        raise ValueError(
            "CHIPDB-INFO generated parts do not match the bins in "
            f"{chipdb}: info={sorted(generated)}, bins={present}")
    for part in present:
        path = chipdb / f"{part}.bin"
        entry = generated[part]
        if entry["size"] != path.stat().st_size:
            raise ValueError(f"CHIPDB-INFO size differs for {part}")
        if entry["sha256"] != _sha256(path):
            raise ValueError(f"CHIPDB-INFO sha256 differs for {part}")
    return len(generated), info["available-count"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("info", type=Path)
    parser.add_argument("chipdb", type=Path)
    args = parser.parse_args()
    try:
        generated, available = validate_package_info(args.info, args.chipdb)
    except ValueError as error:
        parser.exit(1, f"error: {error}\n")
    print(f"CHIPDB-INFO: {generated} generated parts match the bins in "
          f"{args.chipdb} ({available} available in the packaged database)")


if __name__ == "__main__":
    main()
