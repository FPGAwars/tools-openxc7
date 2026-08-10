#!/usr/bin/env bash
#
# Common helpers and version pins for the openXC7 installers.
# Single source of truth -- source this from install-*.sh / uninstall-*.sh.

# ---------------------------------------------------------------------------
# Version pins: date of the GitHub release to download, one per toolchain.
# Keep these in ONE place to avoid drift between the installer scripts.
# Overridable via environment (CI/validation use disposable prefixes and may
# pin a different oss-cad-suite date); defaults preserve the user behavior.
# ---------------------------------------------------------------------------
# They must track the latest PROMOTED release of each repo (nightly
# prereleases are excluded on purpose) and match what apio installs via its
# remote-config. scripts/check-versions.sh verifies all three agree.
OSS_CAD_SUITE_DATE="${OSS_CAD_SUITE_DATE:-2026-08-07}"
OPENXC7_DATE="${OPENXC7_DATE:-2026-08-07}"

# -- Upstream repos
OSS_CAD_SUITE_REPO="https://github.com/FPGAwars/tools-oss-cad-suite"
OPENXC7_REPO="https://github.com/FPGAwars/tools-openxc7"

# -- Local install destinations (overridable via environment)
OSS_CAD_SUITE_PATH="${OSS_CAD_SUITE_PATH:-$HOME/.local/oss-cad-suite}"
OPENXC7_INSTALL_PATH="${OPENXC7_INSTALL_PATH:-$HOME/.local/openxc7}"

# -- ANSI colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN="\033[36m"
MAG="\033[35m"
RESET='\033[0m'

# ---------------------------------------------------------------------------
# detect_platform -> sets PLATFORM_TOKEN: linux-x86-64, linux-aarch64,
# darwin-arm64 or darwin-x86-64. Mirrors plat_token() in openxc7-pack.py and
# the release-asset naming of FPGAwars/tools-oss-cad-suite (note the
# asymmetry: arm64 on darwin, aarch64 on linux).
# ---------------------------------------------------------------------------
detect_platform() {
    local os arch
    case "$(uname -s)" in
        Linux)  os="linux"  ;;
        Darwin) os="darwin" ;;
        *) printf "❌ Unsupported OS: %s\n" "$(uname -s)" >&2; return 1 ;;
    esac
    case "$(uname -m)" in
        x86_64|amd64)  arch="x86-64" ;;
        arm64|aarch64) [ "$os" = "darwin" ] && arch="arm64" || arch="aarch64" ;;
        *) printf "❌ Unsupported architecture: %s\n" "$(uname -m)" >&2; return 1 ;;
    esac
    PLATFORM_TOKEN="${os}-${arch}"
}

# pkg_name <tool> <version_id>  ->  apio-<tool>-<token>-<version_id>.tgz
pkg_name() {
    printf "apio-%s-%s-%s.tgz" "$1" "$PLATFORM_TOKEN" "$2"
}

# date_to_id YYYY-MM-DD -> YYYYMMDD
date_to_id() {
    printf "%s" "${1//-/}"
}

# banner <text> -- yellow section header
banner() {
    printf "\n$YELLOW""────────────────────────────────\n"
    printf "$YELLOW""  %s\n" "$1"
    printf "$YELLOW""────────────────────────────────\n"
    printf "$RESET"
}

# download <url> -- fetch into the current dir, resuming if interrupted.
# curl is preferred because macOS ships curl but not wget; -L follows the
# GitHub release redirect to the storage backend.
download() {
    local url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl -fL -C - -O "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -c -q --show-progress "$url"
    else
        printf "❌ Neither curl nor wget found in PATH\n" >&2
        return 1
    fi
}

# strip_quarantine <dir> -- remove the com.apple.quarantine xattr on macOS so
# Gatekeeper does not block the freshly downloaded, ad-hoc-signed binaries.
# No-op on Linux. (Full Developer-ID notarization is a later phase.)
strip_quarantine() {
    [ "$(uname -s)" = "Darwin" ] || return 0
    xattr -dr com.apple.quarantine "$1" 2>/dev/null || true
}
