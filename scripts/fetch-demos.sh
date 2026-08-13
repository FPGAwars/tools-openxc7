#!/usr/bin/env bash
#
# fetch-demos.sh -- materialise the third-party trees locked in
# regress/lock.json under regress/external/ (gitignored: locked, fetched,
# never committed).
#
# Idempotent: a tree already at the locked rev is left alone. Needs GitHub
# access — run it where that exists (dev machine, CI runner); on the build
# server the fetched tree arrives with the ordinary rsync instead.
#
# Usage:  scripts/fetch-demos.sh

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LOCK="$REPO_ROOT/regress/lock.json"

REPO=$(python3 -c "import json; print(json.load(open('$LOCK'))['demo-projects']['repository'])")
REV=$(python3 -c "import json; print(json.load(open('$LOCK'))['demo-projects']['rev'])")
DST="$REPO_ROOT/regress/external/demo-projects"

if [ -d "$DST/.git" ] && [ "$(git -C "$DST" rev-parse HEAD 2>/dev/null)" = "$REV" ]; then
    echo "demo-projects already at $REV"
    exit 0
fi

rm -rf "$DST"
mkdir -p "$DST"
git -C "$DST" init -q
git -C "$DST" remote add origin "https://github.com/$REPO.git"
git -C "$DST" fetch -q --depth 1 origin "$REV"
git -C "$DST" checkout -q FETCH_HEAD
echo "demo-projects fetched at $REV"
