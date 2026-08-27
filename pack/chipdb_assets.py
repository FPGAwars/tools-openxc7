"""Per-FPGA chipdb assets and the release information file.

One deterministic ``.bin.tgz`` per generated part, plus the schema-3
document that describes every footprint the release knows about. That
document travels twice: as the dated release asset
``apio-xilinx-chipdb-index-<YYYYMMDD>.json`` and, under the name
``CHIPDB-INFO.json``, at the root of every platform package -- it is what
tells apio's on-demand loader which bin to fetch, what it must end up
with on disk, and which footprints the database knows but this release
did not build.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .families import family_of

SCHEMA = 3

NOTE = (
    "Keyed by chipdb footprint, without speed grade. A part with "
    "generated=true is built for THIS release: download <asset> from the "
    "release named by release-tag and leave <part>.bin in the package's "
    "chipdb/ directory. size/sha256 describe that uncompressed .bin (what "
    "must end up on disk); tgz_size/tgz_sha256 describe the downloaded "
    "asset, a tar.gz carrying <part>.bin at its root. A part with "
    "generated=false is a footprint present in the packaged prjxray-db "
    "that this release did not build -- supported by the database, not "
    "available for download. Bins are only valid with the openxc7 package "
    "of the SAME release tag; chipdb-id is the identity stamp of the set."
)

# Name of the identity stamp inside a chipdb directory (pack.chipdb owns it;
# repeated here to keep this module importable on its own).
STAMP = "chipdb-id.txt"


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def asset_name(part: str, date: str) -> str:
    """Release asset carrying one part's chipdb, for a given date."""
    return f"apio-xilinx-chipdb-{part}-{date}.bin.tgz"


def release_tag(date: str) -> str:
    """The release tag a YYYYMMDD asset date comes from (apio's rule)."""
    if len(date) != 8 or not date.isdigit():
        raise ValueError(f"asset date must be YYYYMMDD: {date!r}")
    return f"{date[:4]}-{date[4:6]}-{date[6:]}"


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


def _cache_is_usable(cache: Path | None, stamp: str) -> bool:
    """True when *cache* holds tgz built from bins of identity *stamp*.

    The tgz of a part is a pure function of its .bin, and the .bin of a
    stamp is fixed -- so a cache carrying the same stamp can be reused
    verbatim. A cache from another toolchain revision is ignored (never
    used, never overwritten silently: it is refreshed below).
    """
    if cache is None or not cache.is_dir():
        return False
    stamp_file = cache / STAMP
    return stamp_file.is_file() and \
        stamp_file.read_text(encoding="utf-8").strip() == stamp


def _one_asset(part: str, family: str, source: Path, destination: Path,
               cache: Path | None, reuse: bool) -> dict:
    """Produce one release asset and describe it. Runs in a worker thread."""
    cached = cache / f"{part}.bin.tgz" if cache is not None else None
    if reuse and cached is not None and cached.is_file():
        shutil.copyfile(cached, destination)
        origin = "cache"
    else:
        deterministic_tgz(source, destination, f"{part}.bin")
        origin = "built"
        if cache is not None:
            cache.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(destination, cached)
    # Always hashed from the bytes that are about to be published: the
    # document never repeats numbers recorded by an earlier run.
    return {
        "family": family,
        "generated": True,
        "asset": destination.name,
        "size": source.stat().st_size,
        "sha256": sha256(source),
        "tgz_size": destination.stat().st_size,
        "tgz_sha256": sha256(destination),
        "_origin": origin,
        "_part": part,
    }


def build_assets(repo: Path, chipdb: Path, output: Path, date: str,
                 database: Path, cache: Path | None = None,
                 jobs: int = 1) -> Path:
    """Build the release assets and the schema-3 chipdb information file.

    ``cache`` is an optional directory of date-free ``<part>.bin.tgz``
    guarded by the identity stamp: compressing 1.1 GB is the expensive
    half of this step and its result only depends on the bins. ``jobs``
    compresses and hashes several parts at once (zlib and hashlib both
    release the GIL).
    """
    stamp_file = chipdb / STAMP
    if not stamp_file.is_file():
        raise ValueError(f"{chipdb} has no {STAMP} (unstamped set)")

    manifest = json.loads((repo / "chipdb-parts.json").read_text(
        encoding="utf-8"))
    inventory = available_parts(database)
    output.mkdir(parents=True, exist_ok=True)
    stamp = stamp_file.read_text(encoding="utf-8").strip()
    reuse = _cache_is_usable(cache, stamp)
    if cache is not None:
        print(f"asset cache: {cache} ({'reusable' if reuse else 'cold'})")

    wanted = []
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
            wanted.append((part, family, source,
                           output / asset_name(part, date)))

    with ThreadPoolExecutor(max_workers=max(jobs, 1)) as pool:
        built = list(pool.map(
            lambda item: _one_asset(item[0], item[1], item[2], item[3],
                                    cache, reuse),
            wanted))

    generated = {}
    for entry in built:
        part = entry.pop("_part")
        origin = entry.pop("_origin")
        generated[part] = entry
        print(f"  {entry['asset']}  "
              f"({entry['size'] / 1e6:.0f} MB -> "
              f"{entry['tgz_size'] / 1e6:.0f} MB, {origin})")
    if cache is not None and not reuse:
        # The cache now matches these bins; stamp it so the next run can
        # tell (a stale stamp is what makes a foreign cache unusable).
        cache.mkdir(parents=True, exist_ok=True)
        (cache / STAMP).write_text(stamp + "\n", encoding="utf-8")

    # Families in manifest order first, then whatever else the database
    # carries; parts sorted inside each family. Insertion order is what a
    # reader of the JSON sees.
    ordered_families = list(manifest)
    ordered_families.extend(
        family for family in sorted(inventory) if family not in manifest
    )
    parts_doc = {}
    available_count = 0
    for family in ordered_families:
        for part in inventory.get(family, []):
            available_count += 1
            parts_doc[part] = generated.get(
                part, {"family": family, "generated": False})

    missing = sorted(set(generated) - set(parts_doc))
    if missing:                       # cannot happen: checked against the db
        raise ValueError(f"generated parts absent from the database: {missing}")

    info = {
        "schema": SCHEMA,
        "date": date,
        "release-tag": release_tag(date),
        "chipdb-id": stamp,
        "generated-count": len(generated),
        "available-count": available_count,
        "note": NOTE,
        "parts": parts_doc,
    }
    info_path = output / f"apio-xilinx-chipdb-index-{date}.json"
    info_path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(
        f"chipdb info: {info_path.name} "
        f"({len(generated)} generated, {available_count} available, "
        f"chipdb-id {stamp})"
    )
    return info_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("chipdb", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("date")
    parser.add_argument("database", type=Path)
    parser.add_argument("--cache", type=Path, default=None,
                        help="directory of date-free <part>.bin.tgz to reuse")
    parser.add_argument("--jobs", type=int,
                        default=int(os.environ.get("OPENXC7_ASSET_JOBS") or 1),
                        help="parts compressed and hashed at once")
    args = parser.parse_args()
    try:
        build_assets(args.repo, args.chipdb, args.output, args.date,
                     args.database, args.cache, args.jobs)
    except ValueError as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
