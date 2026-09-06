#!/usr/bin/env python3
"""Generate a minimal valid XDC for a part, from the prjxray-db package pins.

Usage: gen_xdc.py <prjxray-db-dir> <family> <part>   (part e.g. xc7a35tcpg236)

Picks a clock-capable pin (MRCC/SRCC) for `clk` and the first plain IO pin
for `led`, so the E2E blinky routes on any package without board-specific
constraints.  The clk candidate chosen is the one whose tile Y is closest
to the median tile Y of all the package IOs: the open zynq7 database is
missing the 32 BUFG cascade rows (CASCO<-CASCIN) of CLK_HROW_BOT_R, so a
clock net that must cross clock regions on its way to the BUFG row fails
in fasm2frames on the big zynq7 parts.  Keeping the blinky clock near the
vertical middle of the package keeps it within reach of the BUFG row, so
the E2E does not depend on the missing cascade.
"""
import csv
import re
import statistics
import sys
from pathlib import Path

db_dir, family, part = Path(sys.argv[1]), sys.argv[2], sys.argv[3]

# first speedgrade dir, like the packer / nix chipdb derivation
devices = sorted(d for d in (db_dir / family).glob(f"{part}-*") if d.is_dir())
if not devices:
    sys.exit(f"no {part}-<speedgrade> under {db_dir / family}")
pins_csv = devices[0] / "package_pins.csv"

TILE_Y = re.compile(r"_X\d+Y(\d+)$")


def is_general_io(row):
    fn = row["pin_function"]
    if fn.startswith("MGT") or "VREF" in fn:
        return False  # transceiver / reference pins are not general IO
    return fn.startswith("IO_")


def tile_y(row):
    m = TILE_Y.search(row["tile"])
    return int(m.group(1)) if m else None


def pick(rows, want_hr, y_median):
    """clk (MRCC/SRCC) + led on the requested bank class.

    High-performance banks (IOB18 tiles) are 1.8 V territory: LVCMOS33 on
    them is rejected by nextpnr, so the blinky must sit on high-range
    (IOB33) pins wherever the package has them.  Among the clock-capable
    candidates the one nearest to y_median wins (stable csv order breaks
    ties), per the module docstring."""
    clk_candidates = []
    led = None
    for row in rows:
        if not is_general_io(row):
            continue
        tile_is_hr = "IOB33" in row["tile"]
        if tile_is_hr != want_hr:
            continue
        if "MRCC" in row["pin_function"] or "SRCC" in row["pin_function"]:
            clk_candidates.append(row)
        elif led is None:
            led = row
    clk = None
    if clk_candidates:
        if y_median is None:
            clk = clk_candidates[0]
        else:
            clk = min(clk_candidates,
                      key=lambda r: abs(tile_y(r) - y_median))
    return clk, led


with open(pins_csv, newline="") as f:
    rows = list(csv.DictReader(f))

io_ys = [y for y in (tile_y(r) for r in rows if is_general_io(r))
         if y is not None]
y_median = statistics.median(io_ys) if io_ys else None

clk, led = pick(rows, want_hr=True, y_median=y_median)
iostandard = "LVCMOS33"
if not (clk and led):
    # No high-range bank on this package: fall back to the HP banks with a
    # standard they accept.
    clk, led = pick(rows, want_hr=False, y_median=y_median)
    iostandard = "LVCMOS18"

if not (clk and led):
    sys.exit(f"could not pick pins from {pins_csv}")

print(f"# auto-generated E2E constraints for {part} "
      f"(clk={clk['pin']} {clk['pin_function']}, led={led['pin']})")
print(f"set_property PACKAGE_PIN {clk['pin']} [get_ports clk]")
print(f"set_property IOSTANDARD {iostandard} [get_ports clk]")
print(f"set_property PACKAGE_PIN {led['pin']} [get_ports led]")
print(f"set_property IOSTANDARD {iostandard} [get_ports led]")
