#!/usr/bin/env bash

# -- Load common helpers (install paths -> single source of truth)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib/common.sh"

printf "🔵 Borrando carpeta: $OSS_CAD_SUITE_PATH\n"
chmod -Rf +w "$OSS_CAD_SUITE_PATH"
rm -rf "$OSS_CAD_SUITE_PATH"
printf "\n"
