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

# -w rather than \b: BSD/macOS regex has no \b in -E, and this must give
# the same answer on a dev mac and on the CI runner.
if git grep -n -i -w -E 'pinned|pinning|repin|repinned|unpinned' -- \
        . ':!README-archived.md' ':!doc'; then
    echo
    echo "❌ terminology: the lines above say pad when they mean version."
    echo "   Use version / tag / revision / \"bump the version\" (apio#924)."
    exit 1
fi
echo "terminology: OK — no pad-vs-version wording in the tree"
