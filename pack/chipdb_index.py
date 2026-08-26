"""Validation for the chipdb index embedded in an openXC7 package."""

import argparse
import hashlib
import json
from pathlib import Path

from .families import family_of


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_package_index(index_path: Path, chipdb: Path) -> int:
    """Validate schema and return the number of generated parts."""
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read chipdb index: {error}") from error

    if index.get("schema") != 2:
        raise ValueError(f"chipdb index schema is {index.get('schema')!r}, expected 2")
    families = index.get("families")
    if not isinstance(families, dict) or not families:
        raise ValueError("chipdb index families must be a non-empty object")

    generated_entries = []
    for family, data in families.items():
        if not isinstance(data, dict):
            raise ValueError(f"chipdb index family {family} must be an object")
        generated = data.get("generated-parts")
        available = data.get("available-parts")
        if not isinstance(generated, list) or not isinstance(available, list):
            raise ValueError(
                f"chipdb index family {family} needs generated-parts and "
                "available-parts arrays"
            )
        if any(not isinstance(name, str) for name in available):
            raise ValueError(f"chipdb index family {family} has an invalid footprint")
        if len(available) != len(set(available)):
            raise ValueError(f"chipdb index family {family} repeats a footprint")
        for entry in generated:
            if not isinstance(entry, dict):
                raise ValueError(f"generated part in {family} must be an object")
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError(f"generated part in {family} has no name")
            if entry.get("part") != name:
                raise ValueError(f"generated part {name} breaks the schema-1 part key")
            if entry.get("family") != family or family_of(name) != family:
                raise ValueError(f"generated part {name} has inconsistent family")
            if name not in available:
                raise ValueError(f"generated part {name} is absent from available-parts")
            for key in ("asset", "size", "sha256", "tgz_size", "tgz_sha256"):
                if key not in entry:
                    raise ValueError(f"generated part {name} has no {key}")
            generated_entries.append(entry)

    names = [entry["name"] for entry in generated_entries]
    if len(names) != len(set(names)):
        raise ValueError("chipdb index repeats a generated part")

    flat_parts = index.get("parts")
    if not isinstance(flat_parts, list):
        raise ValueError("chipdb index has no schema-1 parts array")
    if [entry.get("part") for entry in flat_parts] != [
            entry["name"] for entry in generated_entries]:
        raise ValueError("chipdb index parts and generated-parts differ")

    packaged = sorted(path.stem for path in chipdb.glob("*.bin"))
    if sorted(names) != packaged:
        raise ValueError(
            "chipdb index generated-parts do not match packaged bins: "
            f"index={sorted(names)}, package={packaged}"
        )
    by_name = {entry["name"]: entry for entry in generated_entries}
    for name in packaged:
        path = chipdb / f"{name}.bin"
        entry = by_name[name]
        if entry["size"] != path.stat().st_size:
            raise ValueError(f"chipdb index size differs for {name}")
        if entry["sha256"] != _sha256(path):
            raise ValueError(f"chipdb index sha256 differs for {name}")
    return len(packaged)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("index", type=Path)
    parser.add_argument("chipdb", type=Path)
    args = parser.parse_args()
    try:
        count = validate_package_index(args.index, args.chipdb)
    except ValueError as error:
        parser.exit(1, f"error: {error}\n")
    print(f"chipdb index: {count} generated parts match the packaged bins")


if __name__ == "__main__":
    main()
