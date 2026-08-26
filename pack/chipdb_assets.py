"""Per-FPGA chipdb assets and the release index."""

import argparse
import gzip
import hashlib
import json
import tarfile
from pathlib import Path

from .families import family_of


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_tgz(source: Path, destination: Path, arcname: str) -> None:
    """Write a tar.gz whose bytes depend only on the source bytes."""
    with destination.open("wb") as output:
        # An empty gzip filename keeps the destination name out of the header.
        with gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as archive:
                info = archive.gettarinfo(str(source), arcname=arcname)
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with source.open("rb") as data:
                    archive.addfile(info, data)


def available_parts(database: Path) -> dict[str, list[str]]:
    """Enumerate footprint names represented by the packaged prjxray-db.

    Database directories include a speed suffix (for example ``-1`` or
    ``-2L``). Chipdb names are footprints without that suffix, so all speed
    variants collapse to one name.
    """
    if not database.is_dir():
        raise ValueError(f"prjxray-db directory not found: {database}")

    result: dict[str, list[str]] = {}
    for family_dir in sorted(path for path in database.iterdir()
                             if path.is_dir()):
        footprints = set()
        for part_yaml in family_dir.glob("*/part.yaml"):
            speed_part = part_yaml.parent.name
            if "-" not in speed_part:
                raise ValueError(f"database part has no speed suffix: {speed_part}")
            footprint = speed_part.rsplit("-", 1)[0]
            mapped_family = family_of(footprint)
            if mapped_family != family_dir.name:
                raise ValueError(
                    f"database family mismatch for {footprint}: "
                    f"directory {family_dir.name}, mapping {mapped_family}"
                )
            footprints.add(footprint)
        if footprints:
            result[family_dir.name] = sorted(footprints)
    return result


def build_assets(repo: Path, chipdb: Path, output: Path, date: str,
                 database: Path) -> Path:
    """Build deterministic assets and their schema-2 JSON index."""
    stamp_file = chipdb / "chipdb-id.txt"
    if not stamp_file.is_file():
        raise ValueError(f"{chipdb} has no chipdb-id.txt (unstamped set)")

    manifest = json.loads((repo / "chipdb-parts.json").read_text(
        encoding="utf-8"))
    inventory = available_parts(database)
    output.mkdir(parents=True, exist_ok=True)
    stamp = stamp_file.read_text(encoding="utf-8").strip()

    entries = []
    for declared_family, parts in manifest.items():
        for part in parts:
            family = family_of(part)
            if family != declared_family:
                raise ValueError(
                    f"manifest family mismatch for {part}: "
                    f"declared {declared_family}, mapping {family}"
                )
            if part not in inventory.get(family, []):
                raise ValueError(
                    f"manifest part not present in packaged prjxray-db: {part}"
                )
            source = chipdb / f"{part}.bin"
            if not source.is_file():
                raise ValueError(f"manifest part without bin: {source}")
            asset = f"apio-xilinx-chipdb-{part}-{date}.bin.tgz"
            destination = output / asset
            deterministic_tgz(source, destination, f"{part}.bin")
            entry = {
                # ``part`` and all size/hash keys are the schema-1 contract.
                "part": part,
                "name": part,
                "family": family,
                "asset": asset,
                "size": source.stat().st_size,
                "sha256": sha256(source),
                "tgz_size": destination.stat().st_size,
                "tgz_sha256": sha256(destination),
            }
            entries.append(entry)
            print(
                f"  {asset}  "
                f"({entry['size'] / 1e6:.0f} MB -> "
                f"{entry['tgz_size'] / 1e6:.0f} MB)"
            )

    families = {}
    ordered_families = list(manifest)
    ordered_families.extend(
        family for family in sorted(inventory) if family not in manifest
    )
    for family in ordered_families:
        families[family] = {
            "generated-parts": [
                entry for entry in entries if entry["family"] == family
            ],
            "available-parts": inventory.get(family, []),
        }

    index = {
        "schema": 2,
        "date": date,
        "chipdb_id": stamp,
        "note": "chipdb .bin files are platform-independent; sha256 is the "
                "UNCOMPRESSED bin the loader must end up with, tgz_sha256 the "
                "downloaded asset (a tar.gz with <part>.bin at its root). "
                "Only generated-parts are supported by this release; "
                "available-parts inventories footprints in its packaged "
                "prjxray-db. Bins are only valid with the openxc7 package "
                "of the SAME release tag.",
        "parts": entries,
        "families": families,
    }
    index_path = output / f"apio-xilinx-chipdb-index-{date}.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    available_count = sum(
        len(data["available-parts"]) for data in families.values()
    )
    print(
        f"index: {index_path.name} "
        f"({len(entries)} generated, {available_count} available, "
        f"chipdb_id {stamp})"
    )
    return index_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("chipdb", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("date")
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    try:
        build_assets(args.repo, args.chipdb, args.output, args.date,
                     args.database)
    except ValueError as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
