#!/usr/bin/env bash
#
# regress.sh -- run the regression suite against a package.
#
#   scripts/regress.sh <package.tgz|package-dir> [options]
#
# Options are passed straight through to the harness:
#   --list               show the test catalogue and exit (no package needed)
#   --test <name>        restrict to one test (repeatable)
#   --part <part>        restrict to one part (repeatable)
#   --tier <n>           run tiers up to n
#   --tag <tag>          run tests carrying this tag
#   --update-baseline    record the measured values as the new baseline
#   --json <file>        write the report as JSON
#   --markdown <file>    write the report as markdown (CI job summary)
#   --keep               keep the work directory for inspection
#
# A test is a directory under regress/tests/ with a test.json declaration —
# see regress/README.md. Adding one never requires touching code.
#
# Needs yosys on PATH — from the required oss-cad-suite version, the same one apio
# installs, so that measurements are comparable with what users get.

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

# --list needs no toolchain at all
case " $* " in
    *" --list "*) exec python3 "$REPO_ROOT/regress/harness" "$@" ;;
esac

if ! command -v yosys >/dev/null 2>&1; then
    echo "❌ yosys not on PATH (install the required oss-cad-suite version and re-run)" >&2
    exit 1
fi

exec python3 "$REPO_ROOT/regress/harness" "$@"
