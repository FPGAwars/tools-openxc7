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

if [ ! -f "$CHECK_FILE" ]; then
    printf "📦 Extrayendo..."
    tar zxf $PKG_NAME -C $OSS_CAD_SUITE_PATH
    printf "OK!\n"
else
    printf "📌 Herramienta instalada previamente... se omite\n"
fi

printf "\n"
