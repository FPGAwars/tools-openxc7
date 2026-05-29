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
MONTH=05
DAY=29

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

#-- Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN="\033[36m"
MAG="\033[35m"
RESET='\033[0m'  #-- Color por defecto

printf "\n"
printf "$YELLOW""────────────────────────────────\n"
printf "$YELLOW""  INSTALACION DE OPENXC7\n"
printf "$YELLOW""────────────────────────────────\n"
printf "$RESET"

# -- Descargar el paquete tgz
printf "\n"
printf "🔵 Descargando paquete: $PKG_NAME\n\n"
printf "  ➡️  URL: $PKG_URL\n\n"
wget -c -q --show-progress $PKG_URL
printf "\n"

# -- Crear directorio destino, si no exitiese
mkdir -p $OPENXC7_INSTALL_PATH

# -- Uncompress it
printf "🔵 Instalando en $OPENXC7_INSTALL_PATH\n"

if [ ! -f "$CHECK_FILE" ]; then
    printf "📦 Extrayendo..."
    printf "$PKG_NAME\n"
    tar zxf $PKG_NAME -C $OPENXC7_INSTALL_PATH
    printf "OK!\n"
else
    printf "📌 Herramienta instalada previamente... se omite\n"
fi

printf "\n"

