# spartan7-blinky — the first spartan7 design through the toolchain

## What it probes

A 24-bit counter blinky on `xc7s50csga324` (the Arty S7-50 part), with
generated constraints. First spartan7 coverage in the suite: chipdb,
prjxray-db and fasm features of that family all run for the first time
here. Our own design because upstream's spartan7 demos are DDR3/litex
projects, not smoke material. (The Arty S7-25 stays unsupported: xc7s25
is not in the prjxray db.)

## Expected result

Routes and produces a bitstream; `FDRE >= 24` plus the carry chain.

## Reading a failure

- **Only this fails, artix7 green** — spartan7-specific packaging;
  check `constant/xc7s50csga324` to scope.
