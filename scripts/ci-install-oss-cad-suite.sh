#!/usr/bin/env bash
#
# CI helper: install the oss-cad-suite this repo VALIDATES against.
#
# The L1/L2 gates run the packaged toolchain together with the same
# oss-cad-suite an apio user gets (yosys for synthesis, its python for
# fasm2frames).  This script states NO version: the release to install is
# passed in OSS_CAD_SUITE_DATE, whose single literal lives in
# build-pre-release.yaml (OSS_CAD_SUITE_RELEASE).  scripts/check-versions.sh
# reads that literal and compares it against what apio's remote-configs
# serve, so a drift shows up in the daily monitor instead of silently
# validating against the wrong tools.
#
# (The former end-user standalone installers live on the
# archive/standalone-installers branch — this repo is an apio package;
# non-apio users should use the upstream openXC7 project directly.)

set -euo pipefail

# Release of FPGAwars/tools-oss-cad-suite to install (YYYY-MM-DD). No
# default on purpose: a second literal here is what made a version bump
# silently install the old suite (apio#1094).
: "${OSS_CAD_SUITE_DATE:?set OSS_CAD_SUITE_DATE=<tools-oss-cad-suite release YYYY-MM-DD> (the literal lives in build-pre-release.yaml, OSS_CAD_SUITE_RELEASE)}"
case "$OSS_CAD_SUITE_DATE" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
    *) echo "OSS_CAD_SUITE_DATE must be YYYY-MM-DD, got '$OSS_CAD_SUITE_DATE'" >&2; exit 2 ;;
esac

OSS_CAD_SUITE_REPO="https://github.com/FPGAwars/tools-oss-cad-suite"
OSS_CAD_SUITE_PATH="${OSS_CAD_SUITE_PATH:-$HOME/.local/oss-cad-suite}"

case "$(uname -s)" in
    Linux)  os="linux"  ;;
    Darwin) os="darwin" ;;
    *) echo "unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
    x86_64|amd64)  arch="x86-64" ;;
    arm64|aarch64) [ "$os" = "darwin" ] && arch="arm64" || arch="aarch64" ;;
    *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;;
esac

PKG="apio-oss-cad-suite-${os}-${arch}-${OSS_CAD_SUITE_DATE//-/}.tgz"
URL="$OSS_CAD_SUITE_REPO/releases/download/$OSS_CAD_SUITE_DATE/$PKG"

# The suite on disk must BE the requested release (a stale cache or a
# half-changed version is the failure this guards against) and must say
# which yosys it repackages: that tag goes into every package's BUILD-INFO
# (apio#927), read by scripts/build-info.sh from the same file.
verify_installed() {
    python3 - "$OSS_CAD_SUITE_PATH/BUILD-INFO.json" "$OSS_CAD_SUITE_DATE" <<'PYEOF'
import json, sys
path, want = sys.argv[1], sys.argv[2]
try:
    info = json.load(open(path))
except (OSError, ValueError) as e:
    sys.exit(f"::error::cannot read {path}: {e}")
got = info.get("release-tag")
yosys = info.get("yosys-release-tag")
if got != want:
    sys.exit(f"::error::oss-cad-suite on disk is release {got!r}, requested {want!r}")
if not yosys:
    sys.exit(f"::error::{path} has no yosys-release-tag")
print(f"oss-cad-suite release {got} (yosys-release-tag {yosys})")
PYEOF
}

if [ -x "$OSS_CAD_SUITE_PATH/bin/yosys" ]; then
    echo "oss-cad-suite already present at $OSS_CAD_SUITE_PATH"
    verify_installed
    exit 0
fi

echo "installing oss-cad-suite $OSS_CAD_SUITE_DATE -> $OSS_CAD_SUITE_PATH"
curl -fL -C - -O "$URL"
mkdir -p "$OSS_CAD_SUITE_PATH"
tar zxf "$PKG" -C "$OSS_CAD_SUITE_PATH"
rm -f "$PKG"
# macOS: drop the quarantine xattr so Gatekeeper allows the binaries
[ "$os" = "darwin" ] && xattr -dr com.apple.quarantine "$OSS_CAD_SUITE_PATH" 2>/dev/null || true
verify_installed
echo "done"
