#!/usr/bin/env bash
#
# CI helper: install the oss-cad-suite this repo VALIDATES against.
#
# The L1/L2 gates run the packaged toolchain together with the same
# oss-cad-suite an apio user gets (yosys for synthesis, its python for
# fasm2frames).  This is the single place that states which oss-cad-suite
# version that is; scripts/check-versions.sh compares it against what
# apio's remote-config actually serves, so a drift shows up in the daily
# monitor instead of silently validating against the wrong tools.
#
# (The former end-user standalone installers live on the
# archive/standalone-installers branch — this repo is an apio package;
# non-apio users should use the upstream openXC7 project directly.)

set -euo pipefail

# Version of FPGAwars/tools-oss-cad-suite the CI validates against.
# Track the latest PROMOTED release (never a nightly pre-release).
OSS_CAD_SUITE_DATE="${OSS_CAD_SUITE_DATE:-2026-08-07}"

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

if [ -x "$OSS_CAD_SUITE_PATH/bin/yosys" ]; then
    echo "oss-cad-suite already present at $OSS_CAD_SUITE_PATH"
    exit 0
fi

echo "installing oss-cad-suite $OSS_CAD_SUITE_DATE -> $OSS_CAD_SUITE_PATH"
curl -fL -C - -O "$URL"
mkdir -p "$OSS_CAD_SUITE_PATH"
tar zxf "$PKG" -C "$OSS_CAD_SUITE_PATH"
rm -f "$PKG"
# macOS: drop the quarantine xattr so Gatekeeper allows the binaries
[ "$os" = "darwin" ] && xattr -dr com.apple.quarantine "$OSS_CAD_SUITE_PATH" 2>/dev/null || true
echo "done"
