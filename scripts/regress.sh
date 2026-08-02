#!/usr/bin/env bash
#
# regress.sh -- run the regression suite against a package.
#
#   scripts/regress.sh <package.tgz|package-dir> [options]
#
# Options are passed straight through to regress/harness.py:
#   --design <name>      restrict to one design (repeatable)
#   --part <part>        restrict to one part (repeatable)
#   --update-baseline    record the measured values as the new baseline
#   --json <file>        also write the report as JSON
#   --keep               keep the work directory for inspection
#
# Needs yosys on PATH — from the pinned oss-cad-suite, the same one apio
# installs, so that measurements are comparable with what users get.

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

if ! command -v yosys >/dev/null 2>&1; then
    echo "❌ yosys not on PATH (install the pinned oss-cad-suite and re-run)" >&2
    exit 1
fi

exec python3 "$REPO_ROOT/regress/harness.py" "$@"
