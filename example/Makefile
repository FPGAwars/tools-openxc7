

# -- Folder were the binaries are located
# -- It is read from the TOOLS_OPENXC7 env variable, defined
# -- when start is called (. start)
# -- If it is not defined, it is read from the distribution itself,
# -- generated in the dist folder when openxc7-pack.py is executed
TOOLS_OPENXC7 ?= ${PWD}/../dist

# -- Makefile variables
# -- We want to use bash as the shell
SHELL := /usr/bin/env bash

# -- Path were the prjxray database is located
PRJXRAY_DB_DIR = ${TOOLS_OPENXC7}/share/nextpnr/external/prjxray-db

# -- Path of the python tools for the nextpnr executable
NEXTPNR_XILINX_PYTHON_DIR = ${TOOLS_OPENXC7}/share/nextpnr/python

# -- Folder for the binary database
CHIPDB_DIR = ${TOOLS_OPENXC7}/chipdb

#-- ANSI Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN="\033[36m"
MAG="\033[35m"
RESET='\033[0m'  #-- Default colors

#-- Top module
TOP = ledon

#-- FPGA model
PART=xc7a35tcpg236
PART1=${PART}"-1"

#-- Constraint file
XDC = ../config/basys3.xdc

#-- Database file
CHIPDB = ${CHIPDB_DIR}/${PART}.bin

#──────────────────────────────────────────────────
#─── Main target: GENERATE THE BITSTREAM
#──────────────────────────────────────────────────
.PHONY: all
all: ${TOP}.bit


#──────────────────────────────────────────────────
#─── SHOW THE HELP
#──────────────────────────────────────────────────
.PHONY: help
help:
	@echo -e ""
	@echo -e ${BLUE}"─────────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"HARDWARE SYNTHESIS FOR THE BASYS3 BOARD"${RESET}
	@echo -e $(GREEN)"ARTIX7 FPGA from Xilinx/AMD"${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────────"${RESET}
	@echo -e "Uso:"
	@echo -e "  "${YELLOW}"make"${RESET}"  ---> Generate the bitstream"
	@echo -e "  "${YELLOW}"make"${CYAN}" TARGET"${RESET}
	@echo -e ""
	@echo -e ${CYAN}"TARGET:"${RESET}
	@echo -e ${MAG}"  help"${RESET}"         Show this help"
	@echo -e ${MAG}"  clean"${RESET}"        Clean building artifacts"
	@echo -e ${MAG}"  chipdb"${RESET}"       Build the Artix7 Database"
	@echo -e ${MAG}"  clean-db"${RESET}"     Delete the database"
	@echo -e ${MAG}"  prog"${RESET}"         Upload the bitstream in the FPGA (RAM)"
	@echo -e ${MAG}"  flash"${RESET}"        Write the bitstream in the flash memory"
	@echo -e ""



#──────────────────────────────────────────────────
#─── SYNTHESIS
#──────────────────────────────────────────────────
#-- Ficheros .v ---> .json
${TOP}.json: ${TOP}.v
	@echo
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"➡️  Synthesizing..."${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	yosys -p "synth_xilinx -arch xc7 -top ${TOP}; \
	          write_json ${TOP}.json" \
	          ${TOP}.v ${DEPS} -q
	@echo


#──────────────────────────────────────────────────
#─── PLACE AND ROUTE
#──────────────────────────────────────────────────
#-- .json --> .fasm
$(TOP).fasm: ${TOP}.json ${CHIPDB}
	@echo
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"➡️  Routing..."${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	nextpnr-xilinx --chipdb ${CHIPDB} \
       --xdc ${XDC} --json ${TOP}.json --fasm ${TOP}.fasm #-q
	@echo


#──────────────────────────────────────────────────
#───  BITSTREAM GENERATION
#──────────────────────────────────────────────────
#-- .fasm ---> .frames
$(TOP).frames: $(TOP).fasm
	@echo
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"➡️  Generating bitstream..."${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	fasm2frames --part ${PART1} \
  		--db-root ${PRJXRAY_DB_DIR}/artix7 \
  		${TOP}.fasm > ${TOP}.frames
	@echo


#──────────────────────────────────────────────────
#───  BITSTREAM COMPRESION. FINAL .bit
#──────────────────────────────────────────────────
#--- .frames ---> .bit
$(TOP).bit: $(TOP).frames
	@echo
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"➡️  Packing..."${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	xc7frames2bit --part_file ${PRJXRAY_DB_DIR}/artix7/${PART1}/part.yaml \
  		--part_name ${PART1} --frm_file ${TOP}.frames \
  		--output_file ${TOP}.bit
	@echo
	@echo -e ${GREEN}"─────────────────────────────────"
	@echo -e ${GREEN}"✅ OK! Bitstream GENERATED"${RESET}
	@echo -e ${GREEN}"─────────────────────────────────\n"${RESET}



#──────────────────────────────────────────────────
#───  DATABASE BUILDING
#──────────────────────────────────────────────────
.PHONY: chipdb
chipdb: ${CHIPDB}
	
${CHIPDB}:
	@echo
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	@echo -e ${BLUE}"➡️  Database building..."${RESET}
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
	@echo -e ${BLUE}"➡️  Erasing the database..."${RESET}
	@echo -e ${BLUE}"─────────────────────────────────────"${RESET}
	rm -f ${CHIPDB}
	@echo


#──────────────────────────────────────────────────
#───  PROGRAMING: Uploading the bitstream
#──────────────────────────────────────────────────
.PHONY: prog
prog:	${TOP}.bit
	@echo -e ${YELLOW}"─────────────────────────────────────"${RESET}
	@echo -e ${YELLOW}"➡️  Uploading the bitstream in RAM..."${RESET}
	@echo -e ${YELLOW}"─────────────────────────────────────"${RESET}
	openFPGALoader --board basys3 --bitstream ${TOP}.bit
	@echo -e ${GREEN}"─────────────────────────────────"
	@echo -e ${GREEN}"✅ OK! Bitstream UPLOADED!"${RESET}
	@echo -e ${GREEN}"─────────────────────────────────\n"${RESET}
	@echo


#──────────────────────────────────────────────────
#───  PROGRAMING: Writing to FLAsH Memory
#──────────────────────────────────────────────────
.PHONY: flash
flash:  ${TOP}.bit
	@echo -e ${YELLOW}"─────────────────────────────────────"${RESET}
	@echo -e ${YELLOW}"➡️  Writting bitstream to FLASH..."${RESET}
	@echo -e ${YELLOW}"─────────────────────────────────────"${RESET}
	openFPGALoader --board basys3 --write-flash ${TOP}.bit
	@echo -e ${GREEN}"─────────────────────────────────"
	@echo -e ${GREEN}"✅ OK! Bitstream WRITTEN"${RESET}
	@echo -e ${GREEN}"─────────────────────────────────\n"${RESET}
	@echo


#──────────────────────────────────────────────────
#───  CLEAN
#──────────────────────────────────────────────────
.PHONY: clean
clean:
	@echo
	@echo -e ${RED}"➡️  Erase files..."${RESET}
	rm -rf *.fasm *.frames *.json *.bit
	@echo

