

# -- INSTALACION DE Tools-openxc7
# -- Colocar en esta variable el path donde estan instaladas
# -- las tools-openxc7 en el sistema
# -- CAMBIA ESTO PARA ADAPTARLO A TU SISTEMA!!!!
#TOOLS_OPENXC7 = ${HOME}/Develop/Learn-Basys-3-board-OpenFPGA/dist

TOOLS_OPENXC7 ?= ${PWD}/../dist

# -- Variable de makefile
# -- Queremos usar el bash como shell
SHELL := /usr/bin/env bash

# -- Ruta donde esta la base de datos de prjxray
PRJXRAY_DB_DIR = ${TOOLS_OPENXC7}/share/nextpnr/external/prjxray-db

# -- Ruta de herramientas python de nextpnr
NEXTPNR_XILINX_PYTHON_DIR = ${TOOLS_OPENXC7}/share/nextpnr/python

# -- Directorio de la Base de datos binaria
CHIPDB_DIR = ${TOOLS_OPENXC7}/chipdb

# -- Variables de entorno
# -- PRJXRAY_DB_DIR: Ruta de la base de datos de prjxray
# -- Ej
# -- PRJXRAY_DB_DIR=/home/obijuan/Develop/Learn-Basys-3-board-OpenFPGA/
# --     dist/share/nextpnr/external/prjxray-db
# --
# -- NEXTPNR_XILINX_PYTHON_DIR: Ruta a herramientas python de nextpnr
# --
# -- Ej.
# -- NEXTPNR_XILINX_PYTHON_DIR = 
# --      /home/obijuan/Develop/Learn-Basys-3-board-OpenFPGA/
# --      dist/share/nextpnr/python



#-- Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN="\033[36m"
MAG="\033[35m"
RESET='\033[0m'  #-- Color por defecto

#-- Top module
TOP = ledon

#-- Descripcion de la FPGA usada
PART=xc7a35tcpg236
PART1=${PART}"-1"

#-- Fichero de restricciones
XDC = ../config/basys3.xdc

#-- Fichero con la base de datos
CHIPDB = ${CHIPDB_DIR}/${PART}.bin

#──────────────────────────────────────────────────
#─── Objetivo principal: GENERAR BITSTREAM BINARIO
#──────────────────────────────────────────────────
.PHONY: all
all: ${TOP}.bit


