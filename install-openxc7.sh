#!/usr/bin/env bash

# -- Load common helpers, version pins and platform detection
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib/common.sh"
detect_platform || exit 1

# -- File for checking if it was already installed or not
CHECK_FILE="$OPENXC7_INSTALL_PATH/VERSION"

# -- Version, package name and URL (per OS/arch)
VERSION_ID="$(date_to_id "$OPENXC7_DATE")"
PKG_NAME="$(pkg_name openxc7 "$VERSION_ID")"
PKG_URL="$OPENXC7_REPO/releases/download/$OPENXC7_DATE/$PKG_NAME"

banner "INSTALLING OPENXC7"

# -- Check if it has been already installed
if [ -f "$CHECK_FILE" ]; then
    printf "📌 Tool already installed...\n"
else

    # -- Download the tarball (curl/wget, resumable)
    printf "\n"
    printf "🔵 Downloading tarball: $PKG_NAME\n"
    printf "  ➡️  URL: $PKG_URL\n\n"
    download "$PKG_URL"
    printf "\n"

    # -- Create the installation folder, if it does not exist yet
    mkdir -p "$OPENXC7_INSTALL_PATH"

    # -- Uncompress it
    printf "🔵 Installing in $OPENXC7_INSTALL_PATH\n"
    printf "📦 Uncompressing... $PKG_NAME\n"
    tar zxf "$PKG_NAME" -C "$OPENXC7_INSTALL_PATH"

    # -- macOS: drop the quarantine xattr so Gatekeeper allows the binaries
    strip_quarantine "$OPENXC7_INSTALL_PATH"
    printf "OK!\n"
fi
printf "\n"
