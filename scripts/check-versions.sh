#!/usr/bin/env bash
#
# check-versions.sh -- is the openxc7 package aligned with the rest of apio?
#
# (a) yosys: the toolchain release this repo repackages (OPENXC7_RELEASE_TAG
#     in build-pre-release.yaml) was validated with one YosysHQ oss-cad-suite
#     tag, its yosys-release-tag. apio requires the oss-cad-suite package
#     it installs to carry the same one. A mismatch fails.
# (b) toolchain: OPENXC7_RELEASE_TAG against the latest release of the
#     toolchain repo. Informational: a newer one means a bump is due.
#
# Usage:
#   scripts/check-versions.sh
#
# Env: APIO_REMOTE_CONFIG_URL to use another apio remote-config
#      (default: apio-1.7.x.jsonc on apio's main).

set -euo pipefail

WORKFLOW="$(dirname "$0")/../.github/workflows/build-pre-release.yaml"
REMOTE_CONFIG=${APIO_REMOTE_CONFIG_URL:-https://raw.githubusercontent.com/FPGAwars/apio/main/remote-config/apio-1.7.x.jsonc}

# The value of a "  NAME: value" line of a workflow, without quotes.
workflow_value() {
    sed -n "s/^  $1: *\"\{0,1\}\([^\"]*\)\"\{0,1\} *$/\1/p" | head -n 1
}

openxc7_tag=$(workflow_value OPENXC7_RELEASE_TAG < "$WORKFLOW")
openxc7_repo=$(workflow_value OPENXC7_REPO < "$WORKFLOW")

# (a) The yosys of the toolchain release...
toolchain_yosys=$(curl -fsSL "https://github.com/$openxc7_repo/releases/download/$openxc7_tag/BUILD-INFO.json" |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["yosys-release-tag"])')

# ... and the one of the oss-cad-suite release apio installs: the
# YOSYS_RELEASE_TAG of tools-oss-cad-suite's workflow at that release's tag.
suite_tag=$(curl -fsSL "$REMOTE_CONFIG" | python3 -c '
import json, sys
lines = [line for line in sys.stdin if not line.lstrip().startswith("//")]
print(json.loads("".join(lines))["packages"]["oss-cad-suite"]["release"]["tag"])')
suite_yosys=$(curl -fsSL "https://raw.githubusercontent.com/FPGAwars/tools-oss-cad-suite/$suite_tag/.github/workflows/build-pre-release.yaml" |
    workflow_value YOSYS_RELEASE_TAG)

# (b) The latest release of the toolchain repo.
latest_url=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$openxc7_repo/releases/latest")
latest_tag=${latest_url##*/}

echo "openXC7 toolchain release:  $openxc7_repo $openxc7_tag (latest: $latest_tag)"
echo "  its yosys-release-tag:    $toolchain_yosys"
echo "apio oss-cad-suite release: $suite_tag ($REMOTE_CONFIG)"
echo "  its yosys-release-tag:    $suite_yosys"

if [ "$openxc7_tag" != "$latest_tag" ]; then
    echo "note: $openxc7_repo has a newer latest release, $latest_tag: bump OPENXC7_RELEASE_TAG?"
fi

if [ "$toolchain_yosys" != "$suite_yosys" ]; then
    echo "DRIFT: the toolchain was validated with yosys $toolchain_yosys, apio installs $suite_yosys" >&2
    exit 1
fi
echo "yosys aligned"
