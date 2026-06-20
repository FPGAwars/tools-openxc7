#!/usr/bin/env bash

# -- Load common helpers (install paths -> single source of truth)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib/common.sh"

printf "🔵 Borrando carpeta: $OPENXC7_INSTALL_PATH\n"
chmod -Rf +w "$OPENXC7_INSTALL_PATH"
rm -rf "$OPENXC7_INSTALL_PATH"
printf "\n"
