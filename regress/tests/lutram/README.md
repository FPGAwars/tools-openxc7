# lutram — distributed RAM in the fabric

## What it probes

A 64x8 memory with a synchronous write and an asynchronous read, pinned to
distributed RAM with `(* ram_style = "distributed" *)` so a yosys heuristic
change can never silently turn it into a second copy of the `bram` test.
Asserted: at least one RAM64M in the netlist.

Between `bram` (block RAM), `srl` (LUT as shift register) and this test,
the three memory idioms of the fabric each have a guard.

## Why it exists

LUTRAM shares the SLICEM machinery with SRLs (the write port needs WE/WCLK
and the DI pins) but drives a *different* packing path — RAM64M bundles
four 64x1 ports into one slice — and a different set of fasm features.
The pin attribute matters: without it, small memories sit on the boundary
of yosys' BRAM-vs-LUTRAM heuristic, and a flip of that heuristic would
change what this test covers without anyone noticing.

## Expected result

Three RAM64M (8 data bits over 4-bit-per-slice bundles), the addressing
mux tree around them, a routed bitstream. The async-read path makes fmax
meaningful but modest.

## Reading a failure

- **`RAM64M: expected >=1, netlist has 0`** — inference changed; check the
  yosys version and the attribute before touching the expectation.
- **DI/WE pin routing errors** — SLICEM placement of the write port went
  wrong; same failure family as `srl`.
- **Wrong read data would not show here** — this suite checks structure and
  routability, not simulation; a functional LUTRAM bug shows up on a board,
  which is what the HIL tier is for.
