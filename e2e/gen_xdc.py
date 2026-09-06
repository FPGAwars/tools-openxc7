#!/usr/bin/env python3
"""Generate a minimal valid XDC for a part, from the prjxray-db package pins.

Usage: gen_xdc.py <prjxray-db-dir> <family> <part>   (part e.g. xc7a35tcpg236)

Picks the first clock-capable pin (MRCC/SRCC) for `clk` and the first plain
IO pin for `led`, so the E2E blinky routes on any package without
board-specific constraints.
"""
import csv
import sys
from pathlib import Path

db_dir, family, part = Path(sys.argv[1]), sys.argv[2], sys.argv[3]

# first speedgrade dir, like the packer / nix chipdb derivation
devices = sorted(d for d in (db_dir / family).glob(f"{part}-*") if d.is_dir())
if not devices:
    sys.exit(f"no {part}-<speedgrade> under {db_dir / family}")
pins_csv = devices[0] / "package_pins.csv"

def pick(rows, want_hr):
    """clk (MRCC/SRCC) + led on the requested bank class.

    High-performance banks (IOB18 tiles) are 1.8 V territory: LVCMOS33 on
    them is rejected by nextpnr, so the blinky must sit on high-range
    (IOB33) pins wherever the package has them."""
    clk = led = None
    for row in rows:
        fn = row["pin_function"]
        if fn.startswith("MGT") or "VREF" in fn:
            continue  # transceiver / reference pins are not general IO
        if not fn.startswith("IO_"):
            continue
        tile_is_hr = "IOB33" in row["tile"]
        if tile_is_hr != want_hr:
            continue
        if clk is None and ("MRCC" in fn or "SRCC" in fn):
            clk = row
        elif led is None and "MRCC" not in fn and "SRCC" not in fn:
            led = row
        if clk and led:
            break
    return clk, led

with open(pins_csv, newline="") as f:
    rows = list(csv.DictReader(f))

clk, led = pick(rows, want_hr=True)
iostandard = "LVCMOS33"
if not (clk and led):
    # No high-range bank on this package: fall back to the HP banks with a
    # standard they accept.
    clk, led = pick(rows, want_hr=False)
    iostandard = "LVCMOS18"

if not (clk and led):
    sys.exit(f"could not pick pins from {pins_csv}")

print(f"# auto-generated E2E constraints for {part} "
      f"(clk={clk['pin']} {clk['pin_function']}, led={led['pin']})")
print(f"set_property PACKAGE_PIN {clk['pin']} [get_ports clk]")
print(f"set_property IOSTANDARD {iostandard} [get_ports clk]")
print(f"set_property PACKAGE_PIN {led['pin']} [get_ports led]")
print(f"set_property IOSTANDARD {iostandard} [get_ports led]")
