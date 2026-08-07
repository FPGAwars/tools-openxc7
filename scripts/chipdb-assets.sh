#!/usr/bin/env bash
#
# chipdb-assets.sh -- build the per-FPGA chipdb release assets.
#
# The chipdb .bin files are platform-independent (asserted at release
# time), so they are published ONCE per release as individual gzipped
# assets next to the full platform tarballs, plus an index that apio's
# upcoming on-demand loader can resolve and verify against:
#
#   apio-xilinx-chipdb-<part>-<YYYYMMDD>.bin.tgz   one per manifest part
#   apio-xilinx-chipdb-index-<YYYYMMDD>.json        part -> family, sizes, sha256s
#
# Naming and format agreed with the apio maintainer (apio#897/#900): the
# apio-xilinx-chipdb- prefix groups after the three platform packages in
# the release listing; .bin.tgz = a deterministic tar.gz containing
# <part>.bin at its root (apio reuses its package-archive handling).
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


def deterministic_tgz(src, dst, arcname):
    """tar.gz with fixed metadata: same bin, same asset bytes."""
    import tarfile
    with open(dst, "wb") as fo:
        with gzip.GzipFile(fileobj=fo, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                info = tar.gettarinfo(str(src), arcname=arcname)
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with open(src, "rb") as fi:
                    tar.addfile(info, fi)


entries = []
for part in parts:
    src = chipdb / f"{part}.bin"
    if not src.exists():
        sys.exit(f"❌ manifest part without bin: {src}")
    asset = f"apio-xilinx-chipdb-{part}-{date}.bin.tgz"
    dst = out / asset
    deterministic_tgz(src, dst, f"{part}.bin")
    entries.append({
        "part": part,
        "family": family_of(part),
        "asset": asset,
        "size": src.stat().st_size,
        "sha256": sha256(src),
        "tgz_size": dst.stat().st_size,
        "tgz_sha256": sha256(dst),
    })
    print(f"  {asset}  ({entries[-1]['size'] / 1e6:.0f} MB -> {entries[-1]['tgz_size'] / 1e6:.0f} MB)")

index = {
    "date": date,
    "chipdb_id": stamp,
    "note": "chipdb .bin files are platform-independent; sha256 is the "
            "UNCOMPRESSED bin the loader must end up with, tgz_sha256 the "
            "downloaded asset (a tar.gz with <part>.bin at its root). Bins "
            "are only valid with the openxc7 package of the SAME release "
            "tag (content changes across releases under the same names).",
    "parts": entries,
}
(out / f"apio-xilinx-chipdb-index-{date}.json").write_text(json.dumps(index, indent=2) + "\n")
print(f"index: apio-xilinx-chipdb-index-{date}.json ({len(entries)} parts, chipdb_id {stamp})")
PYEOF
