#!/usr/bin/env bash

# ----------------------------------------------
# -- USER CONFIGURATION
# ----------------------------------------------
# -- Local path where to store the tools-openxc7 package
OSS_CAD_SUITE_PATH=$HOME/.local/oss-cad-suite

# -----------------------------------------------
# -- END OF USER CONFIGURATION
# -----------------------------------------------

OSS_CAD_SUITE=OSS_CAD_SUITE_PATH/openxc7

printf "🔵 Borrando carpeta: $OSS_CAD_SUITE\n"
chmod -Rf +w $OSS_CAD_SUITE
rm -rf $OSS_CAD_SUITE
printf "\n"


