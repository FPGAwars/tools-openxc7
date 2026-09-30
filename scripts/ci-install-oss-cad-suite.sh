#!/usr/bin/env bash
#
# CI helper: install the oss-cad-suite this repo VALIDATES against.
#
# The L1/L2 gates run the packaged toolchain together with the yosys (and
# the python for fasm2frames) of YosysHQ's oss-cad-suite.  apio users get the
# same yosys through its `oss-cad-suite` package, which repackages that
# YosysHQ release.  This script states NO version: the YosysHQ release to
# install is passed in YOSYS_RELEASE_TAG, whose single literal lives in
# build-pre-release.yaml.  scripts/check-versions.sh reads that literal and
# compares it against the yosys tag of the package apio's remote-configs
# serve, so a drift shows up in the daily monitor instead of silently
# validating against the wrong tools.
#
# (The former end-user standalone installers live on the
# archive/standalone-installers branch — this repo is an apio package;
# non-apio users should use the upstream openXC7 project directly.)

set -euo pipefail

# Release of YosysHQ/oss-cad-suite-build to install (YYYY-MM-DD). No
# default on purpose: a second literal here is what made a version bump
# silently install the old suite (apio#1094).
: "${YOSYS_RELEASE_TAG:?set YOSYS_RELEASE_TAG=<YosysHQ oss-cad-suite-build release YYYY-MM-DD> (the literal lives in build-pre-release.yaml)}"
case "$YOSYS_RELEASE_TAG" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
    *) echo "YOSYS_RELEASE_TAG must be YYYY-MM-DD, got '$YOSYS_RELEASE_TAG'" >&2; exit 2 ;;
esac

OSS_CAD_SUITE_REPO="https://github.com/YosysHQ/oss-cad-suite-build"
OSS_CAD_SUITE_PATH="${OSS_CAD_SUITE_PATH:-$HOME/.local/oss-cad-suite}"
DIGITS="${YOSYS_RELEASE_TAG//-/}"

case "$(uname -s)" in
    Linux)  os="linux"  ;;
    Darwin) os="darwin" ;;
    *) echo "unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
    x86_64|amd64)  arch="x64" ;;
    arm64|aarch64) arch="arm64" ;;
    *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;;
esac

PKG="oss-cad-suite-${os}-${arch}-${DIGITS}.tgz"
URL="$OSS_CAD_SUITE_REPO/releases/download/$YOSYS_RELEASE_TAG/$PKG"

# The suite on disk must BE the requested release (a stale cache or a
# half-changed version is the failure this guards against): the VERSION file
# of a YosysHQ suite holds the release date in digits.
verify_installed() {
    local got
    got=$(tr -d '[:space:]' < "$OSS_CAD_SUITE_PATH/VERSION" 2>/dev/null) || got=""
    if [ "$got" != "$DIGITS" ]; then
        echo "::error::oss-cad-suite on disk is release '${got:-unknown}' (VERSION), requested '$DIGITS' ($YOSYS_RELEASE_TAG)" >&2
        exit 1
    fi
    echo "oss-cad-suite (yosys release $YOSYS_RELEASE_TAG)"
}

if [ -x "$OSS_CAD_SUITE_PATH/bin/yosys" ]; then
    echo "oss-cad-suite already present at $OSS_CAD_SUITE_PATH"
    verify_installed
    exit 0
fi

echo "installing oss-cad-suite $YOSYS_RELEASE_TAG -> $OSS_CAD_SUITE_PATH"
curl -fL -C - -O "$URL"
mkdir -p "$OSS_CAD_SUITE_PATH"
# the upstream tarball extracts under one top directory (oss-cad-suite/)
tar zxf "$PKG" -C "$OSS_CAD_SUITE_PATH" --strip-components=1
rm -f "$PKG"
# macOS: drop the quarantine xattr so Gatekeeper allows the binaries
[ "$os" = "darwin" ] && xattr -dr com.apple.quarantine "$OSS_CAD_SUITE_PATH" 2>/dev/null || true
verify_installed
echo "done"
