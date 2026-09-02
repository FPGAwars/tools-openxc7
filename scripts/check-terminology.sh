#!/usr/bin/env bash
#
# check-terminology.sh -- the house rule of apio#924, enforced.
#
# In an FPGA ecosystem the words below read as physical pads, and using
# them for "a fixed version" confused the apio maintainer badly enough
# that the project banned them everywhere: code comments, commit
# messages, workflow names, docs, issue replies, release notes. Say
# version, tag, revision, or "bump the version".
#
# Only the unambiguous forms are gated. Bare "pin"/"pins" is legitimate
# and common here -- package_pins.csv, PACKAGE_PIN, e2e/gen_xdc.py, the
# DI/WE discussions in the test READMEs -- so it is NOT matched: a check
# that cried wolf on real pads would be turned off within a week.
#
# Excluded by name: README-archived.md and doc/, the original toolchain
# documentation by Obijuan, preserved untouched.
#
#   scripts/check-terminology.sh [repo-root]

set -euo pipefail

ROOT=${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
cd "$ROOT"

# Assembled from the root word, so this file does not match its own rule:
# git grep reads every tracked file, this one included, and an exclusion
# would blind the check to whatever else the file grows.
ROOT=pin
PATTERN="${ROOT}ned|${ROOT}ning|re${ROOT}|re${ROOT}ned|un${ROOT}ned"

# -w rather than \b: BSD/macOS regex has no \b in -E, and this must give
# the same answer on a dev mac and on the CI runner.
#
# The exit code is read, not just tested for truth: `git grep` says 1 for
# "no matches" and 128 for "I could not look" (outside a git repository,
# which is exactly what a copy of the tree without .git is -- the build
# server keeps one). An `if` treats both as false, so this check used to
# report OK on a tree it had not read a single line of.
STATUS=0
git grep -n -i -w -E "$PATTERN" -- . ':!README-archived.md' ':!doc' || STATUS=$?
case $STATUS in
    0)
        echo
        echo "❌ terminology: the lines above say pad when they mean version."
        echo "   Use version / tag / revision / \"bump the version\" (apio#924)."
        exit 1
        ;;
    1) echo "terminology: OK — no pad-vs-version wording in the tree" ;;
    *)
        echo "❌ terminology: git grep failed (exit $STATUS) in $PWD" >&2
        echo "   nothing was checked. Is this a git repository?" >&2
        exit 2
        ;;
esac
