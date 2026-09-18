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
# The yosys-release-tag (the runtime matching key, apio#927) comes from the
# YOSYS_RELEASE_TAG env, declared at the top of build-pre-release.yaml and
# propagated through the platform workflows. GITHUB_* envs identify the
# build; local developer builds fall back to git so they get an honest
# BUILD-INFO too. The eigen-version is evaluated from the flake (see below).
# When GITHUB_STEP_SUMMARY is set the JSON is also exported to the run
# summary (same convention).

set -euo pipefail

[ $# -eq 4 ] || { echo "usage: $0 <target-platform> <date YYYY-MM-DD> <file-name> <out-file>" >&2; exit 2; }
PLAT=$1; DATE=$2; FNAME=$3; OUT=$4

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$HERE/.." && pwd)

# The upstream YosysHQ oss-cad-suite release this package expects at
# runtime -- the cross-package matching key apio checks (apio#927).
# Declared at the top of build-pre-release.yaml and propagated via the
# YOSYS_RELEASE_TAG env; local builds without it fall back to reading the
# installed validation env's own BUILD-INFO.json.
YOSYS_TAG="${YOSYS_RELEASE_TAG:-}"
if [ -z "$YOSYS_TAG" ]; then
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
        echo "warning: YOSYS_RELEASE_TAG unset and $OCS_ROOT/BUILD-INFO.json not found; yosys-release-tag=unknown" >&2
    fi
fi

# Provenance of the chipdb bins inside the package (apio#940 follow-up,
# asked by zapta): how they were obtained in THIS build and the identity
# stamp that identifies their content regardless of how they were obtained.
#   CHIPDB_SOURCE  generated | restored-from-cache   (unknown if unset)
#   CHIPDB_ID      the chipdb-id.txt stamp (hash of everything that
#                  determines the bins' content)  (unknown if unset)
# use-cached-chipdb is the boolean view of CHIPDB_SOURCE (name chosen by the
# apio maintainer): true only when the bins were restored from the
# revision-keyed CI cache instead of generated.
CHIPDB_SOURCE="${CHIPDB_SOURCE:-unknown}"
CHIPDB_ID="${CHIPDB_ID:-unknown}"
case "$CHIPDB_SOURCE" in
    restored-from-cache) CHIPDB_CACHE_USED=true ;;
    *)                   CHIPDB_CACHE_USED=false ;;
esac

NEXTPNR_REV=$(sed -n 's/.*rev = "\([0-9a-f]\{7,40\}\)".*/\1/p' "$REPO_ROOT/nix/nextpnr-xilinx.nix" | head -1)

# The Eigen release nextpnr was compiled against. placer_heap solves its
# analytic placement with Eigen, so its results move with the library even
# when the nextpnr revision does not -- the "same revision, different
# binary" trap behind the re-goldens upstream keeps hitting. The revision
# alone does not identify a build; this does.
#
# Read from the flake, never hardcoded: nix/nextpnr-xilinx.nix takes eigen
# from the flake's locked nixpkgs, so this reports whatever that revision
# of nixpkgs carries. The Windows package cross-compiles against the same
# nixpkgs (pkgsCross.mingwW64.eigen, nix/windows/default.nix), so the three
# platforms report the same release and the release-level composition
# (scripts/release-build-info.py) can treat it as a shared field.
# EIGEN_VERSION overrides, for a caller that already knows it.
EIGEN_VERSION="${EIGEN_VERSION:-}"
if [ -z "$EIGEN_VERSION" ]; then
    EIGEN_VERSION=$(nix --extra-experimental-features 'nix-command flakes' \
        eval --raw "$REPO_ROOT#nextpnr-xilinx" --apply \
        'drv: let found = builtins.filter (p: (p.pname or "") == "eigen") drv.buildInputs; in if found == [] then "unknown" else (builtins.head found).version' \
        2>/dev/null) || EIGEN_VERSION=""
    if [ -z "$EIGEN_VERSION" ]; then
        echo "warning: could not evaluate the eigen version from the flake; eigen-version=unknown" >&2
        EIGEN_VERSION="unknown"
    fi
fi

COMMIT=${GITHUB_SHA:-$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)}

# Normalize repo to lower case as we do with the other Apio packages. Not
# with bash's ${var,,}: the macOS runner's /bin/bash is 3.2, which has no
# case conversion ("bad substitution", darwin job, 2026-09-18).
repo=$(printf '%s' "${GITHUB_REPOSITORY:-}" | tr '[:upper:]' '[:lower:]')

cat > "$OUT" <<EOF
{
  "package-name"                   : "openxc7",
  "description"                    : "openXC7 toolchain for Xilinx 7-series FPGAs",
  "release-tag"                    : "$DATE",
  "yosys-release-tag"              : "$YOSYS_TAG",
  "nextpnr-xilinx-revision"        : "${NEXTPNR_REV:-unknown}",
  "eigen-version"                  : "$EIGEN_VERSION",
  "chipdb-source"                  : "$CHIPDB_SOURCE",
  "use-cached-chipdb"              : "$CHIPDB_CACHE_USED",
  "chipdb-id"                      : "$CHIPDB_ID",
  "build-repo"                     : "${repo:-local}",
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
