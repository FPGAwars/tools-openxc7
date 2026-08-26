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
#   scripts/chipdb-assets.sh <chipdb-dir> <out-dir> <YYYYMMDD> [prjxray-db]
#
# <chipdb-dir> must contain the manifest bins AND chipdb-id.txt (the
# identity stamp travels with the set; refuse to publish an unstamped one).
# With no fourth argument, the database is found beside chipdb/ in a complete
# package tree: ../share/nextpnr/external/prjxray-db.

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CHIPDB=${1:?usage: chipdb-assets.sh <chipdb-dir> <out-dir> <YYYYMMDD>}
OUT=${2:?missing out-dir}
DATE=${3:?missing YYYYMMDD date}
DATABASE=${4:-"$CHIPDB/../share/nextpnr/external/prjxray-db"}

[ -f "$CHIPDB/chipdb-id.txt" ] || { echo "❌ $CHIPDB has no chipdb-id.txt (unstamped set)" >&2; exit 1; }
mkdir -p "$OUT"

PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m pack.chipdb_assets \
    "$REPO_ROOT" "$CHIPDB" "$OUT" "$DATE" "$DATABASE"
