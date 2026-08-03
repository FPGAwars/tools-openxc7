# widemux — wide multiplexers and fractured LUTs

## What it probes

A 32:1 multiplexer driven by an LFSR, which synthesis builds as a tree of
LUTs plus the dedicated F7/F8 mux bels (asserted: at least one MUXF7). The
same structure makes LUTs *fracture* — two logical LUT5s packed into one
physical LUT6, sharing input pins.

`metrics_present: fmax_mhz` is as important as the bitstream here, because
the failure this guards did not break routing: it emptied the timing report.

## Why it exists

Two related defects, both in the post-route timing walk:

1. The pin fixup created **false timing loops** out of shared fractured-LUT
   pins. The walk hit them, aborted, and the clock table came back empty — so
   `apio report` showed nothing while the bitstream was perfectly valid.
2. Self-net arcs were counted in the fan-in bookkeeping, with the same
   effect.

There is a lesson attached to this one worth keeping: the first hypothesis
blamed the DSP48, because the A/B comparison varied two factors at once (the
report hook *and* `-nodsp`). The real culprit — shared fractured-LUT pins —
was orthogonal to both. Vary one factor at a time.

## Expected result

Routes and produces a bitstream, at least one MUXF7 in the netlist, and a
populated timing report (~386 MHz on the reference part today).

## Reading a failure

- **fmax missing while the bitstream is fine** — the exact shape of the
  original bug: the timing walk aborted. This is the most valuable signal
  this test produces.
- **`MUXF7: expected >=1, netlist has 0`** — synthesis stopped building the
  mux tree from dedicated muxes, so the test no longer stresses fractured
  LUTs. Check the yosys version.
- **Utilisation jumps** — the mux tree is being built out of plain LUTs
  instead of F7/F8 bels.
