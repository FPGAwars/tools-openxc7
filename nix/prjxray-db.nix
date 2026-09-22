{ fetchFromGitHub, ... }:

# The prjxray device database the package ships and every chipdb is
# generated from. The himbaechel xilinx uarch does not vendor it (the
# nextpnr-xilinx fork carried it as a gitlink under xilinx/external), so it
# has its own revision here, written in this one file: the nextpnr
# derivation links it into share/nextpnr/external/prjxray-db, where apio's
# PRJXRAY_DB_DIR points, and the chipdb generation reads the same tree.
#
# openXC7/prjxray-db master of 2026-09-19 (#21). Over 1768fb35, the
# revision nextpnr-xilinx 0.9.5 carried, our three families change in two
# files only: the tilegrid.json of xc7s25, whose upper *_SING IOB33/IOI3
# tiles lose the fuzzer's start_offset 2 (db#18: the J6/L13/G13 pads of
# the Arty S7-25 are written into their own words), and the one of xc7s100
# (a grid derived from the pristine one, db#17, and the same offset fix,
# db#20). Neither xc7s100 nor xc7s75 is in the manifest.
fetchFromGitHub {
  owner = "openXC7";
  repo = "prjxray-db";
  rev = "a90f27c1caefee5276f47440f4c730b50519a86f";
  hash = "sha256-EugZWK38rwLkhbp81eX/+kr4vrqdzRQuDbLpPn6ij7U=";
}
