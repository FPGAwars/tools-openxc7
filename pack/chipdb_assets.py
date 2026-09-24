"""Per-die chipdb assets and the parts index that maps parts to them.

One deterministic ``.bin.tgz`` per chipdb file this release builds -- one
per die of the manifest -- plus the document that describes every part
the packaged prjxray database knows about. That document travels twice under one name,
``XILINX-PARTS-INDEX.json``: as a release asset and at the root of every
platform package -- it is what tells apio's on-demand loader which chipdb
file a part needs, which asset carries it, what must end up on disk, and
which parts the database supports but this release did not build.

The format itself (schema, key order, validation) lives in
``pack.parts_index``.
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

from .families import die_of, family_of
from .parts_index import (ENTRY_KEYS, INDEX_ASSET, NOTE, SCHEMA,
                          asset_name, chipdb_name, release_tag)

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


def _cache_is_usable(cache: Path | None, stamp: str) -> bool:
    """True when *cache* holds tgz built from bins of identity *stamp*.

    The tgz of a chipdb file is a pure function of that file, and the
    files of a stamp are fixed -- so a cache carrying the same stamp can
    be reused verbatim. A cache from another toolchain revision is
    ignored (never used, never overwritten silently: it is refreshed
    below).
    """
    if cache is None or not cache.is_dir():
        return False
    stamp_file = cache / STAMP
    return stamp_file.is_file() and \
        stamp_file.read_text(encoding="utf-8").strip() == stamp


def _one_asset(die: str, source: Path, destination: Path,
               cache: Path | None, reuse: bool) -> dict:
    """Produce one release asset and describe it. Runs in a worker thread."""
    cached = cache / f"{source.name}.tgz" if cache is not None else None
    if reuse and cached is not None and cached.is_file():
        shutil.copyfile(cached, destination)
        origin = "cache"
    else:
        deterministic_tgz(source, destination, source.name)
        origin = "built"
        if cache is not None:
            cache.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(destination, cached)
    # Always hashed from the bytes that are about to be published: the
    # document never repeats numbers recorded by an earlier run.
    return {
        "chipdb": source.name,
        "chipdb-size": source.stat().st_size,
        "chipdb-sha256": sha256(source),
        "asset": destination.name,
        "asset-size": destination.stat().st_size,
        "asset-sha256": sha256(destination),
        "_origin": origin,
        "_die": die,
    }


def build_assets(repo: Path, chipdb: Path, output: Path, date: str,
                 database: Path, cache: Path | None = None,
                 jobs: int = 1) -> Path:
    """Build the release assets and the parts index that describes them.

    ``cache`` is an optional directory of date-free ``chipdb-<die>.bin.tgz``
    guarded by the identity stamp: compressing the bins is the expensive
    half of this step and its result only depends on them. ``jobs``
    compresses and hashes several dies at once (zlib and hashlib both
    release the GIL).
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
    reuse = _cache_is_usable(cache, stamp)
    if cache is not None:
        print(f"asset cache: {cache} ({'reusable' if reuse else 'cold'})")

    # One asset per die: the manifest parts of a die share its chipdb.
    wanted = {}
    manifest_base_parts = set()
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
            manifest_base_parts.add(base_part)
            source = chipdb / chipdb_name(base_part)
            if not source.is_file():
                raise ValueError(f"manifest part without bin: {source}")
            wanted.setdefault(die_of(base_part), (
                source, output / asset_name(base_part, date)))

    with ThreadPoolExecutor(max_workers=max(jobs, 1)) as pool:
        built = list(pool.map(
            lambda item: _one_asset(item[0], item[1][0], item[1][1], cache,
                                    reuse),
            wanted.items()))

    by_die = {}
    for entry in built:
        die = entry.pop("_die")
        origin = entry.pop("_origin")
        by_die[die] = entry
        print(f"  {entry['asset']}  "
              f"({entry['chipdb-size'] / 1e6:.0f} MB -> "
              f"{entry['asset-size'] / 1e6:.0f} MB, {origin})")
    if cache is not None and not reuse:
        # The cache now matches these bins; stamp it so the next run can
        # tell (a stale stamp is what makes a foreign cache unusable).
        cache.mkdir(parents=True, exist_ok=True)
        (cache / STAMP).write_text(stamp + "\n", encoding="utf-8")

    # One entry per part of the database, part-sorted, with the keys of an
    # entry always in the same order. A part is built when its base part
    # is in the manifest -- the parts L1 routes -- and the parts of a die
    # repeat its chipdb file, asset and hashes on purpose: which parts
    # share a file is ours to change, and the index is what hides it.
    # The schema number says which engine the file was built for.
    parts_doc = {}
    for part, meta in inventory.items():
        entry = dict(meta)
        entry["generated"] = meta["base-part"] in manifest_base_parts
        if entry["generated"]:
            entry.update(by_die[die_of(meta["base-part"])])
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
        "chipdb-count": len(by_die),
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
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("chipdb", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("date")
    parser.add_argument("database", type=Path)
    parser.add_argument("--cache", type=Path, default=None,
                        help="directory of date-free chipdb-<die>.bin.tgz to reuse")
    parser.add_argument("--jobs", type=int,
                        default=int(os.environ.get("OPENXC7_ASSET_JOBS") or 1),
                        help="chipdb files compressed and hashed at once")
    args = parser.parse_args()
    try:
        build_assets(args.repo, args.chipdb, args.output, args.date,
                     args.database, args.cache, args.jobs)
    except ValueError as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
