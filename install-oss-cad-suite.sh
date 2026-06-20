#!/usr/bin/env bash

# -- Load common helpers, version pins and platform detection
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib/common.sh"
detect_platform || exit 1

# -- File for checking if it was already installed or not
CHECK_FILE="$OSS_CAD_SUITE_PATH/YOSYS-VERSION"

# -- Version, package name and URL (per OS/arch)
VERSION_ID="$(date_to_id "$OSS_CAD_SUITE_DATE")"
PKG_NAME="$(pkg_name oss-cad-suite "$VERSION_ID")"
PKG_URL="$OSS_CAD_SUITE_REPO/releases/download/$OSS_CAD_SUITE_DATE/$PKG_NAME"

banner "INSTALLING OSS-CAD-SUITE"

# -- Check if it has been already installed
if [ -f "$CHECK_FILE" ]; then
    printf "📌 Tool already installed...\n"
else

    # -- Download the .tgz (curl/wget, resumable)
    printf "\n"
    printf "🔵 Downloading tarball: $PKG_NAME\n"
    printf "  ➡️  URL: $PKG_URL\n\n"
    download "$PKG_URL"
    printf "\n"

    # -- Create the installation folder, if it does not exist yet
    mkdir -p "$OSS_CAD_SUITE_PATH"

    # -- Uncompress it
    printf "🔵 Installing in $OSS_CAD_SUITE_PATH\n"
    printf "📦 Uncompressing..."
    tar zxf "$PKG_NAME" -C "$OSS_CAD_SUITE_PATH"

    # -- macOS: drop the quarantine xattr so Gatekeeper allows the binaries
    strip_quarantine "$OSS_CAD_SUITE_PATH"
    printf "OK!\n"
fi
printf "\n"
