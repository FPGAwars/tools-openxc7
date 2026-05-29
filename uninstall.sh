#!/usr/bin/env bash

# ----------------------------------------------
# -- USER CONFIGURATION
# ----------------------------------------------
# -- Local path where to store the tools-openxc7 package
OPENXC7_INSTALL_PATH=$HOME/.local/openxc7

# -----------------------------------------------
# -- END OF USER CONFIGURATION
# -----------------------------------------------

OPENXC7=$OPENXC7_INSTALL_PATH

printf "🔵 Borrando carpeta: $OPENXC7\n"
chmod -Rf +w $OPENXC7
rm -rf $OPENXC7
printf "\n"


