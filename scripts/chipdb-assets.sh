#!/usr/bin/env bash
#
# chipdb-assets.sh -- build the per-FPGA chipdb release assets.
#
# The chipdb .bin files are platform-independent (asserted at release
# time), so they are published ONCE per release as individual gzipped
# assets next to the full platform tarballs, plus an index that apio's
# upcoming on-demand loader can resolve and verify against:
#
#   chipdb-<part>-<YYYYMMDD>.bin.gz     one per manifest part
#   chipdb-index-<YYYYMMDD>.json        part -> family, sizes, sha256s
#
# Every asset carries the tag's date (house rule: a mistagged asset must
# be impossible to fetch by accident). The index records the sha256 of
# BOTH the uncompressed bin (what the loader must end up with on disk)
# and the gzip (what it downloads), plus the chipdb identity stamp.
#
# Usage:
#   scripts/chipdb-assets.sh <chipdb-dir> <out-dir> <YYYYMMDD>
#
# <chipdb-dir> must contain the manifest bins AND chipdb-id.txt (the
# identity stamp travels with the set; refuse to publish an unstamped one).

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CHIPDB=${1:?usage: chipdb-assets.sh <chipdb-dir> <out-dir> <YYYYMMDD>}
OUT=${2:?missing out-dir}
DATE=${3:?missing YYYYMMDD date}

[ -f "$CHIPDB/chipdb-id.txt" ] || { echo "❌ $CHIPDB has no chipdb-id.txt (unstamped set)" >&2; exit 1; }
mkdir -p "$OUT"

python3 - "$REPO_ROOT" "$CHIPDB" "$OUT" "$DATE" <<'PYEOF'
import gzip, hashlib, json, shutil, sys
from pathlib import Path

repo, chipdb, out, date = map(Path, sys.argv[1:4]) , None, None, None
repo = Path(sys.argv[1]); chipdb = Path(sys.argv[2]); out = Path(sys.argv[3]); date = sys.argv[4]
sys.path.insert(0, str(repo))
from pack.families import family_of

manifest = json.loads((repo / "chipdb-parts.json").read_text())
parts = [p for ps in manifest.values() for p in ps]
stamp = (chipdb / "chipdb-id.txt").read_text().strip()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


entries = []
for part in parts:
    src = chipdb / f"{part}.bin"
    if not src.exists():
        sys.exit(f"❌ manifest part without bin: {src}")
    asset = f"chipdb-{part}-{date}.bin.gz"
    dst = out / asset
    # mtime=0: deterministic gzip -- same bin, same asset bytes
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        with gzip.GzipFile(fileobj=fo, mode="wb", mtime=0) as gz:
            shutil.copyfileobj(fi, gz)
    entries.append({
        "part": part,
        "family": family_of(part),
        "asset": asset,
        "size": src.stat().st_size,
        "sha256": sha256(src),
        "gz_size": dst.stat().st_size,
        "gz_sha256": sha256(dst),
    })
    print(f"  {asset}  ({entries[-1]['size'] / 1e6:.0f} MB -> {entries[-1]['gz_size'] / 1e6:.0f} MB)")

index = {
    "date": date,
    "chipdb_id": stamp,
    "note": "chipdb .bin files are platform-independent; sha256 is the "
            "UNCOMPRESSED bin the loader must end up with, gz_sha256 the "
            "downloaded asset. Bins are only valid with the openxc7 "
            "package of the SAME release tag (content changes across "
            "releases under the same file names).",
    "parts": entries,
}
(out / f"chipdb-index-{date}.json").write_text(json.dumps(index, indent=2) + "\n")
print(f"index: chipdb-index-{date}.json ({len(entries)} parts, chipdb_id {stamp})")
PYEOF
