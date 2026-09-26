#!/usr/bin/env bash
#
# chipdb-assets.sh -- write XILINX-PARTS-INDEX.json from a stamped chipdb
# directory.
#
# The name is historical: schema 7 and earlier also built one
# apio-xilinx-chipdb-<die>-<YYYYMMDD>.bin.tgz per die here, and apio
# downloaded it (apio#947). Schema 8 ships those files inside the platform
# packages, so this script writes the index only. The module that owns the
# format is pack/parts_index.py; pack/chipdb_assets.py inventories the
# packaged prjxray database and fills the document.
#
# The index keeps one name everywhere -- as a release asset and at the
# root of every package -- because the release it belongs to is written
# inside it (release-tag). Named XILINX-PARTS-INDEX.json since apio#1002
# (PARTS-INDEX.json before it, apio#990).
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
