#!/usr/bin/env bash

# ----------------------------------------------
# -- USER CONFIGURATION
# ----------------------------------------------
# -- Local path where to store the oss-cad-suite package
OSS_CAD_SUITE_PATH=$HOME/.local/oss-cad-suite

# -----------------------------------------------
# -- END OF USER CONFIGURATION
# -----------------------------------------------

# -- File for checking if it was already installed or not
CHECK_FILE=$OSS_CAD_SUITE_PATH/YOSYS-VERSION

# -- Date for the version to download
YEAR=2026
MONTH=03
DAY=24

# -- Oss_cad_suite repo
REPO_URL="https://github.com/FPGAwars/tools-oss-cad-suite"


# -- Version to download
VERSION_ID=$YEAR$MONTH$DAY

# -- date
DATE="$YEAR-$MONTH-$DAY"

# -- Package name
PKG_NAME="apio-oss-cad-suite-linux-x86-64-"$VERSION_ID".tgz"

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
printf "$YELLOW""  INSTALACION DE OSS-CAD-SUITE\n"
printf "$YELLOW""────────────────────────────────\n"
printf "$RESET"

# -- Check if it has been already installed
if [ -f "$CHECK_FILE" ]; then
    printf "📌 Herramienta instalada previamente...\n"
else

    # -- Descargar el paquete tgz
    printf "\n"
    printf "🔵 Descargando paquete: $PKG_NAME\n"
    printf "  ➡️  URL: $PKG_URL\n\n"
    wget -c -q --show-progress $PKG_URL
    printf "\n"

    # -- Crear directorio destino, si no exitiese
    mkdir -p $OSS_CAD_SUITE_PATH

    # -- Uncompress it
    printf "🔵 Instalando en $OSS_CAD_SUITE_PATH\n"
    printf "📦 Extrayendo..."
    tar zxf $PKG_NAME -C $OSS_CAD_SUITE_PATH
    printf "OK!\n"
fi
printf "\n"


