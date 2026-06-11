#!/usr/bin/env bash

# ----------------------------------------------
# -- USER CONFIGURATION
# ----------------------------------------------
# -- Local path where to store the tools-openxc7 package
OPENXC7_INSTALL_PATH=$HOME/.local/openxc7

# -----------------------------------------------
# -- END OF USER CONFIGURATION
# -----------------------------------------------

# -- File for checking if it was already installed or not
CHECK_FILE=$OPENXC7_INSTALL_PATH/VERSION

# -- Date for the version to download
YEAR=2026
MONTH=06
DAY=11

# -- Openxc7 repo
REPO_URL="https://github.com/FPGAwars/tools-openxc7"

# -- Version to download
VERSION_ID=$YEAR$MONTH$DAY

# -- date
DATE="$YEAR-$MONTH-$DAY"

# -- Package name
PKG_NAME="apio-openxc7-linux-x86-64-"$VERSION_ID".tgz"

# -- Package URL
PKG_URL=$REPO_URL"/releases/download/"$DATE/$PKG_NAME

#-- ANSI colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN="\033[36m"
MAG="\033[35m"
RESET='\033[0m'

printf "\n"
printf "$YELLOW""────────────────────────────────\n"
printf "$YELLOW""  INSTALLING OPENXC7\n"
printf "$YELLOW""────────────────────────────────\n"
printf "$RESET"

# -- Check if it has been already installed
if [ -f "$CHECK_FILE" ]; then
    printf "📌 Tool already installed...\n"
else

    # -- Download the tarball
    printf "\n"
    printf "🔵 Downloading tarball: $PKG_NAME\n\n"
    printf "  ➡️  URL: $PKG_URL\n\n"
    wget -c -q --show-progress $PKG_URL
    printf "\n"

    # -- Create the installation folder, it is does not exist yet
    mkdir -p $OPENXC7_INSTALL_PATH

    # -- Uncompress it
    printf "🔵 Installing in $OPENXC7_INSTALL_PATH\n"
    printf "📦 Uncompressing..."
    printf "$PKG_NAME\n"
    tar zxf $PKG_NAME -C $OPENXC7_INSTALL_PATH
    printf "OK!\n"

fi
printf "\n"



