#!/usr/bin/env bash
#
# chipdb-assets.sh -- build the per-FPGA chipdb release assets and the
# XILINX-PARTS-INDEX document that maps parts to them.
#
# The chipdb .bin files are platform-independent, so they are published
# ONCE per release as individual gzipped assets next to the platform
# tarballs, and the packages themselves ship none of them: apio downloads
# the one the board needs (apio#947). What tells apio which asset to fetch
# and what it must end up with on disk is the index built here:
#
#   apio-xilinx-chipdb-<base-part>-<YYYYMMDD>.bin.tgz  one per chipdb file
#   XILINX-PARTS-INDEX.json                            the index itself
#
# The index keeps that one name everywhere -- as a release asset and at
# the root of every package -- because the release it belongs to is
# written inside it (release-tag), which is what a reader checks anyway.
# Named XILINX-PARTS-INDEX.json since apio#1002 (PARTS-INDEX.json before
# it, apio#990). The per-FPGA assets stay dated: they are opaque payloads.
#
# Naming and format agreed with the apio maintainer (apio#897/#900): the
# apio-xilinx-chipdb- prefix groups after the three platform packages in
# the release listing; .bin.tgz = a deterministic tar.gz containing
# <part>.bin at its root (apio reuses its package-archive handling).
#
# Every asset carries the tag's date (house rule: a mistagged asset must
# be impossible to fetch by accident). The index records, per part, the
# chipdb file it needs and the sha256 of BOTH that file (what the loader
# must end up with on disk) and the gzip (what it downloads), plus the
# chipdb identity stamp, plus every part the packaged database supports
# but this release did not build (so apio can say "not in this release"
# instead of "unknown part").
#
# Usage:
#   scripts/chipdb-assets.sh <chipdb-dir> <out-dir> <YYYYMMDD> [prjxray-db]
#
# <chipdb-dir> must contain the manifest bins AND chipdb-id.txt (the
# identity stamp travels with the set; refuse to publish an unstamped one).
# With no fourth argument, the database is found beside chipdb/ in a complete
# package tree: ../share/nextpnr/external/prjxray-db.
#
# Env:
#   OPENXC7_ASSET_JOBS   parts compressed and hashed at once (default 1)
#   OPENXC7_ASSET_CACHE  directory of date-free <part>.bin.tgz to reuse.
#                        Compressing 1.1 GB is the slow half of this step
#                        and the result depends only on the bins, so a
#                        cache stamped with the same chipdb identity is
#                        copied instead of rebuilt (and refreshed when
#                        the stamp differs). Hashes are always taken from
#                        the bytes about to be published.

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CHIPDB=${1:?usage: chipdb-assets.sh <chipdb-dir> <out-dir> <YYYYMMDD>}
OUT=${2:?missing out-dir}
DATE=${3:?missing YYYYMMDD date}
DATABASE=${4:-"$CHIPDB/../share/nextpnr/external/prjxray-db"}

[ -f "$CHIPDB/chipdb-id.txt" ] || { echo "❌ $CHIPDB has no chipdb-id.txt (unstamped set)" >&2; exit 1; }
mkdir -p "$OUT"

ARGS=()
if [ -n "${OPENXC7_ASSET_CACHE:-}" ]; then ARGS+=(--cache "$OPENXC7_ASSET_CACHE"); fi
if [ -n "${OPENXC7_ASSET_JOBS:-}" ]; then ARGS+=(--jobs "$OPENXC7_ASSET_JOBS"); fi

# ${ARGS[@]+...}: bash 3.2 (macOS) treats an empty array as unset under -u
PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m pack.chipdb_assets \
    "$REPO_ROOT" "$CHIPDB" "$OUT" "$DATE" "$DATABASE" ${ARGS[@]+"${ARGS[@]}"}
