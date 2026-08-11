#!/usr/bin/env bash
#
# build-info.sh -- compose the ecosystem-convention BUILD-INFO.json.
#
# Every apio package carries a BUILD-INFO.json at its root describing the
# package and the build that produced it (FPGAwars convention, see
# tools-oss-cad-suite). Usage:
#
#   scripts/build-info.sh <target-platform> <date YYYY-MM-DD> <file-name> <out-file>
#
# The apio oss-cad-suite dependency tag comes from
# scripts/ci-install-oss-cad-suite.sh -- the single place that states it
# (check-versions.sh compares that same value against apio's remote-config).
# GITHUB_* envs identify the build; local developer builds fall back to git
# so they get an honest BUILD-INFO too. When GITHUB_STEP_SUMMARY is set the
# JSON is also exported to the run summary (same convention).

set -euo pipefail

[ $# -eq 4 ] || { echo "usage: $0 <target-platform> <date YYYY-MM-DD> <file-name> <out-file>" >&2; exit 2; }
PLAT=$1; DATE=$2; FNAME=$3; OUT=$4

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$HERE/.." && pwd)

OCS=${OSS_CAD_SUITE_DATE:-$(sed -n 's/^OSS_CAD_SUITE_DATE="\${OSS_CAD_SUITE_DATE:-\(.*\)}"$/\1/p' "$HERE/ci-install-oss-cad-suite.sh")}
[ -n "$OCS" ] || { echo "could not resolve the apio oss-cad-suite tag from ci-install-oss-cad-suite.sh" >&2; exit 1; }

# The upstream YosysHQ oss-cad-suite release, re-exported from the installed
# apio oss-cad-suite package's own BUILD-INFO.json (its declared field, so
# the match semantics are exact). This is the version-matching key apio
# checks at runtime across packages (apio#927): repackaging bumps of the
# apio oss-cad-suite that keep the same upstream yosys do not invalidate
# this package.
OCS_ROOT="${OSS_CAD_SUITE_PATH:-$HOME/.local/oss-cad-suite}"
YOSYS_TAG="unknown"
if [ -f "$OCS_ROOT/BUILD-INFO.json" ]; then
    YOSYS_TAG=$(python3 -c "
import json, sys
try:
    print(json.load(open(sys.argv[1])).get('yosys-release-tag') or 'unknown')
except Exception:
    print('unknown')" "$OCS_ROOT/BUILD-INFO.json")
else
    echo "warning: $OCS_ROOT/BUILD-INFO.json not found; yosys-release-tag=unknown" >&2
fi

NEXTPNR_REV=$(sed -n 's/.*rev = "\([0-9a-f]\{7,40\}\)".*/\1/p' "$REPO_ROOT/nix/nextpnr-xilinx.nix" | head -1)

COMMIT=${GITHUB_SHA:-$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)}

cat > "$OUT" <<EOF
{
  "package-name"                   : "openxc7",
  "description"                    : "openXC7 toolchain for Xilinx 7-series FPGAs",
  "release-tag"                    : "$DATE",
  "apio-oss-cad-suite-release-tag" : "$OCS",
  "yosys-release-tag"              : "$YOSYS_TAG",
  "nextpnr-xilinx-revision"        : "${NEXTPNR_REV:-unknown}",
  "build-repo"                     : "${GITHUB_REPOSITORY:-local}",
  "build-workflow"                 : "${GITHUB_WORKFLOW:-local}",
  "workflow-run-id"                : "${GITHUB_RUN_ID:-local}",
  "workflow-run-number"            : "${GITHUB_RUN_NUMBER:-local}",
  "build-time"                     : "$(date -u '+%Y-%m-%d %H:%M:%S UTC')",
  "commit"                         : "$COMMIT",
  "target-platform"                : "$PLAT",
  "file-name"                      : "$FNAME"
}
EOF

python3 -m json.tool "$OUT" > /dev/null

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    { echo "### BUILD-INFO.json ($PLAT)"; echo '```json'; cat "$OUT"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
fi
echo "BUILD-INFO composed: $OUT"