#──────────────────────────────────────────────────
#─── MOSTRAR LA AYUDA
#──────────────────────────────────────────────────
.PHONY: help
help:
	@echo -e ""
	@echo -e ${BLUE}"─────────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"SINTESIS DE HARDWARE EN PLACA BASYS3"${RESET}
	@echo -e $(GREEN)"FPGA ARTIX7 de Xilinx/AMD"${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────────"${RESET}
	@echo -e "Uso:"
	@echo -e "  "${YELLOW}"make"${RESET}"  ---> Generar bitstream"
	@echo -e "  "${YELLOW}"make"${CYAN}" TARGET"${RESET}
	@echo -e ""
	@echo -e ${CYAN}"TARGET:"${RESET}
	@echo -e ${MAG}"  help"${RESET}"         Sacar esta ayuda"
	@echo -e ${MAG}"  clean"${RESET}"        Borrar archivos de construccion"
	@echo -e ${MAG}"  chipdb"${RESET}"       Crear la base de datos para la Artix7"
	@echo -e ${MAG}"  clean-db"${RESET}"     Borrar la base de datos"
	@echo -e ${MAG}"  prog"${RESET}"         Cargar el bitstream en la FPGA (RAM)"
	@echo -e ${MAG}"  flash"${RESET}"        Grabar el bitstream en la memoria Flash"
	@echo -e ""



#──────────────────────────────────────────────────
#─── SINTESIS
#──────────────────────────────────────────────────
#-- Ficheros .v ---> .json
${TOP}.json: ${TOP}.v
	@echo
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"➡️  Sintetizando..."${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	yosys -p "synth_xilinx -arch xc7 -top ${TOP}; \
	          write_json ${TOP}.json" \
	          ${TOP}.v ${DEPS} -q
	@echo


#──────────────────────────────────────────────────
#─── RUTADO
#──────────────────────────────────────────────────
#-- .json --> .fasm
$(TOP).fasm: ${TOP}.json ${CHIPDB}
	@echo
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"➡️  Rutando..."${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	nextpnr-xilinx --chipdb ${CHIPDB} \
       --xdc ${XDC} --json ${TOP}.json --fasm ${TOP}.fasm #-q
	@echo


#──────────────────────────────────────────────────
#───  GENERACION DEL BITSTREAM
#──────────────────────────────────────────────────
#-- .fasm ---> .frames
$(TOP).frames: $(TOP).fasm
	@echo
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"➡️  Generando bitstream..."${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	fasm2frames --part ${PART1} \
  		--db-root ${PRJXRAY_DB_DIR}/artix7 \
  		${TOP}.fasm > ${TOP}.frames
	@echo


#──────────────────────────────────────────────────
#───  COMPRESION DEL BIT STREAM. FINAL: .bit
#──────────────────────────────────────────────────
#--- .frames ---> .bit
$(TOP).bit: $(TOP).frames
	@echo
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"➡️  Comprimiendo..."${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	xc7frames2bit --part_file ${PRJXRAY_DB_DIR}/artix7/${PART1}/part.yaml \
  		--part_name ${PART1} --frm_file ${TOP}.frames \
  		--output_file ${TOP}.bit
	@echo
	@echo -e ${GREEN}"─────────────────────────────────"
	@echo -e ${GREEN}"✅ OK! Bitstream GENERADO"${RESET}
	@echo -e ${GREEN}"─────────────────────────────────\n"${RESET}



#──────────────────────────────────────────────────
#───  Construccion de la base de datos
#──────────────────────────────────────────────────
.PHONY: chipdb
chipdb: ${CHIPDB}
	
${CHIPDB}:
	@echo
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"➡️  Generando base de datos..."${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	pypy3 ${NEXTPNR_XILINX_PYTHON_DIR}/bbaexport.py \
		  --device ${PART1} --bba ${PART}.bba
	bbasm -l ${PART}.bba ${CHIPDB}
	rm -f ${PART}.bba
	@echo

#-- Borrado de la base de datos
.PHONY: clean-db
clean-db:
	@echo
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"➡️  Borrando base de datos..."${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	rm -f ${CHIPDB}
	@echo


#──────────────────────────────────────────────────
#───  PROGRAMACION: Grabacion del bitstream en RAM
#──────────────────────────────────────────────────
.PHONY: prog
prog:	${TOP}.bit
	@echo -e ${YELLOW}"─────────────────────────────────────"${RESET}
	@echo -e ${YELLOW}"➡️  Cargando bitstream en RAM..."${RESET}
	@echo -e ${YELLOW}"─────────────────────────────────────"${RESET}
	openFPGALoader --board basys3 --bitstream ${TOP}.bit
	@echo -e ${GREEN}"─────────────────────────────────"
	@echo -e ${GREEN}"✅ OK! Bitstream CARGADO"${RESET}
	@echo -e ${GREEN}"─────────────────────────────────\n"${RESET}
	@echo


#──────────────────────────────────────────────────
#───  PROGRAMACION: Grabacion en memoria FLASH
#──────────────────────────────────────────────────
.PHONY: flash
flash:  ${TOP}.bit
	@echo -e ${YELLOW}"─────────────────────────────────────"${RESET}
	@echo -e ${YELLOW}"➡️  Cargando bitstream en FLASH..."${RESET}
	@echo -e ${YELLOW}"─────────────────────────────────────"${RESET}
	openFPGALoader --board basys3 --write-flash ${TOP}.bit
	@echo -e ${GREEN}"─────────────────────────────────"
	@echo -e ${GREEN}"✅ OK! Bitstream GRABADO"${RESET}
	@echo -e ${GREEN}"─────────────────────────────────\n"${RESET}
	@echo


#──────────────────────────────────────────────────
#───  LIMPIEZA
#──────────────────────────────────────────────────
.PHONY: clean
clean:
	@echo
	@echo -e ${RED}"➡️  Borrando ficheros..."${RESET}
	rm -rf *.fasm *.frames *.json *.bit
	@echo

