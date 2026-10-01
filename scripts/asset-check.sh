#!/usr/bin/env bash
#
# asset-check.sh -- check a release the way apio fetches it.
#
# apio derives the package name from the release TAG: tag 2026-10-01 ->
# apio-openxc7-<platform>-20261001.tgz at that release. A missing or
# misdated asset is a 404 at `apio packages install` time. This checks
# the six assets of a release: the three packages exist, BUILD-INFO.json
# names this tag, the parts index is schema 8, and SHA256SUMS matches.
# With --full it also downloads the three packages and checks their sha256.
#
# Usage:
#   scripts/asset-check.sh <tag> [--full]
#
# Env: ASSET_CHECK_REPO to check another repo (default FPGAwars/tools-openxc7).

set -euo pipefail

TAG=${1:?usage: scripts/asset-check.sh <tag> [--full]}
FULL=${2:-}
REPO=${ASSET_CHECK_REPO:-FPGAwars/tools-openxc7}
BASE="https://github.com/$REPO/releases/download/$TAG"
DATE=${TAG//-/}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"

for file in SHA256SUMS BUILD-INFO.json XILINX-PARTS-INDEX.json; do
    curl -fsSLO "$BASE/$file"
    echo "OK  $file"
done

for platform in linux-x86-64 darwin-arm64 windows-amd64; do
    package="apio-openxc7-$platform-$DATE.tgz"
    if [ "$FULL" = "--full" ]; then
        curl -fsSLO "$BASE/$package"
    else
        curl -fsSLI -o /dev/null "$BASE/$package"
    fi
    echo "OK  $package"
done

python3 - "$TAG" <<'EOF'
import json, sys
tag = sys.argv[1]
build_info = json.load(open("BUILD-INFO.json"))
assert build_info["release-tag"] == tag, f"BUILD-INFO.json names {build_info['release-tag']}"
index = json.load(open("XILINX-PARTS-INDEX.json"))
assert index["schema"] == 8, f"XILINX-PARTS-INDEX.json is schema {index['schema']}"
print(f"OK  release-tag {tag}, yosys-release-tag {build_info['yosys-release-tag']}, index schema 8")
EOF

# SHA256SUMS lists the other five assets. Without --full only the small
# files are here to check.
[ "$(wc -l < SHA256SUMS)" -eq 5 ] || { echo "SHA256SUMS does not list 5 assets" >&2; exit 1; }
if [ "$FULL" = "--full" ]; then
    shasum -a 256 -c SHA256SUMS
else
    grep -v '\.tgz$' SHA256SUMS | shasum -a 256 -c
fi

echo "asset-check: OK ($REPO $TAG)"
