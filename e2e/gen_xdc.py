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

clk = led = None
with open(pins_csv, newline="") as f:
    for row in csv.DictReader(f):
        fn = row["pin_function"]
        if fn.startswith("MGT") or "VREF" in fn:
            continue  # transceiver / reference pins are not general IO
        if not fn.startswith("IO_"):
            continue
        if clk is None and ("MRCC" in fn or "SRCC" in fn):
            clk = row
        elif led is None and "MRCC" not in fn and "SRCC" not in fn:
            led = row
        if clk and led:
            break

if not (clk and led):
    sys.exit(f"could not pick pins from {pins_csv}")

print(f"# auto-generated E2E constraints for {part} "
      f"(clk={clk['pin']} {clk['pin_function']}, led={led['pin']})")
print(f"set_property PACKAGE_PIN {clk['pin']} [get_ports clk]")
print("set_property IOSTANDARD LVCMOS33 [get_ports clk]")
print(f"set_property PACKAGE_PIN {led['pin']} [get_ports led]")
print("set_property IOSTANDARD LVCMOS33 [get_ports led]")
